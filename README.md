# Portfolio Strategy Dashboard

FastAPI dashboard for tracking individual strategies inside a Webull account. V1 treats all account activity as `Vol_Factor` and marks positions with local market data from `/srv/data/stocks`.

## Setup

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
```

The app reads existing credentials from `.env` and `conf/token.txt`.

Optional `.env` settings:

```bash
DASHBOARD_HOST=127.0.0.1
DASHBOARD_PORT=8080
MARKET_DATA_DIR=/srv/data/stocks
SYNC_INTERVAL_MINUTES=15
```

For Tailscale-only access, set `DASHBOARD_HOST` to the server's Tailscale IP or MagicDNS hostname target and run uvicorn with that host.

## Commands

```bash
python -m portfolio_dashboard.sync
uvicorn portfolio_dashboard.app:app --host "$DASHBOARD_HOST" --port "$DASHBOARD_PORT"
python -m pytest
```

Routes:

- `GET /`
- `POST /sync`
- `GET /api/strategies/Vol_Factor/performance`
- `GET /health`
