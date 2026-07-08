import unittest
from datetime import datetime, timedelta, timezone

from ai_progress_monitor.models import SessionStatus, SessionUpdate, SurfaceKind, ToolKind
from ai_progress_monitor.notifier import (
    NOTIFICATION_COMMAND_TIMEOUT_SECONDS,
    NotificationManager,
    build_macos_notification,
    build_windows_notification,
)


class NotifierTests(unittest.TestCase):
    def test_builds_macos_notification_command(self):
        command = build_macos_notification("Needs action", "Claude Code")

        self.assertEqual(command[0], "osascript")
        self.assertIn("display notification", command[-1])
        self.assertIn("Needs action", command[-1])

    def test_builds_windows_notification_command(self):
        command = build_windows_notification("Needs action", "Codex")

        self.assertEqual(command[0], "powershell")
        self.assertIn("New-BurntToastNotification", command[-1])
        self.assertIn("System.Windows.Forms", command[-1])
        self.assertIn("Add-Type -AssemblyName System.Drawing", command[-1])
        self.assertIn("ShowBalloonTip", command[-1])

    def test_notification_command_timeout_covers_windows_balloon_fallback(self):
        command = build_windows_notification("Needs action", "Codex")

        self.assertIn("Start-Sleep -Seconds 6", command[-1])
        self.assertGreaterEqual(NOTIFICATION_COMMAND_TIMEOUT_SECONDS, 7)

    def test_notifies_needs_action_once_during_cooldown(self):
        sent = []
        manager = NotificationManager(sender=lambda title, message: sent.append((title, message)), cooldown_seconds=60)
        now = datetime(2026, 6, 30, tzinfo=timezone.utc)
        session = make_session("s1", SessionStatus.NEEDS_ACTION, now)

        manager.notify_for_sessions([session], now=now)
        manager.notify_for_sessions([session], now=now + timedelta(seconds=30))

        self.assertEqual(len(sent), 1)

    def test_notifies_needs_action_on_first_observation(self):
        sent = []
        manager = NotificationManager(sender=lambda title, message: sent.append((title, message)), cooldown_seconds=60)
        now = datetime(2026, 6, 30, tzinfo=timezone.utc)

        manager.notify_for_sessions([make_session("s1", SessionStatus.NEEDS_ACTION, now)], now=now)

        self.assertEqual(len(sent), 1)
        self.assertIn("需要处理", sent[0][0])

    def test_notifies_again_after_cooldown(self):
        sent = []
        manager = NotificationManager(sender=lambda title, message: sent.append((title, message)), cooldown_seconds=60)
        now = datetime(2026, 6, 30, tzinfo=timezone.utc)
        session = make_session("s1", SessionStatus.NEEDS_ACTION, now)

        manager.notify_for_sessions([session], now=now)
        manager.notify_for_sessions([session], now=now + timedelta(seconds=61))

        self.assertEqual(len(sent), 2)

    def test_coalesces_multiple_needs_action_sessions_into_one_notification(self):
        sent = []
        manager = NotificationManager(sender=lambda title, message: sent.append((title, message)), cooldown_seconds=60)
        now = datetime(2026, 6, 30, tzinfo=timezone.utc)
        sessions = [
            make_session("s1", SessionStatus.NEEDS_ACTION, now),
            make_session("s2", SessionStatus.NEEDS_ACTION, now),
            make_session("s3", SessionStatus.NEEDS_ACTION, now),
        ]

        manager.notify_for_sessions(sessions, now=now)
        manager.notify_for_sessions(sessions, now=now + timedelta(seconds=30))

        self.assertEqual(len(sent), 1)
        self.assertIn("3 个会话", sent[0][1])

    def test_does_not_notify_running_session(self):
        sent = []
        manager = NotificationManager(sender=lambda title, message: sent.append((title, message)))

        manager.notify_for_sessions([make_session("s1", SessionStatus.RUNNING, datetime.now(timezone.utc))])

        self.assertEqual(sent, [])

    def test_lightly_notifies_when_running_session_becomes_idle(self):
        sent = []
        manager = NotificationManager(sender=lambda title, message: sent.append((title, message)))
        now = datetime(2026, 6, 30, tzinfo=timezone.utc)

        manager.notify_for_sessions([make_session("s1", SessionStatus.RUNNING, now)], now=now)
        manager.notify_for_sessions([make_session("s1", SessionStatus.IDLE, now + timedelta(seconds=5))], now=now + timedelta(seconds=5))
        manager.notify_for_sessions([make_session("s1", SessionStatus.IDLE, now + timedelta(seconds=10))], now=now + timedelta(seconds=10))

        self.assertEqual(len(sent), 1)
        self.assertIn("已完成", sent[0][0])

    def test_does_not_notify_idle_session_on_first_seen(self):
        sent = []
        manager = NotificationManager(sender=lambda title, message: sent.append((title, message)))

        manager.notify_for_sessions([make_session("s1", SessionStatus.IDLE, datetime.now(timezone.utc))])

        self.assertEqual(sent, [])

    def test_lightly_notifies_when_running_session_becomes_stuck(self):
        sent = []
        manager = NotificationManager(sender=lambda title, message: sent.append((title, message)))
        now = datetime(2026, 6, 30, tzinfo=timezone.utc)

        manager.notify_for_sessions([make_session("s1", SessionStatus.RUNNING, now)], now=now)
        manager.notify_for_sessions([make_session("s1", SessionStatus.STUCK, now + timedelta(seconds=301))], now=now + timedelta(seconds=301))
        manager.notify_for_sessions([make_session("s1", SessionStatus.STUCK, now + timedelta(seconds=302))], now=now + timedelta(seconds=302))

        self.assertEqual(len(sent), 1)
        self.assertIn("疑似卡住", sent[0][0])

    def test_does_not_notify_stuck_session_on_first_seen(self):
        sent = []
        manager = NotificationManager(sender=lambda title, message: sent.append((title, message)))

        manager.notify_for_sessions([make_session("s1", SessionStatus.STUCK, datetime.now(timezone.utc))])

        self.assertEqual(sent, [])


def make_session(session_id: str, status: SessionStatus, updated_at: datetime) -> SessionUpdate:
    return SessionUpdate(
        session_id=session_id,
        title="Claude Code - task",
        tool=ToolKind.CLAUDE_CODE,
        surface=SurfaceKind.TERMINAL,
        status=status,
        summary="Do you want to continue?",
        updated_at=updated_at,
    )


if __name__ == "__main__":
    unittest.main()
