from datetime import date

from portfolio_dashboard import app as dashboard_app


class _FakeDb:
    def __init__(self):
        self.upserted_prices = []

    def initialize(self) -> None:
        pass

    def fetch_positions(self, strategy):
        return [{"symbol": "ABC", "quantity": 2, "avg_price": 5}]

    def fetch_orders(self, strategy, start_date):
        return []

    def fetch_price_rows(self, symbols, start_date):
        return [{"symbol": "ABC", "date": "2026-06-14", "close": 10}]

    def upsert_prices(self, symbol, rows, source):
        self.upserted_prices.append((symbol, rows, source))


class _FakeWebullClient:
    def __init__(self, settings):
        pass

    def latest_quotes(self, symbols):
        return {"ABC": 12}


def test_performance_uses_and_persists_live_webull_prices(monkeypatch) -> None:
    fake_db = _FakeDb()
    monkeypatch.setattr(dashboard_app, "db", fake_db)
    monkeypatch.setattr(dashboard_app, "WebullClient", _FakeWebullClient)
    monkeypatch.setattr(dashboard_app, "cache_prices", lambda db, settings, symbols: 0)
    monkeypatch.setattr(dashboard_app, "load_risk_free_rates", lambda path: {})

    result = dashboard_app._performance("Vol_Factor")

    assert result["summary"]["net_exposure"] == 24
    assert result["summary"]["latest_equity"] == 24
    assert result["summary"]["history_end"] == date.today().isoformat()
    assert result["holdings"][0]["last_price"] == 12
    assert fake_db.upserted_prices == [
        ("ABC", [(date.today().isoformat(), 12.0)], "sdk:webull.latest_quotes")
    ]


def test_account_summary_returns_use_account_net_aum_when_available() -> None:
    strategies = [
        {
            "summary": {
                "net_exposure": 25,
                "gross_exposure": 50,
                "latest_equity": 5,
                "daily_pnl": 2,
                "total_pnl": 4,
                "spy_daily_return": 0.003,
                "spy_total_return": 0.015,
                "max_drawdown": 0,
                "open_positions": 1,
                "trade_count": 1,
                "history_start": "2026-06-12",
                "history_end": "2026-06-15",
            }
        }
    ]
    account_assets = [{"net_aum": 200, "raw_json": "{}"}]

    result = dashboard_app._account_summary(strategies, [], account_assets)

    assert result["gross_exposure"] == 50
    assert result["daily_return"] == 0.01
    assert result["total_return"] == 0.02
    assert result["daily_return_over_spy"] == 0.007
    assert result["total_return_over_spy"] == 0.005


def test_account_summary_uses_webull_account_pnl_when_available() -> None:
    strategies = [
        {
            "summary": {
                "net_exposure": 25,
                "gross_exposure": 50,
                "latest_equity": 999,
                "daily_pnl": 999,
                "total_pnl": 999,
                "spy_daily_return": None,
                "spy_total_return": None,
                "max_drawdown": 0,
                "open_positions": 1,
                "trade_count": 1,
                "history_start": "2026-06-12",
                "history_end": "2026-06-15",
            }
        }
    ]
    account_assets = [
        {
            "net_aum": 200,
            "raw_json": (
                '{"payload": {"total_day_profit_loss": "9.18", '
                '"total_unrealized_profit_loss": "9.65"}}'
            ),
        }
    ]

    result = dashboard_app._account_summary(strategies, [], account_assets)

    assert result["latest_equity"] == 9.65
    assert result["daily_pnl"] == 9.18
    assert result["total_pnl"] == 9.65
