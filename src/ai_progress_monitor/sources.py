from __future__ import annotations

import json
import os
import platform
import re
import signal
import sqlite3
import subprocess
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterable, List, Optional, Tuple

from .cleanup import cleanup_session_files
from .classifier import classify_session_text
from .models import ActionKind, SafeAction, SessionStatus, SessionUpdate, SurfaceKind, ToolKind
from .terminal_bridge import clean_terminal_text


SOURCE_COMMAND_TIMEOUT_SECONDS = 4.0
DEFAULT_CLAUDE_SESSIONS_DIR = Path.home() / ".claude" / "sessions"
DEFAULT_CODEX_SESSIONS_DIR = Path.home() / ".codex" / "sessions"
DEFAULT_QODER_LOGS_DIRS: Tuple[Path, ...] = (
    Path.home() / "Library" / "Application Support" / "QoderCN" / "logs",
    Path.home() / "Library" / "Application Support" / "QoderCN" / "SharedClientCache" / "logs",
    Path.home() / "Library" / "Application Support" / "Qoder" / "logs",
    Path.home() / "Library" / "Application Support" / "Qoder" / "SharedClientCache" / "logs",
)
DEFAULT_WORKBUDDY_DB_PATHS: Tuple[Path, ...] = (Path.home() / ".workbuddy" / "workbuddy.db",)
CLAUDE_SESSION_STATUS_FRESH_SECONDS = 30.0
CLAUDE_INITIAL_IDLE_GRACE_SECONDS = 2.0
CODEX_SESSION_RUNNING_STALE_SECONDS = 10 * 60.0
CODEX_SESSION_COMPLETED_VISIBLE_SECONDS = 120.0
CODEX_SESSION_TAIL_BYTES = 256 * 1024
CODEX_SESSION_HEAD_BYTES = 64 * 1024
QODER_TASK_RUNNING_STALE_SECONDS = 10 * 60.0
QODER_REFRESH_STALE_SNAPSHOT_SECONDS = 3.0
QODER_TERMINAL_RESULT_IDLE_GRACE_SECONDS = 5.0
QODER_SHORT_RUN_MIN_SECONDS = 1.0
QODER_SHORT_RUN_MAX_SECONDS = 6.0
QODER_SHORT_RUN_VISIBLE_AFTER_COMPLETION_SECONDS = 8.0
QODER_LOG_TAIL_BYTES = 512 * 1024
QODER_LOG_SESSION_DIR_LIMIT = 6
QODER_LOG_WINDOW_DIR_LIMIT = 8
QODER_LOG_PATH_LIMIT = 24
QODER_TASK_SESSION_LIMIT = 8
QODER_CACHE_DB_ROW_LIMIT = 48
QODER_STATUS_LOG_FILENAMES: Tuple[str, ...] = ("quest.log", "agent.log")
WORKBUDDY_SESSION_RUNNING_STALE_SECONDS = 10 * 60.0
WORKBUDDY_SESSION_ROW_LIMIT = 20
WORKBUDDY_SESSION_LIMIT = 8
WORKBUDDY_SESSION_LOG_TAIL_BYTES = 64 * 1024
WORKBUDDY_RUNTIME_LOG_TAIL_BYTES = 1024 * 1024
WORKBUDDY_RUNTIME_LOG_PATH_LIMIT = 24
WORKBUDDY_RUNTIME_DB_CLOCK_SKEW_SECONDS = 2.0
RUNNING_STATUS_NAMES = frozenset(
    {
        "running",
        "busy",
        "working",
        "thinking",
        "processing",
        "planning",
        "inprogress",
        "inflight",
        "prompting",
        "streaming",
    }
)
USER_ATTENTION_STATUS_NAMES = frozenset(
    {
        "needsaction",
        "actionrequired",
        "waiting",
        "awaitinguser",
        "waitingforuser",
        "waitingonuser",
        "awaitingresponse",
        "waitingforinput",
        "awaitinginput",
        "inputrequired",
        "userinputrequired",
        "requiresuserinput",
        "needsinput",
        "inputneeded",
        "requiresapproval",
        "approvalrequired",
        "needsapproval",
        "approvalneeded",
        "awaitingapproval",
        "waitingforapproval",
        "needsreview",
        "reviewrequired",
        "needsconfirmation",
        "confirmationrequired",
        "suspended",
        "paused",
        "blocked",
    }
)
QODER_USER_ATTENTION_SIGNAL_STATUS_NAMES = frozenset(
    {
        "awaitinguser",
        "waitingforuser",
        "waitingonuser",
        "awaitingresponse",
        "waitingforinput",
        "awaitinginput",
        "inputrequired",
        "userinputrequired",
        "requiresuserinput",
        "needsinput",
        "inputneeded",
        "requiresapproval",
        "approvalrequired",
        "needsapproval",
        "approvalneeded",
        "awaitingapproval",
        "waitingforapproval",
        "needsconfirmation",
        "confirmationrequired",
        "suspended",
        "blocked",
    }
)


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
                status_source=_optional_str(payload.get("status_source")),
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
        qoder_logs_dirs: Optional[Iterable[Path]] = None,
        workbuddy_db_paths: Optional[Iterable[Path]] = None,
        source_started_at: Optional[datetime] = None,
        now: Optional[Callable[[], datetime]] = None,
    ):
        self.claude_sessions_dir = claude_sessions_dir or DEFAULT_CLAUDE_SESSIONS_DIR
        self.qoder_logs_dirs = tuple(qoder_logs_dirs) if qoder_logs_dirs is not None else DEFAULT_QODER_LOGS_DIRS
        self.workbuddy_db_paths = (
            tuple(workbuddy_db_paths) if workbuddy_db_paths is not None else DEFAULT_WORKBUDDY_DB_PATHS
        )
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
                qoder_logs_dirs=self.qoder_logs_dirs,
                workbuddy_db_paths=self.workbuddy_db_paths,
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
    status_source: str = "claude-session"


@dataclass(frozen=True)
class _QoderTaskState:
    status: SessionStatus
    updated_at: datetime
    task_id: Optional[str] = None
    title: Optional[str] = None
    cwd: Optional[str] = None
    user_attention_signal: bool = False
    last_running_at: Optional[datetime] = None
    short_run_visibility_allowed: bool = True


@dataclass(frozen=True)
class _QoderTaskMetadata:
    updated_at: datetime
    title: Optional[str] = None
    cwd: Optional[str] = None


@dataclass(frozen=True)
class _WorkBuddySessionState:
    status: SessionStatus
    updated_at: datetime
    session_id: str
    title: Optional[str] = None
    cwd: Optional[str] = None
    user_attention_signal: bool = False
    status_source: str = "workbuddy-db"


@dataclass(frozen=True)
class _WorkBuddyRuntimeState:
    status: SessionStatus
    updated_at: datetime
    session_id: str


@dataclass(frozen=True)
class AiToolDefinition:
    key: str
    display_name: str
    tool: ToolKind = ToolKind.UNKNOWN
    cli_executables: Tuple[str, ...] = ()
    desktop_main_binaries: Tuple[str, ...] = ()
    ignored_command_tokens: Tuple[str, ...] = ()
    ignored_desktop_command_tokens: Tuple[str, ...] = ()
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
    AiToolDefinition(
        key="workbuddy",
        display_name="WorkBuddy",
        cli_executables=("workbuddy", "workbuddy.exe", "codebuddy", "codebuddy.exe"),
        desktop_main_binaries=(
            "/workbuddy.app/contents/macos/workbuddy",
            "/workbuddy.app/contents/macos/electron",
        ),
        ignored_desktop_command_tokens=(
            "/main/daemon-app-server-entry.js",
            "/main/sidecar-entry.js",
            "/cli/bin/codebuddy --serve",
            "mcp-app-bootstrap.cjs",
        ),
    ),
    AiToolDefinition(
        key="qoder",
        display_name="Qoder",
        cli_executables=("qoder", "qoder.exe", "qodercn", "qodercn.exe"),
        desktop_main_binaries=(
            "/qoder.app/contents/macos/qoder",
            "/qoder.app/contents/macos/electron",
            "/qoder cn.app/contents/macos/electron",
        ),
        generated_conversation_path_patterns=(
            r"(^|/|\\)Documents(/|\\)QoderCN(/|\\)\d{4}-\d{2}-\d{2}(/|\\)[^/\\]+$",
            r"(^|/|\\)Documents(/|\\)Qoder(/|\\)\d{4}-\d{2}-\d{2}(/|\\)[^/\\]+$",
        ),
        ignored_command_tokens=(
            "/qoder.app/contents/resources/app/resources/bin/",
            "/qoder cn.app/contents/resources/app/resources/bin/",
        ),
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
    qoder_logs_dir: Optional[Path] = None,
    qoder_logs_dirs: Iterable[Path] = (),
    workbuddy_db_paths: Iterable[Path] = DEFAULT_WORKBUDDY_DB_PATHS,
    source_started_at: Optional[datetime] = None,
    now: Optional[datetime] = None,
) -> Iterable[SessionUpdate]:
    current = now or datetime.now(timezone.utc)
    qoder_log_dirs = _qoder_log_dirs(qoder_logs_dir, qoder_logs_dirs)
    qoder_states_by_dirs: dict[Tuple[str, ...], List[_QoderTaskState]] = {}
    workbuddy_states: Optional[List[_WorkBuddySessionState]] = None
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
            tool_display_name = _tool_display_name_for_process(tool_definition, process_name, command)
            tool = tool_definition.tool
            surface = SurfaceKind.DESKTOP
            title = f"{tool_display_name} Desktop"
            if tool_definition.key == "qoder" and qoder_log_dirs:
                selected_qoder_log_dirs = _qoder_log_dirs_for_process(process_name, command, qoder_log_dirs)
                cache_key = tuple(str(path) for path in selected_qoder_log_dirs)
                if cache_key not in qoder_states_by_dirs:
                    qoder_states_by_dirs[cache_key] = _read_qoder_active_task_states(
                        selected_qoder_log_dirs,
                        current,
                        source_started_at,
                    )
                qoder_states = qoder_states_by_dirs[cache_key]
                if qoder_states:
                    focus_process_id = focus_process_id or process_id
                    focus_app_name = focus_app_name or tool_display_name
                    for qoder_state in qoder_states:
                        yield SessionUpdate(
                            session_id=_qoder_task_session_id(qoder_state, process_id),
                            title=_qoder_task_title(tool_display_name, qoder_state),
                            tool=tool,
                            surface=surface,
                            status=qoder_state.status,
                            summary=_qoder_task_summary(qoder_state.status),
                            updated_at=qoder_state.updated_at,
                            source="process",
                            process_id=process_id,
                            process_name=process_name or title,
                            focus_process_id=focus_process_id,
                            focus_app_name=focus_app_name,
                            cwd=qoder_state.cwd,
                            view_ack_required=_qoder_task_requires_view_ack(qoder_state),
                            status_source="qoder-log",
                            tool_display_name=tool_display_name,
                            generated_conversation_path=_is_generated_conversation_path(
                                tool,
                                qoder_state.cwd,
                                tool_display_name,
                            ),
                        )
                    continue
            if tool_definition.key == "workbuddy" and workbuddy_db_paths:
                if workbuddy_states is None:
                    workbuddy_states = _read_workbuddy_active_session_states(
                        workbuddy_db_paths,
                        current,
                        source_started_at,
                    )
                if workbuddy_states:
                    focus_process_id = focus_process_id or process_id
                    focus_app_name = focus_app_name or tool_display_name
                    for workbuddy_state in workbuddy_states:
                        yield SessionUpdate(
                            session_id=_workbuddy_session_update_id(workbuddy_state),
                            title=_workbuddy_session_title(tool_display_name, workbuddy_state),
                            tool=tool,
                            surface=surface,
                            status=workbuddy_state.status,
                            summary=_workbuddy_session_summary(workbuddy_state.status),
                            updated_at=workbuddy_state.updated_at,
                            source="process",
                            process_id=process_id,
                            process_name=process_name or title,
                            focus_process_id=focus_process_id,
                            focus_app_name=focus_app_name,
                            cwd=workbuddy_state.cwd,
                            view_ack_required=_workbuddy_session_requires_view_ack(workbuddy_state),
                            status_source=workbuddy_state.status_source,
                            tool_display_name=tool_display_name,
                            generated_conversation_path=False,
                        )
                    continue
            status = SessionStatus.IDLE
            status_source = "desktop-process"
            updated_at = current
            summary = f"{tool_display_name} 桌面 App 正在运行；尚未识别具体对话，先作为空闲入口。"
            focus_process_id = focus_process_id or process_id
            focus_app_name = focus_app_name or tool_display_name
        else:
            tool_definition = _detect_process_tool(process_name, command)
            if tool_definition is not None and _is_detached_terminal_process(stat):
                continue
            tool_display_name = (
                _tool_display_name_for_process(tool_definition, process_name, command)
                if tool_definition is not None
                else None
            )
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
            status_source = claude_state.status_source if claude_state is not None and claude_state.status is not None else "process"
            cwd = claude_state.cwd if claude_state is not None and claude_state.cwd else cwd
            updated_at = (
                claude_state.updated_at
                if claude_state is not None and claude_state.status is not None and claude_state.updated_at is not None
                else current
            )
            title = _process_title(tool_definition, cwd, tool_display_name) if tool_definition is not None else ""
            summary = f"只能确认 CLI 会话进程存在（{tool_display_name if tool_display_name else 'AI'}），无法读取终端内容、具体进度、待确认状态或 Yes/No 按钮。"
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
            tool_display_name=tool_display_name,
        )


def _qoder_log_dirs(qoder_logs_dir: Optional[Path], qoder_logs_dirs: Iterable[Path]) -> Tuple[Path, ...]:
    paths: List[Path] = []
    seen = set()
    for path in ((qoder_logs_dir,) if qoder_logs_dir is not None else ()) + tuple(qoder_logs_dirs):
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        paths.append(path)
    return tuple(paths)


def _qoder_log_dirs_for_process(process_name: str, command: str, log_dirs: Tuple[Path, ...]) -> Tuple[Path, ...]:
    text = f"{process_name} {command}".lower()
    if "qoder cn.app" in text or "qodercn" in text:
        return _filter_qoder_log_dirs(log_dirs, "qodercn")
    if "qoder.app" in text or re.search(r"(^|[\\/\\s])qoder(?:\\.exe)?([\\s/\\\\]|$)", text):
        return _filter_qoder_log_dirs(log_dirs, "qoder")
    return log_dirs


def _filter_qoder_log_dirs(log_dirs: Tuple[Path, ...], product: str) -> Tuple[Path, ...]:
    filtered: List[Path] = []
    for path in log_dirs:
        parts = {part.lower() for part in path.parts}
        has_cn = "qodercn" in parts or "qoder cn" in parts
        has_regular = "qoder" in parts
        if product == "qodercn" and has_cn:
            filtered.append(path)
        elif product == "qoder" and has_regular and not has_cn:
            filtered.append(path)
    return tuple(filtered) or log_dirs


def _read_qoder_task_state(logs_dirs: Iterable[Path], now: datetime) -> Optional[_QoderTaskState]:
    states = _read_qoder_active_task_states(logs_dirs, now)
    return states[0] if states else None


def _read_qoder_active_task_states(
    logs_dirs: Iterable[Path],
    now: datetime,
    source_started_at: Optional[datetime] = None,
) -> List[_QoderTaskState]:
    states_by_task: dict[str, _QoderTaskState] = {}
    anonymous_states: List[_QoderTaskState] = []
    metadata_by_task: dict[str, _QoderTaskMetadata] = {}
    for path in _qoder_quest_log_paths(logs_dirs):
        for task_id, metadata in _read_qoder_task_metadata_from_log(path).items():
            existing_metadata = metadata_by_task.get(task_id)
            if existing_metadata is None or metadata.updated_at >= existing_metadata.updated_at:
                metadata_by_task[task_id] = metadata
        for state in _read_qoder_task_states_from_log(path):
            if state.task_id:
                existing = states_by_task.get(state.task_id)
                if existing is None:
                    states_by_task[state.task_id] = _qoder_state_with_running_history(state)
                elif _qoder_state_should_replace(state, existing):
                    states_by_task[state.task_id] = _qoder_state_with_running_history(state, existing)
                else:
                    states_by_task[state.task_id] = _qoder_merge_running_history(existing, state)
            else:
                anonymous_states.append(state)
    cache_db_paths = _qoder_cache_db_paths_from_log_dirs(logs_dirs)
    for state in _read_qoder_task_states_from_cache_db_paths(cache_db_paths):
        if state.task_id:
            existing = states_by_task.get(state.task_id)
            if existing is None:
                states_by_task[state.task_id] = _qoder_state_with_running_history(state)
            elif _qoder_state_should_replace(state, existing):
                states_by_task[state.task_id] = _qoder_state_with_running_history(state, existing)
            else:
                states_by_task[state.task_id] = _qoder_merge_running_history(existing, state)
    for task_id, metadata in _read_qoder_task_metadata_from_project_dirs(
        _qoder_project_dirs_from_log_dirs(logs_dirs)
    ).items():
        metadata_by_task[task_id] = _merge_qoder_task_metadata(metadata_by_task.get(task_id), metadata)
    for task_id, metadata in _read_qoder_task_metadata_from_cache_db_paths(
        cache_db_paths,
        states_by_task.keys(),
    ).items():
        metadata_by_task[task_id] = _merge_qoder_task_metadata(metadata_by_task.get(task_id), metadata)
    task_states = [_qoder_state_with_metadata(state, metadata_by_task) for state in states_by_task.values()]
    latest_task_state: Optional[_QoderTaskState] = None
    for state in task_states:
        if latest_task_state is None or state.updated_at >= latest_task_state.updated_at:
            latest_task_state = state
    states = task_states + [
        state
        for state in anonymous_states
        if latest_task_state is None or state.updated_at > latest_task_state.updated_at
    ]
    active: List[_QoderTaskState] = []
    for state in states:
        state = _qoder_state_with_short_run_visibility(state, now)
        age_seconds = (now - state.updated_at).total_seconds()
        if (
            source_started_at is not None
            and state.updated_at < source_started_at
            and state.status != SessionStatus.RUNNING
            and not state.user_attention_signal
        ):
            continue
        if state.status == SessionStatus.RUNNING and age_seconds > QODER_TASK_RUNNING_STALE_SECONDS:
            continue
        if state.status == SessionStatus.IDLE:
            continue
        active.append(state)
    return sorted(active, key=_qoder_task_sort_key)[:QODER_TASK_SESSION_LIMIT]


def _qoder_task_sort_key(state: _QoderTaskState):
    priority = 0 if state.status == SessionStatus.NEEDS_ACTION else 1
    return (priority, -state.updated_at.timestamp(), state.title or "", state.task_id or "")


def _qoder_quest_log_paths(logs_dirs: Iterable[Path]) -> List[Path]:
    paths: List[Path] = []
    seen = set()
    for logs_dir in logs_dirs:
        candidates: List[Path] = []
        try:
            if logs_dir.is_file():
                candidates.append(logs_dir)
            elif logs_dir.exists():
                session_dirs = sorted(
                    (child for child in logs_dir.iterdir() if child.is_dir()),
                    key=_path_mtime,
                    reverse=True,
                )
                for session_dir in session_dirs[:QODER_LOG_SESSION_DIR_LIMIT]:
                    candidates.extend(session_dir / filename for filename in QODER_STATUS_LOG_FILENAMES)
                    try:
                        window_dirs = sorted(
                            (child for child in session_dir.iterdir() if child.is_dir()),
                            key=_path_mtime,
                            reverse=True,
                        )
                    except OSError:
                        continue
                    for child in window_dirs[:QODER_LOG_WINDOW_DIR_LIMIT]:
                        candidates.extend(child / filename for filename in QODER_STATUS_LOG_FILENAMES)
        except OSError:
            continue
        for path in candidates:
            key = str(path)
            try:
                if key in seen or not path.is_file():
                    continue
            except OSError:
                continue
            seen.add(key)
            paths.append(path)
    return sorted(paths, key=_path_mtime, reverse=True)[:QODER_LOG_PATH_LIMIT]


def _path_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _read_qoder_task_state_from_log(path: Path) -> Optional[_QoderTaskState]:
    latest: Optional[_QoderTaskState] = None
    for state in _read_qoder_task_states_from_log(path):
        if latest is None or state.updated_at >= latest.updated_at:
            latest = state
    return latest


def _read_qoder_task_states_from_log(path: Path) -> List[_QoderTaskState]:
    latest_by_task: dict[str, _QoderTaskState] = {}
    anonymous_states: List[_QoderTaskState] = []
    metadata_by_task: dict[str, _QoderTaskMetadata] = {}
    for line in _read_text_tail(path, QODER_LOG_TAIL_BYTES).splitlines():
        updated_at = _parse_qoder_log_timestamp(line)
        if updated_at is None:
            continue
        payload = _qoder_log_json_payload(line) if "{" in line else None
        task_id = _qoder_task_id(line, payload)
        if task_id:
            metadata = _qoder_task_metadata(line, payload, updated_at)
            if metadata is not None:
                existing_metadata = metadata_by_task.get(task_id)
                if existing_metadata is None or metadata.updated_at >= existing_metadata.updated_at:
                    metadata_by_task[task_id] = metadata
        state = _qoder_log_line_state(line, updated_at)
        if state is None:
            continue
        if state.task_id:
            existing = latest_by_task.get(state.task_id)
            if existing is None:
                latest_by_task[state.task_id] = _qoder_state_with_running_history(state)
            elif _qoder_state_should_replace(state, existing):
                latest_by_task[state.task_id] = _qoder_state_with_running_history(state, existing)
            else:
                latest_by_task[state.task_id] = _qoder_merge_running_history(existing, state)
        else:
            anonymous_states.append(state)
    return [_qoder_state_with_metadata(state, metadata_by_task) for state in latest_by_task.values()] + anonymous_states


def _read_qoder_task_metadata_from_log(path: Path) -> dict[str, _QoderTaskMetadata]:
    metadata_by_task: dict[str, _QoderTaskMetadata] = {}
    for line in _read_text_tail(path, QODER_LOG_TAIL_BYTES).splitlines():
        updated_at = _parse_qoder_log_timestamp(line)
        if updated_at is None:
            continue
        payload = _qoder_log_json_payload(line) if "{" in line else None
        task_id = _qoder_task_id(line, payload)
        if not task_id:
            continue
        metadata = _qoder_task_metadata(line, payload, updated_at)
        if metadata is None:
            continue
        existing_metadata = metadata_by_task.get(task_id)
        if existing_metadata is None or metadata.updated_at >= existing_metadata.updated_at:
            metadata_by_task[task_id] = metadata
    return metadata_by_task


def _qoder_project_dirs_from_log_dirs(logs_dirs: Iterable[Path]) -> Tuple[Path, ...]:
    dirs: List[Path] = []
    seen = set()
    for logs_dir in logs_dirs:
        candidates: List[Path] = []
        if logs_dir.name == "logs":
            if logs_dir.parent.name == "SharedClientCache":
                candidates.append(logs_dir.parent / "cli" / "projects")
            candidates.append(logs_dir.parent / "SharedClientCache" / "cli" / "projects")
        for candidate in candidates:
            key = str(candidate)
            if key in seen:
                continue
            seen.add(key)
            dirs.append(candidate)
    return tuple(dirs)


def _qoder_cache_db_paths_from_log_dirs(logs_dirs: Iterable[Path]) -> Tuple[Path, ...]:
    paths: List[Path] = []
    seen = set()
    for logs_dir in logs_dirs:
        candidates: List[Path] = []
        if logs_dir.name == "logs":
            if logs_dir.parent.name == "SharedClientCache":
                candidates.append(logs_dir.parent / "cache" / "db" / "local.db")
            candidates.append(logs_dir.parent / "SharedClientCache" / "cache" / "db" / "local.db")
        for candidate in candidates:
            key = str(candidate)
            if key in seen:
                continue
            seen.add(key)
            paths.append(candidate)
    return tuple(paths)


def _read_qoder_task_metadata_from_project_dirs(project_dirs: Iterable[Path]) -> dict[str, _QoderTaskMetadata]:
    metadata_by_task: dict[str, _QoderTaskMetadata] = {}
    for project_dir in project_dirs:
        try:
            paths = sorted(project_dir.glob("*-session.json"), key=_path_mtime, reverse=True)
        except OSError:
            continue
        for path in paths[:QODER_LOG_PATH_LIMIT]:
            task_id = _qoder_task_id_from_project_session_path(path)
            if task_id is None:
                continue
            metadata = _read_qoder_task_metadata_from_project_session_file(path)
            if metadata is None:
                continue
            metadata_by_task[task_id] = _merge_qoder_task_metadata(metadata_by_task.get(task_id), metadata)
    return metadata_by_task


def _read_qoder_task_metadata_from_cache_db_paths(
    db_paths: Iterable[Path],
    task_ids: Iterable[str],
) -> dict[str, _QoderTaskMetadata]:
    normalized_task_ids = tuple(task_id for task_id in (_normalize_qoder_task_id(value) for value in task_ids) if task_id)
    if not normalized_task_ids:
        return {}
    metadata_by_task: dict[str, _QoderTaskMetadata] = {}
    for db_path in db_paths:
        for task_id, metadata in _read_qoder_task_metadata_from_cache_db(db_path, normalized_task_ids).items():
            metadata_by_task[task_id] = _merge_qoder_task_metadata(metadata_by_task.get(task_id), metadata)
    return metadata_by_task


def _read_qoder_task_metadata_from_cache_db(
    db_path: Path,
    task_ids: Iterable[str],
) -> dict[str, _QoderTaskMetadata]:
    try:
        if not db_path.is_file():
            return {}
    except OSError:
        return {}
    uri = f"file:{db_path}?mode=ro"
    connection: Optional[sqlite3.Connection] = None
    try:
        connection = sqlite3.connect(uri, uri=True, timeout=0.2)
        connection.row_factory = sqlite3.Row
        columns = _sqlite_table_columns(connection, "chat_session")
        if "session_id" not in columns:
            return {}
        selected_columns = [
            column
            for column in (
                "session_id",
                "session_title",
                "project_uri",
                "project_name",
                "status",
                "extra",
                "gmt_create",
                "gmt_modified",
            )
            if column in columns
        ]
        order_clause = " ORDER BY gmt_modified DESC" if "gmt_modified" in columns else ""
        rows: List[sqlite3.Row] = []
        for task_id in task_ids:
            session_ids = (task_id, f"{task_id}.session.execution")
            rows.extend(
                connection.execute(
                    f"""
                    SELECT {", ".join(selected_columns)}
                    FROM chat_session
                    WHERE session_id IN (?, ?)
                    {order_clause}
                    LIMIT 1
                    """,
                    session_ids,
                ).fetchall()
            )
            if len(rows) >= QODER_CACHE_DB_ROW_LIMIT:
                break
    except (OSError, sqlite3.Error):
        return {}
    finally:
        if connection is not None:
            connection.close()
    metadata_by_task: dict[str, _QoderTaskMetadata] = {}
    for row in rows[:QODER_CACHE_DB_ROW_LIMIT]:
        task_id = _normalize_qoder_task_id(row["session_id"])
        if task_id is None:
            continue
        metadata = _qoder_task_metadata_from_cache_row(row, db_path)
        if metadata is None:
            continue
        metadata_by_task[task_id] = _merge_qoder_task_metadata(metadata_by_task.get(task_id), metadata)
    return metadata_by_task


def _read_qoder_task_states_from_cache_db_paths(db_paths: Iterable[Path]) -> List[_QoderTaskState]:
    states_by_task: dict[str, _QoderTaskState] = {}
    for db_path in db_paths:
        for state in _read_qoder_task_states_from_cache_db(db_path):
            if not state.task_id:
                continue
            existing = states_by_task.get(state.task_id)
            if existing is None or _qoder_state_should_replace(state, existing):
                states_by_task[state.task_id] = state
    return list(states_by_task.values())


def _read_qoder_task_states_from_cache_db(db_path: Path) -> List[_QoderTaskState]:
    try:
        if not db_path.is_file():
            return []
    except OSError:
        return []
    uri = f"file:{db_path}?mode=ro"
    connection: Optional[sqlite3.Connection] = None
    try:
        connection = sqlite3.connect(uri, uri=True, timeout=0.2)
        connection.row_factory = sqlite3.Row
        columns = _sqlite_table_columns(connection, "chat_session")
        if "session_id" not in columns:
            return []
        selected_columns = [
            column
            for column in (
                "session_id",
                "session_title",
                "project_uri",
                "project_name",
                "status",
                "stop_reason",
                "extra",
                "last_user_query_at",
                "gmt_create",
                "gmt_modified",
            )
            if column in columns
        ]
        order_clause = " ORDER BY gmt_modified DESC" if "gmt_modified" in columns else ""
        rows = connection.execute(
            f"""
            SELECT {", ".join(selected_columns)}
            FROM chat_session
            {order_clause}
            LIMIT ?
            """,
            (QODER_CACHE_DB_ROW_LIMIT,),
        ).fetchall()
    except (OSError, sqlite3.Error):
        return []
    finally:
        if connection is not None:
            connection.close()

    states: List[_QoderTaskState] = []
    for row in rows:
        state = _qoder_task_state_from_cache_row(row, db_path)
        if state is not None:
            states.append(state)
    return states


def _sqlite_table_columns(connection: sqlite3.Connection, table_name: str) -> set[str]:
    try:
        rows = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    except sqlite3.Error:
        return set()
    return {str(row[1]) for row in rows}


def _qoder_task_state_from_cache_row(row: sqlite3.Row, db_path: Path) -> Optional[_QoderTaskState]:
    task_id = _normalize_qoder_task_id(row["session_id"])
    if task_id is None:
        return None
    payload = _qoder_cache_row_status_payload(row)
    status = _qoder_cache_payload_status(payload)
    if status is None:
        return None
    metadata = _qoder_task_metadata_from_cache_row(row, db_path)
    updated_at = metadata.updated_at if metadata is not None else None
    if updated_at is None:
        updated_at = datetime.fromtimestamp(_path_mtime(db_path), timezone.utc)
    return _QoderTaskState(
        status=status,
        updated_at=updated_at,
        task_id=task_id,
        title=metadata.title if metadata is not None else None,
        cwd=metadata.cwd if metadata is not None else None,
        user_attention_signal=_qoder_payload_has_user_attention_signal(payload),
    )


def _qoder_cache_row_status_payload(row: sqlite3.Row) -> dict:
    payload = {}
    for key in ("status", "stop_reason"):
        if key in row.keys():
            value = _optional_str(row[key])
            if value:
                payload[key] = value
    extra = _json_dict(row["extra"]) if "extra" in row.keys() else {}
    for key in (
        "acp_session_chat_finish_reason",
        "finish_reason",
        "finishReason",
        "stopReason",
        "acp_session_status_code",
        "statusCode",
        "status_code",
        "errorCode",
        "errorMessage",
        "message",
        "error",
        "lastError",
        "state",
        "acpState",
        "requiresApproval",
        "requiresUserInput",
        "needsUserInput",
        "hasPendingUserInput",
    ):
        if key in extra:
            payload[key] = extra.get(key)
    return payload


def _qoder_cache_payload_status(payload: dict) -> Optional[SessionStatus]:
    if _qoder_payload_has_terminal_error_signal(payload):
        return SessionStatus.NEEDS_ACTION
    for key in (
        "acp_session_chat_finish_reason",
        "finish_reason",
        "finishReason",
        "stop_reason",
        "stopReason",
    ):
        normalized = _normalize_status_token(payload.get(key))
        if normalized in USER_ATTENTION_STATUS_NAMES:
            return SessionStatus.NEEDS_ACTION
        if normalized in {"completed", "complete", "success", "succeeded", "failed", "error"}:
            return SessionStatus.NEEDS_ACTION

    status = _qoder_agent_payload_status(payload)
    if status is not None:
        return status

    stop_reason = _qoder_agent_payload_status({"status": payload.get("stop_reason") or payload.get("stopReason")})
    if stop_reason is not None and stop_reason != SessionStatus.IDLE:
        return stop_reason
    return None


def _qoder_task_metadata_from_cache_row(row: sqlite3.Row, db_path: Path) -> Optional[_QoderTaskMetadata]:
    extra = _json_dict(row["extra"]) if "extra" in row.keys() else {}
    cwd = _optional_str(row["project_uri"] if "project_uri" in row.keys() else None) or _qoder_cwd_from_cache_extra(extra)
    title = _qoder_readable_title(_optional_str(row["session_title"] if "session_title" in row.keys() else None), None)
    if title is None:
        title = _qoder_title_from_cache_extra(extra)
    if title is None and cwd is None:
        return None
    updated_at = None
    for key in ("gmt_modified", "gmt_create"):
        if key in row.keys():
            updated_at = _parse_millis_datetime(row[key])
            if updated_at is not None:
                break
    if updated_at is None:
        updated_at = datetime.fromtimestamp(_path_mtime(db_path), timezone.utc)
    return _QoderTaskMetadata(updated_at=updated_at, title=title, cwd=cwd)


def _qoder_title_from_cache_extra(extra: dict) -> Optional[str]:
    for key in ("title", "conversationTitle", "name", "displayName"):
        title = _qoder_readable_title(_optional_str(extra.get(key)), None)
        if title is not None:
            return title
    plan_info = extra.get("plan_info")
    if isinstance(plan_info, dict):
        return _qoder_readable_title(_optional_str(plan_info.get("title") or plan_info.get("name")), None)
    return None


def _qoder_cwd_from_cache_extra(extra: dict) -> Optional[str]:
    quest_task_info = extra.get("questTaskInfo")
    if isinstance(quest_task_info, dict):
        workspace_config = quest_task_info.get("workspaceConfig")
        if isinstance(workspace_config, dict):
            cwd = _optional_str(workspace_config.get("filePath") or workspace_config.get("cwd"))
            if cwd:
                return cwd
            workspace_info = _json_dict(workspace_config.get("workspaceInfo"))
            cwd = _optional_str(workspace_info.get("projectPath") or workspace_info.get("workspacePath"))
            if cwd:
                return cwd
    return None


def _json_dict(value) -> dict:
    if isinstance(value, dict):
        return value
    text = _optional_str(value)
    if text is None:
        return {}
    try:
        payload = json.loads(text)
    except (TypeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _qoder_task_id_from_project_session_path(path: Path) -> Optional[str]:
    suffix = "-session.json"
    name = path.name
    if not name.endswith(suffix):
        return None
    return _normalize_qoder_task_id(name[: -len(suffix)])


def _read_qoder_task_metadata_from_project_session_file(path: Path) -> Optional[_QoderTaskMetadata]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    title = _qoder_readable_title(
        _optional_str(
            payload.get("title")
            or payload.get("conversationTitle")
            or payload.get("name")
            or payload.get("displayName")
        ),
        None,
    )
    cwd = _optional_str(payload.get("filePath") or payload.get("cwd") or payload.get("workspacePath"))
    if title is None and cwd is None:
        return None
    return _QoderTaskMetadata(updated_at=_qoder_project_session_updated_at(path, payload), title=title, cwd=cwd)


def _qoder_project_session_updated_at(path: Path, payload: dict) -> datetime:
    for key in ("updatedAt", "updated_at", "gmt_modified", "modifiedAt"):
        parsed = _parse_millis_datetime(payload.get(key))
        if parsed is not None:
            return parsed
    return datetime.fromtimestamp(_path_mtime(path), timezone.utc)


def _merge_qoder_task_metadata(
    existing: Optional[_QoderTaskMetadata],
    candidate: _QoderTaskMetadata,
) -> _QoderTaskMetadata:
    if existing is None:
        return candidate
    return _QoderTaskMetadata(
        updated_at=max(existing.updated_at, candidate.updated_at),
        title=candidate.title or existing.title,
        cwd=candidate.cwd or existing.cwd,
    )


def _qoder_state_with_metadata(
    state: _QoderTaskState,
    metadata_by_task: dict[str, _QoderTaskMetadata],
) -> _QoderTaskState:
    if not state.task_id:
        return state
    metadata = metadata_by_task.get(state.task_id)
    if metadata is None:
        return state
    title = state.title
    if metadata.title is not None and (title is None or _qoder_title_should_use_metadata(title, state.cwd or metadata.cwd)):
        title = metadata.title
    return replace(
        state,
        title=title,
        cwd=state.cwd or metadata.cwd,
    )


def _qoder_title_should_use_metadata(title: str, cwd: Optional[str]) -> bool:
    text = title.strip()
    if _qoder_is_generated_chat_title(text):
        return True
    if cwd and text == Path(str(cwd)).name and _qoder_is_generated_chat_title(text):
        return True
    return text.startswith("task-") or text.endswith(".session.execution")


def _qoder_is_generated_chat_title(value: str) -> bool:
    return re.fullmatch(r"chat-\d+", value.strip(), re.IGNORECASE) is not None


def _qoder_log_line_state(line: str, updated_at: datetime) -> Optional[_QoderTaskState]:
    payload = _qoder_log_json_payload(line) if "{" in line else None
    user_attention_signal = False
    if "task.status.update" in line:
        if payload is None:
            return None
        status = _qoder_task_status_from_payload(line, payload, updated_at)
        user_attention_signal = _qoder_payload_has_user_attention_signal(payload)
    else:
        status = _qoder_agent_stream_status(line, payload)
        user_attention_signal = _qoder_line_has_user_attention_signal(line) or _qoder_payload_has_user_attention_signal(payload)
    if status is None:
        return None
    return _QoderTaskState(
        status=status,
        updated_at=updated_at,
        task_id=_qoder_task_id(line, payload),
        user_attention_signal=user_attention_signal and status == SessionStatus.NEEDS_ACTION,
        short_run_visibility_allowed=not _qoder_state_is_explicit_user_attention(line, payload, status),
    )


def _qoder_task_status_from_payload(line: str, payload: dict, updated_at: datetime) -> Optional[SessionStatus]:
    if "task.status.update.afterRefresh" not in line:
        return _qoder_session_status(
            payload.get("status")
            or payload.get("toStatus")
            or payload.get("pushedStatus")
            or payload.get("acpState")
        )
    pushed_status = _qoder_session_status(payload.get("pushedStatus"))
    final_value = payload.get("finalStatus") or payload.get("refreshedStatus") or payload.get("status")
    final_status = _qoder_session_status(final_value)
    if (
        pushed_status is None
        and final_status == SessionStatus.NEEDS_ACTION
        and _qoder_status_value_is_view_ack_completion(final_value)
        and not _qoder_payload_has_user_attention_signal(payload)
    ):
        return SessionStatus.IDLE
    if pushed_status is not None and _optional_bool(payload.get("shouldUsePushedStatus")):
        return pushed_status
    if _qoder_should_prefer_pushed_status(pushed_status, final_status, payload, updated_at):
        return pushed_status
    return final_status or pushed_status


def _qoder_should_prefer_pushed_status(
    pushed_status: Optional[SessionStatus],
    final_status: Optional[SessionStatus],
    payload: dict,
    updated_at: datetime,
) -> bool:
    if pushed_status != SessionStatus.RUNNING or final_status not in {SessionStatus.IDLE, SessionStatus.NEEDS_ACTION}:
        return False
    refreshed_at = _parse_millis_datetime(payload.get("updatedAtTimestamp"))
    if refreshed_at is None:
        return False
    return (updated_at - refreshed_at).total_seconds() > QODER_REFRESH_STALE_SNAPSHOT_SECONDS


def _qoder_status_value_is_view_ack_completion(value) -> bool:
    return _normalize_status_token(value) in {"completed", "complete", "success", "succeeded", "failed", "error"}


def _qoder_agent_stream_status(line: str, payload: Optional[dict] = None) -> Optional[SessionStatus]:
    text = line.lower()
    if "acpprogressstatemachine" in text and "state transition:" in text:
        if "-> error" in text or "error -> cancelled" in text:
            return SessionStatus.NEEDS_ACTION
        if "-> suspended" in text:
            return SessionStatus.NEEDS_ACTION
        if "-> completed" in text:
            return SessionStatus.NEEDS_ACTION
        if "-> initial" in text:
            return SessionStatus.IDLE
        if "-> prompting" in text or "-> streaming" in text:
            return SessionStatus.RUNNING
    payload_status = _qoder_agent_payload_status(payload)
    if payload_status is not None:
        return payload_status
    if "chat_finish" in text and "from=load" in text:
        return SessionStatus.IDLE
    if "acp stream completed" in text or "chat_finish" in text:
        return SessionStatus.NEEDS_ACTION
    if '"state":"error"' in text:
        return SessionStatus.NEEDS_ACTION
    if '"state":"completed"' in text:
        return SessionStatus.IDLE
    if '"state":"streaming"' in text or "acp prompt sent successfully" in text or "handling acp session/prompt" in text:
        return SessionStatus.RUNNING
    return None


def _qoder_agent_payload_status(payload: Optional[dict]) -> Optional[SessionStatus]:
    if payload is None:
        return None
    for key in (
        "hasPendingUserInput",
        "needUserInput",
        "needsUserInput",
        "requiresUserInput",
        "requiresApproval",
    ):
        if _optional_bool(payload.get(key)):
            return SessionStatus.NEEDS_ACTION
    normalized = _normalize_status_token(
        payload.get("state")
        or payload.get("status")
        or payload.get("toStatus")
        or payload.get("pushedStatus")
        or payload.get("acpState")
        or payload.get("finalStatus")
        or payload.get("refreshedStatus")
    )
    if normalized in USER_ATTENTION_STATUS_NAMES:
        return SessionStatus.NEEDS_ACTION
    if normalized in {"error", "failed", "failure", "errored"}:
        return SessionStatus.NEEDS_ACTION
    if normalized in RUNNING_STATUS_NAMES:
        return SessionStatus.RUNNING
    if normalized in {"completed", "cancelled", "canceled", "idle", "initial", "ready", "stopped"}:
        return SessionStatus.IDLE
    return None


def _qoder_line_has_user_attention_signal(line: str) -> bool:
    text = line.lower()
    return "acpprogressstatemachine" in text and "state transition:" in text and "-> suspended" in text


def _qoder_payload_has_user_attention_signal(payload: Optional[dict]) -> bool:
    if payload is None:
        return False
    for key in (
        "hasPendingUserInput",
        "needUserInput",
        "needsUserInput",
        "requiresUserInput",
        "requiresApproval",
    ):
        if _optional_bool(payload.get(key)):
            return True
    for key in (
        "state",
        "acpState",
        "status",
        "pushedStatus",
        "finalStatus",
        "refreshedStatus",
        "reason",
        "statusReason",
    ):
        if _normalize_status_token(payload.get(key)) in QODER_USER_ATTENTION_SIGNAL_STATUS_NAMES:
            return True
    return False


def _qoder_state_is_explicit_user_attention(
    line: str,
    payload: Optional[dict],
    status: SessionStatus,
) -> bool:
    if status != SessionStatus.NEEDS_ACTION:
        return False
    if _qoder_line_has_user_attention_signal(line):
        return True
    if payload is None:
        return False
    for key in (
        "state",
        "acpState",
        "status",
        "toStatus",
        "pushedStatus",
        "finalStatus",
        "refreshedStatus",
        "reason",
        "statusReason",
    ):
        normalized = _normalize_status_token(payload.get(key))
        if normalized in USER_ATTENTION_STATUS_NAMES and not _qoder_status_value_is_view_ack_completion(payload.get(key)):
            return True
    return any(
        _optional_bool(payload.get(key))
        for key in (
            "hasPendingUserInput",
            "needUserInput",
            "needsUserInput",
            "requiresUserInput",
            "requiresApproval",
        )
    )


def _qoder_payload_has_terminal_error_signal(payload: Optional[dict]) -> bool:
    if payload is None:
        return False
    for key in ("acp_session_status_code", "statusCode", "status_code", "code"):
        try:
            status_code = int(str(payload.get(key) or "").strip())
        except ValueError:
            continue
        if status_code >= 400:
            return True
    for key in (
        "state",
        "acpState",
        "status",
        "finalStatus",
        "refreshedStatus",
        "errorCode",
        "errorMessage",
        "message",
        "error",
        "lastError",
        "reason",
        "statusReason",
        "acp_session_chat_finish_reason",
        "finish_reason",
        "finishReason",
        "stop_reason",
        "stopReason",
    ):
        value = payload.get(key)
        normalized = _normalize_status_token(value)
        if normalized in {"error", "failed", "failure", "errored"}:
            return True
        if _qoder_text_has_terminal_error_signal(value):
            return True
    return False


def _qoder_text_has_terminal_error_signal(value) -> bool:
    text = str(value or "").strip().lower()
    if not text:
        return False
    return any(
        token in text
        for token in (
            "something went wrong",
            "request canceled",
            "client.timeout",
            "request timeout",
            "credits exhausted",
            "credit exhausted",
            "quota",
            "insufficient credit",
            "insufficient balance",
            "no model config",
        )
    )


def _qoder_state_should_replace(candidate: _QoderTaskState, existing: _QoderTaskState) -> bool:
    if candidate.status == SessionStatus.IDLE and existing.status == SessionStatus.NEEDS_ACTION:
        age_seconds = (candidate.updated_at - existing.updated_at).total_seconds()
        if 0 <= age_seconds <= QODER_TERMINAL_RESULT_IDLE_GRACE_SECONDS and not existing.user_attention_signal:
            return False
    if candidate.updated_at > existing.updated_at:
        return True
    if candidate.updated_at < existing.updated_at:
        return False
    return _status_precedence(candidate.status) < _status_precedence(existing.status)


def _qoder_state_with_running_history(
    state: _QoderTaskState,
    existing: Optional[_QoderTaskState] = None,
) -> _QoderTaskState:
    last_running_at = _qoder_latest_running_at(state)
    if existing is not None:
        last_running_at = _latest_datetime(last_running_at, _qoder_latest_running_at(existing))
    if last_running_at == state.last_running_at:
        return state
    return replace(state, last_running_at=last_running_at)


def _qoder_merge_running_history(existing: _QoderTaskState, candidate: _QoderTaskState) -> _QoderTaskState:
    last_running_at = _latest_datetime(_qoder_latest_running_at(existing), _qoder_latest_running_at(candidate))
    if last_running_at == existing.last_running_at:
        return existing
    return replace(existing, last_running_at=last_running_at)


def _qoder_latest_running_at(state: _QoderTaskState) -> Optional[datetime]:
    if state.status == SessionStatus.RUNNING:
        return _latest_datetime(state.last_running_at, state.updated_at)
    return state.last_running_at


def _qoder_state_with_short_run_visibility(state: _QoderTaskState, now: datetime) -> _QoderTaskState:
    if (
        state.status != SessionStatus.NEEDS_ACTION
        or state.user_attention_signal
        or not state.short_run_visibility_allowed
        or state.last_running_at is None
    ):
        return state
    run_seconds = (state.updated_at - state.last_running_at).total_seconds()
    completion_age_seconds = (now - state.updated_at).total_seconds()
    if (
        QODER_SHORT_RUN_MIN_SECONDS <= run_seconds <= QODER_SHORT_RUN_MAX_SECONDS
        and 0 <= completion_age_seconds <= QODER_SHORT_RUN_VISIBLE_AFTER_COMPLETION_SECONDS
    ):
        return replace(state, status=SessionStatus.RUNNING)
    return state


def _latest_datetime(left: Optional[datetime], right: Optional[datetime]) -> Optional[datetime]:
    if left is None:
        return right
    if right is None:
        return left
    return left if left >= right else right


def _status_precedence(status: SessionStatus) -> int:
    priority = {
        SessionStatus.NEEDS_ACTION: 0,
        SessionStatus.STUCK: 1,
        SessionStatus.RUNNING: 2,
        SessionStatus.IDLE: 3,
        SessionStatus.UNKNOWN: 4,
    }
    return priority.get(status, 9)


def _qoder_task_metadata(line: str, payload: Optional[dict], updated_at: datetime) -> Optional[_QoderTaskMetadata]:
    title: Optional[str] = None
    cwd: Optional[str] = None
    if payload is not None:
        cwd = _optional_str(payload.get("filePath") or payload.get("cwd") or payload.get("workspacePath"))
        title = _optional_str(
            payload.get("title")
            or payload.get("conversationTitle")
            or payload.get("name")
            or payload.get("displayName")
        )
    if title is None:
        title_match = re.search(r"\btitle=([^,\n]+?)(?:\s+\w+=|$)", line)
        if title_match is not None:
            title = title_match.group(1).strip()
    title = _qoder_readable_title(title, cwd)
    if title is None and cwd is None:
        return None
    return _QoderTaskMetadata(updated_at=updated_at, title=title, cwd=cwd)


def _qoder_readable_title(title: Optional[str], cwd: Optional[str]) -> Optional[str]:
    text = _optional_str(title)
    if text and not _qoder_title_is_generated_or_technical(text):
        return text
    if cwd:
        folder_name = Path(str(cwd)).name
        if folder_name and not _qoder_title_is_generated_or_technical(folder_name):
            return folder_name
    return None


def _qoder_title_is_generated_or_technical(value: str) -> bool:
    text = value.strip()
    lowered = text.lower()
    if not text:
        return True
    if text in {"新会话", "new chat"} or "会话编辑:" in text:
        return True
    if ".session.execution" in lowered or lowered.startswith("task-"):
        return True
    if _qoder_is_generated_chat_title(text):
        return True
    return re.fullmatch(
        r"(?:[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}|[a-f0-9]{24,})",
        text,
        re.IGNORECASE,
    ) is not None


def _qoder_task_id(line: str, payload: Optional[dict]) -> Optional[str]:
    if payload is not None:
        task_id = _normalize_qoder_task_id(payload.get("taskId") or payload.get("sessionId"))
        if task_id:
            return task_id
    match = re.search(r"(task-[A-Za-z0-9]+)(?:\.session\.execution)?", line)
    if match is not None:
        return match.group(1)
    match = re.search(r"\bsessionId:\s*([A-Za-z0-9][A-Za-z0-9._-]*)", line)
    if match is not None:
        return _normalize_qoder_task_id(match.group(1))
    match = re.search(r"\bacp progress:\s*([A-Za-z0-9][A-Za-z0-9._-]*)", line, re.IGNORECASE)
    if match is not None:
        return _normalize_qoder_task_id(match.group(1))
    return None


def _normalize_qoder_task_id(value) -> Optional[str]:
    text = _optional_str(value)
    if text is None:
        return None
    suffix = ".session.execution"
    if text.endswith(suffix):
        text = text[: -len(suffix)]
    return text or None


def _read_text_tail(path: Path, byte_limit: int) -> str:
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            if size > byte_limit:
                handle.seek(max(0, size - byte_limit))
            raw = handle.read()
    except OSError:
        return ""
    return raw.decode("utf-8", errors="ignore")


def _qoder_log_json_payload(line: str) -> Optional[dict]:
    start = line.find("{")
    end = line.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        payload = json.loads(line[start : end + 1])
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _parse_qoder_log_timestamp(line: str) -> Optional[datetime]:
    match = re.match(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{1,6})", line)
    if match is None:
        return None
    try:
        parsed = datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S.%f")
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc)


def _qoder_session_status(value) -> Optional[SessionStatus]:
    status = str(value or "").strip()
    normalized = _normalize_status_token(status)
    if normalized in RUNNING_STATUS_NAMES:
        return SessionStatus.RUNNING
    if normalized in USER_ATTENTION_STATUS_NAMES:
        return SessionStatus.NEEDS_ACTION
    if normalized in {"completed", "complete", "success", "succeeded", "failed", "error"}:
        return SessionStatus.NEEDS_ACTION
    if normalized in {"cancelled", "canceled", "idle", "ready", "stopped"}:
        return SessionStatus.IDLE
    return None


def _qoder_task_session_id(state: _QoderTaskState, process_id: Optional[int]) -> str:
    raw = state.task_id or f"process-{process_id or 'unknown'}-{int(state.updated_at.timestamp() * 1000)}"
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", raw).strip("-") or "unknown"
    return f"qoder-{normalized}"


def _qoder_task_title(tool_display_name: str, state: _QoderTaskState) -> str:
    suffix = state.title or "对话"
    return f"{tool_display_name} Desktop - {suffix}"


def _qoder_task_requires_view_ack(state: _QoderTaskState) -> bool:
    return state.status == SessionStatus.NEEDS_ACTION and not state.user_attention_signal


def _qoder_task_summary(status: SessionStatus) -> str:
    if status == SessionStatus.RUNNING:
        return "Qoder 正在处理任务。"
    if status == SessionStatus.NEEDS_ACTION:
        return "Qoder 任务已完成或需要用户处理。"
    return "Qoder 任务已完成，当前空闲。"


def _read_workbuddy_active_session_states(
    db_paths: Iterable[Path],
    now: datetime,
    source_started_at: Optional[datetime] = None,
) -> List[_WorkBuddySessionState]:
    states_by_session: dict[str, _WorkBuddySessionState] = {}
    for db_path in db_paths:
        runtime_states = _read_workbuddy_runtime_states_from_logs(db_path)
        for state in _read_workbuddy_session_states_from_db(db_path):
            runtime_state = runtime_states.get(state.session_id)
            if runtime_state is not None:
                state = _workbuddy_state_with_runtime_state(state, runtime_state)
            existing = states_by_session.get(state.session_id)
            if existing is None or state.updated_at >= existing.updated_at:
                states_by_session[state.session_id] = state
        for session_id, runtime_state in runtime_states.items():
            if session_id in states_by_session:
                continue
            state = _workbuddy_session_state_from_runtime_state(runtime_state)
            existing = states_by_session.get(state.session_id)
            if existing is None or state.updated_at >= existing.updated_at:
                states_by_session[state.session_id] = state
    active: List[_WorkBuddySessionState] = []
    for state in states_by_session.values():
        age_seconds = (now - state.updated_at).total_seconds()
        if (
            source_started_at is not None
            and state.updated_at < source_started_at
            and state.status != SessionStatus.RUNNING
            and not state.user_attention_signal
        ):
            continue
        if state.status == SessionStatus.RUNNING and age_seconds > WORKBUDDY_SESSION_RUNNING_STALE_SECONDS:
            continue
        if state.status == SessionStatus.IDLE:
            continue
        active.append(state)
    return sorted(active, key=_workbuddy_session_sort_key)[:WORKBUDDY_SESSION_LIMIT]


def _workbuddy_state_with_runtime_state(
    state: _WorkBuddySessionState,
    runtime_state: _WorkBuddyRuntimeState,
) -> _WorkBuddySessionState:
    min_runtime_at = state.updated_at - timedelta(seconds=WORKBUDDY_RUNTIME_DB_CLOCK_SKEW_SECONDS)
    if runtime_state.updated_at < min_runtime_at:
        return state
    if state.status == SessionStatus.NEEDS_ACTION:
        if state.user_attention_signal or runtime_state.status == SessionStatus.IDLE:
            return state
    user_attention_signal = (
        state.user_attention_signal if runtime_state.status == SessionStatus.NEEDS_ACTION else False
    )
    return replace(
        state,
        status=runtime_state.status,
        updated_at=max(state.updated_at, runtime_state.updated_at),
        user_attention_signal=user_attention_signal,
        status_source="workbuddy-log",
    )


def _workbuddy_session_state_from_runtime_state(runtime_state: _WorkBuddyRuntimeState) -> _WorkBuddySessionState:
    return _WorkBuddySessionState(
        status=runtime_state.status,
        updated_at=runtime_state.updated_at,
        session_id=runtime_state.session_id,
        user_attention_signal=runtime_state.status == SessionStatus.NEEDS_ACTION,
        status_source="workbuddy-log",
    )


def _read_workbuddy_runtime_states_from_logs(db_path: Path) -> dict[str, _WorkBuddyRuntimeState]:
    states_by_session: dict[str, _WorkBuddyRuntimeState] = {}
    for path in _workbuddy_runtime_log_paths(db_path.parent / "logs"):
        for state in _read_workbuddy_runtime_states_from_log(path).values():
            existing = states_by_session.get(state.session_id)
            if existing is None or state.updated_at >= existing.updated_at:
                states_by_session[state.session_id] = state
    return states_by_session


def _workbuddy_runtime_log_paths(logs_root: Path) -> List[Path]:
    try:
        if not logs_root.exists():
            return []
    except OSError:
        return []
    paths: List[Path] = []
    seen = set()
    for pattern in ("*.log", "*/*.log"):
        try:
            candidates = logs_root.glob(pattern)
            for path in candidates:
                key = str(path)
                try:
                    if key in seen or not path.is_file() or not _workbuddy_runtime_log_candidate(path):
                        continue
                except OSError:
                    continue
                seen.add(key)
                paths.append(path)
        except OSError:
            continue
    return sorted(paths, key=_path_mtime, reverse=True)[:WORKBUDDY_RUNTIME_LOG_PATH_LIMIT]


def _read_workbuddy_runtime_states_from_log(path: Path) -> dict[str, _WorkBuddyRuntimeState]:
    states_by_session: dict[str, _WorkBuddyRuntimeState] = {}
    for line in _read_text_tail(path, WORKBUDDY_RUNTIME_LOG_TAIL_BYTES).splitlines():
        state = _workbuddy_runtime_state_from_log_line(line)
        if state is None:
            continue
        existing = states_by_session.get(state.session_id)
        if existing is None or state.updated_at >= existing.updated_at:
            states_by_session[state.session_id] = state
    return states_by_session


def _workbuddy_runtime_log_candidate(path: Path) -> bool:
    name = path.name.lower()
    if name in {"api.log", "vendor-extract.log", "appstartup.log"}:
        return False
    if name.startswith(("__workbuddy_cli_host__", "workbuddymainthread", "update-", "startup-", "migration-")):
        return False
    return True


def _workbuddy_runtime_state_from_log_line(line: str) -> Optional[_WorkBuddyRuntimeState]:
    if "SessionRunStateMachine" not in line or "transition" not in line:
        return None
    updated_at = _parse_workbuddy_log_timestamp(line)
    session_id = _workbuddy_log_field(line, "sessionId")
    if updated_at is None or session_id is None:
        return None
    status = _workbuddy_runtime_status_from_transition(line)
    if status is None:
        return None
    return _WorkBuddyRuntimeState(status=status, updated_at=updated_at, session_id=session_id)


def _workbuddy_runtime_status_from_transition(line: str) -> Optional[SessionStatus]:
    to_state = _normalize_status_token(_workbuddy_log_field(line, "to"))
    lifecycle = _normalize_status_token(_workbuddy_log_field(line, "lifecycle"))
    busy = _normalize_status_token(_workbuddy_log_field(line, "busy"))
    if to_state in USER_ATTENTION_STATUS_NAMES or lifecycle in USER_ATTENTION_STATUS_NAMES:
        return SessionStatus.NEEDS_ACTION
    if busy == "true" or lifecycle == "running" or to_state in {
        "agentrunning",
        "modelrequesting",
        "modelstreaming",
        "modeldone",
        "toolexecuting",
        "toolrunning",
    }:
        return SessionStatus.RUNNING
    if busy == "false" or lifecycle == "idle" or to_state in {"idle", "ready"}:
        return SessionStatus.IDLE
    return None


def _workbuddy_log_field(line: str, name: str) -> Optional[str]:
    match = re.search(rf"(?:^|\|\s*){re.escape(name)}=([^|]+)", line)
    if match is None:
        return None
    return _optional_str(match.group(1))


def _parse_workbuddy_log_timestamp(line: str) -> Optional[datetime]:
    match = re.match(r"^\[(\d{1,2}/\d{1,2}/\d{4}, \d{1,2}:\d{2}:\d{2} [AP]M\.\d{1,6})\]", line)
    if match is None:
        return None
    try:
        parsed = datetime.strptime(match.group(1), "%m/%d/%Y, %I:%M:%S %p.%f")
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc)


def _read_workbuddy_session_states_from_db(db_path: Path) -> List[_WorkBuddySessionState]:
    try:
        if not db_path.is_file():
            return []
    except OSError:
        return []
    uri = f"file:{db_path}?mode=ro"
    connection: Optional[sqlite3.Connection] = None
    try:
        connection = sqlite3.connect(uri, uri=True, timeout=0.2)
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """
            SELECT
                id, cwd, title, custom_title, status, updated_at,
                last_activity_at, deleted_at
            FROM sessions
            WHERE deleted_at IS NULL
            ORDER BY COALESCE(last_activity_at, updated_at) DESC
            LIMIT ?
            """,
            (WORKBUDDY_SESSION_ROW_LIMIT,),
        ).fetchall()
    except (OSError, sqlite3.Error):
        return []
    finally:
        if connection is not None:
            connection.close()
    states: List[_WorkBuddySessionState] = []
    for row in rows:
        has_activity = row["last_activity_at"] is not None
        session_id = _optional_str(row["id"])
        if session_id is None:
            continue
        cwd = _optional_str(row["cwd"])
        status = _workbuddy_session_status(row["status"], has_activity=has_activity)
        if status is None:
            continue
        if status == SessionStatus.NEEDS_ACTION and _workbuddy_completed_session_has_incomplete_final_event(db_path, row["status"], session_id, cwd):
            status = SessionStatus.IDLE
        updated_at = _workbuddy_session_updated_at(row, status)
        if updated_at is None:
            continue
        title = _workbuddy_readable_title(_optional_str(row["custom_title"]) or _optional_str(row["title"]), cwd)
        states.append(
            _WorkBuddySessionState(
                status=status,
                updated_at=updated_at,
                session_id=session_id,
                title=title,
                cwd=cwd,
                user_attention_signal=_workbuddy_session_has_user_attention_signal(
                    row["status"],
                    has_activity=has_activity,
                )
                and status == SessionStatus.NEEDS_ACTION,
            )
        )
    return states


def _workbuddy_session_updated_at(row: sqlite3.Row, status: SessionStatus) -> Optional[datetime]:
    updated_at = _parse_epoch_datetime(row["updated_at"])
    activity_at = _parse_epoch_datetime(row["last_activity_at"])
    if status == SessionStatus.RUNNING:
        candidates = [parsed for parsed in (updated_at, activity_at) if parsed is not None]
        if not candidates:
            return None
        return max(candidates)
    return activity_at or updated_at


def _workbuddy_completed_session_has_incomplete_final_event(
    db_path: Path,
    status_value,
    session_id: str,
    cwd: Optional[str],
) -> bool:
    if _normalize_status_token(status_value) not in {"completed", "complete", "success", "succeeded"}:
        return False
    event_path = _workbuddy_session_event_path(db_path, session_id, cwd)
    if event_path is None:
        return False
    final_event = _workbuddy_final_relevant_event(event_path)
    if final_event is None:
        return False
    if _workbuddy_event_has_interrupted_tool_result(final_event):
        return True
    event_type = _optional_str(final_event.get("type"))
    status = _normalize_status_token(final_event.get("status"))
    if event_type == "message" and _optional_str(final_event.get("role")) == "assistant" and status == "incomplete":
        return True
    return event_type == "reasoning" and status == "incomplete"


def _workbuddy_session_event_path(db_path: Path, session_id: str, cwd: Optional[str]) -> Optional[Path]:
    projects_dir = db_path.parent / "projects"
    try:
        if not projects_dir.is_dir():
            return None
    except OSError:
        return None
    if cwd:
        project_dir_name = _workbuddy_project_dir_name(cwd)
        if project_dir_name:
            candidate = projects_dir / project_dir_name / f"{session_id}.jsonl"
            try:
                if candidate.is_file():
                    return candidate
            except OSError:
                pass
    try:
        return next(projects_dir.glob(f"**/{session_id}.jsonl"))
    except (OSError, StopIteration):
        return None


def _workbuddy_project_dir_name(cwd: str) -> str:
    parts = [part for part in re.split(r"[\\/]+", str(cwd).strip()) if part and part != "."]
    return "-".join(part.replace(":", "") for part in parts)


def _workbuddy_final_relevant_event(path: Path) -> Optional[dict]:
    try:
        with path.open("rb") as handle:
            handle.seek(0, 2)
            size = handle.tell()
            start = max(0, size - WORKBUDDY_SESSION_LOG_TAIL_BYTES)
            handle.seek(start)
            text = handle.read().decode("utf-8", errors="replace")
    except OSError:
        return None
    lines = text.splitlines()
    if start > 0 and lines:
        lines = lines[1:]
    final_event: Optional[dict] = None
    for line in lines:
        try:
            event = json.loads(line)
        except (TypeError, ValueError):
            continue
        if not isinstance(event, dict):
            continue
        if _workbuddy_event_is_relevant_for_completion(event):
            final_event = event
    return final_event


def _workbuddy_event_is_relevant_for_completion(event: dict) -> bool:
    event_type = _optional_str(event.get("type"))
    if event_type in {"message", "reasoning", "function_call", "function_call_result"}:
        return True
    return _workbuddy_event_has_interrupted_tool_result(event)


def _workbuddy_event_has_interrupted_tool_result(event: dict) -> bool:
    provider_data = event.get("providerData")
    if not isinstance(provider_data, dict):
        return False
    tool_result = provider_data.get("toolResult")
    if not isinstance(tool_result, dict):
        return False
    raw_response = tool_result.get("rawResponse")
    return isinstance(raw_response, dict) and raw_response.get("interrupted") is True


def _parse_epoch_datetime(value) -> Optional[datetime]:
    try:
        timestamp = float(value)
    except (TypeError, ValueError):
        return None
    if timestamp <= 0:
        return None
    if timestamp > 10_000_000_000:
        timestamp = timestamp / 1000.0
    try:
        return datetime.fromtimestamp(timestamp, timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def _workbuddy_session_status(value, has_activity: bool) -> Optional[SessionStatus]:
    normalized = _normalize_status_token(value)
    if normalized in RUNNING_STATUS_NAMES:
        return SessionStatus.RUNNING
    if normalized == "paused":
        return SessionStatus.IDLE
    if normalized == "pending":
        return SessionStatus.NEEDS_ACTION if has_activity else None
    if normalized == "queued":
        return SessionStatus.RUNNING if has_activity else None
    if normalized in USER_ATTENTION_STATUS_NAMES:
        return SessionStatus.NEEDS_ACTION
    if normalized in {"completed", "complete", "success", "succeeded", "failed", "error"}:
        return SessionStatus.NEEDS_ACTION
    if normalized in {"cancelled", "canceled", "idle", "ready", "stopped"}:
        return SessionStatus.IDLE
    return None


def _workbuddy_session_has_user_attention_signal(value, has_activity: bool) -> bool:
    normalized = _normalize_status_token(value)
    if normalized == "pending":
        return has_activity
    if normalized == "paused":
        return False
    return normalized in USER_ATTENTION_STATUS_NAMES


def _workbuddy_readable_title(title: Optional[str], cwd: Optional[str]) -> Optional[str]:
    text = _optional_str(title)
    if text and text.strip().lower() not in {"新会话", "new chat", "untitled"}:
        return text
    if cwd:
        return Path(str(cwd)).name or None
    return None


def _workbuddy_session_update_id(state: _WorkBuddySessionState) -> str:
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", state.session_id).strip("-") or "unknown"
    return f"workbuddy-{normalized}"


def _workbuddy_session_title(tool_display_name: str, state: _WorkBuddySessionState) -> str:
    title = state.title or state.session_id or "对话"
    project = _workbuddy_project_title_for_display(state.cwd, title)
    suffix = f"{project} - {title}" if project else title
    return f"{tool_display_name} Desktop - {suffix}"


def _workbuddy_project_title_for_display(cwd: Optional[str], title: str) -> Optional[str]:
    if not cwd:
        return None
    project = _optional_str(Path(str(cwd)).name)
    if not project or project.strip().lower() == title.strip().lower():
        return None
    return project


def _workbuddy_session_summary(status: SessionStatus) -> str:
    if status == SessionStatus.RUNNING:
        return "WorkBuddy 正在处理任务。"
    if status == SessionStatus.NEEDS_ACTION:
        return "WorkBuddy 任务已完成或需要用户处理。"
    return "WorkBuddy 当前空闲。"


def _workbuddy_session_requires_view_ack(state: _WorkBuddySessionState) -> bool:
    return state.status == SessionStatus.NEEDS_ACTION and not state.user_attention_signal


def _workbuddy_session_sort_key(state: _WorkBuddySessionState):
    priority = 0 if state.status == SessionStatus.NEEDS_ACTION else 1
    return (priority, -state.updated_at.timestamp(), state.title or "", state.session_id)


def _detect_desktop_app(process_name: str, command: str) -> Optional[AiToolDefinition]:
    for definition in AI_TOOL_DEFINITIONS:
        lower_command = str(command or "").lower()
        if any(token in lower_command for token in definition.ignored_desktop_command_tokens):
            continue
        if any(_looks_like_invoked_desktop_binary(process_name, command, main_binary) for main_binary in definition.desktop_main_binaries):
            return definition
    return None


def _tool_display_name_for_process(definition: AiToolDefinition, process_name: str, command: str) -> str:
    text = f"{process_name} {command}".lower()
    if definition.key == "qoder" and ("qoder cn.app" in text or "qodercn" in text):
        return "Qoder CN"
    return definition.display_name


def _looks_like_invoked_desktop_binary(process_name: str, command: str, main_binary: str) -> bool:
    needle = main_binary.lower()
    for candidate in (process_name, command):
        text = str(candidate or "").strip().lower().lstrip("'\"")
        if text.startswith("/") and needle in text:
            return True
    return False


def _tool_definition_for_update(tool: ToolKind, tool_display_name: Optional[str] = None) -> Optional[AiToolDefinition]:
    if tool != ToolKind.UNKNOWN:
        for definition in AI_TOOL_DEFINITIONS:
            if definition.tool == tool:
                return definition
    if tool_display_name:
        normalized_name = tool_display_name.strip().lower()
        for definition in AI_TOOL_DEFINITIONS:
            if (
                definition.display_name.lower() == normalized_name
                or definition.key.lower() == normalized_name
                or (definition.key == "qoder" and normalized_name == "qoder cn")
            ):
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


def _process_title(tool_definition: AiToolDefinition, cwd: str, tool_display_name: Optional[str] = None) -> str:
    display_name = tool_display_name or tool_definition.display_name
    base = "Claude Code CLI" if tool_definition.tool == ToolKind.CLAUDE_CODE else f"{display_name} CLI"
    folder = Path(cwd).name if cwd else ""
    return f"{base} - {folder}" if folder else base


def _posix_cli_process_case_patterns() -> str:
    patterns: List[str] = []
    for definition in AI_TOOL_DEFINITIONS:
        patterns.extend(definition.cli_executables)
    return "|".join(patterns)


def _posix_desktop_process_case_patterns() -> str:
    patterns: List[str] = []
    for definition in AI_TOOL_DEFINITIONS:
        for main_binary in definition.desktop_main_binaries:
            pattern = _shell_case_pattern(main_binary)
            patterns.append(f"*:*.{pattern}*" if not main_binary.startswith("/") else f"*:*{pattern}*")
    return "|".join(patterns)


def _posix_ignored_desktop_command_case_patterns() -> str:
    patterns: List[str] = []
    for definition in AI_TOOL_DEFINITIONS:
        for token in definition.ignored_desktop_command_tokens:
            patterns.append(f"*{_shell_case_pattern(token)}*")
    return "|".join(patterns) or "__ai_monitor_no_ignored_desktop_process__"


def _shell_case_pattern(value: str) -> str:
    return value.replace(" ", "\\ ")


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
    pending_user_input_call_indices: dict[str, int] = {}
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
        elif payload_type in {"function_call", "custom_tool_call"}:
            if _is_codex_user_input_tool_call(payload):
                call_id = _codex_tool_call_id(payload) or f"record-{index}"
                pending_user_input_call_indices[call_id] = index
            else:
                latest_running_signal_index = index
        elif payload_type in {"function_call_output", "custom_tool_call_output"}:
            call_id = _codex_tool_call_id(payload)
            if call_id is not None:
                pending_user_input_call_indices.pop(call_id, None)
        elif payload_type == "reasoning":
            latest_running_signal_index = index
    fallback_at = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
    updated_at = latest_at or fallback_at
    if not user_thread:
        return None
    effective_needs_action_index = max(
        last_needs_action_index,
        max(pending_user_input_call_indices.values(), default=-1),
    )
    status = _codex_session_status(
        last_started_index,
        last_completed_index,
        effective_needs_action_index,
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
        effective_needs_action_index,
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


def _is_codex_user_input_tool_call(payload: dict) -> bool:
    name = str(payload.get("name") or payload.get("tool_name") or "").strip().lower()
    normalized = name.replace("-", "_").rsplit(".", 1)[-1].rsplit("/", 1)[-1]
    return normalized == "request_user_input"


def _codex_tool_call_id(payload: dict) -> Optional[str]:
    return _optional_str(payload.get("call_id")) or _optional_str(payload.get("id"))


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
    raw_status = _normalize_status_token(payload.get("status"))
    status = _claude_session_status(payload.get("status"))
    if status not in {SessionStatus.IDLE, SessionStatus.NEEDS_ACTION} and not _claude_session_status_is_fresh(payload.get("updatedAt")):
        status = None
    if raw_status == "prompt":
        status_source = "claude-session-prompt"
    elif _claude_session_is_initial_idle(payload, raw_status, status):
        status_source = "claude-session-initial-idle"
    else:
        status_source = "claude-session"
    return _ClaudeSessionState(
        status=status,
        cwd=recorded_cwd,
        updated_at=_parse_millis_datetime(payload.get("updatedAt")),
        status_source=status_source,
    )


def _claude_session_status(value) -> Optional[SessionStatus]:
    status = _normalize_status_token(value)
    if status in {"idle", "ready", "completed", "prompt"}:
        return SessionStatus.IDLE
    if status in RUNNING_STATUS_NAMES:
        return SessionStatus.RUNNING
    if status in USER_ATTENTION_STATUS_NAMES:
        return SessionStatus.NEEDS_ACTION
    return None


def _claude_session_is_initial_idle(payload: dict, raw_status: str, status: Optional[SessionStatus]) -> bool:
    if status != SessionStatus.IDLE or raw_status not in {"idle", "ready"}:
        return False
    started_at = _parse_millis_datetime(payload.get("startedAt"))
    idle_at = _parse_millis_datetime(payload.get("statusUpdatedAt"))
    if idle_at is None:
        idle_at = _parse_millis_datetime(payload.get("updatedAt"))
    if started_at is None or idle_at is None:
        return False
    age_seconds = (idle_at - started_at).total_seconds()
    return 0 <= age_seconds <= CLAUDE_INITIAL_IDLE_GRACE_SECONDS


def _normalize_status_token(value) -> str:
    return re.sub(r"[\s_-]+", "", str(value or "").strip()).lower()


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
    start_new_session = platform.system().lower() != "windows"
    process = None
    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=start_new_session,
        )
        stdout, _stderr = process.communicate(timeout=SOURCE_COMMAND_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        if process is not None:
            try:
                if start_new_session:
                    os.killpg(process.pid, signal.SIGKILL)
                else:
                    process.kill()
            except OSError:
                pass
            process.communicate()
        return None
    except OSError:
        return None
    if process.returncode != 0:
        return None
    return stdout.splitlines()


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
    cli_process_case_patterns = _posix_cli_process_case_patterns()
    desktop_process_case_patterns = _posix_desktop_process_case_patterns()
    ignored_desktop_command_case_patterns = _posix_ignored_desktop_command_case_patterns()
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
        "exe_raw=${comm##*/}; "
        "case \"$exe_raw\" in sh|bash|zsh|fish) shell_process=1 ;; *) shell_process=0 ;; esac; "
        "desktop_process=0; "
        "case \"$args\" in *.app/Contents/MacOS/*|*.app/contents/macos/*) "
        "args_lc=$(printf '%s' \"$args\" | tr '[:upper:]' '[:lower:]'); "
        "exe=$(printf '%s' \"$exe_raw\" | tr '[:upper:]' '[:lower:]'); "
        "ignored_desktop_process=0; "
        f"case \"$args_lc\" in {ignored_desktop_command_case_patterns}) ignored_desktop_process=1 ;; esac; "
        "if [ \"$shell_process\" = \"0\" ] && [ \"$ignored_desktop_process\" = \"0\" ]; then "
        f"case \"$exe:$args_lc\" in {desktop_process_case_patterns}) desktop_process=1 ;; "
        "esac; "
        "fi; "
        ";; esac; "
        "if [ \"$desktop_process\" = \"1\" ]; then "
        "printf 'process_id=%s\\tprocess_name=%s\\tcommand=%s\\tcwd=\\tcpu_percent=%s\\tstat=%s\\tactive_child_count=0\\tfocus_process_id=%s\\tfocus_app_name=\\n' \"$pid\" \"$comm\" \"$args\" \"$cpu\" \"$stat\" \"$pid\"; "
        "continue; "
        "fi; "
        "case \"$args\" in "
        "*/Qoder.app/Contents/Resources/app/resources/bin/*/Qoder\\ start\\ --workDir*|*/Qoder\\ CN.app/Contents/Resources/app/resources/bin/*/Qoder\\ start\\ --workDir*) continue ;; "
        "esac; "
        "exe=$(printf '%s' \"$exe_raw\" | tr '[:upper:]' '[:lower:]'); "
        f"case \"$exe\" in {cli_process_case_patterns}) ;; "
        "*) continue ;; "
        "esac; "
        "case \"$exe\" in claude|claude.exe) ;; *) cwd=$(lsof -a -p \"$pid\" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p' | head -n 1) ;; esac; "
        "case \"$exe\" in claude|claude.exe) active_children=0 ;; *) active_children=$(printf '%s\\n' \"$all_process_rows\" | awk -v pgid=\"$pgid\" -v pid=\"$pid\" '"
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
