from __future__ import annotations

import csv
from pathlib import Path


CLOSE_COLUMNS = ("Close", "TR.CLOSEPRICE(Adjusted=0)", "Adj Close")


def load_symbol_prices(market_data_dir: Path, symbol: str) -> list[tuple[str, float]]:
    path = market_data_dir / f"{symbol.upper()}_stock_data.csv"
    if not path.exists():
        return []

    prices: list[tuple[str, float]] = []
    with path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            date = (row.get("Date") or "").strip()
            if not date:
                continue
            close = _pick_close(row)
            if close is None:
                continue
            prices.append((date[:10], close))
    return prices


def _pick_close(row: dict[str, str]) -> float | None:
    for column in CLOSE_COLUMNS:
        value = row.get(column)
        if value in (None, ""):
            continue
        try:
            return float(value)
        except ValueError:
            continue
    return None
