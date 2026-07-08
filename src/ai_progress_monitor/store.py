from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from .models import SessionStatus, SessionUpdate, SurfaceKind, ToolKind


class SessionStore:
    def __init__(self, stuck_after_seconds: int = 300, audit_dir: Optional[Path] = None):
        self.stuck_after_seconds = stuck_after_seconds
        self.audit_dir = audit_dir or Path.home() / ".ai-progress-monitor"
        self._sessions: Dict[str, SessionUpdate] = {}
        self._viewed_at_by_session: Dict[str, datetime] = {}
        self._viewed_wall_time_by_session: Dict[str, datetime] = {}

    def apply_updates(self, updates: Iterable[SessionUpdate]) -> None:
        for update in updates:
            existing = self._sessions.get(update.session_id)
            update = self._normalize_update(existing, update)
            if existing is None or update.updated_at >= existing.updated_at:
                self._sessions[update.session_id] = update

    def replace_source_updates(self, source: str, updates: Iterable[SessionUpdate]) -> None:
        updates = list(updates)
        live_ids = {update.session_id for update in updates}
        for session_id, session in list(self._sessions.items()):
            if session.source == source and session_id not in live_ids:
                del self._sessions[session_id]
        self.apply_updates(updates)

    def sessions(self, now: Optional[datetime] = None) -> List[SessionUpdate]:
        current = now or datetime.now(timezone.utc)
        marked = [self._mark_stuck(self._mark_viewed(session), current) for session in self._sessions.values()]
        return sorted(marked, key=_session_sort_key)

    def mark_session_viewed(self, session_id: str, viewed_at: Optional[datetime] = None) -> bool:
        session = self._sessions.get(session_id)
        if session is None:
            return False
        self._viewed_at_by_session[session_id] = session.updated_at
        self._viewed_wall_time_by_session[session_id] = viewed_at or datetime.now(timezone.utc)
        return True

    def session_viewed_at(self, session_id: str) -> Optional[datetime]:
        return self._viewed_wall_time_by_session.get(session_id)

    def audit_action(self, session_id: str, option: str, result: str) -> Path:
        self.audit_dir.mkdir(parents=True, exist_ok=True)
        path = self.audit_dir / f"action-audit-{datetime.now(timezone.utc).date().isoformat()}.jsonl"
        payload = {
            "session_id": session_id,
            "option": option,
            "result": result,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=True) + "\n")
        return path

    def _mark_stuck(self, session: SessionUpdate, now: datetime) -> SessionUpdate:
        if session.status != SessionStatus.RUNNING:
            return session
        if (now - session.updated_at).total_seconds() < self.stuck_after_seconds:
            return session
        return replace(session, status=SessionStatus.STUCK, summary="No progress detected recently")

    def _mark_viewed(self, session: SessionUpdate) -> SessionUpdate:
        viewed_at = self._viewed_at_by_session.get(session.session_id)
        if not session.view_ack_required or viewed_at is None:
            return session
        if viewed_at < session.updated_at:
            return session
        return replace(session, status=SessionStatus.IDLE)

    def _normalize_update(self, existing: Optional[SessionUpdate], update: SessionUpdate) -> SessionUpdate:
        if not _is_claude_terminal_idle_process(update):
            if _is_claude_terminal_process(update) and _is_process_status_fallback(update):
                return self._preserve_claude_semantic_state(existing, update)
            return update
        if _is_process_status_fallback(update):
            return self._preserve_claude_semantic_state(existing, update)
        viewed_at = self._viewed_at_by_session.get(update.session_id)
        if existing is not None and existing.view_ack_required and existing.updated_at == update.updated_at:
            if viewed_at is None or viewed_at < update.updated_at:
                return replace(update, status=SessionStatus.NEEDS_ACTION, view_ack_required=True)
            return update
        if existing is not None and existing.status == SessionStatus.RUNNING and update.updated_at >= existing.updated_at:
            return replace(update, status=SessionStatus.NEEDS_ACTION, view_ack_required=True)
        if existing is not None and update.updated_at > existing.updated_at:
            if viewed_at is None or viewed_at < update.updated_at:
                return replace(update, status=SessionStatus.NEEDS_ACTION, view_ack_required=True)
        return update

    def _preserve_claude_semantic_state(self, existing: Optional[SessionUpdate], update: SessionUpdate) -> SessionUpdate:
        if existing is None:
            return update
        viewed_at = self._viewed_at_by_session.get(update.session_id)
        if existing.view_ack_required:
            if viewed_at is None or viewed_at < existing.updated_at:
                return existing
            return replace(existing, status=SessionStatus.IDLE)
        if viewed_at is not None and viewed_at >= existing.updated_at:
            return replace(existing, status=SessionStatus.IDLE)
        return update


def _session_sort_key(session: SessionUpdate):
    priority = {
        SessionStatus.NEEDS_ACTION: 0,
        SessionStatus.STUCK: 1,
        SessionStatus.IDLE: 2,
        SessionStatus.RUNNING: 3,
        SessionStatus.UNKNOWN: 4,
    }
    monitoring_weight = 1 if session.source == "process" else 0
    return (monitoring_weight, priority.get(session.status, 9), -session.updated_at.timestamp(), session.title.lower())


def _is_claude_terminal_idle_process(session: SessionUpdate) -> bool:
    return _is_claude_terminal_process(session) and session.status == SessionStatus.IDLE


def _is_claude_terminal_process(session: SessionUpdate) -> bool:
    return (
        session.tool == ToolKind.CLAUDE_CODE
        and session.surface == SurfaceKind.TERMINAL
        and session.source == "process"
    )


def _is_process_status_fallback(session: SessionUpdate) -> bool:
    return session.status_source == "process"
