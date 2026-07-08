from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional

from .models import ActionKind, SafeAction, SessionStatus, SessionUpdate, SurfaceKind, ToolKind


HIGH_RISK_PATTERNS = (
    "rm -rf",
    "delete",
    "drop database",
    "format",
    "erase",
    "private key",
    "secret",
    "password",
    "credential",
)


def classify_session_text(title: str, text: str, source_id: str) -> SessionUpdate:
    haystack = f"{title}\n{text}".lower()
    tool = _detect_tool(haystack)
    surface = _detect_surface(haystack)
    safe_action = _detect_safe_action(text)
    status = _detect_status(haystack, safe_action)
    summary = _summary(text, status, safe_action)

    return SessionUpdate(
        session_id=source_id,
        title=title or source_id,
        tool=tool,
        surface=surface,
        status=status,
        summary=summary,
        updated_at=datetime.now(timezone.utc),
        safe_action=safe_action,
        source="classifier",
    )


def _detect_tool(text: str) -> ToolKind:
    if "claude" in text:
        return ToolKind.CLAUDE_CODE
    if "codex" in text:
        return ToolKind.CODEX
    return ToolKind.UNKNOWN


def _detect_surface(text: str) -> SurfaceKind:
    terminal_markers = ("terminal", "iterm", "powershell", "cmd", "windows terminal", "bash", "zsh")
    desktop_markers = ("desktop", "app", "codex")
    if any(marker in text for marker in terminal_markers):
        return SurfaceKind.TERMINAL
    if any(marker in text for marker in desktop_markers):
        return SurfaceKind.DESKTOP
    return SurfaceKind.UNKNOWN


def _detect_status(text: str, safe_action: Optional[SafeAction]) -> SessionStatus:
    if safe_action or _has_action_prompt(text):
        return SessionStatus.NEEDS_ACTION
    if any(token in text for token in ("executing", "running", "working", "building", "testing", "thinking", "正在", "执行中", "运行中", "处理中")):
        return SessionStatus.RUNNING
    if any(
        token in text
        for token in (
            "done",
            "complete",
            "completed",
            "all tests passed",
            "finished",
            "crunched for",
            "完成",
            "已完成",
            "通过",
            "你好",
            "有什么可以帮",
        )
    ):
        return SessionStatus.IDLE
    return SessionStatus.UNKNOWN


def _detect_safe_action(text: str) -> Optional[SafeAction]:
    prompt = " ".join(line.strip() for line in text.splitlines() if line.strip())
    normalized = prompt.lower()
    if not prompt:
        return None
    if any(pattern in normalized for pattern in HIGH_RISK_PATTERNS):
        return None
    if re.search(r"\b\(?(yes|y)\s*/\s*(no|n)\)?\b", normalized) or " yes/no" in normalized:
        return SafeAction(ActionKind.YES_NO, ("Yes", "No"), prompt)
    if _has_numbered_options(normalized, ("yes", "y"), ("no", "n")) and _looks_like_question(normalized):
        return SafeAction(ActionKind.YES_NO, ("Yes", "No"), prompt)
    if re.search(r"\ballow\s*/\s*deny\b", normalized):
        return SafeAction(ActionKind.ALLOW_DENY, ("Allow", "Deny"), prompt)
    if re.search(r"\bcontinue\s*/\s*stop\b", normalized):
        return SafeAction(ActionKind.CONTINUE_STOP, ("Continue", "Stop"), prompt)
    return None


def _has_action_prompt(text: str) -> bool:
    normalized = text.lower()
    if re.search(r"\b\(?(yes|y)\s*/\s*(no|n)\)?\b", normalized) or " yes/no" in normalized:
        return True
    if _has_numbered_options(normalized, ("yes", "y"), ("no", "n")) and _looks_like_question(normalized):
        return True
    action_markers = (
        "waiting for",
        "requires confirmation",
        "needs your confirmation",
        "approve",
        "confirm",
        "需要确认",
        "等待确认",
        "是否",
        "确认",
        "允许",
    )
    return any(marker in text for marker in action_markers)


def _has_numbered_options(text: str, first_options: tuple[str, ...], second_options: tuple[str, ...]) -> bool:
    first = "|".join(re.escape(option) for option in first_options)
    second = "|".join(re.escape(option) for option in second_options)
    return bool(
        re.search(rf"(?:^|\s)(?:1|①|a)[.)、]?\s*(?:{first})\b", text)
        and re.search(rf"(?:^|\s)(?:2|②|b)[.)、]?\s*(?:{second})\b", text)
    )


def _looks_like_question(text: str) -> bool:
    return "?" in text or any(marker in text for marker in ("do you want", "would you like", "是否", "要不要", "确认"))


def _summary(text: str, status: SessionStatus, safe_action: Optional[SafeAction]) -> str:
    if safe_action:
        return safe_action.prompt[:140]
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if lines:
        return lines[-1][:140]
    return status.value.replace("_", " ")
