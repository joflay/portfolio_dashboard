from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from . import DEFAULT_STRATEGY
from .config import Settings, load_settings
from .db import Database
from .market_data import load_symbol_prices
from .webull import WebullClient


@dataclass(frozen=True)
class SyncResult:
    ok: bool
    accounts: int
    positions: int
    orders: int
    prices: int
    error: str | None = None


def run_sync(settings: Settings | None = None) -> SyncResult:
    settings = settings or load_settings()
    db = Database(settings.database_path)
    db.initialize()
    client = WebullClient(settings)

    try:
        accounts = _load_local_accounts(settings)
        if not accounts:
            accounts = client.account_list()
        db.upsert_accounts(accounts)
        account_ids = [_account_id(account) for account in accounts]

        position_count = 0
        order_count = 0
        symbols: set[str] = set()
        for account_id in account_ids:
            if not account_id:
                continue
            positions = client.positions(account_id)
            orders = client.order_history(account_id)
            db.upsert_positions(DEFAULT_STRATEGY, account_id, positions)
            db.upsert_orders(DEFAULT_STRATEGY, account_id, orders)
            position_count += len(positions)
            order_count += len(orders)
            symbols.update(_symbols(positions))
            symbols.update(_symbols(orders))

        price_count = cache_prices(db, settings, symbols)
        result = SyncResult(True, len(accounts), position_count, order_count, price_count)
        db.set_metadata("last_sync", result.__dict__)
        return result
    except Exception as exc:
        result = SyncResult(False, 0, 0, 0, 0, str(exc))
        db.set_metadata("last_sync", result.__dict__)
        return result


def cache_prices(db: Database, settings: Settings, symbols: set[str]) -> int:
    written = 0
    for symbol in sorted(symbols):
        rows = load_symbol_prices(settings.market_data_dir, symbol)
        if rows:
            db.upsert_prices(symbol, rows, str(settings.market_data_dir / f"{symbol}_stock_data.csv"))
            written += len(rows)
    return written


def _account_id(account: dict[str, Any]) -> str:
    for key in ("account_id", "accountId", "id", "secAccountId"):
        if account.get(key):
            return str(account[key])
    return ""


def _load_local_accounts(settings: Settings) -> list[dict[str, Any]]:
    candidates = [
        settings.account_info_file,
        settings.account_info_file.with_name("accountinfo.txt"),
        settings.account_info_file.with_name("accouninfo.txt"),
    ]
    for path in candidates:
        if not path.exists():
            continue
        payload = json.loads(path.read_text())
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if isinstance(payload, dict):
            return [payload]
    return []


def _symbols(rows: list[dict[str, Any]]) -> set[str]:
    output: set[str] = set()
    for row in rows:
        for key in ("symbol", "ticker", "tickerSymbol", "instrumentSymbol"):
            value = row.get(key)
            if value:
                output.add(str(value).upper())
                break
    return output


def main() -> None:
    result = run_sync()
    if not result.ok:
        raise SystemExit(f"sync failed: {result.error}")
    print(
        "sync complete: "
        f"{result.accounts} accounts, {result.positions} positions, "
        f"{result.orders} orders, {result.prices} prices"
    )


if __name__ == "__main__":
    main()
