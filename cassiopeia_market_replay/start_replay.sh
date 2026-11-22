#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
exec ./venv/bin/python -u cassiopeia_market_replay/server.py "$@"
