#!/usr/bin/env bash
set -eu

APP_NAME="AI Progress Monitor Floating Dev"
ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LOG_FILE="${HOME}/Library/Logs/AI Progress Monitor/native-monitor.log"
APPROVED_SHIRT_ASSET="$ROOT_DIR/docs/promo/assets/sloth-mascot-transparent.png"
export APPROVED_SHIRT_ASSET
STRICT=0

for arg in "$@"; do
  case "$arg" in
    --strict) STRICT=1 ;;
    *)
      printf 'Unknown option: %s\n' "$arg" >&2
      printf 'Usage: %s [--strict]\n' "$0" >&2
      exit 2
      ;;
  esac
done

echo "macOS Floating Dev acceptance check"
echo

PROCESS_RUNNING=0
if pgrep -f "$APP_NAME" >/dev/null 2>&1 || pgrep -f "build/macos-dev/.*/ai-progress-monitor.pyz" >/dev/null 2>&1 || pgrep -f "ai-progress-monitor-dev/.*/ai-progress-monitor.pyz" >/dev/null 2>&1; then
  PROCESS_RUNNING=1
fi

echo
echo "Expected log path:"
echo "  ~/Library/Logs/AI Progress Monitor/native-monitor.log"

if [ ! -f "$LOG_FILE" ]; then
  if [ "$PROCESS_RUNNING" = "1" ]; then
    echo "[OK] $APP_NAME process is running"
  else
    echo "[WARN] $APP_NAME process is not running"
    echo "      Start it with: scripts/run_macos_floating_dev.sh"
  fi
  echo "[WARN] Log file not found yet"
  if [ "$STRICT" = "1" ]; then
    echo "Manual acceptance incomplete"
    exit 1
  fi
  exit 0
fi

FILTERED_LOG="$(mktemp "${TMPDIR:-/tmp}/ai-monitor-dev-log.XXXXXX")"
SHIRT_HEADERS="$(mktemp "${TMPDIR:-/tmp}/ai-monitor-shirt-headers.XXXXXX")"
SHIRT_BODY="$(mktemp "${TMPDIR:-/tmp}/ai-monitor-shirt-body.XXXXXX")"
trap 'rm -f "$FILTERED_LOG" "$SHIRT_HEADERS" "$SHIRT_BODY"' EXIT
awk '
  /Starting native companion/ {buffer = ""; seen = 1}
  {buffer = buffer $0 "\n"}
  END {printf "%s", buffer}
' "$LOG_FILE" > "$FILTERED_LOG"

echo
echo "Process status:"
if grep -Eq "AI Progress Monitor sessions: total=[1-9]" "$FILTERED_LOG"; then
  echo "[OK] $APP_NAME service has recent session snapshots"
elif [ "$PROCESS_RUNNING" = "1" ]; then
  echo "[OK] $APP_NAME process is running"
else
  echo "[WARN] $APP_NAME process is not running"
  echo "      Start it with: scripts/run_macos_floating_dev.sh"
fi

echo
echo "Recent monitor URL:"
grep "AI Progress Monitor running at" "$FILTERED_LOG" | tail -n 3 | sed -E 's/token=[^[:space:]]+/token=[REDACTED]/g' || true

echo
echo "Recent session snapshots:"
grep "AI Progress Monitor sessions:" "$FILTERED_LOG" | tail -n 5 || true

echo
echo "Recent pet appearance changes:"
grep "AI Progress Monitor pet appearance:" "$FILTERED_LOG" | tail -n 5 || true

echo
echo "Pet appearance asset check:"
asset_todo=0
monitor_url="$(grep "AI Progress Monitor running at" "$FILTERED_LOG" | tail -n 1 | sed -E 's/^.*(http:\/\/127\.0\.0\.1:[0-9]+)\/\?token=[^[:space:]]+.*$/\1/' || true)"
if [ -z "$monitor_url" ] || [ "$monitor_url" = "$(grep "AI Progress Monitor running at" "$FILTERED_LOG" | tail -n 1 || true)" ]; then
  echo "  [TODO] running app URL unavailable"
  asset_todo=1
elif [ ! -f "$APPROVED_SHIRT_ASSET" ]; then
  echo "  [TODO] approved shirt source image missing"
  asset_todo=1
elif ! command -v curl >/dev/null 2>&1 || ! command -v shasum >/dev/null 2>&1; then
  echo "  [TODO] curl or shasum unavailable"
  asset_todo=1
elif curl -fsS -D "$SHIRT_HEADERS" -o "$SHIRT_BODY" "$monitor_url/assets/pet/shirt.png" >/dev/null 2>&1; then
  expected_hash="$(shasum -a 256 "$APPROVED_SHIRT_ASSET" | awk '{print $1}')"
  actual_hash="$(shasum -a 256 "$SHIRT_BODY" | awk '{print $1}')"
  if [ "$actual_hash" = "$expected_hash" ]; then
    echo "  [OK] shirt asset route serves approved source image"
  else
    echo "  [TODO] shirt asset route does not match approved source image"
    asset_todo=1
  fi
  if grep -iq '^cache-control: no-store' "$SHIRT_HEADERS"; then
    echo "  [OK] shirt asset route disables caching"
  else
    echo "  [TODO] shirt asset route missing cache-control: no-store"
    asset_todo=1
  fi
else
  echo "  [TODO] shirt asset route unavailable"
  asset_todo=1
fi

echo
echo "Manual acceptance evidence:"
manual_todo=0
if grep -Eq "AI Progress Monitor sessions: total=[1-9]" "$FILTERED_LOG"; then
  echo "  [OK] sessions visible"
else
  echo "  [TODO] sessions visible"
  manual_todo=1
fi
if grep -q "Received host resize mode: bubbles" "$FILTERED_LOG" && grep -q "Received host resize mode: compact" "$FILTERED_LOG"; then
  echo "  [OK] left-click open/close evidence"
else
  echo "  [TODO] left-click open/close evidence"
  manual_todo=1
fi
if grep -q "Started window drag" "$FILTERED_LOG" && grep -q "Moved window frame" "$FILTERED_LOG" && grep -q "Stopped window drag" "$FILTERED_LOG"; then
  echo "  [OK] drag evidence"
else
  echo "  [TODO] drag evidence"
  manual_todo=1
fi
if grep -q "Hide monitor requested" "$FILTERED_LOG"; then
  echo "  [OK] hide evidence"
else
  echo "  [TODO] hide evidence"
  manual_todo=1
fi
if grep -q "Show monitor requested from menu" "$FILTERED_LOG" && grep -q "Restored pet web state" "$FILTERED_LOG"; then
  echo "  [OK] menu restore evidence"
else
  echo "  [TODO] menu restore evidence"
  manual_todo=1
fi
if grep -Eq "AI Progress Monitor focus: ok=true|Native focus result: ok=true" "$FILTERED_LOG"; then
  echo "  [OK] bubble focus evidence"
else
  echo "  [TODO] bubble focus evidence"
  manual_todo=1
fi

echo
echo "Recent host messages:"
grep -E "Received host message|Received host resize mode" "$FILTERED_LOG" | tail -n 10 || true

echo
echo "Recent focus actions:"
grep -E "AI Progress Monitor focus:|Native focus result:" "$FILTERED_LOG" | tail -n 5 || true

echo
echo "Recent show/hide/quit actions:"
grep -E "Show monitor requested|Hide monitor requested|Quit requested|Restored pet web state|Show monitor completed frame" "$FILTERED_LOG" | tail -n 12 || true

echo
echo "Manual checks to perform in the dev app:"
echo "  1. Left-click Pet: bubbles open; left-click again: bubbles close; Pet must not hide."
echo "  2. Right-click Pet: menu opens; choosing Hide Pet hides it."
echo "  3. Menu bar icon -> Show Monitor restores the hidden Pet."
echo "  4. Drag across displays and screen edges."
echo "  5. Click a bubble and confirm it returns to the matching AI tool window."

if [ "$STRICT" = "1" ]; then
  if [ "$manual_todo" = "0" ] && [ "$asset_todo" = "0" ]; then
    echo
    echo "Manual acceptance complete"
  else
    echo
    echo "Manual acceptance incomplete"
    exit 1
  fi
fi
