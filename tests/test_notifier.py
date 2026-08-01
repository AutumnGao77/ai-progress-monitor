import threading
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

    def test_pid_reuse_does_not_emit_completion_for_new_process_generation(self):
        sent = []
        manager = NotificationManager(sender=lambda title, message: sent.append((title, message)))
        now = datetime(2026, 7, 31, 5, 25, tzinfo=timezone.utc)
        old_started_at = now - timedelta(days=1)
        new_started_at = now - timedelta(hours=1)

        manager.notify_for_sessions(
            [make_process_session(SessionStatus.RUNNING, now, old_started_at)],
            now=now,
        )
        manager.notify_for_sessions(
            [make_process_session(SessionStatus.IDLE, now + timedelta(seconds=5), new_started_at)],
            now=now + timedelta(seconds=5),
        )

        self.assertEqual(sent, [])

    def test_pid_reuse_does_not_inherit_needs_action_notification_cooldown(self):
        sent = []
        manager = NotificationManager(
            sender=lambda title, message: sent.append((title, message)),
            cooldown_seconds=60,
        )
        now = datetime(2026, 7, 31, 5, 25, tzinfo=timezone.utc)
        old_started_at = now - timedelta(days=1)
        new_started_at = now - timedelta(hours=1)

        manager.notify_for_sessions(
            [make_process_session(SessionStatus.NEEDS_ACTION, now, old_started_at)],
            now=now,
        )
        manager.notify_for_sessions(
            [make_process_session(SessionStatus.NEEDS_ACTION, now + timedelta(seconds=5), new_started_at)],
            now=now + timedelta(seconds=5),
        )

        self.assertEqual(len(sent), 2)

    def test_disabled_notifications_track_state_without_replaying_old_events(self):
        sent = []
        manager = NotificationManager(
            sender=lambda title, message: sent.append((title, message)),
            cooldown_seconds=60,
            enabled=False,
        )
        now = datetime(2026, 6, 30, tzinfo=timezone.utc)
        running = [
            make_session("needs", SessionStatus.NEEDS_ACTION, now),
            make_session("completed", SessionStatus.RUNNING, now),
            make_session("stuck", SessionStatus.RUNNING, now),
        ]
        changed_while_disabled = [
            make_session("needs", SessionStatus.NEEDS_ACTION, now + timedelta(seconds=5)),
            make_session("completed", SessionStatus.IDLE, now + timedelta(seconds=5)),
            make_session("stuck", SessionStatus.STUCK, now + timedelta(seconds=5)),
        ]

        manager.notify_for_sessions(running, now=now)
        manager.notify_for_sessions(changed_while_disabled, now=now + timedelta(seconds=5))
        manager.set_enabled(True, sessions=changed_while_disabled)
        manager.notify_for_sessions(changed_while_disabled, now=now + timedelta(seconds=6))

        self.assertEqual(sent, [])

        manager.notify_for_sessions(
            changed_while_disabled + [make_session("new", SessionStatus.NEEDS_ACTION, now + timedelta(seconds=7))],
            now=now + timedelta(seconds=7),
        )
        self.assertEqual(len(sent), 1)
        self.assertIn("Claude Code - task", sent[0][1])

    def test_suppressed_needs_action_can_notify_after_leaving_and_reentering(self):
        sent = []
        manager = NotificationManager(sender=lambda title, message: sent.append((title, message)), enabled=False)
        now = datetime(2026, 6, 30, tzinfo=timezone.utc)

        manager.notify_for_sessions([make_session("s1", SessionStatus.NEEDS_ACTION, now)], now=now)
        manager.set_enabled(True, sessions=[make_session("s1", SessionStatus.NEEDS_ACTION, now)])
        manager.notify_for_sessions([make_session("s1", SessionStatus.RUNNING, now + timedelta(seconds=1))], now=now + timedelta(seconds=1))
        manager.notify_for_sessions([make_session("s1", SessionStatus.NEEDS_ACTION, now + timedelta(seconds=2))], now=now + timedelta(seconds=2))

        self.assertEqual(len(sent), 1)
        self.assertIn("需要处理", sent[0][0])

    def test_disabling_waits_for_in_flight_delivery_before_confirming(self):
        sender_started = threading.Event()
        release_sender = threading.Event()
        disabled = threading.Event()
        now = datetime(2026, 6, 30, tzinfo=timezone.utc)

        def sender(_title, _message):
            sender_started.set()
            release_sender.wait(timeout=2)

        manager = NotificationManager(sender=sender)
        notify_thread = threading.Thread(
            target=manager.notify_for_sessions,
            args=([make_session("s1", SessionStatus.NEEDS_ACTION, now)],),
            kwargs={"now": now},
        )
        notify_thread.start()
        self.assertTrue(sender_started.wait(timeout=1))

        def disable():
            manager.set_enabled(False, sessions=[make_session("s1", SessionStatus.NEEDS_ACTION, now)])
            disabled.set()

        disable_thread = threading.Thread(target=disable)
        disable_thread.start()
        returned_while_sender_was_blocked = disabled.wait(timeout=0.1)
        release_sender.set()
        notify_thread.join(timeout=2)
        disable_thread.join(timeout=2)

        self.assertFalse(returned_while_sender_was_blocked)
        self.assertTrue(disabled.is_set())
        self.assertFalse(manager.enabled)


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


def make_process_session(
    status: SessionStatus,
    updated_at: datetime,
    process_started_at: datetime,
) -> SessionUpdate:
    return SessionUpdate(
        session_id="process-24645",
        title="Claude Code CLI - task",
        tool=ToolKind.CLAUDE_CODE,
        surface=SurfaceKind.TERMINAL,
        status=status,
        summary="Claude Code state",
        updated_at=updated_at,
        source="process",
        process_id=24645,
        process_started_at=process_started_at,
    )


if __name__ == "__main__":
    unittest.main()
