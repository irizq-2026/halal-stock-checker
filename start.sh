#!/usr/bin/env bash
# Start Streamlit + Flask internally, then expose both via Caddy (WebSocket-aware).
# Streamlit is supervised and auto-restarted if it crashes/OOM-exits.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

PORT="${PORT:-10000}"
export PORT
export STREAMLIT_BROWSER_GATHER_USAGE_STATS=false
export STREAMLIT_SERVER_FILE_WATCHER_TYPE=none

CADDY_BIN="$ROOT/bin/caddy"
CADDY_VERSION="2.8.4"

STREAMLIT_PID=""
GUNICORN_PID=""
CADDY_PID=""
STREAMLIT_SUPERVISOR_PID=""
HEALTH_WATCHER_PID=""
STOPPING=0

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

start_streamlit_once() {
  echo "Starting Streamlit on 127.0.0.1:8501..."
  streamlit run app.py \
    --server.port 8501 \
    --server.address 127.0.0.1 \
    --server.headless true \
    --server.enableCORS false \
    --server.enableXsrfProtection false \
    --server.fileWatcherType none &
  STREAMLIT_PID=$!
  echo "Streamlit pid=${STREAMLIT_PID}"
}

supervise_streamlit() {
  while [[ "$STOPPING" -eq 0 ]]; do
    start_streamlit_once
    set +e
    wait "${STREAMLIT_PID}"
    exit_code=$?
    set -e
    STREAMLIT_PID=""
    if [[ "$STOPPING" -ne 0 ]]; then
      break
    fi
    echo "WARNING: Streamlit exited (code=${exit_code}). Restarting in 2s..." >&2
    sleep 2
  done
}

watch_streamlit_health() {
  while [[ "$STOPPING" -eq 0 ]]; do
    sleep 15
    if [[ "$STOPPING" -ne 0 ]]; then
      break
    fi
    if ! curl -sf "http://127.0.0.1:8501/_stcore/health" >/dev/null 2>&1; then
      echo "WARNING: Streamlit health check failing at $(date -u +%Y-%m-%dT%H:%M:%SZ)" >&2
    fi
  done
}

cleanup() {
  STOPPING=1
  echo "Shutting down (streamlit=${STREAMLIT_PID:-none} supervisor=${STREAMLIT_SUPERVISOR_PID:-none} health=${HEALTH_WATCHER_PID:-none} gunicorn=${GUNICORN_PID:-none} caddy=${CADDY_PID:-none})..."
  kill "${CADDY_PID}" "${HEALTH_WATCHER_PID}" "${STREAMLIT_SUPERVISOR_PID}" "${STREAMLIT_PID}" "${GUNICORN_PID}" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "PORT=${PORT}"

supervise_streamlit &
STREAMLIT_SUPERVISOR_PID=$!

echo "Starting Flask ebook API on 127.0.0.1:5000..."
gunicorn email_app:app \
  --bind 127.0.0.1:5000 \
  --timeout 120 \
  --workers 1 &
GUNICORN_PID=$!

# Bind Render's $PORT immediately. Health checks should use /healthz.
echo "Starting Caddy on 0.0.0.0:${PORT}..."
"$CADDY_BIN" run --config "$ROOT/Caddyfile" --adapter caddyfile &
CADDY_PID=$!

echo "Waiting for Streamlit health check..."
for _ in $(seq 1 90); do
  if curl -sf "http://127.0.0.1:8501/_stcore/health" >/dev/null 2>&1; then
    echo "Streamlit is ready."
    break
  fi
  if ! kill -0 "$CADDY_PID" 2>/dev/null; then
    echo "Caddy process exited unexpectedly." >&2
    exit 1
  fi
  sleep 1
done

echo "Waiting for Flask ebook API..."
for _ in $(seq 1 30); do
  if curl -sf "http://127.0.0.1:5000/ebook" >/dev/null 2>&1; then
    echo "Flask is ready."
    break
  fi
  if ! kill -0 "$GUNICORN_PID" 2>/dev/null; then
    echo "Gunicorn process exited unexpectedly." >&2
    exit 1
  fi
  sleep 1
done

watch_streamlit_health &
HEALTH_WATCHER_PID=$!

echo "All processes running. Supervising Caddy (pid=${CADDY_PID})..."
wait "$CADDY_PID"
