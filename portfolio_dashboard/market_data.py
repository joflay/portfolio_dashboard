from __future__ import annotations

import csv
from datetime import UTC, date, datetime, timedelta
import json
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen


CLOSE_COLUMNS = ("Close", "TR.CLOSEPRICE(Adjusted=0)", "Adj Close")
NASDAQ_HISTORICAL_URL = "https://api.nasdaq.com/api/quote/{symbol}/historical"
YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"


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


def fetch_benchmark_daily_prices(symbol: str, start_date: str, end_date: str | None = None) -> list[tuple[str, float]]:
    return fetch_nasdaq_daily_prices(symbol, start_date, end_date) or fetch_yahoo_daily_prices(
        symbol,
        start_date,
        end_date,
    )


def fetch_nasdaq_daily_prices(symbol: str, start_date: str, end_date: str | None = None) -> list[tuple[str, float]]:
    start = _date(start_date)
    end = _date(end_date) if end_date else date.today()
    if start is None or end is None:
        return []
    params = urlencode(
        {
            "assetclass": "etf",
            "fromdate": start.isoformat(),
            "todate": end.isoformat(),
            "limit": 9999,
        }
    )
    url = f"{NASDAQ_HISTORICAL_URL.format(symbol=symbol.upper())}?{params}"
    try:
        with urlopen(_request(url), timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        return []
    return _nasdaq_daily_prices(payload, start, end)


def fetch_yahoo_daily_prices(symbol: str, start_date: str, end_date: str | None = None) -> list[tuple[str, float]]:
    start = _date(start_date)
    end = _date(end_date) if end_date else date.today()
    if start is None or end is None:
        return []
    period1 = _timestamp(start - timedelta(days=7))
    period2 = _timestamp(end + timedelta(days=1))
    params = urlencode(
        {
            "period1": period1,
            "period2": period2,
            "interval": "1d",
            "includePrePost": "false",
            "events": "history",
        }
    )
    url = f"{YAHOO_CHART_URL.format(symbol=symbol.upper())}?{params}"
    try:
        with urlopen(_request(url), timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        return []
    return _yahoo_daily_prices(payload, start, end)


def _request(url: str) -> Request:
    return Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json, text/plain, */*",
        },
    )


def _nasdaq_daily_prices(payload: dict, start: date, end: date) -> list[tuple[str, float]]:
    rows = (((payload.get("data") or {}).get("tradesTable") or {}).get("rows") or [])
    prices: list[tuple[str, float]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        day = _nasdaq_date(row.get("date"))
        close = _price(row.get("close"))
        if day is not None and close is not None and start <= day <= end:
            prices.append((day.isoformat(), close))
    return sorted(prices)


def _yahoo_daily_prices(payload: dict, start: date, end: date) -> list[tuple[str, float]]:
    try:
        result = payload["chart"]["result"][0]
    except (KeyError, IndexError, TypeError):
        return []
    timestamps = result.get("timestamp") or []
    closes = (((result.get("indicators") or {}).get("quote") or [{}])[0] or {}).get("close") or []
    prices: list[tuple[str, float]] = []
    for timestamp, close in zip(timestamps, closes, strict=False):
        if close is None:
            continue
        day = datetime.fromtimestamp(int(timestamp), UTC).date()
        if start <= day <= end:
            prices.append((day.isoformat(), float(close)))
    return prices


def _nasdaq_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%m/%d/%Y").date()
    except ValueError:
        return None


def _date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _timestamp(value: date) -> int:
    return int(datetime(value.year, value.month, value.day, tzinfo=UTC).timestamp())


def _price(value: str | float | int | None) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace("$", "").replace(",", ""))
    except ValueError:
        return None


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
