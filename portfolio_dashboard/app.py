from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import DEFAULT_STRATEGY
from .analytics import build_performance
from .config import load_settings
from .db import Database
from .risk_free import load_risk_free_rates
from .symbols import canonical_symbol, lookup_symbols
from .sync import cache_prices, run_sync


settings = load_settings()
db = Database(settings.database_path)
app = FastAPI(title="Portfolio Strategy Dashboard API")
BENCHMARK_SYMBOL = "SPY"

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup() -> None:
    db.initialize()
    asyncio.create_task(_periodic_sync())


@app.get("/")
def api_index() -> dict[str, Any]:
    return {
        "name": "Portfolio Strategy Dashboard API",
        "frontend": "Run the Next.js app from ./frontend",
        "strategy": DEFAULT_STRATEGY,
        "routes": [
            "/health",
            "/sync",
            "/api/dashboard",
            "/api/strategies",
            f"/api/strategies/{DEFAULT_STRATEGY}/performance",
        ],
    }


@app.get("/health")
def health() -> dict[str, Any]:
    db.initialize()
    return {
        "ok": True,
        "strategy": DEFAULT_STRATEGY,
        "database": str(settings.database_path),
        "market_data_dir": str(settings.market_data_dir),
        "risk_free_rate_file": str(settings.risk_free_rate_file),
        "strategy_start_date": settings.strategy_start_date,
        "last_sync": db.get_metadata("last_sync"),
    }


@app.post("/sync")
def manual_sync() -> dict[str, Any]:
    result = run_sync(settings)
    return result.__dict__


@app.get("/api/dashboard")
def dashboard_api() -> dict[str, Any]:
    strategies = [_performance(strategy) for strategy in _strategy_names()]
    return {
        "account_summary": _account_summary(strategies, db.fetch_accounts(), db.fetch_account_assets()),
        "strategies": strategies,
    }


@app.get("/api/strategies")
def strategies_api() -> dict[str, Any]:
    return {"strategies": _strategy_names()}


@app.get("/api/strategies/{strategy}/performance")
def performance_api(strategy: str) -> dict[str, Any]:
    return _performance(strategy)


async def _periodic_sync() -> None:
    while True:
        await asyncio.sleep(max(settings.sync_interval_minutes, 1) * 60)
        await asyncio.to_thread(run_sync, settings)


def _strategy_names() -> list[str]:
    db.initialize()
    names = db.fetch_strategies()
    return names or [DEFAULT_STRATEGY]


def _performance(strategy: str) -> dict[str, Any]:
    db.initialize()
    positions = db.fetch_positions(strategy)
    orders = db.fetch_orders(strategy, settings.strategy_start_date)
    symbols = {canonical_symbol(row["symbol"]) for row in positions if row["symbol"]}
    symbols.update(canonical_symbol(row["symbol"]) for row in orders if row["symbol"])
    cache_symbols = symbols | {BENCHMARK_SYMBOL}
    if cache_symbols:
        cache_prices(db, settings, cache_symbols)
    price_symbols = lookup_symbols(cache_symbols)
    prices = [dict(row) for row in db.fetch_price_rows(price_symbols, settings.strategy_start_date)]
    risk_free_rates = load_risk_free_rates(settings.risk_free_rate_file)
    return build_performance(
        positions,
        orders,
        prices,
        risk_free_rates,
        strategy=strategy,
        rebalance_start_date=settings.strategy_rebalance_start_date,
        rebalance_days=settings.strategy_rebalance_days,
    )


def _account_summary(strategies: list[dict[str, Any]], accounts: list[Any], account_assets: list[Any]) -> dict[str, Any]:
    summaries = [strategy["summary"] for strategy in strategies]
    history_starts = [summary["history_start"] for summary in summaries if summary["history_start"]]
    history_ends = [summary["history_end"] for summary in summaries if summary["history_end"]]
    account_net_aum_values = [_asset_net_aum(asset) for asset in account_assets]
    if not any(value is not None for value in account_net_aum_values):
        account_net_aum_values = [_account_net_aum(account) for account in accounts]
    account_net_aum_values = [value for value in account_net_aum_values if value is not None]
    net_exposure = round(sum(float(summary.get("net_exposure") or summary.get("net_aum") or 0.0) for summary in summaries), 2)
    gross_exposure = round(sum(float(summary.get("gross_exposure") or 0.0) for summary in summaries), 2)
    broker_pnl = _account_broker_pnl(account_assets)
    strategy_latest_equity = sum(float(summary.get("latest_equity") or 0.0) for summary in summaries)
    strategy_daily_pnl = sum(float(summary.get("daily_pnl") or 0.0) for summary in summaries)
    strategy_total_pnl = sum(float(summary.get("total_pnl") or 0.0) for summary in summaries)
    latest_equity = round(
        broker_pnl["unrealized"] if broker_pnl["unrealized"] is not None else strategy_latest_equity,
        2,
    )
    daily_pnl = round(broker_pnl["daily"] if broker_pnl["daily"] is not None else strategy_daily_pnl, 2)
    total_pnl = round(broker_pnl["unrealized"] if broker_pnl["unrealized"] is not None else strategy_total_pnl, 2)
    net_aum = round(sum(account_net_aum_values), 2) if account_net_aum_values else None
    return_baseline = net_aum if net_aum not in (None, 0.0) else gross_exposure
    daily_return = _exposure_return(daily_pnl, return_baseline)
    total_return = _exposure_return(total_pnl, return_baseline)
    spy_daily_return = _first_summary_float(summaries, "spy_daily_return")
    spy_total_return = _first_summary_float(summaries, "spy_total_return")
    return {
        "net_aum": net_aum,
        "net_aum_in_db": bool(account_net_aum_values),
        "net_exposure": net_exposure,
        "gross_exposure": gross_exposure,
        "latest_equity": latest_equity,
        "daily_pnl": daily_pnl,
        "total_pnl": total_pnl,
        "daily_return": round(daily_return, 8),
        "total_return": round(total_return, 8),
        "spy_daily_return": round(spy_daily_return, 8) if spy_daily_return is not None else None,
        "spy_total_return": round(spy_total_return, 8) if spy_total_return is not None else None,
        "daily_return_over_spy": (
            round(daily_return - spy_daily_return, 8) if spy_daily_return is not None else None
        ),
        "total_return_over_spy": (
            round(total_return - spy_total_return, 8) if spy_total_return is not None else None
        ),
        "max_drawdown": min((float(summary.get("max_drawdown") or 0.0) for summary in summaries), default=0.0),
        "open_positions": sum(int(summary.get("open_positions") or 0) for summary in summaries),
        "trade_count": sum(int(summary.get("trade_count") or 0) for summary in summaries),
        "account_count": len(accounts),
        "account_asset_count": len(account_assets),
        "strategy_count": len(strategies),
        "history_start": min(history_starts) if history_starts else None,
        "history_end": max(history_ends) if history_ends else None,
    }


def _exposure_return(pnl: float, gross_exposure: float) -> float:
    return 0.0 if gross_exposure == 0 else pnl / gross_exposure


def _first_summary_float(summaries: list[dict[str, Any]], key: str) -> float | None:
    for summary in summaries:
        value = _float(summary.get(key))
        if value is not None:
            return value
    return None


def _asset_net_aum(asset: Any) -> float | None:
    if "net_aum" in asset.keys():
        direct = _float(asset["net_aum"])
        if direct is not None:
            return direct
    raw_json = asset["raw_json"] if "raw_json" in asset.keys() else None
    if not raw_json:
        return None
    try:
        payload = json.loads(raw_json)
    except (TypeError, ValueError):
        return None
    return _net_aum_from_payload(payload)


def _account_net_aum(account: Any) -> float | None:
    raw_json = account["raw_json"] if "raw_json" in account.keys() else None
    if not raw_json:
        return None
    try:
        payload = json.loads(raw_json)
    except (TypeError, ValueError):
        return None
    return _net_aum_from_payload(payload)


def _net_aum_from_payload(payload: Any) -> float | None:
    return _first_float(
        payload,
        "net_aum",
        "netAum",
        "net_liquidation",
        "netLiquidation",
        "netLiquidationValue",
        "net_liquidation_value",
        "total_net_liquidation_value",
        "account_value",
        "accountValue",
        "total_equity",
        "totalEquity",
        "total_asset",
        "totalAsset",
        "portfolio_value",
        "portfolioValue",
    )


def _account_broker_pnl(account_assets: list[Any]) -> dict[str, float | None]:
    daily_values: list[float] = []
    unrealized_values: list[float] = []
    for asset in account_assets:
        payload = _asset_payload(asset)
        if payload is None:
            continue
        daily = _first_float(
            payload,
            "total_day_profit_loss",
            "totalDayProfitLoss",
            "day_profit_loss",
            "dayProfitLoss",
        )
        unrealized = _first_float(
            payload,
            "total_unrealized_profit_loss",
            "totalUnrealizedProfitLoss",
            "unrealized_profit_loss",
            "unrealizedProfitLoss",
        )
        if daily is not None:
            daily_values.append(daily)
        if unrealized is not None:
            unrealized_values.append(unrealized)
    return {
        "daily": sum(daily_values) if daily_values else None,
        "unrealized": sum(unrealized_values) if unrealized_values else None,
    }


def _asset_payload(asset: Any) -> Any | None:
    raw_json = asset["raw_json"] if "raw_json" in asset.keys() else None
    if not raw_json:
        return None
    try:
        payload = json.loads(raw_json)
    except (TypeError, ValueError):
        return None
    return payload.get("payload", payload) if isinstance(payload, dict) else payload


def _first_float(source: Any, *names: str) -> float | None:
    if isinstance(source, dict):
        for name in names:
            value = source.get(name)
            parsed = _float(value)
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
