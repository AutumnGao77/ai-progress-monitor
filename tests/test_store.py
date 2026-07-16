import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ai_progress_monitor.models import SessionStatus, SessionUpdate, SurfaceKind, ToolKind
from ai_progress_monitor.store import SessionStore


class SessionStoreTests(unittest.TestCase):
    def test_keeps_latest_update_for_same_session(self):
        store = SessionStore(stuck_after_seconds=60)
        old = SessionUpdate(
            session_id="s1",
            title="Old",
            tool=ToolKind.CODEX,
            surface=SurfaceKind.TERMINAL,
            status=SessionStatus.RUNNING,
            summary="old",
            updated_at=datetime(2026, 6, 30, 1, 0, tzinfo=timezone.utc),
        )
        new = SessionUpdate(
            session_id="s1",
            title="New",
            tool=ToolKind.CODEX,
            surface=SurfaceKind.TERMINAL,
            status=SessionStatus.NEEDS_ACTION,
            summary="new",
            updated_at=datetime(2026, 6, 30, 1, 1, tzinfo=timezone.utc),
        )

        store.apply_updates([old])
        store.apply_updates([new])

        self.assertEqual(store.sessions()[0].title, "New")
        self.assertEqual(store.sessions()[0].status, SessionStatus.NEEDS_ACTION)

    def test_orders_needs_action_before_running(self):
        store = SessionStore(stuck_after_seconds=60)
        now = datetime.now(timezone.utc)
        store.apply_updates(
            [
                SessionUpdate("run", "Running", ToolKind.CODEX, SurfaceKind.DESKTOP, SessionStatus.RUNNING, "running", now),
                SessionUpdate("act", "Action", ToolKind.CLAUDE_CODE, SurfaceKind.TERMINAL, SessionStatus.NEEDS_ACTION, "act", now),
            ]
        )

        self.assertEqual([s.session_id for s in store.sessions()], ["act", "run"])

    def test_orders_full_sessions_before_process_only_detection(self):
        store = SessionStore(stuck_after_seconds=60)
        now = datetime.now(timezone.utc)
        store.apply_updates(
            [
                SessionUpdate("process-1", "Claude CLI", ToolKind.CLAUDE_CODE, SurfaceKind.TERMINAL, SessionStatus.RUNNING, "process", now, source="process"),
                SessionUpdate("json-1", "Claude task", ToolKind.CLAUDE_CODE, SurfaceKind.TERMINAL, SessionStatus.RUNNING, "full", now, source="json:task.json"),
            ]
        )

        self.assertEqual([s.session_id for s in store.sessions()], ["json-1", "process-1"])

    def test_marks_stale_running_session_as_stuck(self):
        store = SessionStore(stuck_after_seconds=10)
        old = datetime.now(timezone.utc) - timedelta(seconds=30)
        store.apply_updates(
            [
                SessionUpdate("run", "Running", ToolKind.CODEX, SurfaceKind.TERMINAL, SessionStatus.RUNNING, "running", old),
            ]
        )

        self.assertEqual(store.sessions(now=datetime.now(timezone.utc))[0].status, SessionStatus.STUCK)

    def test_replace_source_updates_removes_disappeared_volatile_sessions(self):
        store = SessionStore(stuck_after_seconds=60)
        now = datetime.now(timezone.utc)
        store.apply_updates(
            [
                SessionUpdate("process-1", "Claude", ToolKind.CLAUDE_CODE, SurfaceKind.TERMINAL, SessionStatus.RUNNING, "running", now, source="process"),
                SessionUpdate("json-1", "Task", ToolKind.CODEX, SurfaceKind.TERMINAL, SessionStatus.RUNNING, "running", now, source="json:task.json"),
            ]
        )

        store.replace_source_updates("process", [])

        self.assertEqual([session.session_id for session in store.sessions()], ["json-1"])

    def test_mark_viewed_turns_view_ack_session_idle(self):
        store = SessionStore(stuck_after_seconds=60)
        now = datetime(2026, 7, 2, 9, 0, tzinfo=timezone.utc)
        store.apply_updates(
            [
                SessionUpdate(
                    "codex-1",
                    "Codex Desktop - checkout-flow",
                    ToolKind.CODEX,
                    SurfaceKind.DESKTOP,
                    SessionStatus.NEEDS_ACTION,
                    "reply",
                    now,
                    view_ack_required=True,
                )
            ]
        )

        self.assertTrue(store.mark_session_viewed("codex-1"))

        self.assertEqual(store.sessions()[0].status, SessionStatus.IDLE)

    def test_mark_viewed_keeps_authorization_needs_action(self):
        store = SessionStore(stuck_after_seconds=60)
        now = datetime(2026, 7, 2, 9, 0, tzinfo=timezone.utc)
        store.apply_updates(
            [
                SessionUpdate(
                    "codex-approval",
                    "Codex Desktop - checkout-flow",
                    ToolKind.CODEX,
                    SurfaceKind.DESKTOP,
                    SessionStatus.NEEDS_ACTION,
                    "approval",
                    now,
                    view_ack_required=False,
                )
            ]
        )

        self.assertTrue(store.mark_session_viewed("codex-approval"))

        self.assertEqual(store.sessions()[0].status, SessionStatus.NEEDS_ACTION)

    def test_new_reply_after_viewed_returns_to_needs_action(self):
        store = SessionStore(stuck_after_seconds=60)
        first = datetime(2026, 7, 2, 9, 0, tzinfo=timezone.utc)
        second = datetime(2026, 7, 2, 9, 2, tzinfo=timezone.utc)
        store.apply_updates(
            [
                SessionUpdate(
                    "codex-1",
                    "Codex Desktop - checkout-flow",
                    ToolKind.CODEX,
                    SurfaceKind.DESKTOP,
                    SessionStatus.NEEDS_ACTION,
                    "reply",
                    first,
                    view_ack_required=True,
                )
            ]
        )
        store.mark_session_viewed("codex-1")
        store.apply_updates(
            [
                SessionUpdate(
                    "codex-1",
                    "Codex Desktop - checkout-flow",
                    ToolKind.CODEX,
                    SurfaceKind.DESKTOP,
                    SessionStatus.NEEDS_ACTION,
                    "new reply",
                    second,
                    view_ack_required=True,
                )
            ]
        )

        self.assertEqual(store.sessions()[0].status, SessionStatus.NEEDS_ACTION)

    def test_claude_terminal_idle_after_running_requires_view_ack_for_ide_terminal(self):
        store = SessionStore(stuck_after_seconds=60)
        started = datetime(2026, 7, 2, 9, 0, tzinfo=timezone.utc)
        replied = datetime(2026, 7, 2, 9, 1, tzinfo=timezone.utc)
        store.apply_updates(
            [
                SessionUpdate(
                    "process-27876",
                    "Claude Code CLI - checkout-flow",
                    ToolKind.CLAUDE_CODE,
                    SurfaceKind.TERMINAL,
                    SessionStatus.RUNNING,
                    "running",
                    started,
                    source="process",
                    process_id=27876,
                    focus_process_id=75407,
                    focus_app_name="Zed",
                    cwd="/Users/Gao/Documents/projects/checkout-flow",
                    status_source="claude-session",
                )
            ]
        )
        store.apply_updates(
            [
                SessionUpdate(
                    "process-27876",
                    "Claude Code CLI - checkout-flow",
                    ToolKind.CLAUDE_CODE,
                    SurfaceKind.TERMINAL,
                    SessionStatus.IDLE,
                    "reply complete",
                    replied,
                    source="process",
                    process_id=27876,
                    focus_process_id=75407,
                    focus_app_name="Zed",
                    cwd="/Users/Gao/Documents/projects/checkout-flow",
                    status_source="claude-session",
                )
            ]
        )

        session = store.sessions()[0]
        self.assertEqual(session.status, SessionStatus.NEEDS_ACTION)
        self.assertTrue(session.view_ack_required)
        self.assertEqual(session.focus_app_name, "Zed")

        store.mark_session_viewed("process-27876")

        self.assertEqual(store.sessions()[0].status, SessionStatus.IDLE)

    def test_claude_terminal_quick_reply_idle_timestamp_requires_view_ack_without_running_sample(self):
        store = SessionStore(stuck_after_seconds=60)
        original_idle = datetime(2026, 7, 2, 9, 0, tzinfo=timezone.utc)
        quick_reply = datetime(2026, 7, 2, 9, 0, 2, tzinfo=timezone.utc)
        store.apply_updates(
            [
                SessionUpdate(
                    "process-22534",
                    "Claude Code CLI - StudyCC",
                    ToolKind.CLAUDE_CODE,
                    SurfaceKind.TERMINAL,
                    SessionStatus.IDLE,
                    "already idle",
                    original_idle,
                    source="process",
                    process_id=22534,
                    cwd="/Users/Gao/Documents/StudyCC",
                    status_source="claude-session",
                )
            ]
        )
        store.mark_session_viewed("process-22534")

        store.apply_updates(
            [
                SessionUpdate(
                    "process-22534",
                    "Claude Code CLI - StudyCC",
                    ToolKind.CLAUDE_CODE,
                    SurfaceKind.TERMINAL,
                    SessionStatus.IDLE,
                    "quick reply complete",
                    quick_reply,
                    source="process",
                    process_id=22534,
                    cwd="/Users/Gao/Documents/StudyCC",
                    status_source="claude-session",
                )
            ]
        )

        session = store.sessions()[0]
        self.assertEqual(session.status, SessionStatus.NEEDS_ACTION)
        self.assertTrue(session.view_ack_required)

        store.mark_session_viewed("process-22534")

        self.assertEqual(store.sessions()[0].status, SessionStatus.IDLE)

    def test_claude_terminal_prompt_timestamp_refresh_stays_idle(self):
        store = SessionStore(stuck_after_seconds=60)
        original_idle = datetime(2026, 7, 2, 9, 0, tzinfo=timezone.utc)
        prompt_refresh = datetime(2026, 7, 2, 9, 0, 2, tzinfo=timezone.utc)
        store.apply_updates(
            [
                SessionUpdate(
                    "process-22534",
                    "Claude Code CLI - StudyCC",
                    ToolKind.CLAUDE_CODE,
                    SurfaceKind.TERMINAL,
                    SessionStatus.IDLE,
                    "already idle",
                    original_idle,
                    source="process",
                    process_id=22534,
                    cwd="/Users/Gao/Documents/StudyCC",
                    status_source="claude-session-prompt",
                )
            ]
        )
        store.apply_updates(
            [
                SessionUpdate(
                    "process-22534",
                    "Claude Code CLI - StudyCC",
                    ToolKind.CLAUDE_CODE,
                    SurfaceKind.TERMINAL,
                    SessionStatus.IDLE,
                    "prompt refreshed",
                    prompt_refresh,
                    source="process",
                    process_id=22534,
                    cwd="/Users/Gao/Documents/StudyCC",
                    status_source="claude-session-prompt",
                )
            ]
        )

        session = store.sessions()[0]
        self.assertEqual(session.status, SessionStatus.IDLE)
        self.assertFalse(session.view_ack_required)

    def test_claude_terminal_prompt_after_running_still_requires_view_ack(self):
        store = SessionStore(stuck_after_seconds=60)
        started = datetime(2026, 7, 2, 9, 0, tzinfo=timezone.utc)
        prompt_after_run = datetime(2026, 7, 2, 9, 1, tzinfo=timezone.utc)
        store.apply_updates(
            [
                SessionUpdate(
                    "process-22534",
                    "Claude Code CLI - StudyCC",
                    ToolKind.CLAUDE_CODE,
                    SurfaceKind.TERMINAL,
                    SessionStatus.RUNNING,
                    "running",
                    started,
                    source="process",
                    process_id=22534,
                    cwd="/Users/Gao/Documents/StudyCC",
                    status_source="claude-session",
                )
            ]
        )
        store.apply_updates(
            [
                SessionUpdate(
                    "process-22534",
                    "Claude Code CLI - StudyCC",
                    ToolKind.CLAUDE_CODE,
                    SurfaceKind.TERMINAL,
                    SessionStatus.IDLE,
                    "prompt after run",
                    prompt_after_run,
                    source="process",
                    process_id=22534,
                    cwd="/Users/Gao/Documents/StudyCC",
                    status_source="claude-session-prompt",
                )
            ]
        )

        session = store.sessions()[0]
        self.assertEqual(session.status, SessionStatus.NEEDS_ACTION)
        self.assertTrue(session.view_ack_required)

    def test_claude_terminal_initial_idle_after_process_startup_noise_stays_idle(self):
        store = SessionStore(stuck_after_seconds=60)
        startup_scan = datetime(2026, 7, 2, 9, 0, tzinfo=timezone.utc)
        initial_idle = datetime(2026, 7, 2, 9, 0, 1, tzinfo=timezone.utc)
        store.apply_updates(
            [
                SessionUpdate(
                    "process-22534",
                    "Claude Code CLI - StudyCC",
                    ToolKind.CLAUDE_CODE,
                    SurfaceKind.TERMINAL,
                    SessionStatus.RUNNING,
                    "startup process activity",
                    startup_scan,
                    source="process",
                    process_id=22534,
                    cwd="/Users/Gao/Documents/StudyCC",
                    status_source="process",
                )
            ]
        )
        store.apply_updates(
            [
                SessionUpdate(
                    "process-22534",
                    "Claude Code CLI - StudyCC",
                    ToolKind.CLAUDE_CODE,
                    SurfaceKind.TERMINAL,
                    SessionStatus.IDLE,
                    "initial idle",
                    initial_idle,
                    source="process",
                    process_id=22534,
                    cwd="/Users/Gao/Documents/StudyCC",
                    status_source="claude-session-initial-idle",
                )
            ]
        )

        session = store.sessions()[0]
        self.assertEqual(session.status, SessionStatus.IDLE)
        self.assertFalse(session.view_ack_required)

    def test_claude_terminal_initial_idle_replaces_newer_process_startup_noise(self):
        store = SessionStore(stuck_after_seconds=60)
        initial_idle = datetime(2026, 7, 2, 9, 0, 1, tzinfo=timezone.utc)
        startup_scan = datetime(2026, 7, 2, 9, 0, 2, tzinfo=timezone.utc)
        store.apply_updates(
            [
                SessionUpdate(
                    "process-22534",
                    "Claude Code CLI - StudyCC",
                    ToolKind.CLAUDE_CODE,
                    SurfaceKind.TERMINAL,
                    SessionStatus.RUNNING,
                    "startup process activity",
                    startup_scan,
                    source="process",
                    process_id=22534,
                    cwd="/Users/Gao/Documents/StudyCC",
                    status_source="process",
                )
            ]
        )
        store.apply_updates(
            [
                SessionUpdate(
                    "process-22534",
                    "Claude Code CLI - StudyCC",
                    ToolKind.CLAUDE_CODE,
                    SurfaceKind.TERMINAL,
                    SessionStatus.IDLE,
                    "initial idle",
                    initial_idle,
                    source="process",
                    process_id=22534,
                    cwd="/Users/Gao/Documents/StudyCC",
                    status_source="claude-session-initial-idle",
                )
            ]
        )

        session = store.sessions()[0]
        self.assertEqual(session.status, SessionStatus.IDLE)
        self.assertEqual(session.status_source, "claude-session-initial-idle")
        self.assertFalse(session.view_ack_required)

    def test_viewed_claude_terminal_reply_ignores_process_activity_fallback_noise(self):
        store = SessionStore(stuck_after_seconds=60)
        started = datetime(2026, 7, 2, 9, 0, tzinfo=timezone.utc)
        replied = datetime(2026, 7, 2, 9, 1, tzinfo=timezone.utc)
        noisy_running = datetime(2026, 7, 2, 9, 3, tzinfo=timezone.utc)
        noisy_idle = datetime(2026, 7, 2, 9, 4, tzinfo=timezone.utc)
        store.apply_updates(
            [
                SessionUpdate(
                    "process-22534",
                    "Claude Code CLI - StudyCC",
                    ToolKind.CLAUDE_CODE,
                    SurfaceKind.TERMINAL,
                    SessionStatus.RUNNING,
                    "running",
                    started,
                    source="process",
                    process_id=22534,
                    cwd="/Users/Gao/Documents/StudyCC",
                    status_source="claude-session",
                )
            ]
        )
        store.apply_updates(
            [
                SessionUpdate(
                    "process-22534",
                    "Claude Code CLI - StudyCC",
                    ToolKind.CLAUDE_CODE,
                    SurfaceKind.TERMINAL,
                    SessionStatus.IDLE,
                    "reply complete",
                    replied,
                    source="process",
                    process_id=22534,
                    cwd="/Users/Gao/Documents/StudyCC",
                    status_source="claude-session",
                )
            ]
        )
        self.assertEqual(store.sessions()[0].status, SessionStatus.NEEDS_ACTION)

        store.mark_session_viewed("process-22534")
        store.apply_updates(
            [
                SessionUpdate(
                    "process-22534",
                    "Claude Code CLI - StudyCC",
                    ToolKind.CLAUDE_CODE,
                    SurfaceKind.TERMINAL,
                    SessionStatus.RUNNING,
                    "process activity",
                    noisy_running,
                    source="process",
                    process_id=22534,
                    cwd="/Users/Gao/Documents/StudyCC",
                    status_source="process",
                )
            ]
        )
        self.assertEqual(store.sessions()[0].status, SessionStatus.IDLE)

        store.apply_updates(
            [
                SessionUpdate(
                    "process-22534",
                    "Claude Code CLI - StudyCC",
                    ToolKind.CLAUDE_CODE,
                    SurfaceKind.TERMINAL,
                    SessionStatus.IDLE,
                    "process quiet",
                    noisy_idle,
                    source="process",
                    process_id=22534,
                    cwd="/Users/Gao/Documents/StudyCC",
                    status_source="process",
                )
            ]
        )
        self.assertEqual(store.sessions()[0].status, SessionStatus.IDLE)

    def test_unviewed_claude_terminal_reply_ignores_process_activity_fallback_noise(self):
        store = SessionStore(stuck_after_seconds=60)
        started = datetime(2026, 7, 2, 9, 0, tzinfo=timezone.utc)
        replied = datetime(2026, 7, 2, 9, 1, tzinfo=timezone.utc)
        noisy_running = datetime(2026, 7, 2, 9, 3, tzinfo=timezone.utc)
        store.apply_updates(
            [
                SessionUpdate(
                    "process-22534",
                    "Claude Code CLI - StudyCC",
                    ToolKind.CLAUDE_CODE,
                    SurfaceKind.TERMINAL,
                    SessionStatus.RUNNING,
                    "running",
                    started,
                    source="process",
                    process_id=22534,
                    cwd="/Users/Gao/Documents/StudyCC",
                    status_source="claude-session",
                )
            ]
        )
        store.apply_updates(
            [
                SessionUpdate(
                    "process-22534",
                    "Claude Code CLI - StudyCC",
                    ToolKind.CLAUDE_CODE,
                    SurfaceKind.TERMINAL,
                    SessionStatus.IDLE,
                    "reply complete",
                    replied,
                    source="process",
                    process_id=22534,
                    cwd="/Users/Gao/Documents/StudyCC",
                    status_source="claude-session",
                )
            ]
        )

        store.apply_updates(
            [
                SessionUpdate(
                    "process-22534",
                    "Claude Code CLI - StudyCC",
                    ToolKind.CLAUDE_CODE,
                    SurfaceKind.TERMINAL,
                    SessionStatus.RUNNING,
                    "process activity",
                    noisy_running,
                    source="process",
                    process_id=22534,
                    cwd="/Users/Gao/Documents/StudyCC",
                    status_source="process",
                )
            ]
        )

        self.assertEqual(store.sessions()[0].status, SessionStatus.NEEDS_ACTION)

    def test_claude_terminal_initial_idle_stays_idle_for_system_terminal(self):
        store = SessionStore(stuck_after_seconds=60)
        store.apply_updates(
            [
                SessionUpdate(
                    "process-27876",
                    "Claude Code CLI - checkout-flow",
                    ToolKind.CLAUDE_CODE,
                    SurfaceKind.TERMINAL,
                    SessionStatus.IDLE,
                    "already idle",
                    datetime(2026, 7, 2, 9, 0, tzinfo=timezone.utc),
                    source="process",
                    process_id=27876,
                    focus_process_id=800,
                    focus_app_name="Terminal",
                    cwd="/Users/Gao/Documents/projects/checkout-flow",
                )
            ]
        )

        session = store.sessions()[0]
        self.assertEqual(session.status, SessionStatus.IDLE)
        self.assertFalse(session.view_ack_required)
        self.assertEqual(session.focus_app_name, "Terminal")

    def test_writes_action_audit_log(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SessionStore(audit_dir=Path(temp_dir))
            store.audit_action("s1", "Yes", "sent")

            files = list(Path(temp_dir).glob("action-audit-*.jsonl"))
            self.assertEqual(len(files), 1)
            self.assertIn('"session_id": "s1"', files[0].read_text())


if __name__ == "__main__":
    unittest.main()
