from __future__ import annotations

import json
import platform
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, List, Optional, Tuple

from .cleanup import cleanup_session_files
from .classifier import classify_session_text
from .models import ActionKind, SafeAction, SessionStatus, SessionUpdate, SurfaceKind, ToolKind
from .terminal_bridge import clean_terminal_text


SOURCE_COMMAND_TIMEOUT_SECONDS = 4.0
DEFAULT_CLAUDE_SESSIONS_DIR = Path.home() / ".claude" / "sessions"
DEFAULT_CODEX_SESSIONS_DIR = Path.home() / ".codex" / "sessions"
CLAUDE_SESSION_STATUS_FRESH_SECONDS = 30.0
CODEX_SESSION_RUNNING_STALE_SECONDS = 10 * 60.0
CODEX_SESSION_COMPLETED_VISIBLE_SECONDS = 120.0
CODEX_SESSION_TAIL_BYTES = 256 * 1024
CODEX_SESSION_HEAD_BYTES = 64 * 1024


class JsonSessionSource:
    volatile_source = "json"

    def __init__(
        self,
        directory: Path,
        cleanup_after_seconds: int = 7 * 24 * 60 * 60,
        source_started_at: Optional[datetime] = None,
    ):
        self.directory = directory
        self.cleanup_after_seconds = cleanup_after_seconds
        self.source_started_at = source_started_at

    def poll(self) -> List[SessionUpdate]:
        if not self.directory.exists():
            return []
        cleanup_session_files(self.directory, self.cleanup_after_seconds)
        updates: List[SessionUpdate] = []
        for path in sorted(self.directory.glob("*.json")):
            update = self._read_update(path)
            if update is not None:
                updates.append(update)
        return updates

    def _read_update(self, path: Path) -> Optional[SessionUpdate]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            updated_at = _parse_datetime(payload.get("updated_at"))
            if self.source_started_at is not None and updated_at < self.source_started_at:
                return None
            return SessionUpdate(
                session_id=str(payload["session_id"]),
                title=str(payload.get("title") or payload["session_id"]),
                tool=ToolKind(str(payload.get("tool", "unknown"))),
                surface=SurfaceKind(str(payload.get("surface", "unknown"))),
                status=SessionStatus(str(payload.get("status", "unknown"))),
                summary=clean_terminal_text(str(payload.get("summary", ""))),
                updated_at=updated_at,
                safe_action=_parse_safe_action(payload),
                source=self.volatile_source,
                window_id=_optional_str(payload.get("window_id")),
                process_id=_optional_int(payload.get("process_id")),
                process_name=_optional_str(payload.get("process_name")),
                focus_process_id=_optional_int(payload.get("focus_process_id")),
                focus_app_name=_optional_str(payload.get("focus_app_name")),
                cwd=_optional_str(payload.get("cwd")),
                view_ack_required=_optional_bool(payload.get("view_ack_required")),
                tool_display_name=_optional_str(payload.get("tool_display_name")),
                generated_conversation_path=_optional_bool(payload.get("generated_conversation_path")),
            )
        except (KeyError, ValueError, TypeError, json.JSONDecodeError, OSError):
            return None


class OsWindowSource:
    volatile_source = "os-window"

    def poll(self) -> Optional[List[SessionUpdate]]:
        system = platform.system().lower()
        if system == "darwin":
            rows = _run_command(_macos_window_command())
        elif system == "windows":
            rows = _run_command(_windows_window_command())
        else:
            rows = []
        if rows is None:
            return None
        return list(_classify_window_rows(rows))


class ProcessSource:
    volatile_source = "process"

    def __init__(
        self,
        claude_sessions_dir: Optional[Path] = None,
        source_started_at: Optional[datetime] = None,
        now: Optional[Callable[[], datetime]] = None,
    ):
        self.claude_sessions_dir = claude_sessions_dir or DEFAULT_CLAUDE_SESSIONS_DIR
        self.source_started_at = source_started_at
        self.now = now or (lambda: datetime.now(timezone.utc))

    def poll(self) -> Optional[List[SessionUpdate]]:
        system = platform.system().lower()
        if system == "windows":
            rows = _run_command(_windows_process_command())
        else:
            rows = _run_command(_posix_process_command())
        if rows is None:
            return None
        return list(
            _classify_process_rows(
                rows,
                claude_sessions_dir=self.claude_sessions_dir,
                source_started_at=self.source_started_at,
                now=self.now(),
            )
        )


class CodexSessionSource:
    volatile_source = "codex-session"

    def __init__(
        self,
        directory: Optional[Path] = None,
        now: Optional[Callable[[], datetime]] = None,
        running_stale_seconds: float = CODEX_SESSION_RUNNING_STALE_SECONDS,
        completed_visible_seconds: float = CODEX_SESSION_COMPLETED_VISIBLE_SECONDS,
        source_started_at: Optional[datetime] = None,
    ):
        self.directory = directory or DEFAULT_CODEX_SESSIONS_DIR
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.running_stale_seconds = running_stale_seconds
        self.completed_visible_seconds = completed_visible_seconds
        self.source_started_at = source_started_at

    def poll(self) -> List[SessionUpdate]:
        if not self.directory.exists():
            return []
        current = self.now()
        updates: List[SessionUpdate] = []
        paths = sorted(self.directory.glob("**/*.jsonl"), key=lambda path: path.stat().st_mtime, reverse=True)
        for path in paths[:80]:
            update = _read_codex_session_update(
                path,
                current,
                self.running_stale_seconds,
                self.completed_visible_seconds,
                self.source_started_at,
            )
            if update is not None:
                updates.append(update)
        return updates


def _classify_window_rows(rows: Iterable[str]) -> Iterable[SessionUpdate]:
    for index, row in enumerate(rows):
        if not row.strip():
            continue
        metadata = _parse_window_row(row)
        title = metadata.get("title") or row.strip()
        process_name = metadata.get("process_name")
        window_id = metadata.get("window_id")
        process_id = _optional_int(metadata.get("process_id"))
        lower = f"{process_name or ''} {title}".lower()
        if not any(token in lower for token in ("claude", "codex")):
            continue
        source_id = f"window-{window_id or process_id or index}"
        update = classify_session_text(title=title.strip(), text=title.strip(), source_id=source_id)
        yield SessionUpdate(
            session_id=update.session_id,
            title=update.title,
            tool=update.tool,
            surface=SurfaceKind.DESKTOP,
            status=update.status,
            summary=update.summary,
            updated_at=update.updated_at,
            safe_action=update.safe_action,
            source="os-window",
            window_id=window_id,
            process_id=process_id,
            process_name=process_name,
        )


@dataclass(frozen=True)
class _ClaudeSessionState:
    status: Optional[SessionStatus]
    cwd: Optional[str]
    updated_at: Optional[datetime]


@dataclass(frozen=True)
class AiToolDefinition:
    key: str
    display_name: str
    tool: ToolKind = ToolKind.UNKNOWN
    cli_executables: Tuple[str, ...] = ()
    desktop_main_binaries: Tuple[str, ...] = ()
    ignored_command_tokens: Tuple[str, ...] = ()
    generated_conversation_path_patterns: Tuple[str, ...] = ()


AI_TOOL_DEFINITIONS: Tuple[AiToolDefinition, ...] = (
    AiToolDefinition(
        key="codex",
        display_name="Codex",
        tool=ToolKind.CODEX,
        cli_executables=("codex", "codex.exe"),
        desktop_main_binaries=("/codex.app/contents/macos/codex",),
        ignored_command_tokens=(" app-server", " sandbox"),
        generated_conversation_path_patterns=(r"(^|/|\\)Documents(/|\\)Codex(/|\\)\d{4}-\d{2}-\d{2}(/|\\)[^/\\]+$",),
    ),
    AiToolDefinition(
        key="claude",
        display_name="Claude",
        tool=ToolKind.CLAUDE_CODE,
        cli_executables=("claude", "claude.exe"),
        desktop_main_binaries=("/claude.app/contents/macos/claude",),
    ),
    AiToolDefinition(
        key="chatgpt",
        display_name="ChatGPT",
        cli_executables=("chatgpt", "chatgpt.exe"),
        desktop_main_binaries=("/chatgpt.app/contents/macos/chatgpt",),
    ),
    AiToolDefinition(
        key="gemini",
        display_name="Gemini",
        cli_executables=("gemini", "gemini.exe"),
        desktop_main_binaries=("/gemini.app/contents/macos/gemini",),
    ),
    AiToolDefinition(
        key="perplexity",
        display_name="Perplexity",
        cli_executables=("perplexity", "perplexity.exe"),
        desktop_main_binaries=("/perplexity.app/contents/macos/perplexity",),
    ),
    AiToolDefinition(
        key="poe",
        display_name="Poe",
        cli_executables=("poe", "poe.exe"),
        desktop_main_binaries=("/poe.app/contents/macos/poe",),
    ),
    AiToolDefinition(key="cursor-agent", display_name="Cursor Agent", cli_executables=("cursor-agent", "cursor-agent.exe")),
    AiToolDefinition(key="gemini-cli", display_name="Gemini", cli_executables=("gemini-cli", "gemini-cli.exe")),
    AiToolDefinition(key="qwen-code", display_name="Qwen Code", cli_executables=("qwen", "qwen-code", "qwen.exe")),
    AiToolDefinition(key="aider", display_name="Aider", cli_executables=("aider", "aider.exe")),
    AiToolDefinition(key="opencode", display_name="OpenCode", cli_executables=("opencode", "opencode.exe")),
    AiToolDefinition(key="goose", display_name="Goose", cli_executables=("goose", "goose.exe")),
    AiToolDefinition(key="continue", display_name="Continue", cli_executables=("continue", "continue.exe")),
    AiToolDefinition(
        key="kiro",
        display_name="Kiro",
        cli_executables=("kiro", "kiro.exe"),
        desktop_main_binaries=("/kiro.app/contents/macos/kiro",),
    ),
)


def _classify_process_rows(
    rows: Iterable[str],
    claude_sessions_dir: Optional[Path] = None,
    source_started_at: Optional[datetime] = None,
    now: Optional[datetime] = None,
) -> Iterable[SessionUpdate]:
    current = now or datetime.now(timezone.utc)
    for row in rows:
        metadata = _parse_window_row(row)
        process_id = _optional_int(metadata.get("process_id"))
        process_name = metadata.get("process_name") or ""
        command = metadata.get("command") or ""
        cwd = metadata.get("cwd") or ""
        cpu_percent = _optional_float(metadata.get("cpu_percent"))
        stat = metadata.get("stat") or ""
        active_child_count = _optional_int(metadata.get("active_child_count"))
        focus_process_id = _optional_int(metadata.get("focus_process_id"))
        focus_app_name = _optional_str(metadata.get("focus_app_name"))
        desktop_app = _detect_desktop_app(process_name, command)
        if desktop_app is not None:
            tool_definition = desktop_app
            tool = tool_definition.tool
            surface = SurfaceKind.DESKTOP
            status = SessionStatus.IDLE
            status_source = "desktop-process"
            title = f"{tool_definition.display_name} Desktop"
            summary = f"{tool_definition.display_name} 桌面 App 正在运行；尚未识别具体对话，先作为空闲入口。"
            focus_process_id = focus_process_id or process_id
            focus_app_name = focus_app_name or tool_definition.display_name
            updated_at = current
        else:
            tool_definition = _detect_process_tool(process_name, command)
            if tool_definition is not None and _is_detached_terminal_process(stat):
                continue
            tool = tool_definition.tool if tool_definition is not None else None
            surface = SurfaceKind.TERMINAL
            claude_state = (
                _read_claude_session_state(process_id, claude_sessions_dir, cwd)
                if tool_definition is not None and tool_definition.tool == ToolKind.CLAUDE_CODE and process_id is not None
                else None
            )
            status = (
                claude_state.status
                if claude_state is not None and claude_state.status is not None
                else _process_only_terminal_status(cpu_percent, stat, active_child_count)
            )
            status_source = "claude-session" if claude_state is not None and claude_state.status is not None else "process"
            cwd = claude_state.cwd if claude_state is not None and claude_state.cwd else cwd
            updated_at = (
                claude_state.updated_at
                if claude_state is not None and claude_state.status is not None and claude_state.updated_at is not None
                else current
            )
            title = _process_title(tool_definition, cwd) if tool_definition is not None else ""
            summary = f"只能确认 CLI 会话进程存在（{tool_definition.display_name if tool_definition else 'AI'}），无法读取终端内容、具体进度、待确认状态或 Yes/No 按钮。"
        if tool is None or process_id is None or tool_definition is None:
            continue
        yield SessionUpdate(
            session_id=f"process-{process_id}",
            title=title,
            tool=tool,
            surface=surface,
            status=status,
            summary=summary,
            updated_at=updated_at,
            source="process",
            process_id=process_id,
            process_name=process_name or title,
            focus_process_id=focus_process_id,
            focus_app_name=focus_app_name,
            cwd=_optional_str(cwd),
            status_source=status_source,
            tool_display_name=tool_definition.display_name,
        )


def _detect_desktop_app(process_name: str, command: str) -> Optional[AiToolDefinition]:
    haystack = f"{process_name or ''} {command or ''}".lower()
    for definition in AI_TOOL_DEFINITIONS:
        if any(main_binary in haystack for main_binary in definition.desktop_main_binaries):
            return definition
    return None


def _tool_definition_for_update(tool: ToolKind, tool_display_name: Optional[str] = None) -> Optional[AiToolDefinition]:
    if tool != ToolKind.UNKNOWN:
        for definition in AI_TOOL_DEFINITIONS:
            if definition.tool == tool:
                return definition
    if tool_display_name:
        normalized_name = tool_display_name.strip().lower()
        for definition in AI_TOOL_DEFINITIONS:
            if definition.display_name.lower() == normalized_name or definition.key.lower() == normalized_name:
                return definition
    return None


def _is_generated_conversation_path(
    tool: ToolKind,
    cwd: Optional[str],
    tool_display_name: Optional[str] = None,
) -> bool:
    if not cwd:
        return False
    definition = _tool_definition_for_update(tool, tool_display_name)
    if definition is None:
        return False
    return any(re.search(pattern, cwd) for pattern in definition.generated_conversation_path_patterns)


def _detect_process_tool(process_name: str, command: str) -> Optional[AiToolDefinition]:
    executable = Path((process_name or "").strip()).name.lower()
    lower_command = f" {command.lower()} "
    for definition in AI_TOOL_DEFINITIONS:
        if executable not in definition.cli_executables:
            continue
        if any(token in lower_command for token in definition.ignored_command_tokens):
            return None
        return definition
    return None


def _process_title(tool_definition: AiToolDefinition, cwd: str) -> str:
    base = "Claude Code CLI" if tool_definition.tool == ToolKind.CLAUDE_CODE else f"{tool_definition.display_name} CLI"
    folder = Path(cwd).name if cwd else ""
    return f"{base} - {folder}" if folder else base


def _posix_process_case_patterns() -> str:
    patterns: List[str] = []
    for definition in AI_TOOL_DEFINITIONS:
        patterns.extend(f"{executable}:*" for executable in definition.cli_executables)
        patterns.extend(f"*:*.{main_binary}" if not main_binary.startswith("/") else f"*:*{main_binary}" for main_binary in definition.desktop_main_binaries)
    return "|".join(patterns)


def _posix_desktop_process_case_patterns() -> str:
    patterns: List[str] = []
    for definition in AI_TOOL_DEFINITIONS:
        patterns.extend(f"*:*.{main_binary}" if not main_binary.startswith("/") else f"*:*{main_binary}" for main_binary in definition.desktop_main_binaries)
    return "|".join(patterns)


def _windows_process_name_regex() -> str:
    names = sorted({executable for definition in AI_TOOL_DEFINITIONS for executable in definition.cli_executables})
    escaped = [name.replace(".", "\\.") for name in names]
    return "^(" + "|".join(escaped) + ")$"


def _process_only_terminal_status(cpu_percent: Optional[float], stat: str, active_child_count: Optional[int]) -> SessionStatus:
    if active_child_count is not None and active_child_count > 0:
        return SessionStatus.RUNNING
    if stat.strip().upper().startswith("R"):
        return SessionStatus.RUNNING
    if cpu_percent is not None:
        return SessionStatus.RUNNING if cpu_percent >= 1.0 else SessionStatus.IDLE
    return SessionStatus.RUNNING


def _is_detached_terminal_process(stat: str) -> bool:
    text = stat.strip()
    return bool(text) and "+" not in text


def _read_codex_session_update(
    path: Path,
    now: datetime,
    running_stale_seconds: float,
    completed_visible_seconds: float,
    source_started_at: Optional[datetime],
) -> Optional[SessionUpdate]:
    records = _read_codex_jsonl_records(path)
    if not records:
        return None
    session_id = _codex_session_id_from_path(path)
    cwd: Optional[str] = None
    user_thread = True
    latest_at: Optional[datetime] = None
    last_started_index = -1
    last_completed_index = -1
    last_needs_action_index = -1
    latest_running_signal_index = -1
    latest_visible_reply_index = -1
    for index, record in enumerate(records):
        timestamp = _parse_codex_timestamp(record.get("timestamp"))
        if timestamp is not None and (latest_at is None or timestamp >= latest_at):
            latest_at = timestamp
        payload = _codex_payload(record)
        if record.get("type") == "session_meta":
            session_id = _optional_str(payload.get("id")) or _optional_str(payload.get("session_id")) or session_id
            cwd = _optional_str(payload.get("cwd")) or cwd
            if _is_codex_internal_thread(payload):
                user_thread = False
        if record.get("type") == "turn_context":
            cwd = _optional_str(payload.get("cwd")) or cwd
        payload_type = str(payload.get("type") or "").strip()
        if payload_type == "task_started":
            last_started_index = index
            latest_running_signal_index = index
        elif payload_type == "task_complete":
            last_completed_index = index
        elif payload_type in {"approval_requested", "apply_patch_approval_requested", "exec_approval_requested", "user_input_requested"}:
            last_needs_action_index = index
        elif payload_type == "agent_message":
            latest_running_signal_index = index
            latest_visible_reply_index = index
        elif payload_type in {"reasoning", "function_call", "custom_tool_call"}:
            latest_running_signal_index = index
    fallback_at = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
    updated_at = latest_at or fallback_at
    if not user_thread:
        return None
    status = _codex_session_status(
        last_started_index,
        last_completed_index,
        last_needs_action_index,
        latest_running_signal_index,
        latest_visible_reply_index,
    )
    if status is None:
        return None
    if source_started_at is not None and updated_at < source_started_at:
        return None
    view_ack_required = _codex_session_requires_view_ack(
        status,
        last_started_index,
        last_completed_index,
        last_needs_action_index,
        latest_visible_reply_index,
    )
    age_seconds = (now - updated_at).total_seconds()
    if status == SessionStatus.IDLE and age_seconds > completed_visible_seconds:
        return None
    if status == SessionStatus.RUNNING and age_seconds > running_stale_seconds:
        return None
    folder = Path(cwd).name if cwd else session_id
    title = f"Codex Desktop - {folder}" if folder else "Codex Desktop"
    return SessionUpdate(
        session_id=f"codex-session-{session_id}",
        title=title,
        tool=ToolKind.CODEX,
        surface=SurfaceKind.DESKTOP,
        status=status,
        summary="Codex 桌面端会话状态",
        updated_at=updated_at,
        source="codex-session",
        focus_app_name="Codex",
        cwd=cwd,
        view_ack_required=view_ack_required,
        generated_conversation_path=_is_generated_conversation_path(ToolKind.CODEX, cwd),
    )


def _codex_session_status(
    last_started_index: int,
    last_completed_index: int,
    last_needs_action_index: int,
    latest_running_signal_index: int,
    latest_visible_reply_index: int,
) -> Optional[SessionStatus]:
    if last_needs_action_index > last_completed_index:
        return SessionStatus.NEEDS_ACTION
    if last_started_index > last_completed_index or latest_running_signal_index > last_completed_index:
        return SessionStatus.RUNNING
    if last_completed_index >= 0:
        if latest_visible_reply_index >= last_started_index:
            return SessionStatus.NEEDS_ACTION
        return SessionStatus.IDLE
    return None


def _codex_session_requires_view_ack(
    status: SessionStatus,
    last_started_index: int,
    last_completed_index: int,
    last_needs_action_index: int,
    latest_visible_reply_index: int,
) -> bool:
    return (
        status == SessionStatus.NEEDS_ACTION
        and last_completed_index >= 0
        and latest_visible_reply_index >= last_started_index
        and last_needs_action_index <= last_completed_index
    )


def _read_codex_jsonl_records(path: Path) -> List[dict]:
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            head = handle.read(CODEX_SESSION_HEAD_BYTES)
            if size > CODEX_SESSION_HEAD_BYTES + CODEX_SESSION_TAIL_BYTES:
                handle.seek(max(0, size - CODEX_SESSION_TAIL_BYTES))
                tail = handle.read()
                raw = head + b"\n" + tail
            else:
                raw = head + handle.read()
    except OSError:
        return []
    records: List[dict] = []
    for line in raw.decode("utf-8", errors="ignore").splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


def _codex_payload(record: dict) -> dict:
    payload = record.get("payload")
    if isinstance(payload, dict):
        return payload
    for key in ("event_msg", "msg", "item"):
        value = record.get(key)
        if isinstance(value, dict):
            return value
    return {}


def _is_codex_internal_thread(payload: dict) -> bool:
    thread_source = str(payload.get("thread_source") or "").strip().lower()
    if thread_source and thread_source != "user":
        return True
    source = payload.get("source")
    if isinstance(source, dict) and "subagent" in source:
        return True
    return False


def _parse_codex_timestamp(value) -> Optional[datetime]:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _codex_session_id_from_path(path: Path) -> str:
    stem = path.stem
    parts = stem.split("-")
    if len(parts) >= 5:
        tail = "-".join(parts[-5:])
        if all(parts[-index] for index in range(1, 6)):
            return tail
    return stem


def _read_claude_session_state(
    process_id: int,
    claude_sessions_dir: Optional[Path],
    cwd: str,
) -> Optional[_ClaudeSessionState]:
    if claude_sessions_dir is None:
        return None
    path = claude_sessions_dir / f"{process_id}.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    recorded_pid = _optional_int(payload.get("pid"))
    if recorded_pid is not None and recorded_pid != process_id:
        return None
    recorded_cwd = _optional_str(payload.get("cwd"))
    if recorded_cwd and cwd and Path(recorded_cwd) != Path(cwd):
        return None
    status = _claude_session_status(payload.get("status"))
    if status not in {SessionStatus.IDLE, SessionStatus.NEEDS_ACTION} and not _claude_session_status_is_fresh(payload.get("updatedAt")):
        status = None
    return _ClaudeSessionState(status=status, cwd=recorded_cwd, updated_at=_parse_millis_datetime(payload.get("updatedAt")))


def _claude_session_status(value) -> Optional[SessionStatus]:
    status = str(value or "").strip().lower()
    if status in {"idle", "ready", "completed"}:
        return SessionStatus.IDLE
    if status in {"busy", "running", "working", "thinking"}:
        return SessionStatus.RUNNING
    if status in {"needs_action", "waiting", "awaiting_user", "waiting_for_user", "waiting_for_input", "prompt"}:
        return SessionStatus.NEEDS_ACTION
    return None


def _claude_session_status_is_fresh(updated_at) -> bool:
    try:
        updated_at_seconds = float(updated_at) / 1000.0
    except (TypeError, ValueError):
        return False
    age_seconds = datetime.now(timezone.utc).timestamp() - updated_at_seconds
    return 0 <= age_seconds <= CLAUDE_SESSION_STATUS_FRESH_SECONDS


def _parse_millis_datetime(value) -> Optional[datetime]:
    try:
        return datetime.fromtimestamp(float(value) / 1000.0, timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


def _parse_datetime(value) -> datetime:
    if isinstance(value, str) and value:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed
    return datetime.now(timezone.utc)


def _parse_window_row(row: str) -> dict:
    parts = [part for part in row.split("\t") if "=" in part]
    if not parts:
        return {"title": row.strip()}
    metadata = {}
    for part in parts:
        key, value = part.split("=", 1)
        metadata[key.strip()] = value.strip()
    return metadata


def _optional_str(value) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_int(value) -> Optional[int]:
    try:
        if value is None or str(value).strip() == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_float(value) -> Optional[float]:
    try:
        if value is None or str(value).strip() == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y"}


def _parse_safe_action(payload: dict) -> Optional[SafeAction]:
    action = payload.get("safe_action")
    if not isinstance(action, dict):
        return None
    try:
        return SafeAction(
            ActionKind(str(action["kind"])),
            tuple(str(option) for option in action["options"]),
            clean_terminal_text(str(action.get("prompt") or payload.get("summary") or "")),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _run_command(command: List[str]) -> Optional[List[str]]:
    try:
        completed = subprocess.run(command, check=False, capture_output=True, text=True, timeout=SOURCE_COMMAND_TIMEOUT_SECONDS)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.splitlines()


def _macos_window_command() -> List[str]:
    script = (
        'tell application "System Events"\n'
        'set output to ""\n'
        'repeat with proc in application processes\n'
        'repeat with win in windows of proc\n'
        'try\n'
        'set output to output & "window_id=" & (id of win as string) & tab & "process_id=" & (unix id of proc as string) & tab & "process_name=" & name of proc & tab & "title=" & name of win & linefeed\n'
        'end try\n'
        'end repeat\n'
        'end repeat\n'
        'return output\n'
        'end tell'
    )
    return ["osascript", "-e", script]


def _windows_window_command() -> List[str]:
    script = (
        "Get-Process | Where-Object {$_.MainWindowTitle} | "
        "ForEach-Object {'window_id=' + $_.MainWindowHandle + \"`t\" + 'process_id=' + $_.Id + \"`t\" + 'process_name=' + $_.ProcessName + \"`t\" + 'title=' + $_.MainWindowTitle}"
    )
    return ["powershell", "-NoProfile", "-Command", script]


def _posix_process_command() -> List[str]:
    process_case_patterns = _posix_process_case_patterns()
    desktop_process_case_patterns = _posix_desktop_process_case_patterns()
    script = (
        "focus_app_name() { case \"$1\" in "
        "*/Terminal.app/*) printf 'Terminal' ;; "
        "*/iTerm.app/*|*/iTerm2.app/*) printf 'iTerm' ;; "
        "*/Warp.app/*) printf 'Warp' ;; "
        "*/WezTerm.app/*) printf 'WezTerm' ;; "
        "*/kitty.app/*) printf 'kitty' ;; "
        "*/Alacritty.app/*) printf 'Alacritty' ;; "
        "*/Zed.app/*) printf 'Zed' ;; "
        "*/Cursor.app/*) printf 'Cursor' ;; "
        "*Visual\\ Studio\\ Code*.app*) printf 'Visual Studio Code' ;; "
        "*/Windsurf.app/*) printf 'Windsurf' ;; "
        "*Sublime\\ Text.app*) printf 'Sublime Text' ;; "
        "*/Nova.app/*) printf 'Nova' ;; "
        "*/Xcode.app/*) printf 'Xcode' ;; "
        "*Android\\ Studio.app*) printf 'Android Studio' ;; "
        "*/CLion.app/*) printf 'CLion' ;; "
        "*/GoLand.app/*) printf 'GoLand' ;; "
        "*IntelliJ\\ IDEA*.app*) printf 'IntelliJ IDEA' ;; "
        "*/PhpStorm.app/*) printf 'PhpStorm' ;; "
        "*/PyCharm*.app/*) printf 'PyCharm' ;; "
        "*/Rider.app/*) printf 'Rider' ;; "
        "*/RubyMine.app/*) printf 'RubyMine' ;; "
        "*/WebStorm.app/*) printf 'WebStorm' ;; "
        "*/Codex.app/*) printf 'Codex' ;; "
        "*) return 1 ;; "
        "esac; }; "
        "all_process_rows=$(ps -axo pid=,ppid=,pgid=,stat=,%cpu=,comm=,args= 2>/dev/null); "
        "printf '%s\\n' \"$all_process_rows\" | while read -r pid ppid pgid stat cpu comm args; do "
        "exe=$(basename -- \"$comm\" | tr '[:upper:]' '[:lower:]'); "
        "first_arg=${args%% *}; "
        "first_arg_lc=$(printf '%s' \"$first_arg\" | tr '[:upper:]' '[:lower:]'); "
        f"case \"$exe:$first_arg_lc\" in {process_case_patterns}) ;; "
        "*) continue ;; "
        "esac; "
        f"case \"$exe:$first_arg_lc\" in {desktop_process_case_patterns}) "
        "printf 'process_id=%s\\tprocess_name=%s\\tcommand=%s\\tcwd=\\tcpu_percent=%s\\tstat=%s\\tactive_child_count=0\\tfocus_process_id=%s\\tfocus_app_name=\\n' \"$pid\" \"$comm\" \"$args\" \"$cpu\" \"$stat\" \"$pid\"; "
        "continue ;; "
        "esac; "
        "case \"$exe:$first_arg_lc\" in claude:*|claude.exe:*) ;; *) cwd=$(lsof -a -p \"$pid\" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p' | head -n 1) ;; esac; "
        "case \"$exe:$first_arg_lc\" in claude:*|claude.exe:*) active_children=0 ;; *) active_children=$(printf '%s\\n' \"$all_process_rows\" | awk -v pgid=\"$pgid\" -v pid=\"$pid\" '"
        "function background_ai_helper(text) { "
        "text=tolower(text); "
        "return text ~ /(mcp|tavily|searxng)/ && text ~ /(npm|npx|node|\\.bin)/ "
        "} "
        "$3 == pgid && $1 != pid && $4 !~ /^Z/ && ($4 ~ /^R/ || $5 >= 1.0) { "
        "text=\"\"; for (i=6; i<=NF; i++) text=text \" \" $i; "
        "if (background_ai_helper(text)) next; "
        "count++ "
        "} "
        "END {print count + 0}') ;; esac; "
        "focus_pid=; focus_app=; ancestor=\"$ppid\"; hops=0; "
        "while [ -n \"$ancestor\" ] && [ \"$ancestor\" != \"1\" ] && [ \"$hops\" -lt 8 ]; do "
        "ancestor_row=$(printf '%s\\n' \"$all_process_rows\" | awk -v target=\"$ancestor\" '$1 == target {text=\"\"; for (i=7; i<=NF; i++) text=text \" \" $i; print $2 \"|\" text; exit}'); "
        "[ -n \"$ancestor_row\" ] || break; "
        "ancestor_args=${ancestor_row#*|}; "
        "app=$(focus_app_name \"$ancestor_args\" || true); "
        "if [ -n \"$app\" ]; then focus_pid=\"$ancestor\"; focus_app=\"$app\"; break; fi; "
        "ancestor=${ancestor_row%%|*}; "
        "hops=$((hops + 1)); "
        "done; "
        "printf 'process_id=%s\\tprocess_name=%s\\tcommand=%s\\tcwd=%s\\tcpu_percent=%s\\tstat=%s\\tactive_child_count=%s\\tfocus_process_id=%s\\tfocus_app_name=%s\\n' \"$pid\" \"$comm\" \"$args\" \"$cwd\" \"$cpu\" \"$stat\" \"$active_children\" \"$focus_pid\" \"$focus_app\"; "
        "done"
    )
    return ["sh", "-c", script]


def _windows_process_command() -> List[str]:
    process_name_regex = _windows_process_name_regex()
    script = (
        "Get-CimInstance Win32_Process | "
        f"Where-Object {{$_.Name.ToLowerInvariant() -match '{process_name_regex}'}} | "
        "ForEach-Object {'process_id=' + $_.ProcessId + \"`t\" + 'process_name=' + $_.Name + \"`t\" + 'command=' + $_.CommandLine}"
    )
    return ["powershell", "-NoProfile", "-Command", script]
