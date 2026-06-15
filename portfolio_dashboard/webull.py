from __future__ import annotations

from datetime import date
import json
from typing import Any
from urllib.parse import urlparse

from .config import Settings


class WebullClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._trade_client: Any | None = None
        self._data_client: Any | None = None

    @property
    def trade_client(self) -> Any:
        if self._trade_client is None:
            self._trade_client = _build_trade_client(self.settings)
        return self._trade_client

    @property
    def data_client(self) -> Any:
        if self._data_client is None:
            self._data_client = _build_data_client(self.settings)
        return self._data_client

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
        method = getattr(account_v2, "get_account_positions", None) or getattr(
            account_v2,
            "get_account_position",
            None,
        )
        if method is None:
            raise RuntimeError("Webull SDK account_v2 account position method is unavailable")
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

    def latest_quotes(self, symbols: set[str]) -> dict[str, float]:
        symbol_list = sorted({symbol.upper() for symbol in symbols if symbol})
        if not symbol_list:
            return {}

        try:
            quotes = self._latest_quotes_from_data_client(symbol_list)
        except Exception:
            quotes = {}
        if quotes:
            return quotes
        return self._latest_quotes_from_trade_client(symbol_list)

    def _latest_quotes_from_data_client(self, symbols: list[str]) -> dict[str, float]:
        quotes: dict[str, float] = {}
        market_data = self.data_client.market_data
        for category in _QUOTE_CATEGORIES:
            try:
                snapshot = market_data.get_snapshot(symbols, category)
            except TypeError:
                try:
                    snapshot = market_data.get_snapshot(symbols, category)
                except Exception:
                    continue
            except Exception:
                continue
            quotes.update(_quotes_from_payload(_response_json(snapshot), symbols))

        missing = [symbol for symbol in symbols if symbol not in quotes]
        for symbol in missing:
            for category in _QUOTE_CATEGORIES:
                try:
                    quote = market_data.get_quotes(symbol, category)
                except TypeError:
                    try:
                        quote = market_data.get_quotes(symbol, category)
                    except Exception:
                        continue
                except Exception:
                    continue
                parsed = _quotes_from_payload(_response_json(quote), [symbol])
                if parsed:
                    quotes.update(parsed)
                    break
        return quotes

    def _latest_quotes_from_trade_client(self, symbols: list[str]) -> dict[str, float]:
        quotes: dict[str, float] = {}
        for namespace_name, method_name in _QUOTE_METHODS:
            namespace = getattr(self.trade_client, namespace_name, None)
            method = (
                getattr(namespace, method_name, None)
                if namespace_name
                else getattr(self.trade_client, method_name, None)
            )
            if method is None:
                continue
            try:
                payload = self._call_quote_method(method, symbols, f"{namespace_name}.{method_name}".strip("."))
            except TypeError:
                continue
            quotes.update(_quotes_from_payload(payload, symbols))
            if quotes:
                return quotes
        return quotes

    @staticmethod
    def _call(method: Any, label: str, **kwargs: Any) -> Any:
        response = method(**kwargs)
        payload = _response_json(response)
        status = getattr(response, "status_code", None)
        if status and int(status) != 200:
            raise RuntimeError(f"Webull SDK {label} failed {status}: {json.dumps(payload)}")
        return payload

    @classmethod
    def _call_quote_method(cls, method: Any, symbols: list[str], label: str) -> Any:
        attempts = (
            ((), {"symbols": symbols}),
            ((symbols,), {}),
            ((), {"ticker": ",".join(symbols)}),
            ((), {"symbol": ",".join(symbols)}),
        )
        last_error: TypeError | None = None
        for args, kwargs in attempts:
            try:
                response = method(*args, **kwargs)
            except TypeError as exc:
                last_error = exc
                continue
            payload = _response_json(response)
            status = getattr(response, "status_code", None)
            if status and int(status) != 200:
                raise RuntimeError(f"Webull SDK {label} failed {status}: {json.dumps(payload)}")
            return payload

        payloads = []
        for symbol in symbols:
            try:
                payloads.append(cls._call(method, label, symbol=symbol))
            except TypeError as exc:
                last_error = exc
                break
        if payloads:
            return payloads
        if last_error:
            raise last_error
        return {}


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


def _build_data_client(settings: Settings) -> Any:
    try:
        from webull.core.client import ApiClient
        from webull.data.data_client import DataClient
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Webull SDK is not installed. Install the SDK package that provides "
            "webull.core.client.ApiClient and webull.data.data_client.DataClient."
        ) from exc

    region = str(settings.region or "us").lower()
    endpoint = urlparse(settings.endpoint).netloc or settings.endpoint
    api_client = ApiClient(settings.app_key, settings.app_secret, region)
    api_client.add_endpoint(region, endpoint)
    return DataClient(api_client)


_QUOTE_CATEGORIES = ("US_STOCK", "US_ETF")


_QUOTE_METHODS = (
    ("market_data_v2", "get_quote"),
    ("market_data_v2", "get_quotes"),
    ("market_data_v2", "get_stock_quote"),
    ("market_data_v2", "get_batch_quote"),
    ("market_data", "get_quote"),
    ("market_data", "get_quotes"),
    ("market_data", "get_stock_quote"),
    ("market_data", "get_batch_quote"),
    ("quote_v2", "get_quote"),
    ("quote_v2", "get_quotes"),
    ("quote_v2", "get_stock_quote"),
    ("quote_v2", "get_batch_quote"),
    ("quote", "get_quote"),
    ("quote", "get_quotes"),
    ("quote", "get_stock_quote"),
    ("quote", "get_batch_quote"),
    ("stock_v2", "get_quote"),
    ("stock_v2", "get_quotes"),
    ("stock", "get_quote"),
    ("stock", "get_quotes"),
    ("", "get_quote"),
    ("", "get_quotes"),
)


def _response_json(response: Any) -> Any:
    if isinstance(response, (dict, list)):
        return response
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


def _quotes_from_payload(payload: Any, requested_symbols: list[str]) -> dict[str, float]:
    quotes: dict[str, float] = {}
    for item in _quote_items(payload):
        symbol = _quote_symbol(item)
        price = _quote_price(item)
        if symbol and price is not None:
            quotes[symbol] = price
    if len(requested_symbols) == 1 and not quotes:
        price = _quote_price(payload)
        if price is not None:
            quotes[requested_symbols[0]] = price
    return quotes


def _quote_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        items: list[dict[str, Any]] = []
        for value in payload:
            items.extend(_quote_items(value))
        return items
    if not isinstance(payload, dict):
        return []
    output: list[dict[str, Any]] = []
    for key, value in payload.items():
        if isinstance(value, dict) and _quote_price(value) is not None:
            item = dict(value)
            item.setdefault("symbol", key)
            output.append(item)
        elif isinstance(value, list):
            output.extend(item for item in value if isinstance(item, dict))
        elif isinstance(value, dict):
            output.extend(_quote_items(value))
    if _quote_price(payload) is not None:
        output.append(payload)
    return output


def _quote_symbol(item: dict[str, Any]) -> str:
    for key in ("symbol", "ticker", "tickerSymbol", "instrumentSymbol", "disSymbol", "symbolName"):
        value = item.get(key)
        if value:
            return str(value).upper()
    return ""


def _quote_price(source: Any) -> float | None:
    spread_midpoint = _bid_ask_midpoint(source)
    if spread_midpoint is not None:
        return spread_midpoint
    return _first_float(
        source,
        "last_price",
        "lastPrice",
        "last",
        "price",
        "pPrice",
        "close",
        "closePrice",
        "tradePrice",
        "marketPrice",
        "latestPrice",
    )


def _bid_ask_midpoint(source: Any) -> float | None:
    if not isinstance(source, dict):
        return None
    bid = _first_book_price(source.get("bids"))
    ask = _first_book_price(source.get("asks"))
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


def _first_float(source: Any, *names: str) -> float | None:
    if isinstance(source, dict):
        for name in names:
            parsed = _float(source.get(name))
            if parsed is not None:
                return parsed
        for value in source.values():
            nested = _first_float(value, *names)
            if nested is not None:
                return nested
    elif isinstance(source, list):
        for item in source:
            nested = _first_float(item, *names)
            if nested is not None:
                return nested
    return None


def _float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


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
