#!/usr/bin/env bash
# Start Streamlit + Flask internally, then expose both via Caddy (WebSocket-aware).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

PORT="${PORT:-10000}"
export PORT

CADDY_BIN="$ROOT/bin/caddy"
CADDY_VERSION="2.8.4"

download_caddy() {
  mkdir -p "$ROOT/bin"
  echo "Downloading Caddy ${CADDY_VERSION}..."
  curl -fsSL \
    "https://github.com/caddyserver/caddy/releases/download/v${CADDY_VERSION}/caddy_${CADDY_VERSION}_linux_amd64.tar.gz" \
    | tar -xz -C "$ROOT/bin" caddy
  chmod +x "$CADDY_BIN"
}

if [[ ! -x "$CADDY_BIN" ]]; then
  download_caddy
fi

echo "Starting Streamlit on 127.0.0.1:8501..."
streamlit run app.py \
  --server.port 8501 \
  --server.address 127.0.0.1 \
  --server.headless true \
  --server.enableCORS false \
  --server.enableXsrfProtection false &
STREAMLIT_PID=$!

echo "Starting Flask ebook API on 127.0.0.1:5000..."
gunicorn email_app:app \
  --bind 127.0.0.1:5000 \
  --timeout 120 \
  --workers 1 &
GUNICORN_PID=$!

cleanup() {
  echo "Shutting down..."
  kill "$STREAMLIT_PID" "$GUNICORN_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "Waiting for Streamlit health check..."
for _ in $(seq 1 60); do
  if curl -sf "http://127.0.0.1:8501/_stcore/health" >/dev/null 2>&1; then
    echo "Streamlit is ready."
    break
  fi
  if ! kill -0 "$STREAMLIT_PID" 2>/dev/null; then
    echo "Streamlit process exited unexpectedly." >&2
    exit 1
  fi
  sleep 1
done

echo "Starting Caddy on 0.0.0.0:${PORT}..."
exec "$CADDY_BIN" run --config "$ROOT/Caddyfile" --adapter caddyfile
