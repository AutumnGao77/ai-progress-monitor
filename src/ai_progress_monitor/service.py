from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import time
from typing import Callable, Iterable, List, Optional

from .actions import ActionExecutor, is_low_risk_action
from .models import ActionResult, SessionStatus, SessionUpdate, SurfaceKind, ToolKind
from .notifier import NotificationManager
from .preferences import MonitorPreferences
from .store import SessionStore
from .terminal_bridge import clean_terminal_text
from .window_focus import FocusResult, WindowFocusManager


VIEWED_DESKTOP_IDLE_VISIBLE_SECONDS = 15 * 60


class MonitorService:
    def __init__(
        self,
        sources: Iterable,
        store: SessionStore,
        executor: ActionExecutor,
        notifier: Optional[NotificationManager] = None,
        focus_manager: Optional[WindowFocusManager] = None,
        preferences: Optional[MonitorPreferences] = None,
        process_empty_grace_seconds: float = 12.0,
        clock: Optional[Callable[[], float]] = None,
        now: Optional[Callable[[], datetime]] = None,
        viewed_desktop_idle_visible_seconds: float = VIEWED_DESKTOP_IDLE_VISIBLE_SECONDS,
    ):
        self.sources = list(sources)
        self.store = store
        self.executor = executor
        self.notifier = notifier
        self.focus_manager = focus_manager or WindowFocusManager()
        self.preferences = preferences or MonitorPreferences()
        self.paused = False
        self.process_empty_grace_seconds = process_empty_grace_seconds
        self.clock = clock or time.monotonic
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.viewed_desktop_idle_visible_seconds = viewed_desktop_idle_visible_seconds
        self._process_empty_started_at: Optional[float] = None

    def refresh(self) -> List[SessionUpdate]:
        if not self.paused:
            for source, updates in self._poll_sources():
                if updates is None:
                    continue
                volatile_source = getattr(source, "volatile_source", None)
                if volatile_source:
                    self._replace_volatile_source_updates(str(volatile_source), updates)
                else:
                    self.store.apply_updates(updates)
        sessions = self.visible_sessions()
        if self.notifier is not None:
            self.notifier.notify_for_sessions(sessions)
        return sessions

    def _poll_sources(self) -> List[tuple[object, Optional[List[SessionUpdate]]]]:
        if not self.sources:
            return []
        with ThreadPoolExecutor(max_workers=len(self.sources)) as executor:
            futures = [executor.submit(source.poll) for source in self.sources]
            results: List[tuple[object, Optional[List[SessionUpdate]]]] = []
            for source, future in zip(self.sources, futures):
                try:
                    updates = future.result()
                except Exception as error:
                    print(
                        f"AI Progress Monitor source failed: {source.__class__.__name__} ({error.__class__.__name__})",
                        flush=True,
                    )
                    updates = None
                results.append((source, updates))
            return results

    def _replace_volatile_source_updates(self, source: str, updates: Optional[List[SessionUpdate]]) -> None:
        if updates is None:
            return
        if source == "process" and not updates and self._has_source_sessions("process"):
            now = self.clock()
            if self._process_empty_started_at is None:
                self._process_empty_started_at = now
                return
            if now - self._process_empty_started_at < self.process_empty_grace_seconds:
                return
        if source == "process" and updates:
            self._process_empty_started_at = None
        if source == "process":
            updates = self._retain_recent_full_process_desktop_sessions(updates)
            updates = self._add_desktop_app_fallbacks(updates)
        self.store.replace_source_updates(source, updates)
        if source == "process" and not updates:
            self._process_empty_started_at = None

    def _has_source_sessions(self, source: str) -> bool:
        return any(session.source == source for session in self.store.sessions())

    def visible_sessions(self) -> List[SessionUpdate]:
        current = self.now()
        sessions = [
            session
            for session in self.store.sessions(now=current)
            if not self.preferences.is_hidden(session.session_id)
            and not self._is_expired_viewed_desktop_idle_session(session, current)
        ]
        full_process_ids = {
            session.process_id
            for session in sessions
            if session.process_id is not None and (session.source != "process" or _is_full_process_desktop_session(session))
        }
        full_desktop_tools = {
            session.tool
            for session in sessions
            if _is_full_desktop_session(session) and session.tool != ToolKind.UNKNOWN
        }
        full_desktop_display_names = {
            session.tool_display_name
            for session in sessions
            if _is_full_desktop_session(session) and session.tool == ToolKind.UNKNOWN and session.tool_display_name
        }
        return [
            session
            for session in sessions
            if not self._is_duplicate_process_session(session, full_process_ids, full_desktop_tools, full_desktop_display_names)
        ]

    def _is_duplicate_process_session(
        self,
        session: SessionUpdate,
        full_process_ids: set,
        full_desktop_tools: set,
        full_desktop_display_names: set,
    ) -> bool:
        if session.source != "process":
            return False
        if _is_full_process_desktop_session(session):
            return False
        if session.process_id in full_process_ids:
            return True
        if session.surface != SurfaceKind.DESKTOP:
            return False
        if session.tool != ToolKind.UNKNOWN and session.tool in full_desktop_tools:
            return True
        return bool(session.tool == ToolKind.UNKNOWN and session.tool_display_name in full_desktop_display_names)

    def _retain_recent_full_process_desktop_sessions(self, updates: List[SessionUpdate]) -> List[SessionUpdate]:
        live_ids = {update.session_id for update in updates}
        live_desktop_process_ids = {
            update.process_id
            for update in updates
            if update.source == "process" and update.surface == SurfaceKind.DESKTOP and update.process_id is not None
        }
        current = self.now()
        retained = [
            session
            for session in self.store.sessions(now=current)
            if session.session_id not in live_ids
            and _is_full_process_desktop_session(session)
            and session.process_id in live_desktop_process_ids
            and not self._is_expired_retained_process_desktop_session(session, current)
        ]
        return updates + retained

    def _add_desktop_app_fallbacks(self, updates: List[SessionUpdate]) -> List[SessionUpdate]:
        existing_fallback_keys = {
            _desktop_app_fallback_key(update)
            for update in updates
            if _is_desktop_app_idle_fallback(update)
        }
        fallbacks: List[SessionUpdate] = []
        current = self.now()
        for update in updates:
            if not _is_full_process_desktop_session(update):
                continue
            fallback = _desktop_app_fallback_for_full_process_session(update, current)
            if fallback is None:
                continue
            key = _desktop_app_fallback_key(fallback)
            if key in existing_fallback_keys:
                continue
            existing_fallback_keys.add(key)
            fallbacks.append(fallback)
        return updates + fallbacks

    def _is_expired_retained_process_desktop_session(self, session: SessionUpdate, now: datetime) -> bool:
        viewed_at = self.store.session_viewed_at(session.session_id)
        retention_started_at = viewed_at if viewed_at is not None and session.status == SessionStatus.IDLE else session.updated_at
        return (now - retention_started_at).total_seconds() >= self.viewed_desktop_idle_visible_seconds

    def _is_expired_viewed_desktop_idle_session(self, session: SessionUpdate, now: datetime) -> bool:
        if _is_desktop_app_idle_fallback(session):
            return False
        if session.source == "process" and not _is_full_process_desktop_session(session):
            return False
        if session.surface != SurfaceKind.DESKTOP:
            return False
        if session.status != SessionStatus.IDLE:
            return False
        viewed_at = self.store.session_viewed_at(session.session_id)
        if viewed_at is None:
            return False
        return (now - viewed_at).total_seconds() >= self.viewed_desktop_idle_visible_seconds

    def sessions_payload(self) -> List[dict]:
        return [self._session_to_payload(session) for session in self.refresh()]

    def execute_action(self, session_id: str, option: str) -> ActionResult:
        session = self._find_session(session_id)
        if session is None:
            return ActionResult(False, "Session not found")
        if session.safe_action is None or not is_low_risk_action(session.safe_action):
            self.store.audit_action(session_id, option, "blocked")
            return ActionResult(False, "Action blocked by low-risk policy")
        result = self.executor.execute(session_id, session.safe_action, option)
        self.store.audit_action(session_id, option, "sent" if result.ok else result.detail)
        return result

    def set_paused(self, paused: bool) -> None:
        self.paused = paused

    def hide_session(self, session_id: str) -> ActionResult:
        if self._find_session(session_id) is None:
            return ActionResult(False, "Session not found")
        self.preferences.hide_session(session_id)
        self.store.audit_action(session_id, "hide-session", "hidden")
        return ActionResult(True, "hidden")

    def unhide_session(self, session_id: str) -> ActionResult:
        if not self.preferences.is_hidden(session_id):
            return ActionResult(False, "Session is not hidden")
        self.preferences.unhide_session(session_id)
        self.store.audit_action(session_id, "unhide-session", "visible")
        return ActionResult(True, "visible")

    def hidden_sessions_payload(self) -> List[dict]:
        hidden = self.preferences.hidden_sessions()
        return [self._session_to_payload(session) for session in self.store.sessions() if session.session_id in hidden]

    def rename_session(self, session_id: str, title: str) -> ActionResult:
        if self._find_session(session_id) is None:
            return ActionResult(False, "Session not found")
        title = title.strip()
        if not title:
            return ActionResult(False, "Title is required")
        self.preferences.rename_session(session_id, title)
        self.store.audit_action(session_id, "rename-session", "renamed")
        return ActionResult(True, "renamed")

    def reset_session_title(self, session_id: str) -> ActionResult:
        if self._find_session(session_id) is None:
            return ActionResult(False, "Session not found")
        self.preferences.reset_session_alias(session_id)
        self.store.audit_action(session_id, "reset-session-title", "reset")
        return ActionResult(True, "reset")

    def focus_session(self, session_id: str) -> FocusResult:
        session = self._find_session(session_id)
        if session is None:
            return FocusResult(False, "Session not found")
        focus_process_id = session.focus_process_id if session.focus_process_id is not None else session.process_id
        result = self.focus_manager.focus(
            session.title,
            window_id=session.window_id,
            process_id=focus_process_id,
            app_name=session.focus_app_name,
            cwd=session.cwd,
        )
        self.store.audit_action(session_id, "focus-window", result.detail)
        if result.ok:
            self.store.mark_session_viewed(session_id, viewed_at=self.now())
        return result

    def mark_session_viewed(self, session_id: str) -> ActionResult:
        if self.store.mark_session_viewed(session_id):
            self.store.audit_action(session_id, "view-session", "viewed")
            return ActionResult(True, "viewed")
        return ActionResult(False, "Session not found")

    def _find_session(self, session_id: str) -> Optional[SessionUpdate]:
        for session in self.store.sessions():
            if session.session_id == session_id:
                return session
        return None

    def _session_to_payload(self, session: SessionUpdate) -> dict:
        payload = session_to_dict(session)
        payload["original_title"] = session.title
        alias = self.preferences.session_alias(session.session_id)
        if alias:
            payload["title"] = alias
        return payload


def session_to_dict(session: SessionUpdate) -> dict:
    monitoring_level = "process_only" if session.source == "process" and not _is_full_process_desktop_session(session) else "full"
    return {
        "session_id": session.session_id,
        "title": session.title,
        "tool": session.tool.value,
        "tool_display_name": session.tool_display_name,
        "surface": session.surface.value,
        "status": session.status.value,
        "summary": clean_terminal_text(session.summary),
        "updated_at": session.updated_at.isoformat(),
        "age_seconds": max(0, int((datetime.now(timezone.utc) - session.updated_at).total_seconds())),
        "safe_action": None
        if session.safe_action is None
        else {
            "kind": session.safe_action.kind.value,
            "options": list(session.safe_action.options),
            "prompt": clean_terminal_text(session.safe_action.prompt),
        },
        "source": session.source,
        "monitoring_level": monitoring_level,
        "window_id": session.window_id,
        "process_id": session.process_id,
        "process_name": session.process_name,
        "focus_process_id": session.focus_process_id,
        "focus_app_name": session.focus_app_name,
        "cwd": session.cwd,
        "view_ack_required": session.view_ack_required,
        "status_source": session.status_source,
        "generated_conversation_path": session.generated_conversation_path,
    }


def _is_full_process_desktop_session(session: SessionUpdate) -> bool:
    return (
        session.source == "process"
        and session.surface == SurfaceKind.DESKTOP
        and session.status_source in {"qoder-log", "workbuddy-db"}
    )


def _is_full_desktop_session(session: SessionUpdate) -> bool:
    if session.surface != SurfaceKind.DESKTOP:
        return False
    if session.source == "process":
        return _is_full_process_desktop_session(session)
    return True


def _is_desktop_app_idle_fallback(session: SessionUpdate) -> bool:
    return (
        session.source == "process"
        and session.surface == SurfaceKind.DESKTOP
        and session.status == SessionStatus.IDLE
        and session.status_source == "desktop-process"
    )


def _desktop_app_fallback_key(session: SessionUpdate):
    if session.process_id is not None:
        return ("process", session.process_id)
    if session.tool != ToolKind.UNKNOWN:
        return ("tool", session.tool.value)
    return ("display", session.tool_display_name or session.title)


def _desktop_app_fallback_for_full_process_session(
    session: SessionUpdate,
    updated_at: datetime,
) -> Optional[SessionUpdate]:
    process_id = session.focus_process_id if session.focus_process_id is not None else session.process_id
    if process_id is None:
        return None
    display_name = session.tool_display_name or session.focus_app_name or session.title.split(" Desktop", 1)[0].strip()
    if not display_name:
        display_name = "AI"
    return SessionUpdate(
        session_id=f"process-{process_id}",
        title=f"{display_name} Desktop",
        tool=session.tool,
        surface=SurfaceKind.DESKTOP,
        status=SessionStatus.IDLE,
        summary=f"{display_name} 桌面 App 正在运行；尚未识别具体对话，先作为空闲入口。",
        updated_at=updated_at,
        source="process",
        process_id=process_id,
        process_name=session.process_name,
        focus_process_id=process_id,
        focus_app_name=session.focus_app_name or display_name,
        status_source="desktop-process",
        tool_display_name=display_name,
    )
