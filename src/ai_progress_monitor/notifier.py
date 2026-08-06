from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Callable, Dict, Iterable, List, Optional, Set

from .models import SessionStatus, SessionUpdate, session_instance_key


Sender = Callable[[str, str], None]
NOTIFICATION_COMMAND_TIMEOUT_SECONDS = 8
NOTIFICATION_STATE_VERSION = 1
NOTIFICATION_STATE_MAX_ENTRIES = 512
NOTIFICATION_STATE_RETENTION_SECONDS = 7 * 24 * 60 * 60
NOTIFICATION_STATE_SEEN_REFRESH_SECONDS = 60 * 60


class NotificationManager:
    def __init__(
        self,
        sender: Optional[Sender] = None,
        cooldown_seconds: int = 300,
        enabled: bool = True,
        state_path: Optional[Path] = None,
    ):
        self.sender = sender or send_native_notification
        self.cooldown_seconds = cooldown_seconds
        self.enabled = enabled
        self.state_path = Path(state_path) if state_path is not None else None
        self._last_sent: Dict[str, datetime] = {}
        self._last_status: Dict[str, SessionStatus] = {}
        self._last_seen: Dict[str, datetime] = {}
        self._suppressed_needs_action: Set[str] = set()
        self._state_lock = RLock()
        self._persisted_snapshot: Optional[str] = None
        self._load_state()

    def set_enabled(self, enabled: bool, sessions: Optional[Iterable[SessionUpdate]] = None) -> None:
        with self._state_lock:
            enabled = bool(enabled)
            if sessions is not None and (not enabled or not self.enabled):
                self._record_suppressed_state(list(sessions), datetime.now(timezone.utc))
            self.enabled = enabled
            self._persist_state()

    def notify_for_sessions(self, sessions: Iterable[SessionUpdate], now: Optional[datetime] = None) -> None:
        with self._state_lock:
            sessions = list(sessions)
            current = now or datetime.now(timezone.utc)
            if not self.enabled:
                self._record_suppressed_state(sessions, current)
                self._persist_state()
                return
            current_needs_action_keys = {
                _notification_state_key(session)
                for session in sessions
                if session.status == SessionStatus.NEEDS_ACTION
            }
            self._suppressed_needs_action.intersection_update(current_needs_action_keys)
            needs_action = []
            for session in sessions:
                state_key = _notification_state_key(session)
                if session.status != SessionStatus.NEEDS_ACTION:
                    continue
                if self._last_status.get(state_key) == SessionStatus.NEEDS_ACTION:
                    continue
                if state_key in self._suppressed_needs_action or not self._can_send(state_key, current):
                    continue
                needs_action.append(session)
            if len(needs_action) == 1:
                session = needs_action[0]
                self.sender("AI Monitor: 需要处理", f"{session.title}: {session.summary}")
                self._last_sent[_notification_state_key(session)] = current
            elif len(needs_action) > 1:
                self.sender("AI Monitor: 需要处理", f"{len(needs_action)} 个会话需要处理")
                for session in needs_action:
                    self._last_sent[_notification_state_key(session)] = current
            for session in sessions:
                state_key = _notification_state_key(session)
                previous = self._last_status.get(state_key)
                if previous == SessionStatus.RUNNING and session.status == SessionStatus.IDLE:
                    self.sender("AI Monitor: 已完成", f"{session.title}: {session.summary}")
                elif previous == SessionStatus.RUNNING and session.status == SessionStatus.STUCK:
                    self.sender("AI Monitor: 疑似卡住", f"{session.title}: {session.summary}")
                self._last_status[state_key] = session.status
            self._record_seen_sessions(sessions, current)
            self._prune_state(current)
            self._persist_state()

    def _record_suppressed_state(self, sessions: Iterable[SessionUpdate], current: datetime) -> None:
        sessions = list(sessions)
        suppressed = set()
        for session in sessions:
            state_key = _notification_state_key(session)
            self._last_status[state_key] = session.status
            if session.status == SessionStatus.NEEDS_ACTION:
                suppressed.add(state_key)
        self._suppressed_needs_action = suppressed
        self._record_seen_sessions(sessions, current)
        self._prune_state(current)

    def _can_send(self, instance_key: str, now: datetime) -> bool:
        last_sent = self._last_sent.get(instance_key)
        if last_sent is None:
            return True
        return (now - last_sent).total_seconds() >= self.cooldown_seconds

    def _record_seen_sessions(self, sessions: Iterable[SessionUpdate], current: datetime) -> None:
        for session in sessions:
            state_key = _notification_state_key(session)
            last_seen = self._last_seen.get(state_key)
            if (
                last_seen is None
                or current < last_seen
                or (current - last_seen).total_seconds() >= NOTIFICATION_STATE_SEEN_REFRESH_SECONDS
            ):
                self._last_seen[state_key] = current

    def _prune_state(self, current: datetime) -> None:
        stale_keys = {
            state_key
            for state_key, last_seen in self._last_seen.items()
            if current >= last_seen
            and (current - last_seen).total_seconds() > NOTIFICATION_STATE_RETENTION_SECONDS
        }
        remaining_keys = set(self._last_seen) - stale_keys
        if len(remaining_keys) > NOTIFICATION_STATE_MAX_ENTRIES:
            newest_keys = sorted(
                remaining_keys,
                key=lambda state_key: self._last_seen[state_key],
                reverse=True,
            )[:NOTIFICATION_STATE_MAX_ENTRIES]
            stale_keys.update(remaining_keys - set(newest_keys))
        for state_key in stale_keys:
            self._last_sent.pop(state_key, None)
            self._last_status.pop(state_key, None)
            self._last_seen.pop(state_key, None)
            self._suppressed_needs_action.discard(state_key)

    def _load_state(self) -> None:
        if self.state_path is None:
            return
        try:
            if not self.state_path.exists():
                return
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return
        if not isinstance(payload, dict) or payload.get("version") != NOTIFICATION_STATE_VERSION:
            return
        entries = payload.get("entries")
        if not isinstance(entries, dict):
            return
        for state_key, entry in entries.items():
            if not _valid_notification_state_key(state_key) or not isinstance(entry, dict):
                continue
            last_seen = _parse_state_datetime(entry.get("last_seen_at"))
            if last_seen is None:
                continue
            self._last_seen[state_key] = last_seen
            try:
                status = SessionStatus(entry.get("last_status"))
            except (TypeError, ValueError):
                status = None
            if status is not None:
                self._last_status[state_key] = status
            last_sent = _parse_state_datetime(entry.get("last_sent_at"))
            if last_sent is not None:
                self._last_sent[state_key] = last_sent
        suppressed = payload.get("suppressed_needs_action")
        if isinstance(suppressed, list):
            self._suppressed_needs_action = {
                state_key
                for state_key in suppressed
                if _valid_notification_state_key(state_key)
                and self._last_status.get(state_key) == SessionStatus.NEEDS_ACTION
            }
        self._persisted_snapshot = self._serialized_state()

    def _persist_state(self) -> None:
        if self.state_path is None:
            return
        serialized = self._serialized_state()
        if serialized == self._persisted_snapshot:
            return
        temp_path = self.state_path.with_name(f".{self.state_path.name}.{os.getpid()}.tmp")
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            temp_path.write_text(serialized, encoding="utf-8")
            os.chmod(temp_path, 0o600)
            temp_path.replace(self.state_path)
        except OSError:
            try:
                temp_path.unlink()
            except OSError:
                pass
            return
        self._persisted_snapshot = serialized

    def _serialized_state(self) -> str:
        state_keys = set(self._last_seen) | set(self._last_status) | set(self._last_sent)
        entries = {}
        for state_key in sorted(state_keys):
            entry = {}
            status = self._last_status.get(state_key)
            if status is not None:
                entry["last_status"] = status.value
            last_sent = self._last_sent.get(state_key)
            if last_sent is not None:
                entry["last_sent_at"] = last_sent.isoformat()
            last_seen = self._last_seen.get(state_key)
            if last_seen is not None:
                entry["last_seen_at"] = last_seen.isoformat()
            entries[state_key] = entry
        payload = {
            "version": NOTIFICATION_STATE_VERSION,
            "entries": entries,
            "suppressed_needs_action": sorted(self._suppressed_needs_action),
        }
        return json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n"


def _notification_state_key(session: SessionUpdate) -> str:
    identity = session_instance_key(session).encode("utf-8", errors="replace")
    return hashlib.sha256(identity).hexdigest()


def _valid_notification_state_key(value) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _parse_state_datetime(value) -> Optional[datetime]:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def send_native_notification(title: str, message: str) -> None:
    command = build_notification_command(title, message)
    if command is None:
        return
    try:
        subprocess.run(command, check=False, capture_output=True, text=True, timeout=NOTIFICATION_COMMAND_TIMEOUT_SECONDS)
    except (OSError, subprocess.TimeoutExpired):
        return


def build_notification_command(title: str, message: str) -> Optional[List[str]]:
    system = platform.system().lower()
    if system == "darwin":
        return build_macos_notification(title, message)
    if system == "windows":
        return build_windows_notification(title, message)
    return None


def build_macos_notification(title: str, message: str) -> List[str]:
    script = f'display notification "{_escape_applescript(message)}" with title "{_escape_applescript(title)}"'
    return ["osascript", "-e", script]


def build_windows_notification(title: str, message: str) -> List[str]:
    escaped_title = _escape_powershell(title)
    escaped_message = _escape_powershell(message)
    script = (
        "if (Get-Command New-BurntToastNotification -ErrorAction SilentlyContinue) "
        f"{{ New-BurntToastNotification -Text '{escaped_title}', '{escaped_message}' }} "
        "else { "
        "Add-Type -AssemblyName System.Windows.Forms; "
        "Add-Type -AssemblyName System.Drawing; "
        "$notify = New-Object System.Windows.Forms.NotifyIcon; "
        "$notify.Icon = [System.Drawing.SystemIcons]::Information; "
        "$notify.Visible = $true; "
        f"$notify.BalloonTipTitle = '{escaped_title}'; "
        f"$notify.BalloonTipText = '{escaped_message}'; "
        "$notify.ShowBalloonTip(5000); "
        "Start-Sleep -Seconds 6; "
        "$notify.Dispose(); "
        "}"
    )
    return ["powershell", "-NoProfile", "-Command", script]


def _escape_applescript(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _escape_powershell(value: str) -> str:
    return value.replace("'", "''")
