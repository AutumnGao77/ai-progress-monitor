#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path


def default_monitor_home() -> Path:
    return Path(os.environ.get("AI_PROGRESS_MONITOR_HOME") or Path.home() / ".ai-progress-monitor")


def default_session_dir() -> Path:
    return default_monitor_home() / "sessions"


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish an AI progress monitor session event")
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--tool", choices=("claude_code", "codex", "unknown"), required=True)
    parser.add_argument("--tool-display-name", help="Display name for generic AI tools when --tool unknown is used")
    parser.add_argument("--surface", choices=("terminal", "desktop", "unknown"), required=True)
    parser.add_argument("--status", choices=("running", "needs_action", "idle", "stuck", "unknown"), required=True)
    parser.add_argument("--summary", default="")
    parser.add_argument("--session-dir", default=str(default_session_dir()))
    parser.add_argument("--view-ack-required", action="store_true")
    parser.add_argument("--status-source")
    parser.add_argument("--window-id")
    parser.add_argument("--process-id", type=int)
    parser.add_argument("--process-name")
    parser.add_argument("--focus-process-id", type=int)
    parser.add_argument("--focus-app-name")
    parser.add_argument("--cwd")
    parser.add_argument("--generated-conversation-path", action="store_true")
    parser.add_argument("--action-kind", choices=("yes_no", "allow_deny", "continue_stop"))
    parser.add_argument("--action-options", default="")
    args = parser.parse_args()

    payload = {
        "session_id": args.session_id,
        "title": args.title,
        "tool": args.tool,
        "surface": args.surface,
        "status": args.status,
        "summary": args.summary,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    optional_fields = {
        "tool_display_name": args.tool_display_name,
        "view_ack_required": True if args.view_ack_required else None,
        "status_source": args.status_source,
        "window_id": args.window_id,
        "process_id": args.process_id,
        "process_name": args.process_name,
        "focus_process_id": args.focus_process_id,
        "focus_app_name": args.focus_app_name,
        "cwd": args.cwd,
        "generated_conversation_path": True if args.generated_conversation_path else None,
    }
    for key, value in optional_fields.items():
        if value is not None:
            payload[key] = value
    if args.action_kind and args.action_options:
        payload["safe_action"] = {
            "kind": args.action_kind,
            "options": [item.strip() for item in args.action_options.split(",") if item.strip()],
            "prompt": args.summary,
        }

    session_dir = Path(args.session_dir)
    session_dir.mkdir(parents=True, exist_ok=True)
    path = session_dir / f"{args.session_id}.json"
    temp_path = path.with_suffix(".json.tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
    temp_path.replace(path)
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
