# Portfolio Strategy Dashboard

FastAPI API plus Next.js frontend for tracking individual strategies inside a Webull account. V1 treats all account activity as `Vol_Factor` and marks positions with local market data from `/srv/data/stocks`.

## Setup

```bash
python3.13 -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
cd frontend
npm install
```

The app reads existing credentials from `.env` and `conf/token.txt`.
Webull sync uses the official Webull SDK API used by `testscript.py`. The SDK currently supports Python 3.8 through 3.13, so do not use Python 3.14 for the dashboard virtualenv.

Optional `.env` settings:

```bash
DASHBOARD_HOST=127.0.0.1
DASHBOARD_PORT=8080
MARKET_DATA_DIR=/srv/data/stocks
RISK_FREE_RATE_DIR=/srv/data/risk_free_rate
RISK_FREE_RATE_FILE=/srv/data/risk_free_rate/DGS3MO_risk_free_rate.csv
SYNC_INTERVAL_MINUTES=15
STRATEGY_START_DATE=2026-06-12
```

For Tailscale-only access, set `DASHBOARD_HOST` to the server's Tailscale IP or MagicDNS hostname target and run uvicorn with that host.

## Commands

```bash
python -m portfolio_dashboard.sync
chmod +x scripts/dev_dashboard.sh
./scripts/dev_dashboard.sh
python -m pytest
```

`scripts/dev_dashboard.sh` starts at `DASHBOARD_PORT=8080` and `FRONTEND_PORT=5050`, then scans upward if either port is already in use. The FastAPI backend auto-reloads on code changes by default; set `DASHBOARD_RELOAD=0` to disable it. Override the defaults when needed:

```bash
DASHBOARD_HOST=100.68.111.84 DASHBOARD_PORT=8090 FRONTEND_PORT=5051 ./scripts/dev_dashboard.sh
```

Manual two-process mode:

```bash
uvicorn portfolio_dashboard.app:app --host "$DASHBOARD_HOST" --port "$DASHBOARD_PORT"
cd frontend
API_BASE_URL="http://$DASHBOARD_HOST:$DASHBOARD_PORT" npm run dev -- --hostname "$DASHBOARD_HOST" --port 5050
```

Routes:

- FastAPI API: `GET /`
- `POST /sync`
- `GET /api/strategies/Vol_Factor/performance`
- `GET /health`

Open the Next.js frontend from another Tailnet device:

```text
http://100.68.111.84:5050
```
