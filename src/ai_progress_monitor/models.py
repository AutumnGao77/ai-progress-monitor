from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Tuple


class ToolKind(str, Enum):
    CLAUDE_CODE = "claude_code"
    CODEX = "codex"
    CHATGPT = "chatgpt"
    UNKNOWN = "unknown"


class SurfaceKind(str, Enum):
    TERMINAL = "terminal"
    DESKTOP = "desktop"
    UNKNOWN = "unknown"


class SessionStatus(str, Enum):
    RUNNING = "running"
    NEEDS_ACTION = "needs_action"
    IDLE = "idle"
    STUCK = "stuck"
    UNKNOWN = "unknown"


class ActionKind(str, Enum):
    YES_NO = "yes_no"
    ALLOW_DENY = "allow_deny"
    CONTINUE_STOP = "continue_stop"
    FREE_TEXT = "free_text"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class SafeAction:
    kind: ActionKind
    options: Tuple[str, ...]
    prompt: str


@dataclass(frozen=True)
class SessionUpdate:
    session_id: str
    title: str
    tool: ToolKind
    surface: SurfaceKind
    status: SessionStatus
    summary: str
    updated_at: datetime
    safe_action: Optional[SafeAction] = None
    source: str = "unknown"
    window_id: Optional[str] = None
    process_id: Optional[int] = None
    process_name: Optional[str] = None
    focus_process_id: Optional[int] = None
    focus_app_name: Optional[str] = None
    cwd: Optional[str] = None
    view_ack_required: bool = False
    status_source: Optional[str] = None
    tool_display_name: Optional[str] = None
    generated_conversation_path: bool = False

    @staticmethod
    def now() -> datetime:
        return datetime.now(timezone.utc)


@dataclass(frozen=True)
class ActionResult:
    ok: bool
    detail: str
