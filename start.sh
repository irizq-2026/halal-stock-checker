#!/usr/bin/env bash
# Run Streamlit + Flask + Caddy under supervisord on Render.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

PORT="${PORT:-10000}"
export PORT
export ROOT
export STREAMLIT_BROWSER_GATHER_USAGE_STATS=false
export STREAMLIT_SERVER_FILE_WATCHER_TYPE=none

if [[ ! -x "$ROOT/.venv-streamlit/bin/python" || ! -x "$ROOT/.venv-web/bin/python" || ! -x "$ROOT/bin/caddy" ]]; then
  echo "Missing build artifacts; running build.sh..."
  bash "$ROOT/build.sh"
fi

echo "=== startup diagnostics ==="
echo "PORT=${PORT}"
echo "ROOT=${ROOT}"
"$ROOT/.venv-streamlit/bin/python" -c "import streamlit; print('streamlit', streamlit.__version__)"
"$ROOT/.venv-web/bin/python" -c "import flask; print('flask ok')"
"$ROOT/bin/caddy" version
test -f "$ROOT/app.py"
echo "app.py present"

echo "Starting supervisord..."
exec "$ROOT/.venv-web/bin/supervisord" -n -c "$ROOT/supervisord.conf"
