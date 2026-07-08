#!/usr/bin/env bash
set -u

cd "$(dirname "$0")/.."
LOG_DIR="${HOME}/Library/Logs/AI Progress Monitor"
if [ -z "${HOME:-}" ]; then
  LOG_DIR="./logs"
fi
LOG_FILE="${LOG_DIR}/monitor.log"
mkdir -p "$LOG_DIR"
{
  printf '\n[%s] Starting AI Progress Monitor\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
  python3 ai-progress-monitor.pyz --open "$@"
} 2>&1 | tee -a "$LOG_FILE"
STATUS=${PIPESTATUS[0]}
if [ "$STATUS" = "130" ]; then
  echo "Monitor stopped."
  exit 130
fi
if [ "$STATUS" != "0" ]; then
  echo "Monitor failed. See log: $LOG_FILE"
  exit "$STATUS"
fi
