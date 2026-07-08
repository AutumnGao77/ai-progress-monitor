#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish an AI progress monitor session event")
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--tool", choices=("claude_code", "codex", "unknown"), required=True)
    parser.add_argument("--surface", choices=("terminal", "desktop", "unknown"), required=True)
    parser.add_argument("--status", choices=("running", "needs_action", "idle", "stuck", "unknown"), required=True)
    parser.add_argument("--summary", default="")
    parser.add_argument("--session-dir", default=str(Path.home() / ".ai-progress-monitor" / "sessions"))
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
    if args.action_kind and args.action_options:
        payload["safe_action"] = {
            "kind": args.action_kind,
            "options": [item.strip() for item in args.action_options.split(",") if item.strip()],
            "prompt": args.summary,
        }

    session_dir = Path(args.session_dir)
    session_dir.mkdir(parents=True, exist_ok=True)
    path = session_dir / f"{args.session_id}.json"
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
