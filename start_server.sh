#!/bin/bash
# Startet die Kasse: ein Prozess liefert API, WebSocket und Frontend aus.
# Aufruf: ./start_server.sh   (danach im Browser http://<IP-des-Rechners>:5000)
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -x venv/bin/python3 ]; then
  python3 -m venv venv
fi
./venv/bin/pip install -q -r requirements.txt

# Frontend nur neu bauen, wenn sich etwas geändert hat
if [ ! -f frontend/dist/index.html ] || [ -n "$(find frontend/src frontend/index.html frontend/package.json -newer frontend/dist/index.html 2>/dev/null | head -1)" ]; then
  (cd frontend && npm ci --no-audit --no-fund && npm run build)
fi

exec ./venv/bin/python3 main.py
