import sys
from types import ModuleType

from portfolio_dashboard.webull import WebullClient, _build_trade_client, _flatten_order_history


class _Settings:
    app_key = "app-key"
    app_secret = "app-secret"
    region = "US"
    endpoint = "https://api.webull.com"
    strategy_start_date = "2026-06-12"


class _FakeResponse:
    status_code = 200

    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


class _FakeAccountV2:
    def get_account_list(self):
        return _FakeResponse({"data": [{"account_id": "acct"}]})

    def get_account_balance(self, account_id):
        return _FakeResponse({"total_net_liquidation_value": "3702.68", "account_id": account_id})

    def get_account_position(self, account_id):
        return _FakeResponse({"data": [{"symbol": "ABC", "quantity": "1", "account_id": account_id}]})


class _FakeOrderV2:
    def get_order_history(self, **kwargs):
        return _FakeResponse({"data": [{"order_id": "order", "symbol": "ABC", **kwargs}]})


class _FakeMarketDataV2:
    def get_quotes(self, symbols):
        return _FakeResponse(
            {
                "data": [
                    {"symbol": "ABC", "lastPrice": "12.34"},
                    {"symbol": "XYZ", "lastPrice": 56.78},
                ]
            }
        )


class _FakeMarketData:
    def get_snapshot(self, symbols, category, extend_hour_required=None):
        return _FakeResponse({"data": []})

    def get_quotes(self, symbol, category):
        prices = {
            "ABC": {"bids": [{"price": "12.32"}], "asks": [{"price": "12.36"}], "symbol": "ABC"},
            "XYZ": {"bids": [{"price": "56.76"}], "asks": [{"price": "56.80"}], "symbol": "XYZ"},
        }
        return _FakeResponse(prices[symbol])


class _FakeApiClient:
    def __init__(self, app_key, app_secret, region):
        self.args = (app_key, app_secret, region)
        self.endpoint = None

    def add_endpoint(self, region, endpoint):
        self.endpoint = (region, endpoint)


class _FakeTradeClient:
    def __init__(self, api_client):
        self.api_client = api_client
        self.account_v2 = _FakeAccountV2()
        self.order_v2 = _FakeOrderV2()
        self.market_data_v2 = _FakeMarketDataV2()


class _FakeDataClient:
    def __init__(self, api_client):
        self.api_client = api_client
        self.market_data = _FakeMarketData()


def _install_fake_sdk(monkeypatch):
    webull_module = ModuleType("webull")
    core_module = ModuleType("webull.core")
    client_module = ModuleType("webull.core.client")
    data_module = ModuleType("webull.data")
    data_client_module = ModuleType("webull.data.data_client")
    trade_module = ModuleType("webull.trade")
    trade_client_module = ModuleType("webull.trade.trade_client")
    client_module.ApiClient = _FakeApiClient
    data_client_module.DataClient = _FakeDataClient
    trade_client_module.TradeClient = _FakeTradeClient

    monkeypatch.setitem(sys.modules, "webull", webull_module)
    monkeypatch.setitem(sys.modules, "webull.core", core_module)
    monkeypatch.setitem(sys.modules, "webull.core.client", client_module)
    monkeypatch.setitem(sys.modules, "webull.data", data_module)
    monkeypatch.setitem(sys.modules, "webull.data.data_client", data_client_module)
    monkeypatch.setitem(sys.modules, "webull.trade", trade_module)
    monkeypatch.setitem(sys.modules, "webull.trade.trade_client", trade_client_module)


def test_build_trade_client_uses_sdk_endpoint(monkeypatch) -> None:
    _install_fake_sdk(monkeypatch)

    trade_client = _build_trade_client(_Settings())

    assert trade_client.api_client.args == ("app-key", "app-secret", "us")
    assert trade_client.api_client.endpoint == ("us", "api.webull.com")


def test_webull_client_uses_sdk_account_methods(monkeypatch) -> None:
    _install_fake_sdk(monkeypatch)
    client = WebullClient(_Settings())

    assert client.account_list() == [{"account_id": "acct"}]
    assert client.account_assets("acct") == {
        "source_path": "sdk:account_v2.get_account_balance",
        "payload": {"total_net_liquidation_value": "3702.68", "account_id": "acct"},
    }
    assert client.positions("acct") == [{"symbol": "ABC", "quantity": "1", "account_id": "acct"}]
    assert client.order_history("acct")[0]["order_id"] == "order"


def test_webull_client_fetches_latest_quotes(monkeypatch) -> None:
    _install_fake_sdk(monkeypatch)
    client = WebullClient(_Settings())

    assert client.latest_quotes({"abc", "XYZ"}) == {"ABC": 12.34, "XYZ": 56.78}


def test_missing_sdk_fails_clearly(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "webull", None)

    try:
        WebullClient(_Settings())
    except RuntimeError as exc:
        assert "Webull SDK is not installed" in str(exc)
    else:
        raise AssertionError("WebullClient should require the SDK")


def test_flatten_order_history_group_rows() -> None:
    payload = [
        {
            "combo_order_id": "combo",
            "combo_type": "NORMAL",
            "orders": [{"order_id": "order", "symbol": "AAPL"}],
        }
    ]

    assert _flatten_order_history(payload) == [
        {"order_id": "order", "symbol": "AAPL", "combo_order_id": "combo", "combo_type": "NORMAL"}
    ]
