from __future__ import annotations

import asyncio
from html import escape
from typing import Any

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, RedirectResponse

from . import DEFAULT_STRATEGY
from .analytics import build_performance
from .config import load_settings
from .db import Database
from .sync import cache_prices, run_sync


settings = load_settings()
db = Database(settings.database_path)
app = FastAPI(title="Portfolio Strategy Dashboard")


@app.on_event("startup")
async def startup() -> None:
    db.initialize()
    asyncio.create_task(_periodic_sync())


@app.get("/health")
def health() -> dict[str, Any]:
    db.initialize()
    return {
        "ok": True,
        "strategy": DEFAULT_STRATEGY,
        "database": str(settings.database_path),
        "market_data_dir": str(settings.market_data_dir),
        "last_sync": db.get_metadata("last_sync"),
    }


@app.post("/sync")
def manual_sync() -> RedirectResponse:
    run_sync(settings)
    return RedirectResponse("/", status_code=303)


@app.get("/api/strategies/Vol_Factor/performance")
def performance_api() -> dict[str, Any]:
    return _performance()


@app.get("/", response_class=HTMLResponse)
def dashboard() -> HTMLResponse:
    data = _performance()
    summary = data["summary"]
    last_sync = db.get_metadata("last_sync")
    html = _render_dashboard(data, summary, last_sync)
    return HTMLResponse(html)


async def _periodic_sync() -> None:
    while True:
        await asyncio.sleep(max(settings.sync_interval_minutes, 1) * 60)
        await asyncio.to_thread(run_sync, settings)


def _performance() -> dict[str, Any]:
    db.initialize()
    positions = db.fetch_positions(DEFAULT_STRATEGY)
    orders = db.fetch_orders(DEFAULT_STRATEGY)
    symbols = {row["symbol"] for row in positions if row["symbol"]}
    symbols.update(row["symbol"] for row in orders if row["symbol"])
    if symbols:
        cache_prices(db, settings, symbols)
    prices = db.fetch_price_rows(symbols)
    return build_performance(positions, orders, prices)


def _render_dashboard(data: dict[str, Any], summary: dict[str, Any], last_sync: Any) -> str:
    equity = data["equity_curve"]
    holdings = data["holdings"]
    trades = data["trades"]
    daily = list(reversed(equity[-30:]))
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Vol_Factor Dashboard</title>
  <style>
    :root {{
      color-scheme: light;
      --ink: #18202a;
      --muted: #657285;
      --line: #d9e0e8;
      --panel: #f7f9fb;
      --accent: #0f766e;
      --warn: #b42318;
      --bg: #ffffff;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: var(--bg);
      color: var(--ink);
    }}
    header {{
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: center;
      padding: 24px clamp(16px, 4vw, 40px);
      border-bottom: 1px solid var(--line);
    }}
    h1 {{ margin: 0; font-size: clamp(24px, 3vw, 38px); letter-spacing: 0; }}
    h2 {{ margin: 0 0 12px; font-size: 18px; letter-spacing: 0; }}
    p {{ margin: 4px 0 0; color: var(--muted); }}
    main {{ padding: 24px clamp(16px, 4vw, 40px) 40px; }}
    button {{
      border: 1px solid var(--accent);
      background: var(--accent);
      color: white;
      min-height: 38px;
      padding: 0 14px;
      border-radius: 6px;
      font-weight: 700;
      cursor: pointer;
    }}
    .metrics {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
      gap: 12px;
      margin-bottom: 24px;
    }}
    .metric {{
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
      background: var(--panel);
      min-height: 92px;
    }}
    .metric span {{ color: var(--muted); font-size: 13px; }}
    .metric strong {{ display: block; margin-top: 8px; font-size: 24px; }}
    .grid {{
      display: grid;
      grid-template-columns: minmax(0, 1.4fr) minmax(320px, 0.8fr);
      gap: 20px;
      align-items: start;
    }}
    section {{ margin-bottom: 24px; }}
    .chart {{
      width: 100%;
      height: 320px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: white;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: hidden;
      font-size: 14px;
    }}
    th, td {{ padding: 10px 12px; border-bottom: 1px solid var(--line); text-align: right; }}
    th:first-child, td:first-child {{ text-align: left; }}
    th {{ background: var(--panel); color: var(--muted); font-weight: 700; }}
    tr:last-child td {{ border-bottom: 0; }}
    .negative {{ color: var(--warn); }}
    .empty {{ border: 1px dashed var(--line); border-radius: 8px; padding: 24px; color: var(--muted); }}
    @media (max-width: 900px) {{
      header {{ align-items: flex-start; flex-direction: column; }}
      .grid {{ grid-template-columns: 1fr; }}
      th, td {{ padding: 8px; }}
    }}
  </style>
</head>
<body>
  <header>
    <div>
      <h1>Vol_Factor</h1>
      <p>Strategy performance from Webull activity and local market marks.</p>
      <p>Last sync: {escape(str(last_sync or "not run"))}</p>
    </div>
    <form method="post" action="/sync"><button type="submit">Refresh</button></form>
  </header>
  <main>
    <div class="metrics">
      {_metric("Latest Equity", _money(summary["latest_equity"]))}
      {_metric("Daily PnL", _money(summary["daily_pnl"]), summary["daily_pnl"] < 0)}
      {_metric("Total PnL", _money(summary["total_pnl"]), summary["total_pnl"] < 0)}
      {_metric("Max Drawdown", _pct(summary["max_drawdown"]), True)}
      {_metric("Sharpe", f'{summary["sharpe"]:.2f}')}
      {_metric("Trades", str(summary["trade_count"]))}
    </div>
    <div class="grid">
      <div>
        <section>
          <h2>Equity and Drawdown</h2>
          {_chart(equity)}
        </section>
        <section>
          <h2>Daily Performance</h2>
          {_daily_table(daily)}
        </section>
      </div>
      <div>
        <section>
          <h2>Holdings</h2>
          {_holdings_table(holdings)}
        </section>
        <section>
          <h2>Trade History</h2>
          {_trades_table(trades[:20])}
        </section>
      </div>
    </div>
  </main>
</body>
</html>"""


def _metric(label: str, value: str, negative: bool = False) -> str:
    klass = "negative" if negative else ""
    return f'<div class="metric"><span>{escape(label)}</span><strong class="{klass}">{escape(value)}</strong></div>'


def _chart(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return '<div class="empty">No performance history yet. Run a sync after Webull endpoint paths are configured.</div>'
    points = ",".join(f"{row['equity']}" for row in rows[-180:])
    drawdowns = ",".join(f"{abs(float(row['drawdown']))}" for row in rows[-180:])
    labels = ",".join(f"'{escape(str(row['date']))}'" for row in rows[-180:])
    return f"""
<canvas id="equityChart" class="chart" width="900" height="320"></canvas>
<script>
(() => {{
  const canvas = document.getElementById('equityChart');
  const ctx = canvas.getContext('2d');
  const equity = [{points}];
  const drawdown = [{drawdowns}];
  const labels = [{labels}];
  const w = canvas.width, h = canvas.height, pad = 42;
  ctx.clearRect(0, 0, w, h);
  ctx.strokeStyle = '#d9e0e8';
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(pad, pad);
  ctx.lineTo(pad, h - pad);
  ctx.lineTo(w - pad, h - pad);
  ctx.stroke();
  const min = Math.min(...equity);
  const max = Math.max(...equity);
  const span = Math.max(max - min, 1);
  const x = i => pad + (i / Math.max(equity.length - 1, 1)) * (w - pad * 2);
  const y = v => h - pad - ((v - min) / span) * (h - pad * 2);
  ctx.strokeStyle = '#0f766e';
  ctx.lineWidth = 2;
  ctx.beginPath();
  equity.forEach((v, i) => i ? ctx.lineTo(x(i), y(v)) : ctx.moveTo(x(i), y(v)));
  ctx.stroke();
  const ddMax = Math.max(...drawdown, 0.01);
  ctx.strokeStyle = '#b42318';
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  drawdown.forEach((v, i) => {{
    const yy = h - pad - (v / ddMax) * ((h - pad * 2) * 0.45);
    i ? ctx.lineTo(x(i), yy) : ctx.moveTo(x(i), yy);
  }});
  ctx.stroke();
  ctx.fillStyle = '#657285';
  ctx.font = '12px system-ui';
  ctx.fillText(labels[0] || '', pad, h - 12);
  ctx.fillText(labels[labels.length - 1] || '', w - 120, h - 12);
  ctx.fillText('Equity', pad + 8, pad + 14);
  ctx.fillText('Drawdown', pad + 8, pad + 30);
}})();
</script>"""


def _holdings_table(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return '<div class="empty">No open holdings loaded.</div>'
    body = "".join(
        f"<tr><td>{escape(row['symbol'])}</td><td>{row['quantity']:.4g}</td>"
        f"<td>{_money(row.get('last_price'))}</td><td>{_money(row.get('market_value'))}</td>"
        f"<td>{escape(str(row.get('price_date') or ''))}</td></tr>"
        for row in rows
    )
    return f"<table><thead><tr><th>Symbol</th><th>Qty</th><th>Last</th><th>Value</th><th>Price Date</th></tr></thead><tbody>{body}</tbody></table>"


def _trades_table(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return '<div class="empty">No filled trades loaded.</div>'
    body = "".join(
        f"<tr><td>{escape(row['date'])}</td><td>{escape(row['symbol'])}</td><td>{escape(row['side'])}</td>"
        f"<td>{row['quantity']:.4g}</td><td>{_money(row['price'])}</td><td>{_money(row['notional'])}</td></tr>"
        for row in rows
    )
    return f"<table><thead><tr><th>Date</th><th>Symbol</th><th>Side</th><th>Qty</th><th>Price</th><th>Notional</th></tr></thead><tbody>{body}</tbody></table>"


def _daily_table(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return '<div class="empty">No daily history loaded.</div>'
    body = "".join(
        f"<tr><td>{escape(row['date'])}</td><td>{_money(row['equity'])}</td>"
        f"<td class=\"{'negative' if row['daily_pnl'] < 0 else ''}\">{_money(row['daily_pnl'])}</td>"
        f"<td>{_pct(row['daily_return'])}</td><td class=\"negative\">{_pct(row['drawdown'])}</td></tr>"
        for row in rows
    )
    return f"<table><thead><tr><th>Date</th><th>Equity</th><th>PnL</th><th>Return</th><th>Drawdown</th></tr></thead><tbody>{body}</tbody></table>"


def _money(value: Any) -> str:
    try:
        return f"${float(value):,.2f}"
    except (TypeError, ValueError):
        return ""


def _pct(value: Any) -> str:
    try:
        return f"{float(value) * 100:.2f}%"
    except (TypeError, ValueError):
        return ""
