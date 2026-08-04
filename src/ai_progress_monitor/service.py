from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from threading import Event, Lock, RLock, get_ident
import time
from typing import Callable, Dict, Iterable, List, Optional, Tuple

from .actions import ActionExecutor, is_low_risk_action
from .models import ActionResult, SessionStatus, SessionUpdate, SurfaceKind, ToolKind, session_instance_key
from .notifier import NotificationManager
from .preferences import MonitorPreferences
from .store import SessionStore
from .terminal_bridge import clean_terminal_text
from .window_focus import (
    FocusResult,
    WindowFocusManager,
    is_project_editor_app,
    project_window_title_match_score,
)


VIEWED_DESKTOP_IDLE_VISIBLE_SECONDS = 15 * 60
NATIVE_PROJECT_WINDOW_INVENTORY_TTL_SECONDS = 8.0
FULL_PROCESS_DESKTOP_STATUS_SOURCES = frozenset(
    {
        "qoder-log",
        "workbuddy-db",
        "workbuddy-log",
    }
)
ProjectWindowMatcher = Callable[[int, str, str], Optional[Tuple[bool, Optional[str]]]]
NativeProjectWindowRows = Tuple[Tuple[Optional[str], str], ...]
NativeProjectWindowInventory = Dict[int, Optional[NativeProjectWindowRows]]


class _RefreshFlight:
    def __init__(self):
        self.owner_thread_id = get_ident()
        self.done = Event()
        self.sessions: Tuple[SessionUpdate, ...] = ()
        self.error: Optional[BaseException] = None


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
        notifications_forced_off: bool = False,
        native_window_inventory_ttl_seconds: float = NATIVE_PROJECT_WINDOW_INVENTORY_TTL_SECONDS,
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
        self._notifications_forced_off = bool(notifications_forced_off)
        self.native_window_inventory_ttl_seconds = native_window_inventory_ttl_seconds
        self._native_project_window_inventory: Optional[NativeProjectWindowInventory] = None
        self._native_project_window_inventory_updated_at: Optional[float] = None
        self._process_empty_started_at: Optional[float] = None
        self._refresh_flight_lock = Lock()
        self._refresh_flight: Optional[_RefreshFlight] = None
        self._notification_lock = RLock()
        self._preference_identity_lock = RLock()
        self._checked_preference_instance_keys: set[str] = set()
        with self._notification_lock:
            self._sync_notifications_enabled([])

    def refresh(self) -> List[SessionUpdate]:
        with self._refresh_flight_lock:
            flight = self._refresh_flight
            if flight is None:
                flight = _RefreshFlight()
                self._refresh_flight = flight
                is_leader = True
            else:
                is_leader = False

        if not is_leader:
            if flight.owner_thread_id == get_ident():
                raise RuntimeError("MonitorService.refresh() cannot be called recursively")
            flight.done.wait()
            if flight.error is not None:
                raise RuntimeError("Concurrent refresh failed") from flight.error
            return list(flight.sessions)

        try:
            sessions = self._refresh_once()
        except BaseException as error:
            with self._refresh_flight_lock:
                flight.error = error
                if self._refresh_flight is flight:
                    self._refresh_flight = None
                flight.done.set()
            raise

        with self._refresh_flight_lock:
            flight.sessions = tuple(sessions)
            if self._refresh_flight is flight:
                self._refresh_flight = None
            flight.done.set()
        return sessions

    def _refresh_once(self) -> List[SessionUpdate]:
        if not self.paused:
            poll_results = self._poll_sources()
            project_window_matcher = self._native_project_window_matcher()
            if project_window_matcher is None:
                project_window_matcher = self._project_window_matcher(poll_results)
            desktop_process_updates = self._desktop_process_updates_for_poll(poll_results)
            for source, updates in poll_results:
                if updates is None:
                    continue
                volatile_source = getattr(source, "volatile_source", None)
                if volatile_source:
                    poll_had_updates = bool(updates)
                    if volatile_source == "process":
                        updates = self._reconcile_project_editor_sessions(updates, project_window_matcher)
                    self._replace_volatile_source_updates(
                        str(volatile_source),
                        updates,
                        poll_had_updates=poll_had_updates,
                        desktop_process_updates=desktop_process_updates,
                    )
                else:
                    self.store.apply_updates(updates)
        sessions = self.visible_sessions()
        if self.notifier is not None:
            with self._notification_lock:
                self._sync_notifications_enabled(sessions)
                self.notifier.notify_for_sessions(sessions)
        return sessions

    def notifications_enabled(self) -> bool:
        return not self._notifications_forced_off and self.preferences.notifications_enabled()

    def notifications_locked(self) -> bool:
        return self._notifications_forced_off

    def set_notifications_enabled(self, enabled: bool) -> bool:
        with self._notification_lock:
            if self.notifications_locked():
                return False
            changed = self.preferences.set_notifications_enabled(enabled)
            if changed:
                self._sync_notifications_enabled(self.visible_sessions())
            return changed

    def _sync_notifications_enabled(self, sessions: Iterable[SessionUpdate]) -> None:
        if self.notifier is not None:
            self.notifier.set_enabled(self.notifications_enabled(), sessions=sessions)

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

    @staticmethod
    def _project_window_matcher(
        poll_results: List[tuple[object, Optional[List[SessionUpdate]]]],
    ) -> Optional[ProjectWindowMatcher]:
        for source, updates in poll_results:
            matcher = getattr(source, "project_window_match", None)
            if updates is not None and callable(matcher):
                return matcher
        return None

    def set_native_project_window_inventory(self, applications) -> bool:
        if not isinstance(applications, list):
            return False
        parsed: NativeProjectWindowInventory = {}
        for application in applications:
            if not isinstance(application, dict) or set(application) != {"process_id", "available", "windows"}:
                return False
            process_id = application["process_id"]
            available = application["available"]
            windows = application["windows"]
            if isinstance(process_id, bool) or not isinstance(process_id, int) or process_id <= 0:
                return False
            if not isinstance(available, bool) or not isinstance(windows, list) or process_id in parsed:
                return False
            if not available:
                if windows:
                    return False
                parsed[process_id] = None
                continue
            parsed_windows = []
            for window in windows:
                if not isinstance(window, dict) or set(window) != {"window_id", "title"}:
                    return False
                window_id = window["window_id"]
                title = window["title"]
                if not isinstance(window_id, str) or not isinstance(title, str):
                    return False
                parsed_windows.append((window_id.strip() or None, title.strip()))
            parsed[process_id] = tuple(parsed_windows)
        self._native_project_window_inventory = parsed
        self._native_project_window_inventory_updated_at = self.clock()
        return True

    def clear_native_project_window_inventory(self) -> None:
        self._native_project_window_inventory = None
        self._native_project_window_inventory_updated_at = None

    def _native_project_window_matcher(self) -> Optional[ProjectWindowMatcher]:
        inventory = self._native_project_window_inventory
        updated_at = self._native_project_window_inventory_updated_at
        if inventory is None or updated_at is None:
            return None
        age = self.clock() - updated_at
        if age < 0 or age > self.native_window_inventory_ttl_seconds:
            return None

        def match(process_id: int, app_name: str, cwd: str) -> Optional[Tuple[bool, Optional[str]]]:
            if process_id not in inventory:
                return False, None
            windows = inventory[process_id]
            if windows is None:
                return None
            folder_name = Path(cwd).name.strip().casefold()
            if not folder_name or not app_name.strip():
                return None
            best_match: Optional[Tuple[Optional[str], str]] = None
            best_score = 0
            for window_id, title in windows:
                score = project_window_title_match_score(folder_name, title)
                if score > best_score:
                    best_match = (window_id, title)
                    best_score = score
            if best_match is not None:
                return True, best_match[0]
            return False, None

        return match

    @staticmethod
    def _reconcile_project_editor_sessions(
        updates: List[SessionUpdate],
        matcher: Optional[ProjectWindowMatcher],
    ) -> List[SessionUpdate]:
        if matcher is None:
            return updates
        reconciled: List[SessionUpdate] = []
        for update in updates:
            if (
                update.surface != SurfaceKind.TERMINAL
                or not update.focus_app_name
                or not is_project_editor_app(update.focus_app_name)
                or update.focus_process_id is None
                or not update.cwd
            ):
                reconciled.append(update)
                continue
            match = matcher(update.focus_process_id, update.focus_app_name, update.cwd)
            if match is None:
                reconciled.append(update)
                continue
            matched, window_id = match
            if not matched:
                continue
            reconciled.append(replace(update, window_id=window_id) if window_id else update)
        return reconciled

    def _replace_volatile_source_updates(
        self,
        source: str,
        updates: Optional[List[SessionUpdate]],
        poll_had_updates: bool = False,
        desktop_process_updates: Optional[List[SessionUpdate]] = None,
    ) -> None:
        if updates is None:
            return
        if source == "process" and not updates and not poll_had_updates and self._has_source_sessions("process"):
            now = self.clock()
            if self._process_empty_started_at is None:
                self._process_empty_started_at = now
                return
            if now - self._process_empty_started_at < self.process_empty_grace_seconds:
                return
        if source == "process" and (updates or poll_had_updates):
            self._process_empty_started_at = None
        if source == "process":
            updates = self._retain_recent_full_process_desktop_sessions(updates)
            updates = self._add_desktop_app_fallbacks(updates)
        elif source == "chatgpt-session":
            updates = self._retain_viewed_chatgpt_sessions(updates, desktop_process_updates)
        self.store.replace_source_updates(source, updates)
        if source == "process" and not updates:
            self._process_empty_started_at = None

    def _desktop_process_updates_for_poll(
        self,
        poll_results: List[tuple[object, Optional[List[SessionUpdate]]]],
    ) -> Optional[List[SessionUpdate]]:
        for source, updates in poll_results:
            if getattr(source, "volatile_source", None) != "process":
                continue
            if updates is None:
                return None
            if updates:
                return [update for update in updates if update.surface == SurfaceKind.DESKTOP]
            if not self._has_source_sessions("process"):
                return []
            empty_started_at = self._process_empty_started_at
            if empty_started_at is None or self.clock() - empty_started_at < self.process_empty_grace_seconds:
                return [
                    session
                    for session in self.store.sessions(now=self.now())
                    if session.source == "process" and session.surface == SurfaceKind.DESKTOP
                ]
            return []
        return None

    def _retain_viewed_chatgpt_sessions(
        self,
        updates: List[SessionUpdate],
        desktop_process_updates: Optional[List[SessionUpdate]],
    ) -> List[SessionUpdate]:
        if desktop_process_updates is not None and not any(
            update.tool == ToolKind.CHATGPT for update in desktop_process_updates
        ):
            return updates
        live_ids = {update.session_id for update in updates}
        current = self.now()
        retained = [
            session
            for session in self.store.sessions(now=current)
            if session.source == "chatgpt-session"
            and session.session_id not in live_ids
            and session.surface == SurfaceKind.DESKTOP
            and session.status == SessionStatus.IDLE
            and self.store.session_viewed_at(session.session_id) is not None
            and not self._is_expired_viewed_desktop_idle_session(session, current)
        ]
        return updates + retained

    def _has_source_sessions(self, source: str) -> bool:
        return any(session.source == source for session in self.store.sessions())

    def visible_sessions(self) -> List[SessionUpdate]:
        current = self.now()
        sessions = [
            session
            for session in self.store.sessions(now=current)
            if not self.preferences.is_hidden(self._session_preference_key(session))
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
        session = self._find_session(session_id)
        if session is None:
            return ActionResult(False, "Session not found")
        self.preferences.hide_session(self._session_preference_key(session))
        self.store.audit_action(session_id, "hide-session", "hidden")
        return ActionResult(True, "hidden")

    def unhide_session(self, session_id: str) -> ActionResult:
        session = self._find_session(session_id)
        preference_key = self._session_preference_key(session) if session is not None else session_id
        if not self.preferences.is_hidden(preference_key):
            return ActionResult(False, "Session is not hidden")
        self.preferences.unhide_session(preference_key)
        self.store.audit_action(session_id, "unhide-session", "visible")
        return ActionResult(True, "visible")

    def hidden_sessions_payload(self) -> List[dict]:
        sessions_with_preference_keys = [
            (session, self._session_preference_key(session))
            for session in self.store.sessions()
        ]
        hidden = self.preferences.hidden_sessions()
        return [
            self._session_to_payload(session)
            for session, preference_key in sessions_with_preference_keys
            if preference_key in hidden
        ]

    def rename_session(self, session_id: str, title: str) -> ActionResult:
        session = self._find_session(session_id)
        if session is None:
            return ActionResult(False, "Session not found")
        title = title.strip()
        if not title:
            return ActionResult(False, "Title is required")
        self.preferences.rename_session(self._session_preference_key(session), title)
        self.store.audit_action(session_id, "rename-session", "renamed")
        return ActionResult(True, "renamed")

    def reset_session_title(self, session_id: str) -> ActionResult:
        session = self._find_session(session_id)
        if session is None:
            return ActionResult(False, "Session not found")
        self.preferences.reset_session_alias(self._session_preference_key(session))
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
        alias = self.preferences.session_alias(self._session_preference_key(session))
        if alias:
            payload["title"] = alias
        return payload

    def _session_preference_key(self, session: SessionUpdate) -> str:
        instance_key = session_instance_key(session)
        if instance_key == session.session_id:
            return instance_key
        with self._preference_identity_lock:
            if instance_key not in self._checked_preference_instance_keys:
                migrate = getattr(self.preferences, "migrate_session_identity", None)
                if callable(migrate):
                    try:
                        migrate(session.session_id, instance_key)
                    except OSError:
                        return session.session_id
                self._checked_preference_instance_keys.add(instance_key)
        return instance_key


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
        and session.status_source in FULL_PROCESS_DESKTOP_STATUS_SOURCES
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
