from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import json
from datetime import date, timedelta
from math import sqrt
from sqlite3 import Row
from typing import Any

from .risk_free import latest_rate_on_or_before
from .symbols import canonical_symbol


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
    rebalance_start_date: str | None = None,
    rebalance_days: int | None = None,
) -> dict[str, Any]:
    holdings = [_canonicalize_row_symbol(_row_dict(row)) for row in positions]
    fills = _extract_fills(orders)
    prices = _prices_by_date(price_rows)
    _append_current_position_marks(prices, holdings)
    symbols = sorted({h["symbol"] for h in holdings} | {f.symbol for f in fills})

    mark_based = bool(rebalance_start_date and holdings)
    if mark_based:
        equity_curve = _equity_from_rebalance_holdings(holdings, prices, str(rebalance_start_date)[:10])
    else:
        equity_curve = _equity_from_fills(fills, prices, symbols)
    if not equity_curve and holdings:
        equity_curve = _equity_from_current_holdings(holdings, prices)

    marked_holdings = _holdings_with_marks(holdings, prices)
    daily = _daily_rows(equity_curve, return_on_exposure=mark_based)
    risk_free_rates = risk_free_rates or {}
    summary = _summary(daily, marked_holdings, fills, risk_free_rates, prices)
    if rebalance_start_date:
        summary["rebalance_start_date"] = str(rebalance_start_date)[:10]
        summary["rebalance_days"] = rebalance_days
        summary["next_rebalance_date"] = _next_rebalance_date(str(rebalance_start_date)[:10], rebalance_days)
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
        fills.append(Fill(str(placed_at)[:10], canonical_symbol(symbol), side, qty, price, str(item.get("order_id") or "")))
    return fills


def _prices_by_date(price_rows: list[Row | dict[str, Any]]) -> dict[str, dict[str, float]]:
    prices: dict[str, dict[str, float]] = defaultdict(dict)
    for row in price_rows:
        item = _row_dict(row)
        close = _float(item.get("close"))
        if item.get("date") and item.get("symbol") and close is not None:
            prices[str(item["date"])[:10]][canonical_symbol(item["symbol"])] = close
    return dict(sorted(prices.items()))


def _append_current_position_marks(
    prices: dict[str, dict[str, float]],
    holdings: list[dict[str, Any]],
) -> None:
    today = date.today().isoformat()
    marks = prices.setdefault(today, {})
    for holding in holdings:
        symbol = holding.get("symbol")
        if not symbol:
            continue
        mark = _position_mark(holding)
        if mark is not None:
            marks[canonical_symbol(symbol)] = mark


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


def _equity_from_rebalance_holdings(
    holdings: list[dict[str, Any]],
    prices: dict[str, dict[str, float]],
    rebalance_start_date: str,
) -> list[tuple[str, float, float, float, float]]:
    quantities = {row["symbol"]: _float(row.get("quantity")) or 0.0 for row in holdings}
    baseline_marks = _cost_basis_marks(holdings)
    symbols = sorted(quantities)
    curve: list[tuple[str, float, float, float, float]] = []
    last_marks: dict[str, float] = {}
    for day, marks in prices.items():
        if day < rebalance_start_date:
            continue
        last_marks.update(marks)
        if day == rebalance_start_date:
            day_marks = {symbol: baseline_marks.get(symbol, last_marks.get(symbol)) for symbol in symbols}
        else:
            day_marks = {symbol: last_marks.get(symbol, baseline_marks.get(symbol)) for symbol in symbols}
        if any(mark is None for mark in day_marks.values()):
            continue
        market_values = [quantities[symbol] * float(day_marks[symbol]) for symbol in symbols]
        value = sum(market_values)
        long_value = sum(market_value for market_value in market_values if market_value > 0)
        short_value = sum(market_value for market_value in market_values if market_value < 0)
        curve.append((day, value, sum(abs(market_value) for market_value in market_values), long_value, short_value))
    return curve


def _cost_basis_marks(holdings: list[dict[str, Any]]) -> dict[str, float]:
    marks: dict[str, float] = {}
    for holding in holdings:
        symbol = holding.get("symbol")
        qty = _float(holding.get("quantity")) or 0.0
        cost = _position_cost(holding)
        if symbol and qty != 0 and cost is not None:
            marks[symbol] = cost / qty
            continue
        avg_price = _float(holding.get("avg_price"))
        if symbol and avg_price is not None:
            marks[symbol] = avg_price
    return marks


def _daily_rows(
    equity_curve: list[tuple[str, float] | tuple[str, float, float] | tuple[str, float, float, float, float]],
    return_on_exposure: bool = False,
) -> list[dict[str, float | str | None]]:
    rows: list[dict[str, float | str | None]] = []
    peak: float | None = None
    prior: float | None = None
    prior_long: float | None = None
    prior_short: float | None = None
    for point in equity_curve:
        day = point[0]
        equity = point[1]
        exposure = point[2] if len(point) > 2 else None
        long_value = point[3] if len(point) > 3 else None
        short_value = point[4] if len(point) > 4 else None
        pnl = 0.0 if prior is None else equity - prior
        long_pnl = None if long_value is None or prior_long is None else long_value - prior_long
        short_pnl = None if short_value is None or prior_short is None else short_value - prior_short
        return_denominator = exposure if return_on_exposure else prior
        daily_return = 0.0 if return_denominator in (None, 0.0) else pnl / abs(return_denominator)
        long_return = None if long_pnl is None or long_value in (None, 0.0) else long_pnl / abs(long_value)
        short_return = None if short_pnl is None or short_value in (None, 0.0) else short_pnl / abs(short_value)
        peak = equity if peak is None else max(peak, equity)
        drawdown_dollars = equity - peak
        drawdown_denominator = exposure if return_on_exposure else peak
        drawdown = 0.0 if drawdown_denominator in (None, 0.0) else drawdown_dollars / abs(drawdown_denominator)
        rows.append(
            {
                "date": day,
                "equity": round(equity, 4),
                "daily_pnl": round(pnl, 4),
                "daily_return": round(daily_return, 8),
                "long_return": round(long_return, 8) if long_return is not None else None,
                "short_return": round(short_return, 8) if short_return is not None else None,
                "drawdown": round(drawdown, 8),
            }
        )
        prior = equity
        prior_long = long_value
        prior_short = short_value
    return rows


def _summary(
    daily: list[dict[str, Any]],
    holdings: list[dict[str, Any]],
    fills: list[Fill],
    risk_free_rates: dict[str, float],
    prices: dict[str, dict[str, float]],
) -> dict[str, Any]:
    excess_returns = _daily_excess_returns(daily, risk_free_rates)
    synthetic_latest_equity = float(daily[-1]["equity"]) if daily else 0.0
    start_equity = float(daily[0]["equity"]) if daily else 0.0
    max_drawdown = min((float(row["drawdown"]) for row in daily), default=0.0)
    current_drawdown = float(daily[-1]["drawdown"]) if daily else 0.0
    latest_rf = latest_rate_on_or_before(risk_free_rates, str(daily[-1]["date"])) if daily else None
    net_exposure = sum(float(row.get("market_value") or 0.0) for row in holdings)
    gross_exposure = sum(abs(float(row.get("market_value") or 0.0)) for row in holdings)
    synthetic_total_pnl = synthetic_latest_equity - start_equity if daily else 0.0
    synthetic_daily_pnl = float(daily[-1]["daily_pnl"]) if daily else 0.0
    latest_equity = synthetic_latest_equity
    total_pnl = synthetic_total_pnl
    daily_pnl = synthetic_daily_pnl
    daily_return = _exposure_return(daily_pnl, gross_exposure)
    total_return = _exposure_return(total_pnl, gross_exposure)
    latest_date = str(daily[-1]["date"]) if daily else None
    previous_date = str(daily[-2]["date"]) if len(daily) > 1 else None
    spy_daily_return = _symbol_daily_return(prices, "SPY", previous_date, latest_date)
    spy_total_return = (
        _symbol_return(prices, "SPY", str(daily[0]["date"]), str(daily[-1]["date"])) if daily else None
    )
    return {
        "net_exposure": round(net_exposure, 2),
        "gross_exposure": round(gross_exposure, 2),
        "net_aum": round(net_exposure, 2),
        "latest_equity": round(latest_equity, 2),
        "total_pnl": round(total_pnl, 2),
        "daily_pnl": round(daily_pnl, 2),
        "total_return": round(total_return, 8),
        "daily_return": round(daily_return, 8),
        "spy_daily_return": round(spy_daily_return, 8) if spy_daily_return is not None else None,
        "spy_total_return": round(spy_total_return, 8) if spy_total_return is not None else None,
        "daily_return_over_spy": (
            round(daily_return - spy_daily_return, 8) if spy_daily_return is not None else None
        ),
        "total_return_over_spy": (
            round(total_return - spy_total_return, 8) if spy_total_return is not None else None
        ),
        "max_drawdown": round(max_drawdown, 6),
        "current_drawdown": round(current_drawdown, 6),
        "sharpe": round(_sharpe(excess_returns), 4),
        "risk_free_rate": round(latest_rf, 6) if latest_rf is not None else None,
        "open_positions": len(holdings),
        "trade_count": len(fills),
        "history_start": daily[0]["date"] if daily else None,
        "history_end": daily[-1]["date"] if daily else None,
    }


def _exposure_return(pnl: float, gross_exposure: float) -> float:
    return 0.0 if gross_exposure == 0 else pnl / gross_exposure


def _symbol_daily_return(
    prices: dict[str, dict[str, float]],
    symbol: str,
    previous_date: str | None,
    latest_date: str | None,
) -> float | None:
    if not previous_date or not latest_date:
        return None
    previous = prices.get(previous_date, {}).get(symbol)
    latest = prices.get(latest_date, {}).get(symbol)
    if previous is None or latest is None:
        return None
    return None if previous == 0 else (latest - previous) / abs(previous)


def _symbol_return(prices: dict[str, dict[str, float]], symbol: str, start_date: str, end_date: str) -> float | None:
    closes = [marks[symbol] for day, marks in prices.items() if start_date <= day <= end_date and symbol in marks]
    if len(closes) < 2:
        return None
    first = closes[0]
    latest = closes[-1]
    return None if first == 0 else (latest - first) / abs(first)


def _next_rebalance_date(start_date: str, rebalance_days: int | None) -> str | None:
    if not rebalance_days:
        return None
    try:
        return (date.fromisoformat(start_date) + timedelta(days=rebalance_days)).isoformat()
    except ValueError:
        return None


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
        avg_price = _float(holding.get("avg_price"))
        output.append(
            {
                "symbol": symbol,
                "quantity": qty,
                "avg_price": avg_price,
                "market_value": round(qty * mark, 2),
                "last_price": mark,
                "return": _holding_return(qty, avg_price, mark),
                "price_date": marked[0] if marked else None,
                "day_profit_loss": _first_float(
                    holding,
                    "day_profit_loss",
                    "dayProfitLoss",
                    "day_pnl",
                    "dayPnl",
                    "today_profit_loss",
                    "todayProfitLoss",
                ),
                "unrealized_profit_loss": _first_float(
                    holding,
                    "unrealized_profit_loss",
                    "unrealizedProfitLoss",
                    "unrealized_pnl",
                    "unrealizedPnl",
                ),
            }
        )
    return output


def _position_mark(holding: dict[str, Any]) -> float | None:
    mark = _first_float(
        holding,
        "last_price",
        "lastPrice",
        "mark_price",
        "markPrice",
        "current_price",
        "currentPrice",
    )
    if mark is not None:
        return mark
    market_value = _first_float(holding, "market_value", "marketValue", "positionMarketValue")
    qty = _float(holding.get("quantity")) or 0.0
    if market_value is not None and qty != 0:
        return market_value / qty
    return None


def _position_cost(holding: dict[str, Any]) -> float | None:
    cost = _first_float(holding, "cost", "total_cost", "totalCost", "cost_basis", "costBasis")
    if cost is not None:
        return cost
    qty = _float(holding.get("quantity")) or 0.0
    avg_price = _float(holding.get("avg_price"))
    if avg_price is not None:
        return qty * avg_price
    return None


def _holding_return(quantity: float, avg_price: float | None, mark: float) -> float | None:
    if avg_price in (None, 0.0):
        return None
    direction = 1 if quantity >= 0 else -1
    return round(((mark - avg_price) / abs(avg_price)) * direction, 8)


def _first_float(source: Any, *names: str) -> float | None:
    if isinstance(source, dict):
        for name in names:
            value = _float(source.get(name))
            if value is not None:
                return value
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
    item = dict(row)
    raw_json = item.get("raw_json")
    if not raw_json:
        return item
    try:
        payload = json.loads(str(raw_json))
    except (TypeError, ValueError):
        return item
    if not isinstance(payload, dict):
        return item
    return {**payload, **item}


def _canonicalize_row_symbol(item: dict[str, Any]) -> dict[str, Any]:
    if item.get("symbol"):
        return {**item, "symbol": canonical_symbol(item["symbol"])}
    return item


def _float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None
