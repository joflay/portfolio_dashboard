from __future__ import annotations

import base64
from datetime import UTC, date, datetime, timedelta
import hashlib
import hmac
import json
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote, urlencode, urlparse
from urllib.request import Request, urlopen
import uuid

from .config import Settings


class WebullClient:
    def __init__(self, settings: Settings):
        self.settings = settings

    def account_list(self) -> list[dict[str, Any]]:
        payload = self._request("GET", self.settings.account_list_path)
        return _list_payload(payload, "accounts", "data")

    def positions(self, account_id: str) -> list[dict[str, Any]]:
        path = self.settings.account_positions_path.format(account_id=account_id)
        payload = self._request("GET", path, {"account_id": account_id})
        return _list_payload(payload, "positions", "data")

    def order_history(self, account_id: str) -> list[dict[str, Any]]:
        path = self.settings.order_history_path.format(account_id=account_id)
        end = date.today()
        start = end - timedelta(days=730)
        payload = self._request(
            "GET",
            path,
            {
                "account_id": account_id,
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "page_size": "100",
            },
        )
        return _flatten_order_history(payload)

    def _request(self, method: str, path: str, query: dict[str, Any] | None = None) -> Any:
        query = query or {}
        query_string = f"?{urlencode(query)}" if query else ""
        url = f"{self.settings.endpoint}{path}{query_string}"
        body = b""
        headers = self._headers(path, query, None)
        request = Request(url, data=body or None, method=method, headers=headers)
        try:
            with urlopen(request, timeout=30) as response:
                raw = response.read().decode()
        except HTTPError as exc:
            detail = exc.read().decode(errors="replace")
            raise RuntimeError(f"Webull API error {exc.code}: {detail}") from exc
        return json.loads(raw) if raw else {}

    def _headers(self, path: str, query: dict[str, Any], body_string: str | None) -> dict[str, str]:
        timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        nonce = uuid.uuid4().hex
        token = self._read_token()
        host = urlparse(self.settings.endpoint).netloc
        signature = generate_signature(
            path=path,
            query_params=query,
            body_string=body_string,
            app_key=self.settings.app_key,
            app_secret=self.settings.app_secret,
            host=host,
            timestamp=timestamp,
            nonce=nonce,
        )
        return {
            "Accept": "application/json",
            "x-app-key": self.settings.app_key,
            "x-timestamp": timestamp,
            "x-signature": signature,
            "x-signature-algorithm": "HMAC-SHA1",
            "x-signature-version": "1.0",
            "x-signature-nonce": nonce,
            "x-version": "v2",
            "x-access-token": token,
        }

    def _read_token(self) -> str:
        if not self.settings.token_file.exists():
            return ""
        for line in self.settings.token_file.read_text().splitlines():
            token = line.strip()
            if token:
                return token
        return ""


def generate_signature(
    path: str,
    query_params: dict[str, Any],
    body_string: str | None,
    app_key: str,
    app_secret: str,
    host: str,
    timestamp: str,
    nonce: str,
) -> str:
    signing_values = {
        "host": host,
        "x-app-key": app_key,
        "x-signature-algorithm": "HMAC-SHA1",
        "x-signature-nonce": nonce,
        "x-signature-version": "1.0",
        "x-timestamp": timestamp,
    }
    all_params = {str(key): str(value) for key, value in query_params.items()}
    all_params.update(signing_values)
    str1 = "&".join(f"{key}={all_params[key]}" for key in sorted(all_params))
    if body_string:
        body_hash = hashlib.md5(body_string.encode("utf-8")).hexdigest().upper()
        str3 = f"{path}&{str1}&{body_hash}"
    else:
        str3 = f"{path}&{str1}"
    encoded = quote(str3, safe="")
    signing_key = f"{app_secret}&"
    digest = hmac.new(signing_key.encode("utf-8"), encoded.encode("utf-8"), hashlib.sha1).digest()
    return base64.b64encode(digest).decode("utf-8")


def _list_payload(payload: Any, *keys: str) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in keys:
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            nested = _list_payload(value, *keys)
            if nested:
                return nested
    return []


def _flatten_order_history(payload: Any) -> list[dict[str, Any]]:
    rows = _list_payload(payload, "data", "items", "orders")
    flattened: list[dict[str, Any]] = []
    for row in rows:
        child_orders = row.get("orders")
        if isinstance(child_orders, list):
            for child in child_orders:
                if isinstance(child, dict):
                    merged = dict(child)
                    for key in ("client_order_id", "combo_order_id", "combo_type"):
                        if key in row and key not in merged:
                            merged[key] = row[key]
                    flattened.append(merged)
        else:
            flattened.append(row)
    return flattened
