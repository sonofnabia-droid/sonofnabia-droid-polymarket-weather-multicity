#!/usr/bin/env bash
# Isolated PAPER launcher driven by deployment/paper/fleet.json.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
[[ -x ./venv/bin/python ]] || { echo "venv/bin/python em falta." >&2; exit 1; }
exec ./venv/bin/python deployment/paper/launch_fleet.py
