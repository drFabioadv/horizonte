#!/usr/bin/env bash
# Linux/macOS: ./iniciar.sh  (reinicia sozinho se parar)
cd "$(dirname "$0")"
[ -x .venv/bin/python ] || { python3 -m venv .venv && .venv/bin/pip install -r requirements.txt; }
[ -f .env ] || cp .env.example .env
while true; do .venv/bin/python -m horizonte "$@"; echo "Reiniciando em 15 s..."; sleep 15; done
