from __future__ import annotations

import platform
import subprocess
from datetime import datetime, timezone
from typing import Callable, Dict, Iterable, List, Optional

from .models import SessionStatus, SessionUpdate


Sender = Callable[[str, str], None]
NOTIFICATION_COMMAND_TIMEOUT_SECONDS = 8


class NotificationManager:
    def __init__(self, sender: Optional[Sender] = None, cooldown_seconds: int = 300, enabled: bool = True):
        self.sender = sender or send_native_notification
        self.cooldown_seconds = cooldown_seconds
        self.enabled = enabled
        self._last_sent: Dict[str, datetime] = {}
        self._last_status: Dict[str, SessionStatus] = {}

    def notify_for_sessions(self, sessions: Iterable[SessionUpdate], now: Optional[datetime] = None) -> None:
        if not self.enabled:
            return
        current = now or datetime.now(timezone.utc)
        sessions = list(sessions)
        needs_action = [
            session
            for session in sessions
            if session.status == SessionStatus.NEEDS_ACTION and self._can_send(session.session_id, current)
        ]
        if len(needs_action) == 1:
            session = needs_action[0]
            self.sender("AI Monitor: 需要处理", f"{session.title}: {session.summary}")
            self._last_sent[session.session_id] = current
        elif len(needs_action) > 1:
            self.sender("AI Monitor: 需要处理", f"{len(needs_action)} 个会话需要处理")
            for session in needs_action:
                self._last_sent[session.session_id] = current
        for session in sessions:
            previous = self._last_status.get(session.session_id)
            if previous == SessionStatus.RUNNING and session.status == SessionStatus.IDLE:
                self.sender("AI Monitor: 已完成", f"{session.title}: {session.summary}")
            elif previous == SessionStatus.RUNNING and session.status == SessionStatus.STUCK:
                self.sender("AI Monitor: 疑似卡住", f"{session.title}: {session.summary}")
            self._last_status[session.session_id] = session.status

    def _can_send(self, session_id: str, now: datetime) -> bool:
        last_sent = self._last_sent.get(session_id)
        if last_sent is None:
            return True
        return (now - last_sent).total_seconds() >= self.cooldown_seconds


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
