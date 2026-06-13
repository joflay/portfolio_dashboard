from pathlib import Path

from portfolio_dashboard.market_data import load_symbol_prices


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
