#!/usr/bin/env sh
set -eu

cd "$(dirname "$0")/.."
export PYTHONPATH=src
python3 -m ai_progress_monitor --demo --no-windows --host 127.0.0.1 --port 8765
