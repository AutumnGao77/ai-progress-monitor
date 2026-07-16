#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ROOT_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
LAUNCH_DIR=$(pwd)
FOLDER_NAME=$(basename "$LAUNCH_DIR")
SESSION_FOLDER=$(printf "%s" "$FOLDER_NAME" | tr -c "[:alnum:]_.-" "-")
RUN_ID="$(date +%Y%m%d%H%M%S)-$$"

cd "$LAUNCH_DIR"
python3 "$ROOT_DIR/scripts/monitor_command.py" \
  --session-id "${AI_MONITOR_SESSION_ID:-workbuddy-${SESSION_FOLDER}-${RUN_ID}}" \
  --title "${AI_MONITOR_TITLE:-WorkBuddy - ${FOLDER_NAME} #${RUN_ID}}" \
  --tool unknown \
  --tool-display-name WorkBuddy \
  -- "$@"
