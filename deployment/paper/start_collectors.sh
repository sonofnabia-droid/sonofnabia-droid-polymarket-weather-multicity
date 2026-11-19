#!/usr/bin/env bash
# Starts only collectors explicitly enabled in fleet.json.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
[[ -x ./venv/bin/python ]] || { echo "venv/bin/python em falta." >&2; exit 1; }
exec ./venv/bin/python deployment/paper/launch_collectors.py
