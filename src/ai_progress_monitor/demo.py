from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List

from .models import ActionKind, SafeAction, SessionStatus, SessionUpdate, SurfaceKind, ToolKind


class DemoSource:
    def poll(self) -> List[SessionUpdate]:
        now = datetime.now(timezone.utc)
        return [
            SessionUpdate(
                "demo-claude-1",
                "Claude Code - checkout-flow",
                ToolKind.CLAUDE_CODE,
                SurfaceKind.TERMINAL,
                SessionStatus.NEEDS_ACTION,
                "Do you want to continue? (yes/no)",
                now,
                SafeAction(ActionKind.YES_NO, ("Yes", "No"), "Do you want to continue?"),
                "demo",
            ),
            SessionUpdate(
                "demo-chatgpt-1",
                "ChatGPT Desktop - PRD polish",
                ToolKind.CHATGPT,
                SurfaceKind.DESKTOP,
                SessionStatus.RUNNING,
                "Executing tests...",
                now - timedelta(seconds=20),
                None,
                "demo",
                focus_app_name="ChatGPT",
                tool_display_name="ChatGPT",
            ),
            SessionUpdate(
                "demo-claude-2",
                "Claude Code - docs",
                ToolKind.CLAUDE_CODE,
                SurfaceKind.TERMINAL,
                SessionStatus.IDLE,
                "Done. All tests passed.",
                now - timedelta(minutes=2),
                None,
                "demo",
            ),
        ]
