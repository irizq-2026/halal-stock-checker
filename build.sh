#!/usr/bin/env bash
# Build Streamlit + Flask virtualenvs and download Caddy for Render.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

PYTHON_BIN="${PYTHON_BIN:-python3}"
CADDY_VERSION="2.8.4"

echo "Creating Streamlit virtualenv (.venv-streamlit)..."
"${PYTHON_BIN}" -m venv .venv-streamlit
.venv-streamlit/bin/pip install --upgrade pip
.venv-streamlit/bin/pip install -r requirements-streamlit.txt

echo "Creating web/Flask virtualenv (.venv-web)..."
"${PYTHON_BIN}" -m venv .venv-web
.venv-web/bin/pip install --upgrade pip
.venv-web/bin/pip install -r requirements-email.txt

echo "Downloading Caddy ${CADDY_VERSION}..."
mkdir -p bin
curl -fsSL \
  "https://github.com/caddyserver/caddy/releases/download/v${CADDY_VERSION}/caddy_${CADDY_VERSION}_linux_amd64.tar.gz" \
  | tar -xz -C bin caddy
chmod +x bin/caddy

echo "Build complete."
.venv-streamlit/bin/python -c "import streamlit; print('streamlit', streamlit.__version__)"
.venv-web/bin/python -c "import flask, gunicorn, supervisor; print('flask+gunicorn+supervisor ok')"
./bin/caddy version
