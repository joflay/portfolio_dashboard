from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from math import sqrt
from sqlite3 import Row
from typing import Any

from .risk_free import latest_rate_on_or_before


@dataclass(frozen=True)
class Fill:
    date: str
    symbol: str
    side: str
    quantity: float
    price: float
    order_id: str


def build_performance(
    positions: list[Row | dict[str, Any]],
    orders: list[Row | dict[str, Any]],
    price_rows: list[Row | dict[str, Any]],
    risk_free_rates: dict[str, float] | None = None,
    strategy: str = "Vol_Factor",
) -> dict[str, Any]:
    holdings = [_row_dict(row) for row in positions]
    fills = _extract_fills(orders)
    prices = _prices_by_date(price_rows)
    symbols = sorted({h["symbol"] for h in holdings} | {f.symbol for f in fills})

    equity_curve = _equity_from_fills(fills, prices, symbols)
    if not equity_curve and holdings:
        equity_curve = _equity_from_current_holdings(holdings, prices)

    daily = _daily_rows(equity_curve)
    marked_holdings = _holdings_with_marks(holdings, prices)
    risk_free_rates = risk_free_rates or {}
    summary = _summary(daily, marked_holdings, fills, risk_free_rates)
    return {
        "strategy": strategy,
        "summary": summary,
        "equity_curve": daily,
        "drawdown_curve": [{"date": row["date"], "drawdown": row["drawdown"]} for row in daily],
        "holdings": marked_holdings,
        "trades": [_trade_dict(fill) for fill in sorted(fills, key=lambda f: f.date, reverse=True)],
    }


def _extract_fills(orders: list[Row | dict[str, Any]]) -> list[Fill]:
    fills: list[Fill] = []
    for row in orders:
        item = _row_dict(row)
        symbol = item.get("symbol")
        side = (item.get("side") or "").upper()
        qty = _float(item.get("filled_quantity")) or _float(item.get("quantity")) or 0.0
        price = _float(item.get("avg_price")) or 0.0
        placed_at = item.get("placed_at")
        status = (item.get("status") or "").upper()
        if not symbol or side not in {"BUY", "SELL"} or qty <= 0 or price <= 0 or not placed_at:
            continue
        if status and not any(word in status for word in ("FILLED", "EXECUTED", "COMPLETE", "CLOSED")):
            continue
        fills.append(Fill(str(placed_at)[:10], symbol, side, qty, price, str(item.get("order_id") or "")))
    return fills


def _prices_by_date(price_rows: list[Row | dict[str, Any]]) -> dict[str, dict[str, float]]:
    prices: dict[str, dict[str, float]] = defaultdict(dict)
    for row in price_rows:
        item = _row_dict(row)
        close = _float(item.get("close"))
        if item.get("date") and item.get("symbol") and close is not None:
            prices[str(item["date"])[:10]][str(item["symbol"])] = close
    return dict(sorted(prices.items()))


def _equity_from_fills(
    fills: list[Fill],
    prices: dict[str, dict[str, float]],
    symbols: list[str],
) -> list[tuple[str, float]]:
    if not fills or not prices:
        return []
    fills_by_date: dict[str, list[Fill]] = defaultdict(list)
    for fill in fills:
        fills_by_date[fill.date].append(fill)

    first_date = min(fill.date for fill in fills)
    cash = 0.0
    quantities = {symbol: 0.0 for symbol in symbols}
    last_marks: dict[str, float] = {}
    curve: list[tuple[str, float]] = []

    for day, marks in prices.items():
        if day < first_date:
            continue
        for fill in fills_by_date.get(day, []):
            signed_qty = fill.quantity if fill.side == "BUY" else -fill.quantity
            quantities[fill.symbol] = quantities.get(fill.symbol, 0.0) + signed_qty
            cash -= signed_qty * fill.price
        last_marks.update(marks)
        market_value = sum(qty * last_marks.get(symbol, 0.0) for symbol, qty in quantities.items())
        curve.append((day, cash + market_value))
    return curve


def _equity_from_current_holdings(
    holdings: list[dict[str, Any]],
    prices: dict[str, dict[str, float]],
) -> list[tuple[str, float]]:
    quantities = {row["symbol"]: _float(row.get("quantity")) or 0.0 for row in holdings}
    curve: list[tuple[str, float]] = []
    last_marks: dict[str, float] = {}
    for day, marks in prices.items():
        last_marks.update(marks)
        value = sum(qty * last_marks.get(symbol, 0.0) for symbol, qty in quantities.items())
        if value:
            curve.append((day, value))
    return curve


def _daily_rows(equity_curve: list[tuple[str, float]]) -> list[dict[str, float | str]]:
    rows: list[dict[str, float | str]] = []
    peak: float | None = None
    prior: float | None = None
    for day, equity in equity_curve:
        pnl = 0.0 if prior is None else equity - prior
        daily_return = 0.0 if prior in (None, 0.0) else pnl / abs(prior)
        peak = equity if peak is None else max(peak, equity)
        drawdown = 0.0 if not peak else (equity - peak) / abs(peak)
        rows.append(
            {
                "date": day,
                "equity": round(equity, 4),
                "daily_pnl": round(pnl, 4),
                "daily_return": round(daily_return, 8),
                "drawdown": round(drawdown, 8),
            }
        )
        prior = equity
    return rows


def _summary(
    daily: list[dict[str, Any]],
    holdings: list[dict[str, Any]],
    fills: list[Fill],
    risk_free_rates: dict[str, float],
) -> dict[str, Any]:
    excess_returns = _daily_excess_returns(daily, risk_free_rates)
    latest_equity = float(daily[-1]["equity"]) if daily else 0.0
    start_equity = float(daily[0]["equity"]) if daily else 0.0
    max_drawdown = min((float(row["drawdown"]) for row in daily), default=0.0)
    latest_rf = latest_rate_on_or_before(risk_free_rates, str(daily[-1]["date"])) if daily else None
    net_exposure = sum(float(row.get("market_value") or 0.0) for row in holdings)
    return {
        "net_exposure": round(net_exposure, 2),
        "net_aum": round(net_exposure, 2),
        "latest_equity": round(latest_equity, 2),
        "total_pnl": round(latest_equity - start_equity, 2) if daily else 0.0,
        "daily_pnl": round(float(daily[-1]["daily_pnl"]), 2) if daily else 0.0,
        "max_drawdown": round(max_drawdown, 6),
        "sharpe": round(_sharpe(excess_returns), 4),
        "risk_free_rate": round(latest_rf, 6) if latest_rf is not None else None,
        "open_positions": len(holdings),
        "trade_count": len(fills),
        "history_start": daily[0]["date"] if daily else None,
        "history_end": daily[-1]["date"] if daily else None,
    }


def _daily_excess_returns(daily: list[dict[str, Any]], risk_free_rates: dict[str, float]) -> list[float]:
    excess: list[float] = []
    for row in daily[1:]:
        daily_return = row.get("daily_return")
        if daily_return is None:
            continue
        annual_rate = latest_rate_on_or_before(risk_free_rates, str(row["date"])) or 0.0
        excess.append(float(daily_return) - (annual_rate / 252))
    return excess


def _sharpe(daily_returns: list[float]) -> float:
    if len(daily_returns) < 2:
        return 0.0
    mean = sum(daily_returns) / len(daily_returns)
    variance = sum((value - mean) ** 2 for value in daily_returns) / (len(daily_returns) - 1)
    stddev = sqrt(variance)
    return 0.0 if stddev == 0 else (mean / stddev) * sqrt(252)


def _holdings_with_marks(
    holdings: list[dict[str, Any]],
    prices: dict[str, dict[str, float]],
) -> list[dict[str, Any]]:
    latest_by_symbol: dict[str, tuple[str, float]] = {}
    for day, marks in prices.items():
        for symbol, close in marks.items():
            latest_by_symbol[symbol] = (day, close)

    output: list[dict[str, Any]] = []
    for holding in holdings:
        symbol = holding["symbol"]
        qty = _float(holding.get("quantity")) or 0.0
        marked = latest_by_symbol.get(symbol)
        mark = marked[1] if marked else _float(holding.get("avg_price")) or 0.0
        output.append(
            {
                "symbol": symbol,
                "quantity": qty,
                "avg_price": _float(holding.get("avg_price")),
                "market_value": round(qty * mark, 2),
                "last_price": mark,
                "price_date": marked[0] if marked else None,
            }
        )
    return output


def _trade_dict(fill: Fill) -> dict[str, Any]:
    signed_notional = fill.quantity * fill.price * (1 if fill.side == "SELL" else -1)
    return {
        "date": fill.date,
        "symbol": fill.symbol,
        "side": fill.side,
        "quantity": fill.quantity,
        "price": fill.price,
        "notional": round(signed_notional, 2),
        "order_id": fill.order_id,
    }


def _row_dict(row: Row | dict[str, Any]) -> dict[str, Any]:
    return dict(row)


def _float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None
