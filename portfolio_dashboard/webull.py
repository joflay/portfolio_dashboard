from __future__ import annotations

from datetime import date
import json
from typing import Any
from urllib.parse import urlparse

from .config import Settings


class WebullClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.trade_client = _build_trade_client(settings)

    def account_list(self) -> list[dict[str, Any]]:
        payload = self._call(self.trade_client.account_v2.get_account_list, "account list")
        return _list_payload(payload, "accounts", "accountList", "list", "data", "result")

    def account_assets(self, account_id: str) -> dict[str, Any]:
        payload = self._call(
            self.trade_client.account_v2.get_account_balance,
            "account balance",
            account_id=account_id,
        )
        if not isinstance(payload, dict):
            raise RuntimeError("Webull SDK account balance returned a non-object payload")
        return {"source_path": "sdk:account_v2.get_account_balance", "payload": payload}

    def positions(self, account_id: str) -> list[dict[str, Any]]:
        account_v2 = self.trade_client.account_v2
        method = getattr(account_v2, "get_account_position", None)
        if method is None:
            raise RuntimeError("Webull SDK account_v2.get_account_position is unavailable")
        payload = self._call(method, "account positions", account_id=account_id)
        return _list_payload(payload, "positions", "positionList", "list", "data", "result")

    def order_history(self, account_id: str) -> list[dict[str, Any]]:
        end = date.today().isoformat()
        for namespace_name, method_name in (
            ("order_v2", "get_order_history"),
            ("order_v2", "get_orders"),
            ("order", "get_order_history"),
            ("order", "get_orders"),
            ("trade_v2", "get_order_history"),
            ("trade_v2", "get_orders"),
        ):
            namespace = getattr(self.trade_client, namespace_name, None)
            method = getattr(namespace, method_name, None) if namespace is not None else None
            if method is None:
                continue
            payload = self._call(
                method,
                f"{namespace_name}.{method_name}",
                account_id=account_id,
                start_date=self.settings.strategy_start_date,
                end_date=end,
                page_size=100,
            )
            return _flatten_order_history(payload)
        raise RuntimeError("Webull SDK order history method is unavailable")

    @staticmethod
    def _call(method: Any, label: str, **kwargs: Any) -> Any:
        response = method(**kwargs)
        payload = _response_json(response)
        status = getattr(response, "status_code", None)
        if status and int(status) != 200:
            raise RuntimeError(f"Webull SDK {label} failed {status}: {json.dumps(payload)}")
        return payload


def _build_trade_client(settings: Settings) -> Any:
    try:
        from webull.core.client import ApiClient
        from webull.trade.trade_client import TradeClient
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Webull SDK is not installed. Install the SDK package that provides "
            "webull.core.client.ApiClient and webull.trade.trade_client.TradeClient."
        ) from exc

    region = str(settings.region or "us").lower()
    endpoint = urlparse(settings.endpoint).netloc or settings.endpoint
    api_client = ApiClient(settings.app_key, settings.app_secret, region)
    api_client.add_endpoint(region, endpoint)
    return TradeClient(api_client)


def _response_json(response: Any) -> Any:
    try:
        return response.json()
    except Exception:
        return {"raw_text": getattr(response, "text", str(response))}


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
    rows = _list_payload(payload, "data", "items", "orders", "list", "result")
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
