from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Dict, Iterable, List, Optional, Tuple

from .models import SessionStatus, SessionUpdate, SurfaceKind, ToolKind


CLAUDE_TERMINAL_STATE_CLOCK_SKEW_SECONDS = 2.0
CLAUDE_VERIFIED_RUNNING_CONFIRMATION_WINDOW_SECONDS = 10.0


class SessionStore:
    def __init__(self, stuck_after_seconds: int = 300, audit_dir: Optional[Path] = None):
        self.stuck_after_seconds = stuck_after_seconds
        self.audit_dir = audit_dir or Path.home() / ".ai-progress-monitor"
        self._lock = RLock()
        self._sessions: Dict[str, SessionUpdate] = {}
        self._viewed_at_by_session: Dict[str, datetime] = {}
        self._viewed_wall_time_by_session: Dict[str, datetime] = {}
        self._verified_observed_at_by_session: Dict[str, datetime] = {}
        self._verified_running_observed_at_by_session: Dict[str, datetime] = {}
        self._pending_verified_running_by_session: Dict[
            str,
            Tuple[SessionStatus, datetime, datetime, datetime, int],
        ] = {}

    def apply_updates(self, updates: Iterable[SessionUpdate]) -> None:
        updates = list(updates)
        with self._lock:
            self._apply_updates_locked(updates)

    def _apply_updates_locked(self, updates: Iterable[SessionUpdate]) -> None:
        for update in updates:
            existing = self._sessions.get(update.session_id)
            if _has_changed_claude_process_identity(existing, update):
                self._clear_session_state_locked(update.session_id)
                existing = None
            incoming_verified_observed_at = _verified_observed_at(update)
            incoming_verified_running_observed_at = _verified_running_observed_at(update)
            verified_high_water = self._verified_observed_at_by_session.get(update.session_id)
            if _has_older_verified_observation(verified_high_water, incoming_verified_observed_at):
                continue
            allow_out_of_order_terminal = _is_recent_verified_claude_terminal_transition(existing, update)
            allow_recent_initial_idle = _is_recent_initial_idle_over_process_fallback(existing, update)
            verified_over_degraded = _is_verified_claude_state_over_degraded_state(existing, update)
            allow_verified_running_restart = self._allow_verified_running_restart(
                existing,
                update,
                verified_high_water,
            )
            verified_running_requires_confirmation = (
                _is_verified_claude_running_over_terminal_state(existing, update)
                and existing is not None
                and update.updated_at <= existing.updated_at
            )
            allow_running_to_terminal = (
                allow_out_of_order_terminal
                or (
                    verified_over_degraded
                    and existing is not None
                    and existing.status == SessionStatus.RUNNING
                    and _is_claude_terminal_explicit_non_running(update)
                )
            )
            update = self._normalize_update(
                existing,
                update,
                allow_running_to_terminal=allow_running_to_terminal,
                verified_observed_at=verified_high_water,
            )
            if (
                existing is None
                or (
                    update.updated_at >= existing.updated_at
                    and not verified_running_requires_confirmation
                )
                or allow_out_of_order_terminal
                or allow_recent_initial_idle
                or verified_over_degraded
                or allow_verified_running_restart
            ):
                if (
                    existing is not None
                    and existing.status != SessionStatus.RUNNING
                    and update.status == SessionStatus.RUNNING
                    and _is_claude_terminal_semantic_state(update)
                ):
                    self._viewed_at_by_session.pop(update.session_id, None)
                    self._viewed_wall_time_by_session.pop(update.session_id, None)
                self._sessions[update.session_id] = update
                self._pending_verified_running_by_session.pop(update.session_id, None)
                if (
                    _is_claude_terminal_semantic_state(update)
                    and update.status != SessionStatus.RUNNING
                ):
                    self._verified_running_observed_at_by_session.pop(update.session_id, None)
            if incoming_verified_observed_at is not None:
                self._verified_observed_at_by_session[update.session_id] = max(
                    incoming_verified_observed_at,
                    verified_high_water or incoming_verified_observed_at,
                )
            if incoming_verified_running_observed_at is not None:
                current_running_observed_at = self._verified_running_observed_at_by_session.get(
                    update.session_id
                )
                self._verified_running_observed_at_by_session[update.session_id] = max(
                    incoming_verified_running_observed_at,
                    current_running_observed_at or incoming_verified_running_observed_at,
                )

    def _allow_verified_running_restart(
        self,
        existing: Optional[SessionUpdate],
        update: SessionUpdate,
        verified_high_water: Optional[datetime],
    ) -> bool:
        session_id = update.session_id
        if not _is_verified_claude_running_over_terminal_state(existing, update):
            self._pending_verified_running_by_session.pop(session_id, None)
            return False
        incoming_observed_at = update.observed_at
        observation_floor = verified_high_water or existing.observed_at
        if (
            incoming_observed_at is None
            or (observation_floor is not None and incoming_observed_at <= observation_floor)
        ):
            return False
        pending = self._pending_verified_running_by_session.get(session_id)
        observation_gap_seconds = (
            (incoming_observed_at - pending[3]).total_seconds()
            if pending is not None
            else None
        )
        slow_confirmation_window_seconds = max(
            CLAUDE_VERIFIED_RUNNING_CONFIRMATION_WINDOW_SECONDS,
            float(self.stuck_after_seconds),
        )
        matches_pending = (
            pending is not None
            and pending[0] == existing.status
            and pending[1] == existing.updated_at
            and update.updated_at >= pending[2]
            and observation_gap_seconds is not None
            and observation_gap_seconds > 0
        )
        fast_confirmation = (
            matches_pending
            and observation_gap_seconds <= CLAUDE_VERIFIED_RUNNING_CONFIRMATION_WINDOW_SECONDS
        )
        slow_confirmation = (
            matches_pending
            and observation_gap_seconds <= slow_confirmation_window_seconds
            and pending[4] >= 2
        )
        if fast_confirmation or slow_confirmation:
            self._pending_verified_running_by_session.pop(session_id, None)
            return True
        consecutive_observations = (
            pending[4] + 1
            if matches_pending and observation_gap_seconds <= slow_confirmation_window_seconds
            else 1
        )
        self._pending_verified_running_by_session[session_id] = (
            existing.status,
            existing.updated_at,
            update.updated_at,
            incoming_observed_at,
            consecutive_observations,
        )
        return False

    def replace_source_updates(self, source: str, updates: Iterable[SessionUpdate]) -> None:
        updates = list(updates)
        with self._lock:
            live_ids = {update.session_id for update in updates}
            for session_id, session in list(self._sessions.items()):
                if session.source == source and session_id not in live_ids:
                    self._clear_session_state_locked(session_id)
            self._apply_updates_locked(updates)

    def _clear_session_state_locked(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)
        self._viewed_at_by_session.pop(session_id, None)
        self._viewed_wall_time_by_session.pop(session_id, None)
        self._verified_observed_at_by_session.pop(session_id, None)
        self._verified_running_observed_at_by_session.pop(session_id, None)
        self._pending_verified_running_by_session.pop(session_id, None)

    def sessions(self, now: Optional[datetime] = None) -> List[SessionUpdate]:
        current = now or datetime.now(timezone.utc)
        with self._lock:
            marked = [self._mark_stuck(self._mark_viewed(session), current) for session in self._sessions.values()]
            return sorted(marked, key=_session_sort_key)

    def mark_session_viewed(self, session_id: str, viewed_at: Optional[datetime] = None) -> bool:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return False
            self._viewed_at_by_session[session_id] = session.updated_at
            self._viewed_wall_time_by_session[session_id] = viewed_at or datetime.now(timezone.utc)
            return True

    def session_viewed_at(self, session_id: str) -> Optional[datetime]:
        with self._lock:
            return self._viewed_wall_time_by_session.get(session_id)

    def audit_action(self, session_id: str, option: str, result: str) -> Path:
        with self._lock:
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
        progress_at = (
            self._verified_running_observed_at_by_session.get(session.session_id)
            or session.observed_at
            or session.updated_at
            if _is_verified_claude_terminal_running(session)
            else session.updated_at
        )
        if (now - progress_at).total_seconds() < self.stuck_after_seconds:
            return session
        return replace(session, status=SessionStatus.STUCK, summary="No progress detected recently")

    def _mark_viewed(self, session: SessionUpdate) -> SessionUpdate:
        viewed_at = self._viewed_at_by_session.get(session.session_id)
        if not session.view_ack_required or viewed_at is None:
            return session
        if viewed_at < session.updated_at:
            return session
        return replace(session, status=SessionStatus.IDLE)

    def _normalize_update(
        self,
        existing: Optional[SessionUpdate],
        update: SessionUpdate,
        allow_running_to_terminal: bool = False,
        verified_observed_at: Optional[datetime] = None,
    ) -> SessionUpdate:
        if _is_identity_verified_claude_terminal_state(existing) and _is_unverified_claude_terminal_running(update):
            if _is_degraded_running_within_grace(
                verified_observed_at or existing.observed_at,
                update,
                self.stuck_after_seconds,
            ):
                return existing
        if not _is_claude_terminal_idle_process(update):
            if _is_claude_terminal_process(update) and _is_process_status_fallback(update):
                return self._preserve_claude_semantic_state(existing, update)
            return update
        if _is_claude_terminal_initial_idle(update):
            return self._normalize_claude_initial_idle(existing, update)
        if _is_claude_terminal_prompt_idle(update):
            return self._normalize_claude_prompt_idle(existing, update)
        if _is_process_status_fallback(update):
            return self._preserve_claude_semantic_state(existing, update)
        viewed_at = self._viewed_at_by_session.get(update.session_id)
        if existing is not None and existing.view_ack_required and existing.updated_at == update.updated_at:
            if viewed_at is None or viewed_at < update.updated_at:
                return replace(update, status=SessionStatus.NEEDS_ACTION, view_ack_required=True)
            return update
        if (
            existing is not None
            and existing.status == SessionStatus.RUNNING
            and (update.updated_at >= existing.updated_at or allow_running_to_terminal)
        ):
            return replace(update, status=SessionStatus.NEEDS_ACTION, view_ack_required=True)
        if existing is not None and update.updated_at > existing.updated_at:
            if viewed_at is None or viewed_at < update.updated_at:
                return replace(update, status=SessionStatus.NEEDS_ACTION, view_ack_required=True)
        return update

    def _normalize_claude_prompt_idle(self, existing: Optional[SessionUpdate], update: SessionUpdate) -> SessionUpdate:
        if existing is None:
            return update
        viewed_at = self._viewed_at_by_session.get(update.session_id)
        if existing.view_ack_required:
            if viewed_at is None or viewed_at < existing.updated_at:
                return existing
            return update
        if existing.status == SessionStatus.RUNNING:
            return replace(update, status=SessionStatus.NEEDS_ACTION, view_ack_required=True)
        return update

    def _normalize_claude_initial_idle(self, existing: Optional[SessionUpdate], update: SessionUpdate) -> SessionUpdate:
        if existing is None:
            return update
        viewed_at = self._viewed_at_by_session.get(update.session_id)
        if existing.view_ack_required:
            if viewed_at is None or viewed_at < existing.updated_at:
                return existing
            return _with_minimum_updated_at(update, existing.updated_at)
        if _is_process_status_fallback(existing):
            return update
        if existing.status == SessionStatus.RUNNING and update.updated_at >= existing.updated_at:
            return replace(update, status=SessionStatus.NEEDS_ACTION, view_ack_required=True)
        return update

    def _preserve_claude_semantic_state(self, existing: Optional[SessionUpdate], update: SessionUpdate) -> SessionUpdate:
        if existing is None:
            return update
        if _is_claude_terminal_semantic_state(existing):
            return existing
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


def _has_changed_claude_process_identity(
    existing: Optional[SessionUpdate],
    update: SessionUpdate,
) -> bool:
    return (
        existing is not None
        and existing.session_id == update.session_id
        and _is_claude_terminal_process(existing)
        and _is_claude_terminal_process(update)
        and existing.process_id is not None
        and existing.process_id == update.process_id
        and existing.process_started_at is not None
        and update.process_started_at is not None
        and existing.process_started_at != update.process_started_at
    )


def _is_process_status_fallback(session: SessionUpdate) -> bool:
    return session.status_source == "process"


def _is_verified_claude_terminal_running(session: Optional[SessionUpdate]) -> bool:
    return (
        session is not None
        and _is_claude_terminal_process(session)
        and session.status == SessionStatus.RUNNING
        and session.status_source == "claude-session-verified"
    )


def _is_claude_terminal_explicit_non_running(session: SessionUpdate) -> bool:
    return (
        _is_claude_terminal_process(session)
        and session.status in {SessionStatus.IDLE, SessionStatus.NEEDS_ACTION}
        and not _is_process_status_fallback(session)
        and not _is_claude_terminal_initial_idle(session)
    )


def _is_claude_terminal_semantic_state(session: SessionUpdate) -> bool:
    return _is_claude_terminal_process(session) and not _is_process_status_fallback(session)


def _is_identity_verified_claude_terminal_state(session: Optional[SessionUpdate]) -> bool:
    return (
        session is not None
        and _is_claude_terminal_semantic_state(session)
        and session.observed_at is not None
    )


def _is_unverified_claude_terminal_running(session: SessionUpdate) -> bool:
    return (
        _is_claude_terminal_semantic_state(session)
        and session.status == SessionStatus.RUNNING
        and session.observed_at is None
    )


def _verified_observed_at(session: SessionUpdate) -> Optional[datetime]:
    if not _is_identity_verified_claude_terminal_state(session):
        return None
    return session.observed_at


def _verified_running_observed_at(session: SessionUpdate) -> Optional[datetime]:
    if not _is_verified_claude_terminal_running(session):
        return None
    return session.observed_at


def _has_older_verified_observation(
    high_water: Optional[datetime],
    incoming: Optional[datetime],
) -> bool:
    return high_water is not None and incoming is not None and incoming < high_water


def _is_degraded_running_within_grace(
    verified_observed_at: Optional[datetime],
    update: SessionUpdate,
    grace_seconds: float,
) -> bool:
    if verified_observed_at is None:
        return False
    age_seconds = (update.updated_at - verified_observed_at).total_seconds()
    return age_seconds < grace_seconds


def _is_verified_claude_state_over_degraded_state(
    existing: Optional[SessionUpdate],
    update: SessionUpdate,
) -> bool:
    return (
        existing is not None
        and _is_claude_terminal_process(existing)
        and not _is_identity_verified_claude_terminal_state(existing)
        and _is_identity_verified_claude_terminal_state(update)
    )


def _is_verified_claude_running_over_terminal_state(
    existing: Optional[SessionUpdate],
    update: SessionUpdate,
) -> bool:
    return (
        _is_identity_verified_claude_terminal_state(existing)
        and existing.status in {SessionStatus.IDLE, SessionStatus.NEEDS_ACTION}
        and _is_verified_claude_terminal_running(update)
    )


def _is_recent_verified_claude_terminal_transition(
    existing: Optional[SessionUpdate],
    update: SessionUpdate,
) -> bool:
    if not _is_verified_claude_terminal_running(existing):
        return False
    if not _is_claude_terminal_explicit_non_running(update):
        return False
    if not _is_identity_verified_claude_terminal_state(update):
        return False
    if existing.observed_at is not None and update.observed_at < existing.observed_at:
        return False
    skew_seconds = (existing.updated_at - update.updated_at).total_seconds()
    return 0 < skew_seconds <= CLAUDE_TERMINAL_STATE_CLOCK_SKEW_SECONDS


def _is_recent_initial_idle_over_process_fallback(
    existing: Optional[SessionUpdate],
    update: SessionUpdate,
) -> bool:
    if existing is None or not _is_process_status_fallback(existing):
        return False
    if not _is_claude_terminal_initial_idle(update):
        return False
    skew_seconds = (existing.updated_at - update.updated_at).total_seconds()
    return 0 < skew_seconds <= CLAUDE_TERMINAL_STATE_CLOCK_SKEW_SECONDS


def _is_claude_terminal_initial_idle(session: SessionUpdate) -> bool:
    return session.status_source == "claude-session-initial-idle"


def _is_claude_terminal_prompt_idle(session: SessionUpdate) -> bool:
    return session.status_source == "claude-session-prompt"


def _with_minimum_updated_at(session: SessionUpdate, updated_at: datetime) -> SessionUpdate:
    if session.updated_at >= updated_at:
        return session
    return replace(session, updated_at=updated_at)
