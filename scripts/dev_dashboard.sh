#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

DASHBOARD_HOST="${DASHBOARD_HOST:-100.68.111.84}"
DASHBOARD_PORT="${DASHBOARD_PORT:-8080}"
FRONTEND_HOST="${FRONTEND_HOST:-$DASHBOARD_HOST}"
FRONTEND_PORT="${FRONTEND_PORT:-5050}"

cd "$ROOT_DIR"

if [[ ! -x ".venv/bin/uvicorn" ]]; then
  echo "Missing .venv/bin/uvicorn. Run setup from README first." >&2
  exit 1
fi

if [[ ! -d "frontend/node_modules" ]]; then
  echo "Missing frontend/node_modules. Run: cd frontend && npm install" >&2
  exit 1
fi

port_is_free() {
  local host="$1"
  local port="$2"
  ".venv/bin/python" - "$host" "$port" <<'PY'
import socket
import sys

host = sys.argv[1]
port = int(sys.argv[2])

with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind((host, port))
    except OSError:
        raise SystemExit(1)
PY
}

find_free_port() {
  local host="$1"
  local start_port="$2"
  local port="$start_port"
  local end_port=$((start_port + 50))

  while (( port <= end_port )); do
    if port_is_free "$host" "$port"; then
      echo "$port"
      return 0
    fi
    port=$((port + 1))
  done

  echo "No free port found for $host in range $start_port-$end_port" >&2
  return 1
}

DASHBOARD_PORT="$(find_free_port "$DASHBOARD_HOST" "$DASHBOARD_PORT")"
FRONTEND_PORT="$(find_free_port "$FRONTEND_HOST" "$FRONTEND_PORT")"
API_BASE_URL="${API_BASE_URL:-http://$DASHBOARD_HOST:$DASHBOARD_PORT}"

cleanup() {
  trap - INT TERM EXIT
  if [[ -n "${API_PID:-}" ]]; then
    kill "$API_PID" 2>/dev/null || true
  fi
  if [[ -n "${NEXT_PID:-}" ]]; then
    kill "$NEXT_PID" 2>/dev/null || true
  fi
  wait 2>/dev/null || true
}

trap cleanup INT TERM EXIT

echo "Starting FastAPI API on http://$DASHBOARD_HOST:$DASHBOARD_PORT"
".venv/bin/uvicorn" portfolio_dashboard.app:app \
  --host "$DASHBOARD_HOST" \
  --port "$DASHBOARD_PORT" &
API_PID=$!

echo "Starting Next.js frontend on http://$FRONTEND_HOST:$FRONTEND_PORT"
(
  cd "$ROOT_DIR/frontend"
  API_BASE_URL="$API_BASE_URL" npm run dev -- \
    --hostname "$FRONTEND_HOST" \
    --port "$FRONTEND_PORT"
) &
NEXT_PID=$!

echo
echo "Dashboard: http://$FRONTEND_HOST:$FRONTEND_PORT"
echo "API:       http://$DASHBOARD_HOST:$DASHBOARD_PORT"
echo "Press Ctrl-C to stop both."

wait -n "$API_PID" "$NEXT_PID"
