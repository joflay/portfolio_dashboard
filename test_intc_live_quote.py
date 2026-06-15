from __future__ import annotations

import json
import os
from typing import Any
from urllib.parse import urlparse

from dotenv import load_dotenv
from webull.core.client import ApiClient
from webull.data.data_client import DataClient


SYMBOL = "INTC"
EXPECTED_PRICE = 128.0
MAX_ABS_DIFF = 2.0
CATEGORIES = ("US_STOCK", "US_ETF")
PRICE_KEYS = (
    "last_price",
    "lastPrice",
    "latestPrice",
    "tradePrice",
    "marketPrice",
    "pPrice",
    "price",
    "close",
    "closePrice",
)


def main() -> None:
    load_dotenv()
    client = _data_client()

    payloads: list[tuple[str, Any]] = []
    for category in CATEGORIES:
        payloads.append((f"snapshot:{category}", _json(client.market_data.get_snapshot([SYMBOL], category))))
        payloads.append((f"quote:{category}", _json(client.market_data.get_quotes(SYMBOL, category))))

    for label, payload in payloads:
        print(f"\n===== {label} =====")
        print(json.dumps(payload, indent=2, sort_keys=True))

    price = _latest_price([payload for _, payload in payloads], SYMBOL)
    if price is None:
        raise SystemExit(f"Could not find a latest price for {SYMBOL} in Webull responses")

    print(f"\nExtracted {SYMBOL} latest price: {price}")
    if abs(price - EXPECTED_PRICE) > MAX_ABS_DIFF:
        raise SystemExit(f"Expected {SYMBOL} near {EXPECTED_PRICE}, got {price}")


def _data_client() -> DataClient:
    app_key = os.environ.get("WEBULL_APP_KEY")
    app_secret = os.environ.get("WEBULL_APP_SECRET")
    region = os.environ.get("WEBULL_REGION", "us")
    endpoint = os.environ.get("WEBULL_ENDPOINT", "https://api.webull.com")
    if not app_key or not app_secret:
        raise SystemExit("Missing WEBULL_APP_KEY or WEBULL_APP_SECRET in .env")

    api_client = ApiClient(app_key, app_secret, region)
    api_client.add_endpoint(region, urlparse(endpoint).netloc or endpoint)
    return DataClient(api_client)


def _json(response: Any) -> Any:
    if isinstance(response, (dict, list)):
        return response
    try:
        return response.json()
    except Exception:
        return {"raw_text": getattr(response, "text", str(response))}


def _latest_price(payloads: list[Any], symbol: str) -> float | None:
    requested = symbol.upper()
    for payload in payloads:
        for item in _items(payload):
            item_symbol = _symbol(item)
            price = _price(item)
            if price is not None and (not item_symbol or item_symbol == requested):
                return price
    return None


def _items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        output: list[dict[str, Any]] = []
        for value in payload:
            output.extend(_items(value))
        return output
    if not isinstance(payload, dict):
        return []

    output = [payload] if _price(payload) is not None else []
    for key, value in payload.items():
        if isinstance(value, dict):
            item = dict(value)
            item.setdefault("symbol", key)
            output.extend(_items(item))
        elif isinstance(value, list):
            output.extend(_items(value))
    return output


def _symbol(item: dict[str, Any]) -> str:
    for key in ("symbol", "ticker", "tickerSymbol", "instrumentSymbol", "disSymbol", "symbolName"):
        value = item.get(key)
        if value:
            return str(value).upper()
    return ""


def _price(item: dict[str, Any]) -> float | None:
    midpoint = _bid_ask_midpoint(item)
    if midpoint is not None:
        return midpoint
    for key in PRICE_KEYS:
        parsed = _float(item.get(key))
        if parsed is not None:
            return parsed
    for value in item.values():
        if isinstance(value, dict):
            parsed = _price(value)
            if parsed is not None:
                return parsed
    return None


def _bid_ask_midpoint(item: dict[str, Any]) -> float | None:
    bid = _first_book_price(item.get("bids"))
    ask = _first_book_price(item.get("asks"))
    if bid is not None and ask is not None:
        return (bid + ask) / 2
    return ask if ask is not None else bid


def _first_book_price(value: Any) -> float | None:
    if isinstance(value, list):
        for item in value:
            price = _first_book_price(item)
            if price is not None:
                return price
    if isinstance(value, dict):
        return _float(value.get("price"))
    return _float(value)


def _float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


if __name__ == "__main__":
    main()
