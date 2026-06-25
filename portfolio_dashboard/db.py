from __future__ import annotations

from collections.abc import Iterable
from contextlib import contextmanager
from datetime import UTC, datetime
import json
from pathlib import Path
import sqlite3
from typing import Any

from .symbols import canonical_symbol


SCHEMA = """
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS accounts (
    account_id TEXT PRIMARY KEY,
    label TEXT,
    raw_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS account_assets (
    account_id TEXT PRIMARY KEY,
    net_aum REAL,
    raw_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS positions (
    strategy TEXT NOT NULL,
    account_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    quantity REAL NOT NULL,
    avg_price REAL,
    market_value REAL,
    raw_json TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (strategy, account_id, symbol)
);

CREATE TABLE IF NOT EXISTS orders (
    strategy TEXT NOT NULL,
    account_id TEXT NOT NULL,
    order_id TEXT NOT NULL,
    symbol TEXT,
    side TEXT,
    quantity REAL,
    filled_quantity REAL,
    avg_price REAL,
    status TEXT,
    placed_at TEXT,
    raw_json TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (strategy, account_id, order_id)
);

CREATE TABLE IF NOT EXISTS prices (
    symbol TEXT NOT NULL,
    date TEXT NOT NULL,
    close REAL NOT NULL,
    source TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (symbol, date)
);

CREATE TABLE IF NOT EXISTS sync_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Database:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def initialize(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA)

    def set_metadata(self, key: str, value: Any) -> None:
        payload = json.dumps(value, default=str)
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO sync_metadata (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                """,
                (key, payload, now),
            )

    def get_metadata(self, key: str) -> Any | None:
        with self.connect() as conn:
            row = conn.execute("SELECT value FROM sync_metadata WHERE key = ?", (key,)).fetchone()
        return json.loads(row["value"]) if row else None

    def upsert_accounts(self, accounts: Iterable[dict[str, Any]]) -> None:
        now = utc_now()
        with self.connect() as conn:
            for account in accounts:
                account_id = str(_first(account, "account_id", "accountId", "id", "secAccountId") or "")
                if not account_id:
                    continue
                label = str(_first(account, "name", "nickname", "accountType", "type") or account_id)
                conn.execute(
                    """
                    INSERT INTO accounts (account_id, label, raw_json, updated_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(account_id) DO UPDATE SET
                        label = excluded.label,
                        raw_json = excluded.raw_json,
                        updated_at = excluded.updated_at
                    """,
                    (account_id, label, json.dumps(account), now),
                )

    def upsert_account_assets(self, account_id: str, assets: dict[str, Any]) -> None:
        now = utc_now()
        net_aum = _first_float(
            assets,
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
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO account_assets (account_id, net_aum, raw_json, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(account_id) DO UPDATE SET
                    net_aum = excluded.net_aum,
                    raw_json = excluded.raw_json,
                    updated_at = excluded.updated_at
                """,
                (account_id, net_aum, json.dumps(assets), now),
            )

    def upsert_positions(self, strategy: str, account_id: str, positions: Iterable[dict[str, Any]]) -> None:
        now = utc_now()
        seen: set[str] = set()
        with self.connect() as conn:
            for position in positions:
                symbol = normalize_symbol(_first(position, "symbol", "ticker", "tickerSymbol", "instrumentSymbol"))
                if not symbol:
                    continue
                seen.add(symbol)
                conn.execute(
                    """
                    INSERT INTO positions
                        (strategy, account_id, symbol, quantity, avg_price, market_value, raw_json, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(strategy, account_id, symbol) DO UPDATE SET
                        quantity = excluded.quantity,
                        avg_price = excluded.avg_price,
                        market_value = excluded.market_value,
                        raw_json = excluded.raw_json,
                        updated_at = excluded.updated_at
                    """,
                    (
                        strategy,
                        account_id,
                        symbol,
                        _float(_first(position, "quantity", "qty", "position", "holdingQty")) or 0.0,
                        _float(_first(position, "avg_price", "avgPrice", "costPrice", "cost_price", "averagePrice")),
                        _float(_first(position, "market_value", "marketValue", "positionMarketValue")),
                        json.dumps(position),
                        now,
                    ),
                )
            if seen:
                placeholders = ",".join("?" for _ in seen)
                conn.execute(
                    f"""
                    DELETE FROM positions
                    WHERE strategy = ? AND account_id = ? AND symbol NOT IN ({placeholders})
                    """,
                    (strategy, account_id, *seen),
                )

    def upsert_orders(self, strategy: str, account_id: str, orders: Iterable[dict[str, Any]]) -> None:
        now = utc_now()
        with self.connect() as conn:
            for order in orders:
                order_id = str(_first(order, "order_id", "orderId", "id", "clientOrderId") or "")
                if not order_id:
                    continue
                symbol = normalize_symbol(_first(order, "symbol", "ticker", "tickerSymbol", "instrumentSymbol"))
                conn.execute(
                    """
                    INSERT INTO orders
                        (strategy, account_id, order_id, symbol, side, quantity, filled_quantity,
                         avg_price, status, placed_at, raw_json, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(strategy, account_id, order_id) DO UPDATE SET
                        symbol = excluded.symbol,
                        side = excluded.side,
                        quantity = excluded.quantity,
                        filled_quantity = excluded.filled_quantity,
                        avg_price = excluded.avg_price,
                        status = excluded.status,
                        placed_at = excluded.placed_at,
                        raw_json = excluded.raw_json,
                        updated_at = excluded.updated_at
                    """,
                    (
                        strategy,
                        account_id,
                        order_id,
                        symbol,
                        _side(_first(order, "side", "action", "orderSide")),
                        _float(_first(order, "quantity", "qty", "totalQuantity", "total_quantity")),
                        _float(_first(order, "filled_quantity", "filledQty", "filledQuantity", "executedQty")),
                        _float(_first(order, "avg_price", "avgPrice", "averagePrice", "filledAvgPrice", "filled_price", "price")),
                        str(_first(order, "status", "orderStatus") or ""),
                        _date_text(_first(order, "placed_at", "placedAt", "place_time_at", "createTime", "createdTime", "place_time", "time")),
                        json.dumps(order),
                        now,
                    ),
                )

    def upsert_prices(self, symbol: str, rows: Iterable[tuple[str, float]], source: str) -> None:
        now = utc_now()
        with self.connect() as conn:
            conn.executemany(
                """
                INSERT INTO prices (symbol, date, close, source, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(symbol, date) DO UPDATE SET
                    close = excluded.close,
                    source = excluded.source,
                    updated_at = excluded.updated_at
                """,
                [(symbol, date, close, source, now) for date, close in rows],
            )

    def fetch_accounts(self) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return list(conn.execute("SELECT * FROM accounts ORDER BY label"))

    def fetch_account_assets(self) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return list(conn.execute("SELECT * FROM account_assets ORDER BY account_id"))

    def fetch_positions(self, strategy: str) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return list(
                conn.execute(
                    "SELECT * FROM positions WHERE strategy = ? ORDER BY symbol",
                    (strategy,),
                )
            )

    def fetch_orders(self, strategy: str, start_date: str | None = None) -> list[sqlite3.Row]:
        params: list[str] = [strategy]
        date_filter = ""
        if start_date:
            date_filter = "AND (placed_at IS NULL OR placed_at >= ?)"
            params.append(start_date)
        with self.connect() as conn:
            return list(
                conn.execute(
                    f"""
                    SELECT * FROM orders
                    WHERE strategy = ?
                    {date_filter}
                    ORDER BY placed_at DESC, order_id DESC
                    """,
                    params,
                )
            )

    def fetch_strategies(self) -> list[str]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT strategy FROM positions
                UNION
                SELECT strategy FROM orders
                ORDER BY strategy
                """
            ).fetchall()
        return [row["strategy"] for row in rows if row["strategy"]]

    def fetch_price_rows(self, symbols: Iterable[str], start_date: str | None = None) -> list[sqlite3.Row]:
        symbol_list = sorted({s for s in symbols if s})
        if not symbol_list:
            return []
        params: list[str] = list(symbol_list)
        date_filter = ""
        if start_date:
            date_filter = "AND date >= ?"
            params.append(start_date)
        placeholders = ",".join("?" for _ in symbol_list)
        with self.connect() as conn:
            return list(
                conn.execute(
                    f"""
                    SELECT symbol, date, close
                    FROM prices
                    WHERE symbol IN ({placeholders})
                    {date_filter}
                    ORDER BY date, symbol
                    """,
                    params,
                )
            )


def normalize_symbol(value: Any) -> str:
    return canonical_symbol(value)


def _first(source: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in source and source[name] not in (None, ""):
            return source[name]
    for value in source.values():
        if isinstance(value, dict):
            nested = _first(value, *names)
            if nested not in (None, ""):
                return nested
    return None


def _float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _first_float(source: Any, *names: str) -> float | None:
    if isinstance(source, dict):
        for name in names:
            parsed = _float(source.get(name))
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


def _side(value: Any) -> str:
    side = str(value or "").upper()
    if "BUY" in side or side in {"B", "BOT"}:
        return "BUY"
    if "SELL" in side or side in {"S", "SLD"}:
        return "SELL"
    return side


def _date_text(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value)
    if text.isdigit() and len(text) >= 10:
        timestamp = int(text[:10])
        return datetime.fromtimestamp(timestamp, UTC).date().isoformat()
    return text[:10]
