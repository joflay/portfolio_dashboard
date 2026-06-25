from pathlib import Path

from portfolio_dashboard import market_data
from portfolio_dashboard.market_data import fetch_nasdaq_daily_prices, fetch_yahoo_daily_prices, load_symbol_prices


def test_load_symbol_prices_prefers_close(tmp_path: Path) -> None:
    path = tmp_path / "ABC_stock_data.csv"
    path.write_text(
        "Date,Close,TR.CLOSEPRICE(Adjusted=0),Adj Close\n"
        "2026-01-02,10,11,12\n"
    )

    assert load_symbol_prices(tmp_path, "ABC") == [("2026-01-02", 10.0)]


def test_load_symbol_prices_falls_back_to_tr_close(tmp_path: Path) -> None:
    path = tmp_path / "ABC_stock_data.csv"
    path.write_text(
        "Date,Close,TR.CLOSEPRICE(Adjusted=0),Adj Close\n"
        "2026-01-02,,11,12\n"
    )

    assert load_symbol_prices(tmp_path, "ABC") == [("2026-01-02", 11.0)]


def test_load_symbol_prices_uses_old_ticker_file_for_echo(tmp_path: Path) -> None:
    path = tmp_path / "SATS_stock_data.csv"
    path.write_text("Date,Close\n2026-01-02,10\n")

    assert load_symbol_prices(tmp_path, "ECHO") == [("2026-01-02", 10.0)]


def test_fetch_nasdaq_daily_prices_parses_historical_payload(monkeypatch) -> None:
    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self):
            return (
                b'{"data":{"tradesTable":{"rows":['
                b'{"date":"06/15/2026","close":"$754.83"},'
                b'{"date":"06/12/2026","close":"741.75"}'
                b"]}}}"
            )

    seen = {}

    def fake_urlopen(request, timeout):
        seen["url"] = request.full_url
        seen["timeout"] = timeout
        return _Response()

    monkeypatch.setattr(market_data, "urlopen", fake_urlopen)

    rows = fetch_nasdaq_daily_prices("SPY", "2026-06-12", "2026-06-16")

    assert rows == [("2026-06-12", 741.75), ("2026-06-15", 754.83)]
    assert "api.nasdaq.com" in seen["url"]
    assert "fromdate=2026-06-12" in seen["url"]
    assert seen["timeout"] == 10


def test_fetch_yahoo_daily_prices_parses_chart_payload(monkeypatch) -> None:
    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self):
            return (
                b'{"chart":{"result":[{"timestamp":[1781222400,1781481600],'
                b'"indicators":{"quote":[{"close":[741.75,740.25]}]}}]}}'
            )

    seen = {}

    def fake_urlopen(url, timeout):
        seen["url"] = url
        seen["timeout"] = timeout
        return _Response()

    monkeypatch.setattr(market_data, "urlopen", fake_urlopen)

    rows = fetch_yahoo_daily_prices("SPY", "2026-06-12", "2026-06-15")

    assert rows == [("2026-06-12", 741.75), ("2026-06-15", 740.25)]
    assert "interval=1d" in seen["url"]
    assert seen["timeout"] == 10


def test_fetch_yahoo_daily_prices_returns_empty_on_fetch_error(monkeypatch) -> None:
    def fake_urlopen(url, timeout):
        raise OSError("offline")

    monkeypatch.setattr(market_data, "urlopen", fake_urlopen)

    assert fetch_yahoo_daily_prices("SPY", "2026-06-12", "2026-06-15") == []
