"use client";

import { useEffect, useMemo, useState } from "react";

type Summary = {
  net_exposure: number;
  gross_exposure: number;
  net_aum?: number;
  latest_equity: number;
  total_pnl: number;
  daily_pnl: number;
  total_return: number;
  daily_return: number;
  spy_daily_return: number | null;
  spy_total_return: number | null;
  daily_return_over_spy: number | null;
  total_return_over_spy: number | null;
  max_drawdown: number;
  sharpe: number;
  risk_free_rate: number | null;
  open_positions: number;
  trade_count: number;
  history_start: string | null;
  history_end: string | null;
};

type AccountSummary = {
  net_exposure: number;
  gross_exposure: number;
  net_aum: number | null;
  net_aum_in_db: boolean;
  latest_equity: number;
  total_pnl: number;
  daily_pnl: number;
  total_return: number;
  daily_return: number;
  spy_daily_return: number | null;
  spy_total_return: number | null;
  daily_return_over_spy: number | null;
  total_return_over_spy: number | null;
  max_drawdown: number;
  open_positions: number;
  trade_count: number;
  history_start: string | null;
  history_end: string | null;
  account_count: number;
  strategy_count: number;
};

type EquityRow = {
  date: string;
  equity: number;
  daily_pnl: number;
  daily_return: number;
  drawdown: number;
};

type Holding = {
  symbol: string;
  quantity: number;
  avg_price: number | null;
  market_value: number;
  last_price: number;
  return: number | null;
  price_date: string | null;
};

type Trade = {
  date: string;
  symbol: string;
  side: string;
  quantity: number;
  price: number;
  notional: number;
  order_id: string;
};

type Performance = {
  strategy: string;
  summary: Summary;
  equity_curve: EquityRow[];
  drawdown_curve: { date: string; drawdown: number }[];
  holdings: Holding[];
  trades: Trade[];
};

type DashboardData = {
  account_summary: AccountSummary;
  strategies: Performance[];
};

type Health = {
  ok: boolean;
  strategy_start_date: string;
  last_sync: unknown;
};

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "/backend";

export default function DashboardPage() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [activeTab, setActiveTab] = useState("home");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);

  async function loadDashboard() {
    setError(null);
    const [dashboardResponse, healthResponse] = await Promise.all([
      fetch(`${API_BASE}/api/dashboard`, { cache: "no-store" }),
      fetch(`${API_BASE}/health`, { cache: "no-store" })
    ]);
    if (!dashboardResponse.ok) {
      throw new Error(`Dashboard request failed: ${dashboardResponse.status}`);
    }
    if (!healthResponse.ok) {
      throw new Error(`Health request failed: ${healthResponse.status}`);
    }
    const dashboard = (await dashboardResponse.json()) as DashboardData;
    setData(dashboard);
    setHealth(await healthResponse.json());
    if (activeTab !== "home" && !dashboard.strategies.some((item) => item.strategy === activeTab)) {
      setActiveTab("home");
    }
  }

  useEffect(() => {
    loadDashboard()
      .catch((caught: Error) => setError(caught.message))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function refresh() {
    setSyncing(true);
    setError(null);
    try {
      const response = await fetch(`${API_BASE}/sync`, { method: "POST" });
      if (!response.ok) {
        throw new Error(`Sync request failed: ${response.status}`);
      }
      await loadDashboard();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Sync failed");
    } finally {
      setSyncing(false);
    }
  }

  const activeStrategy = data?.strategies.find((item) => item.strategy === activeTab) || null;

  return (
    <div className="page">
      <header className="topbar">
        <div>
          <p className="eyebrow">Portfolio Dashboard</p>
          <h1>{activeStrategy?.strategy || "Account Home"}</h1>
          <div className="status">
            <span>Start date: {health?.strategy_start_date || "2026-06-12"}</span>
            <span>Last sync: {formatLastSync(health?.last_sync)}</span>
          </div>
        </div>
        <button type="button" onClick={refresh} disabled={syncing || loading}>
          {syncing ? "Refreshing" : "Refresh"}
        </button>
      </header>

      <main>
        {data ? (
          <nav className="tabs" aria-label="Dashboard tabs">
            <button type="button" className={activeTab === "home" ? "active" : ""} onClick={() => setActiveTab("home")}>
              Home
            </button>
            {data.strategies.map((strategy) => (
              <button
                type="button"
                key={strategy.strategy}
                className={activeTab === strategy.strategy ? "active" : ""}
                onClick={() => setActiveTab(strategy.strategy)}
              >
                {strategy.strategy}
              </button>
            ))}
          </nav>
        ) : null}

        {error ? <div className="error">{error}</div> : null}
        {loading ? <div className="empty">Loading dashboard data...</div> : null}

        {data && activeTab === "home" ? <HomeTab account={data.account_summary} strategies={data.strategies} /> : null}
        {activeStrategy ? <StrategyTab data={activeStrategy} /> : null}
      </main>
    </div>
  );
}

function HomeTab({ account, strategies }: { account: AccountSummary; strategies: Performance[] }) {
  return (
    <>
      <div className="metrics account-metrics">
        <Metric label="Account Net AUM" value={account.net_aum_in_db ? money(account.net_aum) : "Not in DB"} />
        <Metric label="Strategy Net Exposure" value={money(account.net_exposure)} />
        <Metric label="Gross Exposure" value={money(account.gross_exposure)} />
        <Metric label="Strategy PnL" value={money(account.latest_equity)} negative={account.latest_equity < 0} />
        <Metric label="Daily PnL" value={money(account.daily_pnl)} negative={account.daily_pnl < 0} />
        <Metric label="Daily Return" value={percent(account.daily_return)} negative={account.daily_return < 0} />
        <Metric label="Daily vs SPY" value={percent(account.daily_return_over_spy)} negative={(account.daily_return_over_spy || 0) < 0} />
        <Metric label="Total PnL" value={money(account.total_pnl)} negative={account.total_pnl < 0} />
        <Metric label="Total Return" value={percent(account.total_return)} negative={account.total_return < 0} />
        <Metric label="Total vs SPY" value={percent(account.total_return_over_spy)} negative={(account.total_return_over_spy || 0) < 0} />
        <Metric label="Max Drawdown" value={percent(account.max_drawdown)} negative={account.max_drawdown < 0} />
        <Metric label="Accounts" value={String(account.account_count)} />
        <Metric label="Open Positions" value={String(account.open_positions)} />
        <Metric label="Strategies" value={String(account.strategy_count)} />
      </div>

      <section>
        <h2>Strategy Snapshot</h2>
        <StrategySummaryTable rows={strategies} />
      </section>
    </>
  );
}

function StrategyTab({ data }: { data: Performance }) {
  const dailyRows = useMemo(() => [...data.equity_curve].slice(-30).reverse(), [data]);
  const summary = data.summary;

  return (
    <>
      <div className="metrics">
        <Metric label="Strategy Net Exposure" value={money(summary.net_exposure)} />
        <Metric label="Gross Exposure" value={money(summary.gross_exposure)} />
        <Metric label="Strategy PnL" value={money(summary.latest_equity)} negative={summary.latest_equity < 0} />
        <Metric label="Daily PnL" value={money(summary.daily_pnl)} negative={summary.daily_pnl < 0} />
        <Metric label="Daily Return" value={percent(summary.daily_return)} negative={summary.daily_return < 0} />
        <Metric label="Daily vs SPY" value={percent(summary.daily_return_over_spy)} negative={(summary.daily_return_over_spy || 0) < 0} />
        <Metric label="Total PnL" value={money(summary.total_pnl)} negative={summary.total_pnl < 0} />
        <Metric label="Total Return" value={percent(summary.total_return)} negative={summary.total_return < 0} />
        <Metric label="Total vs SPY" value={percent(summary.total_return_over_spy)} negative={(summary.total_return_over_spy || 0) < 0} />
        <Metric label="Max Drawdown" value={percent(summary.max_drawdown)} negative={summary.max_drawdown < 0} />
        <Metric label="Sharpe" value={summary.sharpe.toFixed(2)} />
        <Metric label="Open Positions" value={String(summary.open_positions)} />
      </div>

      <div className="grid">
        <div>
          <section>
            <h2>Equity and Drawdown</h2>
            <EquityChart rows={data.equity_curve} />
          </section>
          <section>
            <h2>Daily Performance</h2>
            <DailyTable rows={dailyRows} />
          </section>
        </div>
        <div>
          <section>
            <h2>Holdings</h2>
            <HoldingsTable rows={data.holdings} />
          </section>
          <section>
            <h2>Trade History</h2>
            <TradesTable rows={data.trades.slice(0, 20)} />
          </section>
        </div>
      </div>
    </>
  );
}

function Metric({ label, value, negative = false }: { label: string; value: string; negative?: boolean }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong className={negative ? "negative" : ""}>{value}</strong>
    </div>
  );
}

function EquityChart({ rows }: { rows: EquityRow[] }) {
  const chartRows = rows.slice(-180);
  if (!chartRows.length) {
    return <div className="empty">No performance history yet. Run a sync after the API is configured.</div>;
  }

  const width = 900;
  const height = 320;
  const pad = 42;
  const equities = chartRows.map((row) => row.equity);
  const drawdowns = chartRows.map((row) => Math.abs(row.drawdown));
  const min = Math.min(...equities);
  const max = Math.max(...equities);
  const span = Math.max(max - min, 1);
  const maxDrawdown = Math.max(...drawdowns, 0.01);
  const x = (index: number) => pad + (index / Math.max(chartRows.length - 1, 1)) * (width - pad * 2);
  const y = (value: number) => height - pad - ((value - min) / span) * (height - pad * 2);
  const ddY = (value: number) => height - pad - (Math.abs(value) / maxDrawdown) * ((height - pad * 2) * 0.45);

  const equityPath = chartRows.map((row, index) => `${index === 0 ? "M" : "L"}${x(index)},${y(row.equity)}`).join(" ");
  const drawdownPath = chartRows.map((row, index) => `${index === 0 ? "M" : "L"}${x(index)},${ddY(row.drawdown)}`).join(" ");

  return (
    <div className="chart">
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Equity and drawdown chart">
        <path d={`M${pad},${pad} L${pad},${height - pad} L${width - pad},${height - pad}`} fill="none" stroke="#d9e0e8" />
        <path d={equityPath} fill="none" stroke="#0f766e" strokeWidth="2.5" />
        <path d={drawdownPath} fill="none" stroke="#b42318" strokeWidth="1.8" />
        <text x={pad + 8} y={pad + 14} fill="#657285" fontSize="12">
          Equity
        </text>
        <text x={pad + 8} y={pad + 30} fill="#657285" fontSize="12">
          Drawdown
        </text>
        <text x={pad} y={height - 12} fill="#657285" fontSize="12">
          {chartRows[0]?.date}
        </text>
        <text x={width - 128} y={height - 12} fill="#657285" fontSize="12">
          {chartRows[chartRows.length - 1]?.date}
        </text>
      </svg>
    </div>
  );
}

function StrategySummaryTable({ rows }: { rows: Performance[] }) {
  if (!rows.length) {
    return <div className="empty">No strategies loaded.</div>;
  }
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Strategy</th>
            <th>Strategy Net Exposure</th>
            <th>Gross Exposure</th>
            <th>Strategy PnL</th>
            <th>Daily PnL</th>
            <th>Daily Return</th>
            <th>Daily vs SPY</th>
            <th>Total PnL</th>
            <th>Total Return</th>
            <th>Total vs SPY</th>
            <th>Max DD</th>
            <th>Open</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.strategy}>
              <td>{row.strategy}</td>
              <td>{money(row.summary.net_exposure)}</td>
              <td>{money(row.summary.gross_exposure)}</td>
              <td className={row.summary.latest_equity < 0 ? "negative" : "positive"}>{money(row.summary.latest_equity)}</td>
              <td className={row.summary.daily_pnl < 0 ? "negative" : "positive"}>{money(row.summary.daily_pnl)}</td>
              <td className={row.summary.daily_return < 0 ? "negative" : "positive"}>{percent(row.summary.daily_return)}</td>
              <td className={(row.summary.daily_return_over_spy || 0) < 0 ? "negative" : "positive"}>{percent(row.summary.daily_return_over_spy)}</td>
              <td className={row.summary.total_pnl < 0 ? "negative" : "positive"}>{money(row.summary.total_pnl)}</td>
              <td className={row.summary.total_return < 0 ? "negative" : "positive"}>{percent(row.summary.total_return)}</td>
              <td className={(row.summary.total_return_over_spy || 0) < 0 ? "negative" : "positive"}>{percent(row.summary.total_return_over_spy)}</td>
              <td className={row.summary.max_drawdown < 0 ? "negative" : ""}>{percent(row.summary.max_drawdown)}</td>
              <td>{row.summary.open_positions}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function HoldingsTable({ rows }: { rows: Holding[] }) {
  if (!rows.length) {
    return <div className="empty">No open holdings loaded.</div>;
  }
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Symbol</th>
            <th>Qty</th>
            <th>Last</th>
            <th>Value</th>
            <th>Return</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.symbol}>
              <td>{row.symbol}</td>
              <td>{number(row.quantity)}</td>
              <td>{money(row.last_price)}</td>
              <td>{money(row.market_value)}</td>
              <td className={(row.return || 0) < 0 ? "negative" : "positive"}>{percent(row.return)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function TradesTable({ rows }: { rows: Trade[] }) {
  if (!rows.length) {
    return <div className="empty">No filled trades loaded.</div>;
  }
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Date</th>
            <th>Symbol</th>
            <th>Side</th>
            <th>Qty</th>
            <th>Price</th>
            <th>Notional</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={`${row.order_id}-${row.symbol}`}>
              <td>{row.date}</td>
              <td>{row.symbol}</td>
              <td>{row.side}</td>
              <td>{number(row.quantity)}</td>
              <td>{money(row.price)}</td>
              <td className={row.notional < 0 ? "negative" : "positive"}>{money(row.notional)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function DailyTable({ rows }: { rows: EquityRow[] }) {
  if (!rows.length) {
    return <div className="empty">No daily history loaded.</div>;
  }
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Date</th>
            <th>Equity</th>
            <th>PnL</th>
            <th>Return</th>
            <th>Drawdown</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.date}>
              <td>{row.date}</td>
              <td>{money(row.equity)}</td>
              <td className={row.daily_pnl < 0 ? "negative" : "positive"}>{money(row.daily_pnl)}</td>
              <td>{percent(row.daily_return)}</td>
              <td className={row.drawdown < 0 ? "negative" : ""}>{percent(row.drawdown)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function formatLastSync(value: unknown): string {
  if (!value) {
    return "not run";
  }
  if (typeof value === "object" && value !== null && "ok" in value) {
    return JSON.stringify(value);
  }
  return String(value);
}

function money(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "";
  }
  return value.toLocaleString("en-US", { style: "currency", currency: "USD" });
}

function percent(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "";
  }
  return `${(value * 100).toFixed(2)}%`;
}

function number(value: number): string {
  return value.toLocaleString("en-US", { maximumFractionDigits: 4 });
}
