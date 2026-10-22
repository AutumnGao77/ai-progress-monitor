"""Read local Qoder desktop lifecycle data without retaining message bodies.

The newer desktop shell projects turns into SQLite instead of the IDE's quest
cache. Session messages are authoritative for completed results; the per-session
SDK log supplements in-flight permissions before their UI projection is saved.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
import json
import re
import sqlite3
import time
from typing import Dict, List, Optional, Set, Tuple

from .models import SessionStatus


SESSION_LIMIT = 128
PAYLOAD_LIMIT = 2 * 1024 * 1024
SNAPSHOT_PAYLOAD_LIMIT = 8 * 1024 * 1024
LOG_BYTE_BUDGET = 2 * 1024 * 1024
LOG_LINE_LIMIT = 64 * 1024
RUNNING_STALE_SECONDS = 10 * 60
IDLE_VISIBLE_SECONDS = 15 * 60
_ATTENTION = frozenset({"waiting_for_input", "waiting_for_permission", "awaiting_input",
                        "awaiting_approval", "permission_required", "needs_action", "suspended"})
_STOPPED = frozenset({"cancelled", "canceled", "aborted", "interrupted", "stopped"})
_COMPLETED = frozenset({"completed", "complete", "success", "succeeded"})
_FAILED = frozenset({"error", "failed", "failure"})
_PENDING_REQUEST_TYPES = frozenset({"can_use_tool", "permission", "ask_user_question", "request_user_input"})


@dataclass(frozen=True)
class QoderDesktopState:
    session_id: str
    status: SessionStatus
    updated_at: datetime
    title: Optional[str] = None
    cwd: Optional[str] = None
    user_attention_signal: bool = False


@dataclass
class _LogSignal:
    started_at: Optional[datetime] = None
    event_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    status: Optional[SessionStatus] = None
    visible_reply: bool = False
    pending: Set[str] = field(default_factory=set)


@dataclass
class _LogReplay:
    identity: Tuple[int, int]
    offset: int = 0
    signal: _LogSignal = field(default_factory=_LogSignal)
    skipping_oversized_record: bool = False


class _IncompleteSnapshot(Exception):
    pass


class QoderDesktopReader:
    def __init__(self, log_byte_budget: int = LOG_BYTE_BUDGET):
        self.log_byte_budget = max(1, log_byte_budget)
        self._snapshots: Dict[Path, List[QoderDesktopState]] = {}
        self._logs: Dict[Path, _LogReplay] = {}

    def read(
        self, db_path: Path, now: datetime, source_started_at: Optional[datetime] = None,
    ) -> Optional[List[QoderDesktopState]]:
        """Return a complete snapshot, preserving the previous one on uncertainty."""
        db_path = Path(db_path)
        try:
            states = self._read_snapshot(db_path, now)
        except (OSError, sqlite3.Error, ValueError, TypeError, _IncompleteSnapshot):
            previous = self._snapshots.get(db_path)
            return list(previous) if previous is not None else None
        filtered = []
        for state in states:
            age = (now - state.updated_at).total_seconds()
            if state.status == SessionStatus.RUNNING and age > RUNNING_STALE_SECONDS:
                continue
            if state.status == SessionStatus.IDLE and age > IDLE_VISIBLE_SECONDS:
                continue
            if (source_started_at is not None and state.updated_at < source_started_at
                    and state.status != SessionStatus.RUNNING and not state.user_attention_signal):
                continue
            filtered.append(state)
        self._snapshots[db_path] = filtered
        return list(filtered)

    def _read_snapshot(self, db_path: Path, now: datetime) -> List[QoderDesktopState]:
        connection = sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True, timeout=0.05)
        connection.row_factory = sqlite3.Row
        deadline = time.monotonic() + 0.5
        connection.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
        states = []
        remaining_payload = SNAPSHOT_PAYLOAD_LIMIT
        remaining_log = self.log_byte_budget
        used_log_paths = set()
        incomplete = False
        try:
            connection.execute("BEGIN")
            sessions = connection.execute("""
                SELECT session_id, title, cwd FROM chat_sessions
                WHERE deleted_at IS NULL AND COALESCE(archived, 0) = 0
                    AND COALESCE(execution_kind, 'local') = 'local'
                ORDER BY updated_at DESC LIMIT ?
            """, (SESSION_LIMIT,)).fetchall()
            for session in sessions:
                rows = connection.execute("""
                    SELECT sequence, role, status, runtime_input_state, has_visible_content,
                        created_at, updated_at, turn_started_at,
                        CASE WHEN length(payload_json) <= ? THEN payload_json END AS payload_json
                    FROM chat_session_messages WHERE session_id = ?
                        AND role IN ('user', 'assistant') AND COALESCE(subtype, '') = ''
                    ORDER BY sequence DESC LIMIT 4
                """, (PAYLOAD_LIMIT, session["session_id"])).fetchall()
                if not rows:
                    continue
                latest = rows[0]
                payload_text = latest["payload_json"] or "{}"
                remaining_payload -= len(payload_text)
                if remaining_payload < 0:
                    raise _IncompleteSnapshot()
                payload = json.loads(payload_text)
                if not isinstance(payload, dict):
                    raise _IncompleteSnapshot()
                state = _message_state(session, latest, payload)
                if state is None:
                    continue
                user_at = next((_timestamp(row["created_at"]) for row in rows if row["role"] == "user"), None)
                log_path = _session_log_path(db_path.parent, str(session["session_id"]))
                if log_path is not None:
                    used_log_paths.add(log_path)
                    signal, consumed = self._read_log(log_path, remaining_log)
                    remaining_log -= consumed
                    if signal is None:
                        incomplete = True
                    else:
                        state = _merge_signal(state, signal, user_at)
                states.append(state)
        finally:
            connection.close()
        if incomplete:
            raise _IncompleteSnapshot()
        self._logs = {path: replay for path, replay in self._logs.items() if path in used_log_paths}
        return states

    def _read_log(self, path: Path, budget: int) -> Tuple[Optional[_LogSignal], int]:
        stat = path.stat()
        identity = (stat.st_dev, stat.st_ino)
        replay = self._logs.get(path)
        if replay is None or replay.identity != identity or stat.st_size < replay.offset:
            replay = _LogReplay(identity)
            self._logs[path] = replay
        consumed = 0
        with path.open("rb") as handle:
            handle.seek(replay.offset)
            while handle.tell() < stat.st_size and consumed < budget:
                line = handle.readline(LOG_LINE_LIMIT)
                consumed += len(line)
                if replay.skipping_oversized_record:
                    replay.offset = handle.tell()
                    if line.endswith(b"\n"):
                        replay.skipping_oversized_record = False
                    continue
                if not line.endswith(b"\n"):
                    # An unfinished record is retried without retaining raw content.
                    if len(line) < LOG_LINE_LIMIT:
                        return None, consumed
                    # Persist only the byte offset and skip flag, so records larger
                    # than a poll's budget cannot stall all future replay attempts.
                    replay.skipping_oversized_record = True
                else:
                    _apply_log_line(replay.signal, line.decode("utf-8", errors="replace"))
                replay.offset = handle.tell()
        after = path.stat()
        if (replay.skipping_oversized_record or replay.offset < stat.st_size or after.st_size != stat.st_size
                or after.st_mtime_ns != stat.st_mtime_ns or (after.st_dev, after.st_ino) != identity):
            return None, consumed
        return deepcopy(replay.signal), consumed


def _timestamp(value) -> Optional[datetime]:
    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value / 1000.0, timezone.utc)
        if isinstance(value, str) and value.strip():
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    except (ValueError, OverflowError, OSError):
        pass
    return None


def _text(value) -> Optional[str]:
    return value.strip() or None if isinstance(value, str) else None


def _message_state(session, row, payload: dict) -> Optional[QoderDesktopState]:
    updated_at = _timestamp(row["updated_at"]) or _timestamp(row["created_at"])
    if updated_at is None:
        return None
    status = str(row["status"] or "").lower()
    attention = False
    if row["role"] == "user":
        updated_at = _timestamp(row["created_at"]) or updated_at
        normalized = SessionStatus.IDLE if row["runtime_input_state"] in {"queued", "rejected"} else SessionStatus.RUNNING
    elif status in _ATTENTION:
        normalized, attention = SessionStatus.NEEDS_ACTION, True
    elif status in _STOPPED:
        normalized = SessionStatus.IDLE
    elif status in _FAILED:
        normalized = SessionStatus.NEEDS_ACTION
        code = str(payload.get("appErrorCode") or payload.get("errorCode") or "").lower()
        attention = any(token in code for token in ("quota", "credit", "subscription", "plan_required", "unauthorized", "auth_required"))
    elif status in _COMPLETED:
        normalized = SessionStatus.NEEDS_ACTION if _visible_reply(payload, row) else SessionStatus.IDLE
        updated_at = _timestamp(payload.get("completedAt")) or updated_at
    elif status in {"running", "streaming", "pending", "in_progress", "incomplete"}:
        attention = _pending_part(payload)
        normalized = SessionStatus.NEEDS_ACTION if attention else SessionStatus.RUNNING
    else:
        return None
    return QoderDesktopState(str(session["session_id"]), normalized, updated_at,
                             _text(session["title"]), _text(session["cwd"]), attention)


def _visible_reply(payload: dict, row) -> bool:
    if row["payload_json"] is None:
        return bool(row["has_visible_content"])
    for part in payload.get("parts", []):
        if not isinstance(part, dict):
            continue
        if part.get("type") == "text" and _text(part.get("text")):
            return True
        if part.get("type") in {"image", "file", "artifact", "error"}:
            return True
    return False


def _pending_part(payload: dict) -> bool:
    for part in payload.get("parts", []):
        if not isinstance(part, dict):
            continue
        if part.get("type") in {"permission", "question", "user_input"}:
            if part.get("status", part.get("state")) in {"pending", "waiting", "requested"}:
                return True
    return False


def _session_log_path(root: Path, session_id: str) -> Optional[Path]:
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,128}", session_id) or session_id in {".", ".."}:
        return None
    logs = root / "logs"
    if not logs.is_dir():
        return None
    directories = sorted((p for p in logs.iterdir() if p.is_dir()), key=lambda p: p.name, reverse=True)
    for directory in directories[:8]:
        candidate = directory / "qodercli" / "sessions" / (session_id + ".log")
        if candidate.is_file():
            return candidate
    return None


def _apply_log_line(signal: _LogSignal, line: str) -> None:
    # Preview text is not needed for lifecycle matching and is never cached.
    header, _, preview = line.partition(" preview=")
    match = re.match(r"^(\S+) \[QueryRunner\] (.*)", header)
    if match is None:
        return
    at = _timestamp(match.group(1))
    if at is None:
        return
    event = match.group(2)
    if event.startswith("outbound session_message sent type=user "):
        signal.started_at = signal.event_at = at
        signal.finished_at = None
        signal.status = SessionStatus.RUNNING
        signal.visible_reply = False
        signal.pending.clear()
        return
    request = re.search(r"request_id=(\S+) subtype=(\S+)", event)
    if request is not None and request.group(2) in _PENDING_REQUEST_TYPES:
        if event.startswith("inbound control_request received "):
            signal.pending.add(request.group(1))
            signal.event_at = at
        elif event.startswith("inbound control_response sent ") and request.group(1) in signal.pending:
            signal.pending.discard(request.group(1))
            signal.event_at = at
        return
    if event.startswith("control_response received ") and "subtype=interrupt " in event and "status=success" in event:
        signal.status = SessionStatus.IDLE
        signal.finished_at = signal.event_at = at
        signal.pending.clear()
    elif event.startswith("inbound session_message received type=assistant "):
        signal.visible_reply = signal.visible_reply or bool(preview.strip().strip('"').strip())
    elif event.startswith("inbound session_message received type=result "):
        signal.status = SessionStatus.NEEDS_ACTION if signal.visible_reply or "subtype=error" in event else SessionStatus.IDLE
        signal.finished_at = signal.event_at = at
        signal.pending.clear()


def _merge_signal(state: QoderDesktopState, signal: _LogSignal, user_at: Optional[datetime]) -> QoderDesktopState:
    if signal.started_at is None or (user_at is not None and user_at > signal.started_at):
        return state
    terminal = state.status in {SessionStatus.IDLE, SessionStatus.NEEDS_ACTION} and not state.user_attention_signal
    # A projected final result closes older in-flight log signals. Its completion
    # timestamp remains authoritative despite later SDK housekeeping events.
    if terminal and state.updated_at >= signal.started_at:
        return state
    if signal.pending:
        return replace(state, status=SessionStatus.NEEDS_ACTION, user_attention_signal=True,
                       updated_at=signal.event_at or state.updated_at)
    if signal.finished_at is not None:
        if signal.finished_at > state.updated_at:
            return replace(state, status=signal.status or SessionStatus.IDLE, user_attention_signal=False,
                           updated_at=signal.finished_at)
        return state
    if signal.status == SessionStatus.RUNNING and (
        signal.started_at > state.updated_at
        or (state.user_attention_signal and signal.event_at is not None and signal.event_at > state.updated_at)
    ):
        return replace(state, status=SessionStatus.RUNNING, user_attention_signal=False,
                       updated_at=signal.event_at or signal.started_at)
    return state
