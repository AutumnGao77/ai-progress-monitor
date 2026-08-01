import tempfile
import threading
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ai_progress_monitor.models import SessionStatus, SessionUpdate, SurfaceKind, ToolKind
from ai_progress_monitor.store import SessionStore


class _AttemptTrackingRLock:
    def __init__(self, tracked_thread_name, attempted):
        self._lock = threading.RLock()
        self._tracked_thread_name = tracked_thread_name
        self._attempted = attempted

    def __enter__(self):
        if threading.current_thread().name == self._tracked_thread_name:
            self._attempted.set()
        self._lock.acquire()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self._lock.release()


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

    def test_verified_claude_running_uses_recent_observation_for_stuck_detection(self):
        store = SessionStore(stuck_after_seconds=60)
        running_at = datetime(2026, 7, 2, 9, 0, tzinfo=timezone.utc)
        first_observed_at = running_at + timedelta(hours=2)
        running = SessionUpdate(
            "process-27876",
            "Claude Code CLI - checkout-flow",
            ToolKind.CLAUDE_CODE,
            SurfaceKind.TERMINAL,
            SessionStatus.RUNNING,
            "running",
            running_at,
            source="process",
            process_id=27876,
            cwd="/Users/Gao/Documents/projects/checkout-flow",
            status_source="claude-session-verified",
            observed_at=first_observed_at,
        )
        store.apply_updates([running])

        fresh = store.sessions(now=first_observed_at + timedelta(seconds=59))[0]
        stale = store.sessions(now=first_observed_at + timedelta(seconds=60))[0]
        store.apply_updates([replace(running, observed_at=first_observed_at + timedelta(seconds=61))])
        recovered = store.sessions(now=first_observed_at + timedelta(seconds=61))[0]

        self.assertEqual(fresh.status, SessionStatus.RUNNING)
        self.assertEqual(stale.status, SessionStatus.STUCK)
        self.assertEqual(recovered.status, SessionStatus.RUNNING)

    def test_verified_claude_running_survives_temporary_process_fallback_and_recovers(self):
        store = SessionStore(stuck_after_seconds=60)
        running_at = datetime(2026, 7, 2, 9, 0, tzinfo=timezone.utc)
        first_observed_at = running_at + timedelta(minutes=2)
        running = SessionUpdate(
            "process-27876",
            "Claude Code CLI - checkout-flow",
            ToolKind.CLAUDE_CODE,
            SurfaceKind.TERMINAL,
            SessionStatus.RUNNING,
            "running",
            running_at,
            source="process",
            process_id=27876,
            cwd="/Users/Gao/Documents/projects/checkout-flow",
            status_source="claude-session-verified",
            observed_at=first_observed_at,
        )
        fallback_idle = replace(
            running,
            status=SessionStatus.IDLE,
            summary="process quiet",
            updated_at=first_observed_at + timedelta(seconds=4),
            status_source="process",
            observed_at=None,
        )
        recovered_running = replace(
            running,
            observed_at=first_observed_at + timedelta(seconds=8),
        )

        store.apply_updates([running])
        store.apply_updates([fallback_idle])
        after_fallback = store.sessions(now=first_observed_at + timedelta(seconds=4))[0]
        store.apply_updates([recovered_running])
        after_recovery = store.sessions(now=first_observed_at + timedelta(seconds=8))[0]
        late_fallback = replace(
            fallback_idle,
            updated_at=first_observed_at + timedelta(seconds=70),
        )
        store.apply_updates([late_fallback])
        after_persistent_fallback = store.sessions(now=first_observed_at + timedelta(seconds=70))[0]
        late_recovery = replace(
            running,
            observed_at=first_observed_at + timedelta(seconds=72),
        )
        store.apply_updates([late_recovery])
        after_late_recovery = store.sessions(now=first_observed_at + timedelta(seconds=72))[0]

        self.assertEqual(after_fallback.status, SessionStatus.RUNNING)
        self.assertEqual(after_fallback.status_source, "claude-session-verified")
        self.assertEqual(after_recovery.status, SessionStatus.RUNNING)
        self.assertEqual(after_recovery.observed_at, recovered_running.observed_at)
        self.assertEqual(after_persistent_fallback.status, SessionStatus.STUCK)
        self.assertEqual(after_late_recovery.status, SessionStatus.RUNNING)

    def test_verified_claude_running_replaces_newer_startup_process_fallback(self):
        store = SessionStore(stuck_after_seconds=60)
        observed_at = datetime(2026, 7, 2, 9, 2, tzinfo=timezone.utc)
        fallback_idle = SessionUpdate(
            "process-27876",
            "Claude Code CLI - checkout-flow",
            ToolKind.CLAUDE_CODE,
            SurfaceKind.TERMINAL,
            SessionStatus.IDLE,
            "process quiet",
            observed_at,
            source="process",
            process_id=27876,
            cwd="/Users/Gao/Documents/projects/checkout-flow",
            status_source="process",
        )
        verified_running = replace(
            fallback_idle,
            status=SessionStatus.RUNNING,
            summary="running",
            updated_at=observed_at - timedelta(minutes=2),
            status_source="claude-session-verified",
            observed_at=observed_at + timedelta(seconds=4),
        )

        store.apply_updates([fallback_idle])
        store.apply_updates([verified_running])

        session = store.sessions(now=observed_at + timedelta(seconds=4))[0]
        self.assertEqual(session.status, SessionStatus.RUNNING)
        self.assertEqual(session.status_source, "claude-session-verified")

    def test_verified_claude_running_survives_fresh_unverified_running_and_recovers(self):
        store = SessionStore(stuck_after_seconds=60)
        running_at = datetime(2026, 7, 2, 9, 0, tzinfo=timezone.utc)
        first_observed_at = running_at + timedelta(minutes=2)
        verified_running = SessionUpdate(
            "process-27876",
            "Claude Code CLI - checkout-flow",
            ToolKind.CLAUDE_CODE,
            SurfaceKind.TERMINAL,
            SessionStatus.RUNNING,
            "verified running",
            running_at,
            source="process",
            process_id=27876,
            cwd="/Users/Gao/Documents/projects/checkout-flow",
            status_source="claude-session-verified",
            observed_at=first_observed_at,
        )
        unverified_running = replace(
            verified_running,
            summary="fresh but unverified running",
            updated_at=first_observed_at + timedelta(seconds=4),
            status_source="claude-session",
            observed_at=None,
        )
        recovered_running = replace(
            verified_running,
            observed_at=first_observed_at + timedelta(seconds=8),
        )

        store.apply_updates([verified_running])
        store.apply_updates([unverified_running])
        after_degradation = store.sessions(now=first_observed_at + timedelta(seconds=4))[0]
        store.apply_updates([recovered_running])
        after_recovery = store.sessions(now=first_observed_at + timedelta(seconds=8))[0]

        self.assertEqual(after_degradation.status_source, "claude-session-verified")
        self.assertEqual(after_degradation.observed_at, first_observed_at)
        self.assertEqual(after_recovery.status, SessionStatus.RUNNING)
        self.assertEqual(after_recovery.status_source, "claude-session-verified")
        self.assertEqual(after_recovery.observed_at, recovered_running.observed_at)

    def test_verified_claude_waiting_survives_process_fallback(self):
        store = SessionStore(stuck_after_seconds=60)
        waiting_at = datetime(2026, 7, 2, 9, 0, tzinfo=timezone.utc)
        observed_at = waiting_at + timedelta(minutes=2)
        waiting = SessionUpdate(
            "process-27876",
            "Claude Code CLI - checkout-flow",
            ToolKind.CLAUDE_CODE,
            SurfaceKind.TERMINAL,
            SessionStatus.NEEDS_ACTION,
            "waiting for approval",
            waiting_at,
            source="process",
            process_id=27876,
            cwd="/Users/Gao/Documents/projects/checkout-flow",
            view_ack_required=False,
            status_source="claude-session",
            observed_at=observed_at,
        )
        fallback_running = replace(
            waiting,
            status=SessionStatus.RUNNING,
            summary="process activity",
            updated_at=observed_at + timedelta(seconds=4),
            status_source="process",
            observed_at=None,
        )

        store.apply_updates([waiting])
        store.apply_updates([fallback_running])

        session = store.sessions(now=observed_at + timedelta(seconds=4))[0]
        self.assertEqual(session.status, SessionStatus.NEEDS_ACTION)
        self.assertFalse(session.view_ack_required)
        self.assertEqual(session.observed_at, observed_at)

    def test_verified_claude_completion_over_degraded_running_requires_view_ack(self):
        store = SessionStore(stuck_after_seconds=60)
        degraded_at = datetime(2026, 7, 2, 9, 2, tzinfo=timezone.utc)
        degraded_running = SessionUpdate(
            "process-27876",
            "Claude Code CLI - checkout-flow",
            ToolKind.CLAUDE_CODE,
            SurfaceKind.TERMINAL,
            SessionStatus.RUNNING,
            "process activity",
            degraded_at,
            source="process",
            process_id=27876,
            cwd="/Users/Gao/Documents/projects/checkout-flow",
            status_source="process",
        )
        verified_completion = replace(
            degraded_running,
            status=SessionStatus.IDLE,
            summary="reply complete",
            updated_at=degraded_at - timedelta(minutes=2),
            status_source="claude-session",
            observed_at=degraded_at + timedelta(seconds=4),
        )

        store.apply_updates([degraded_running])
        store.apply_updates([verified_completion])

        session = store.sessions(now=degraded_at + timedelta(seconds=4))[0]
        self.assertEqual(session.status, SessionStatus.NEEDS_ACTION)
        self.assertTrue(session.view_ack_required)
        self.assertEqual(session.updated_at, verified_completion.updated_at)

    def test_verified_claude_running_upgrades_newer_unverified_running(self):
        store = SessionStore(stuck_after_seconds=60)
        observed_at = datetime(2026, 7, 2, 9, 2, tzinfo=timezone.utc)
        unverified_running = SessionUpdate(
            "process-27876",
            "Claude Code CLI - checkout-flow",
            ToolKind.CLAUDE_CODE,
            SurfaceKind.TERMINAL,
            SessionStatus.RUNNING,
            "unverified running",
            observed_at,
            source="process",
            process_id=27876,
            cwd="/Users/Gao/Documents/projects/checkout-flow",
            status_source="claude-session",
        )
        verified_running = replace(
            unverified_running,
            summary="verified running",
            updated_at=observed_at - timedelta(minutes=2),
            status_source="claude-session-verified",
            observed_at=observed_at + timedelta(seconds=4),
        )

        store.apply_updates([unverified_running])
        store.apply_updates([verified_running])

        session = store.sessions(now=observed_at + timedelta(seconds=4))[0]
        self.assertEqual(session.status, SessionStatus.RUNNING)
        self.assertEqual(session.status_source, "claude-session-verified")
        self.assertEqual(session.observed_at, verified_running.observed_at)

    def test_verified_observation_high_water_survives_degraded_state(self):
        store = SessionStore(stuck_after_seconds=60)
        running_at = datetime(2026, 7, 2, 9, 0, tzinfo=timezone.utc)
        high_water = running_at + timedelta(minutes=2)
        verified_running = SessionUpdate(
            "process-27876",
            "Claude Code CLI - checkout-flow",
            ToolKind.CLAUDE_CODE,
            SurfaceKind.TERMINAL,
            SessionStatus.RUNNING,
            "verified running",
            running_at,
            source="process",
            process_id=27876,
            cwd="/Users/Gao/Documents/projects/checkout-flow",
            status_source="claude-session-verified",
            observed_at=high_water,
        )
        degraded_running = replace(
            verified_running,
            summary="fresh unverified running",
            updated_at=high_water + timedelta(seconds=61),
            status_source="claude-session",
            observed_at=None,
        )
        stale_verified = replace(
            verified_running,
            summary="stale verified observation",
            updated_at=high_water + timedelta(minutes=1),
            observed_at=high_water - timedelta(seconds=10),
        )
        fresh_verified = replace(
            verified_running,
            observed_at=high_water + timedelta(seconds=70),
        )

        store.apply_updates([verified_running])
        store.apply_updates([degraded_running])
        after_degradation = store.sessions(now=high_water + timedelta(seconds=61))[0]
        store.apply_updates([stale_verified])
        after_stale_verified = store.sessions(now=high_water + timedelta(seconds=62))[0]
        store.apply_updates([fresh_verified])
        after_fresh_verified = store.sessions(now=high_water + timedelta(seconds=70))[0]

        self.assertEqual(after_degradation.status_source, "claude-session")
        self.assertIsNone(after_degradation.observed_at)
        self.assertEqual(after_stale_verified.status_source, "claude-session")
        self.assertIsNone(after_stale_verified.observed_at)
        self.assertEqual(after_fresh_verified.status_source, "claude-session-verified")
        self.assertEqual(after_fresh_verified.observed_at, fresh_verified.observed_at)

    def test_repeated_verified_prompt_refreshes_degradation_grace_high_water(self):
        store = SessionStore(stuck_after_seconds=300)
        running_at = datetime(2026, 7, 2, 9, 0, tzinfo=timezone.utc)
        first_observed_at = running_at + timedelta(minutes=2)
        running = SessionUpdate(
            "process-27876",
            "Claude Code CLI - checkout-flow",
            ToolKind.CLAUDE_CODE,
            SurfaceKind.TERMINAL,
            SessionStatus.RUNNING,
            "running",
            running_at,
            source="process",
            process_id=27876,
            cwd="/Users/Gao/Documents/projects/checkout-flow",
            status_source="claude-session-verified",
            observed_at=first_observed_at,
        )
        prompt_at = running_at + timedelta(seconds=1)
        prompt = replace(
            running,
            status=SessionStatus.IDLE,
            summary="reply complete",
            updated_at=prompt_at,
            status_source="claude-session-prompt",
            observed_at=first_observed_at + timedelta(seconds=1),
        )
        refreshed_prompt_observed_at = first_observed_at + timedelta(minutes=10)
        refreshed_prompt = replace(
            prompt,
            observed_at=refreshed_prompt_observed_at,
        )
        unverified_running = replace(
            running,
            summary="fresh unverified running",
            updated_at=refreshed_prompt_observed_at + timedelta(seconds=4),
            status_source="claude-session",
            observed_at=None,
        )

        store.apply_updates([running])
        store.apply_updates([prompt])
        store.apply_updates([refreshed_prompt])
        store.apply_updates([unverified_running])

        session = store.sessions(now=refreshed_prompt_observed_at + timedelta(seconds=4))[0]
        self.assertEqual(session.status, SessionStatus.NEEDS_ACTION)
        self.assertTrue(session.view_ack_required)

    def test_unverified_claude_semantic_states_survive_process_fallback_and_recover(self):
        semantic_at = datetime(2026, 7, 2, 9, 0, tzinfo=timezone.utc)
        base = SessionUpdate(
            "process-27876",
            "Claude Code CLI - checkout-flow",
            ToolKind.CLAUDE_CODE,
            SurfaceKind.TERMINAL,
            SessionStatus.RUNNING,
            "semantic state",
            semantic_at,
            source="process",
            process_id=27876,
            cwd="/Users/Gao/Documents/projects/checkout-flow",
            status_source="claude-session",
        )
        cases = (
            ("running", SessionStatus.RUNNING, "claude-session", False, SessionStatus.IDLE),
            ("waiting", SessionStatus.NEEDS_ACTION, "claude-session", False, SessionStatus.RUNNING),
            ("completion", SessionStatus.IDLE, "claude-session-prompt", False, SessionStatus.RUNNING),
        )

        for label, semantic_status, status_source, view_ack_required, fallback_status in cases:
            with self.subTest(label=label):
                store = SessionStore(stuck_after_seconds=300)
                semantic = replace(
                    base,
                    status=semantic_status,
                    summary=label,
                    status_source=status_source,
                    view_ack_required=view_ack_required,
                )
                fallback = replace(
                    semantic,
                    status=fallback_status,
                    summary="process fallback",
                    updated_at=semantic_at + timedelta(seconds=4),
                    status_source="process",
                    view_ack_required=False,
                )
                recovered = replace(
                    semantic,
                    summary=f"{label} recovered",
                    updated_at=semantic_at + timedelta(seconds=8),
                )

                store.apply_updates([semantic])
                store.apply_updates([fallback])
                during_fallback = store.sessions(now=semantic_at + timedelta(seconds=4))[0]
                store.apply_updates([recovered])
                after_recovery = store.sessions(now=semantic_at + timedelta(seconds=8))[0]

                self.assertEqual(during_fallback.status, semantic_status)
                self.assertEqual(during_fallback.status_source, status_source)
                self.assertEqual(after_recovery.status, semantic_status)
                self.assertEqual(after_recovery.status_source, status_source)

    def test_verified_terminal_state_yields_to_verified_new_running_task_with_clock_skew(self):
        terminal_at = datetime(2026, 7, 2, 9, 0, tzinfo=timezone.utc)
        terminal_observed_at = terminal_at + timedelta(minutes=2)
        cases = (
            ("completion", True),
            ("waiting", False),
        )

        for label, view_ack_required in cases:
            for offset_seconds in (1, 0, -1, -2, -3):
                with self.subTest(label=label, offset_seconds=offset_seconds):
                    store = SessionStore(stuck_after_seconds=300)
                    terminal = SessionUpdate(
                        "process-27876",
                        "Claude Code CLI - checkout-flow",
                        ToolKind.CLAUDE_CODE,
                        SurfaceKind.TERMINAL,
                        SessionStatus.NEEDS_ACTION,
                        label,
                        terminal_at,
                        source="process",
                        process_id=27876,
                        cwd="/Users/Gao/Documents/projects/checkout-flow",
                        view_ack_required=view_ack_required,
                        status_source="claude-session",
                        observed_at=terminal_observed_at,
                    )
                    running = replace(
                        terminal,
                        status=SessionStatus.RUNNING,
                        summary="new task running",
                        updated_at=terminal_at + timedelta(seconds=offset_seconds),
                        view_ack_required=False,
                        status_source="claude-session-verified",
                        observed_at=terminal_observed_at + timedelta(seconds=1),
                    )

                    store.apply_updates([terminal])
                    store.apply_updates([running])
                    after_first_observation = store.sessions(
                        now=terminal_observed_at + timedelta(seconds=1)
                    )[0]

                    if offset_seconds <= 0:
                        self.assertEqual(after_first_observation.status, SessionStatus.NEEDS_ACTION)
                        store.apply_updates(
                            [
                                replace(
                                    running,
                                    observed_at=terminal_observed_at + timedelta(seconds=2),
                                )
                            ]
                        )

                    session = store.sessions(now=terminal_observed_at + timedelta(seconds=2))[0]
                    self.assertEqual(session.status, SessionStatus.RUNNING)
                    self.assertEqual(session.status_source, "claude-session-verified")
                    self.assertIsNone(store.session_viewed_at("process-27876"))

    def test_single_stale_verified_running_snapshot_does_not_reopen_terminal_state(self):
        store = SessionStore(stuck_after_seconds=300)
        terminal_at = datetime(2026, 7, 2, 9, 0, tzinfo=timezone.utc)
        terminal_observed_at = terminal_at + timedelta(minutes=2)
        terminal = SessionUpdate(
            "process-27876",
            "Claude Code CLI - checkout-flow",
            ToolKind.CLAUDE_CODE,
            SurfaceKind.TERMINAL,
            SessionStatus.NEEDS_ACTION,
            "reply complete",
            terminal_at,
            source="process",
            process_id=27876,
            cwd="/Users/Gao/Documents/projects/checkout-flow",
            view_ack_required=True,
            status_source="claude-session",
            observed_at=terminal_observed_at,
        )
        stale_running = replace(
            terminal,
            status=SessionStatus.RUNNING,
            summary="delayed busy snapshot",
            updated_at=terminal_at - timedelta(seconds=1),
            view_ack_required=False,
            status_source="claude-session-verified",
            observed_at=terminal_observed_at + timedelta(seconds=1),
        )

        store.apply_updates([terminal])
        store.apply_updates([stale_running])

        session = store.sessions(now=terminal_observed_at + timedelta(seconds=1))[0]
        self.assertEqual(session.status, SessionStatus.NEEDS_ACTION)
        self.assertEqual(session.updated_at, terminal_at)
        self.assertTrue(session.view_ack_required)

    def test_verified_running_restart_confirms_across_consistently_slow_refreshes(self):
        store = SessionStore(stuck_after_seconds=60)
        terminal_at = datetime(2026, 7, 2, 9, 0, tzinfo=timezone.utc)
        terminal_observed_at = terminal_at + timedelta(minutes=2)
        terminal = SessionUpdate(
            "process-27876",
            "Claude Code CLI - checkout-flow",
            ToolKind.CLAUDE_CODE,
            SurfaceKind.TERMINAL,
            SessionStatus.NEEDS_ACTION,
            "reply complete",
            terminal_at,
            source="process",
            process_id=27876,
            cwd="/Users/Gao/Documents/projects/checkout-flow",
            view_ack_required=True,
            status_source="claude-session",
            observed_at=terminal_observed_at,
        )
        running = replace(
            terminal,
            status=SessionStatus.RUNNING,
            summary="new task running",
            updated_at=terminal_at - timedelta(seconds=1),
            view_ack_required=False,
            status_source="claude-session-verified",
            observed_at=terminal_observed_at + timedelta(seconds=11),
        )

        store.apply_updates([terminal])
        store.apply_updates([running])
        after_first = store.sessions(now=terminal_observed_at + timedelta(seconds=11))[0]
        store.apply_updates(
            [replace(running, observed_at=terminal_observed_at + timedelta(seconds=22))]
        )
        after_second = store.sessions(now=terminal_observed_at + timedelta(seconds=22))[0]
        store.apply_updates(
            [replace(running, observed_at=terminal_observed_at + timedelta(seconds=33))]
        )
        after_third = store.sessions(now=terminal_observed_at + timedelta(seconds=33))[0]

        self.assertEqual(after_first.status, SessionStatus.NEEDS_ACTION)
        self.assertEqual(after_second.status, SessionStatus.NEEDS_ACTION)
        self.assertEqual(after_third.status, SessionStatus.RUNNING)

    def test_pending_verified_running_restart_is_cleared_when_session_is_removed(self):
        store = SessionStore(stuck_after_seconds=300)
        terminal_at = datetime(2026, 7, 2, 9, 0, tzinfo=timezone.utc)
        terminal_observed_at = terminal_at + timedelta(minutes=2)
        terminal = SessionUpdate(
            "process-27876",
            "Claude Code CLI - checkout-flow",
            ToolKind.CLAUDE_CODE,
            SurfaceKind.TERMINAL,
            SessionStatus.NEEDS_ACTION,
            "waiting",
            terminal_at,
            source="process",
            process_id=27876,
            cwd="/Users/Gao/Documents/projects/checkout-flow",
            status_source="claude-session",
            observed_at=terminal_observed_at,
        )
        running = replace(
            terminal,
            status=SessionStatus.RUNNING,
            summary="new task running",
            updated_at=terminal_at - timedelta(seconds=3),
            status_source="claude-session-verified",
            observed_at=terminal_observed_at + timedelta(seconds=1),
        )

        store.replace_source_updates("process", [terminal])
        store.apply_updates([running])
        store.replace_source_updates("process", [])
        self.assertNotIn("process-27876", store._verified_observed_at_by_session)
        self.assertNotIn("process-27876", store._verified_running_observed_at_by_session)
        self.assertNotIn("process-27876", store._pending_verified_running_by_session)
        store.replace_source_updates("process", [terminal])
        store.apply_updates(
            [
                replace(
                    running,
                    observed_at=terminal_observed_at + timedelta(seconds=2),
                )
            ]
        )
        after_first_new_observation = store.sessions(
            now=terminal_observed_at + timedelta(seconds=2)
        )[0]
        store.apply_updates(
            [
                replace(
                    running,
                    observed_at=terminal_observed_at + timedelta(seconds=3),
                )
            ]
        )
        after_second_new_observation = store.sessions(
            now=terminal_observed_at + timedelta(seconds=3)
        )[0]

        self.assertEqual(after_first_new_observation.status, SessionStatus.NEEDS_ACTION)
        self.assertEqual(after_second_new_observation.status, SessionStatus.RUNNING)

    def test_process_fallback_breaks_consecutive_verified_running_restart_observations(self):
        store = SessionStore(stuck_after_seconds=300)
        terminal_at = datetime(2026, 7, 2, 9, 0, tzinfo=timezone.utc)
        terminal_observed_at = terminal_at + timedelta(minutes=2)
        terminal = SessionUpdate(
            "process-27876",
            "Claude Code CLI - checkout-flow",
            ToolKind.CLAUDE_CODE,
            SurfaceKind.TERMINAL,
            SessionStatus.NEEDS_ACTION,
            "waiting",
            terminal_at,
            source="process",
            process_id=27876,
            cwd="/Users/Gao/Documents/projects/checkout-flow",
            status_source="claude-session",
            observed_at=terminal_observed_at,
        )
        running = replace(
            terminal,
            status=SessionStatus.RUNNING,
            summary="new task running",
            updated_at=terminal_at - timedelta(seconds=3),
            status_source="claude-session-verified",
            observed_at=terminal_observed_at + timedelta(seconds=1),
        )
        fallback = replace(
            terminal,
            status=SessionStatus.RUNNING,
            summary="process fallback",
            updated_at=terminal_observed_at + timedelta(seconds=2),
            status_source="process",
            observed_at=None,
        )

        store.apply_updates([terminal])
        store.apply_updates([running])
        store.apply_updates([fallback])
        store.apply_updates(
            [
                replace(
                    running,
                    observed_at=terminal_observed_at + timedelta(seconds=3),
                )
            ]
        )
        after_first_consecutive_observation = store.sessions(
            now=terminal_observed_at + timedelta(seconds=3)
        )[0]
        store.apply_updates(
            [
                replace(
                    running,
                    observed_at=terminal_observed_at + timedelta(seconds=4),
                )
            ]
        )
        after_second_consecutive_observation = store.sessions(
            now=terminal_observed_at + timedelta(seconds=4)
        )[0]

        self.assertEqual(after_first_consecutive_observation.status, SessionStatus.NEEDS_ACTION)
        self.assertEqual(after_second_consecutive_observation.status, SessionStatus.RUNNING)

    def test_pending_verified_running_restart_rejects_delayed_observations(self):
        store = SessionStore(stuck_after_seconds=300)
        terminal_at = datetime(2026, 7, 2, 9, 0, tzinfo=timezone.utc)
        terminal_observed_at = terminal_at + timedelta(seconds=100)
        terminal = SessionUpdate(
            "process-27876",
            "Claude Code CLI - checkout-flow",
            ToolKind.CLAUDE_CODE,
            SurfaceKind.TERMINAL,
            SessionStatus.NEEDS_ACTION,
            "waiting",
            terminal_at,
            source="process",
            process_id=27876,
            cwd="/Users/Gao/Documents/projects/checkout-flow",
            status_source="claude-session",
            observed_at=terminal_observed_at,
        )
        running = replace(
            terminal,
            status=SessionStatus.RUNNING,
            summary="new task running",
            updated_at=terminal_at - timedelta(seconds=3),
            status_source="claude-session-verified",
            observed_at=terminal_at + timedelta(seconds=200),
        )

        store.apply_updates([terminal])
        store.apply_updates([running])
        store.apply_updates(
            [
                replace(
                    running,
                    observed_at=terminal_at + timedelta(seconds=150),
                )
            ]
        )
        store.apply_updates(
            [
                replace(
                    running,
                    observed_at=terminal_at + timedelta(seconds=160),
                )
            ]
        )
        after_delayed_observations = store.sessions(
            now=terminal_at + timedelta(seconds=200)
        )[0]
        high_water_after_delayed_observations = store._verified_observed_at_by_session[
            "process-27876"
        ]
        store.apply_updates(
            [
                replace(
                    running,
                    observed_at=terminal_at + timedelta(seconds=205),
                )
            ]
        )
        after_newer_observation = store.sessions(
            now=terminal_at + timedelta(seconds=205)
        )[0]

        self.assertEqual(after_delayed_observations.status, SessionStatus.NEEDS_ACTION)
        self.assertEqual(
            high_water_after_delayed_observations,
            terminal_at + timedelta(seconds=200),
        )
        self.assertEqual(
            store._verified_observed_at_by_session["process-27876"],
            terminal_at + timedelta(seconds=205),
        )
        self.assertEqual(after_newer_observation.status, SessionStatus.RUNNING)

    def test_pending_verified_running_restart_expires_after_long_observation_gap(self):
        store = SessionStore(stuck_after_seconds=300)
        terminal_at = datetime(2026, 7, 2, 9, 0, tzinfo=timezone.utc)
        terminal_observed_at = terminal_at + timedelta(minutes=2)
        terminal = SessionUpdate(
            "process-27876",
            "Claude Code CLI - checkout-flow",
            ToolKind.CLAUDE_CODE,
            SurfaceKind.TERMINAL,
            SessionStatus.NEEDS_ACTION,
            "waiting",
            terminal_at,
            source="process",
            process_id=27876,
            cwd="/Users/Gao/Documents/projects/checkout-flow",
            status_source="claude-session",
            observed_at=terminal_observed_at,
        )
        running = replace(
            terminal,
            status=SessionStatus.RUNNING,
            summary="new task running",
            updated_at=terminal_at - timedelta(seconds=3),
            status_source="claude-session-verified",
            observed_at=terminal_observed_at + timedelta(seconds=1),
        )

        store.apply_updates([terminal])
        store.apply_updates([running])
        store.apply_updates(
            [
                replace(
                    running,
                    observed_at=terminal_observed_at + timedelta(seconds=31),
                )
            ]
        )
        after_expired_candidate = store.sessions(
            now=terminal_observed_at + timedelta(seconds=31)
        )[0]
        store.apply_updates(
            [
                replace(
                    running,
                    observed_at=terminal_observed_at + timedelta(seconds=32),
                )
            ]
        )
        after_consecutive_candidate = store.sessions(
            now=terminal_observed_at + timedelta(seconds=32)
        )[0]

        self.assertEqual(after_expired_candidate.status, SessionStatus.NEEDS_ACTION)
        self.assertEqual(after_consecutive_candidate.status, SessionStatus.RUNNING)

    def test_rejected_verified_running_timestamp_still_refreshes_stuck_high_water(self):
        store = SessionStore(stuck_after_seconds=60)
        running_at = datetime(2026, 7, 2, 9, 0, tzinfo=timezone.utc)
        first_observed_at = running_at + timedelta(minutes=2)
        running = SessionUpdate(
            "process-27876",
            "Claude Code CLI - checkout-flow",
            ToolKind.CLAUDE_CODE,
            SurfaceKind.TERMINAL,
            SessionStatus.RUNNING,
            "running",
            running_at,
            source="process",
            process_id=27876,
            cwd="/Users/Gao/Documents/projects/checkout-flow",
            status_source="claude-session-verified",
            observed_at=first_observed_at,
        )
        refreshed_observed_at = first_observed_at + timedelta(seconds=50)
        older_semantic_timestamp = replace(
            running,
            updated_at=running_at - timedelta(minutes=1),
            observed_at=refreshed_observed_at,
        )

        store.apply_updates([running])
        store.apply_updates([older_semantic_timestamp])

        before_timeout = store.sessions(
            now=refreshed_observed_at + timedelta(seconds=59)
        )[0]
        after_timeout = store.sessions(
            now=refreshed_observed_at + timedelta(seconds=61)
        )[0]

        self.assertEqual(before_timeout.status, SessionStatus.RUNNING)
        self.assertEqual(after_timeout.status, SessionStatus.STUCK)
        self.assertEqual(before_timeout.observed_at, first_observed_at)
        self.assertEqual(
            store._verified_observed_at_by_session["process-27876"],
            refreshed_observed_at,
        )
        self.assertEqual(
            store._verified_running_observed_at_by_session["process-27876"],
            refreshed_observed_at,
        )

    def test_rejected_verified_terminal_does_not_refresh_running_stuck_clock(self):
        store = SessionStore(stuck_after_seconds=60)
        running_at = datetime(2026, 7, 2, 9, 0, tzinfo=timezone.utc)
        running_observed_at = running_at + timedelta(minutes=2)
        running = SessionUpdate(
            "process-27876",
            "Claude Code CLI - checkout-flow",
            ToolKind.CLAUDE_CODE,
            SurfaceKind.TERMINAL,
            SessionStatus.RUNNING,
            "running",
            running_at,
            source="process",
            process_id=27876,
            cwd="/Users/Gao/Documents/projects/checkout-flow",
            status_source="claude-session-verified",
            observed_at=running_observed_at,
        )
        stale_terminal = replace(
            running,
            status=SessionStatus.IDLE,
            summary="stale terminal state",
            updated_at=running_at - timedelta(minutes=1),
            status_source="claude-session-prompt",
            observed_at=running_observed_at + timedelta(seconds=50),
        )

        store.apply_updates([running])
        store.apply_updates([stale_terminal])
        store.apply_updates(
            [
                replace(
                    stale_terminal,
                    observed_at=running_observed_at + timedelta(seconds=100),
                )
            ]
        )

        session = store.sessions(
            now=running_observed_at + timedelta(seconds=110)
        )[0]

        self.assertEqual(session.status, SessionStatus.STUCK)
        self.assertEqual(session.status_source, "claude-session-verified")
        self.assertEqual(
            store._verified_observed_at_by_session["process-27876"],
            running_observed_at + timedelta(seconds=100),
        )
        self.assertEqual(
            store._verified_running_observed_at_by_session["process-27876"],
            running_observed_at,
        )

    def test_concurrent_verified_observations_keep_newest_high_water(self):
        initial_at = datetime(2026, 7, 2, 9, 0, tzinfo=timezone.utc)
        initial_observed_at = initial_at + timedelta(minutes=1)
        older_observed_at = initial_at + timedelta(minutes=2)
        newer_observed_at = initial_at + timedelta(minutes=3)
        older_entered = threading.Event()
        release_older = threading.Event()
        newer_lock_attempted = threading.Event()
        newer_entered = threading.Event()
        newer_finished = threading.Event()
        errors = []

        class InterleavingStore(SessionStore):
            def _normalize_update(self, existing, update, *args, **kwargs):
                if update.observed_at == older_observed_at:
                    older_entered.set()
                    release_older.wait(timeout=2)
                elif update.observed_at == newer_observed_at:
                    newer_entered.set()
                return super()._normalize_update(existing, update, *args, **kwargs)

        store = InterleavingStore(stuck_after_seconds=300)
        store._lock = _AttemptTrackingRLock("newer-observation", newer_lock_attempted)
        initial = SessionUpdate(
            "process-27876",
            "Claude Code CLI - checkout-flow",
            ToolKind.CLAUDE_CODE,
            SurfaceKind.TERMINAL,
            SessionStatus.RUNNING,
            "running",
            initial_at,
            source="process",
            process_id=27876,
            cwd="/Users/Gao/Documents/projects/checkout-flow",
            status_source="claude-session-verified",
            observed_at=initial_observed_at,
        )
        older = replace(initial, observed_at=older_observed_at)
        newer = replace(initial, observed_at=newer_observed_at)
        store.apply_updates([initial])

        def apply(update, finished=None):
            try:
                store.apply_updates([update])
            except Exception as exc:
                errors.append(exc)
            finally:
                if finished is not None:
                    finished.set()

        older_thread = threading.Thread(target=apply, args=(older,), name="older-observation")
        newer_thread = threading.Thread(
            target=apply,
            args=(newer, newer_finished),
            name="newer-observation",
        )
        older_thread.start()
        self.assertTrue(older_entered.wait(timeout=1))
        newer_thread.start()
        self.assertTrue(newer_lock_attempted.wait(timeout=1))
        self.assertFalse(newer_entered.wait(timeout=0.2))
        release_older.set()
        self.assertTrue(newer_entered.wait(timeout=1))
        older_thread.join(timeout=2)
        newer_thread.join(timeout=2)

        self.assertFalse(older_thread.is_alive())
        self.assertFalse(newer_thread.is_alive())
        self.assertEqual(errors, [])
        session = store.sessions(now=newer_observed_at + timedelta(seconds=1))[0]
        self.assertEqual(session.observed_at, newer_observed_at)
        self.assertEqual(
            store._verified_observed_at_by_session["process-27876"],
            newer_observed_at,
        )
        self.assertEqual(
            store._verified_running_observed_at_by_session["process-27876"],
            newer_observed_at,
        )

    def test_apply_updates_batch_is_atomic_for_readers(self):
        second_entered = threading.Event()
        release_second = threading.Event()
        reader_lock_attempted = threading.Event()
        reader_finished = threading.Event()
        errors = []
        reader_sessions = []

        class PausingStore(SessionStore):
            def _normalize_update(self, existing, update, *args, **kwargs):
                if update.session_id == "batch-2":
                    second_entered.set()
                    release_second.wait(timeout=2)
                return super()._normalize_update(existing, update, *args, **kwargs)

        store = PausingStore(stuck_after_seconds=300)
        store._lock = _AttemptTrackingRLock("batch-reader", reader_lock_attempted)
        now = datetime(2026, 7, 2, 9, 0, tzinfo=timezone.utc)
        updates = [
            SessionUpdate(
                "batch-1",
                "First",
                ToolKind.CODEX,
                SurfaceKind.TERMINAL,
                SessionStatus.RUNNING,
                "first",
                now,
            ),
            SessionUpdate(
                "batch-2",
                "Second",
                ToolKind.CODEX,
                SurfaceKind.TERMINAL,
                SessionStatus.IDLE,
                "second",
                now,
            ),
        ]

        def write_batch():
            try:
                store.apply_updates(updates)
            except Exception as exc:
                errors.append(exc)

        def read_sessions():
            try:
                reader_sessions.extend(store.sessions(now=now))
            except Exception as exc:
                errors.append(exc)
            finally:
                reader_finished.set()

        writer = threading.Thread(target=write_batch, name="batch-writer")
        reader = threading.Thread(target=read_sessions, name="batch-reader")
        writer.start()
        self.assertTrue(second_entered.wait(timeout=1))
        reader.start()
        self.assertTrue(reader_lock_attempted.wait(timeout=1))
        self.assertFalse(reader_finished.wait(timeout=0.2))
        release_second.set()
        writer.join(timeout=2)
        reader.join(timeout=2)

        self.assertFalse(writer.is_alive())
        self.assertFalse(reader.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(
            {session.session_id for session in reader_sessions},
            {"batch-1", "batch-2"},
        )

    def test_replace_source_updates_is_atomic_for_readers(self):
        replacement_entered = threading.Event()
        release_replacement = threading.Event()
        reader_lock_attempted = threading.Event()
        reader_finished = threading.Event()
        errors = []
        reader_sessions = []

        class PausingStore(SessionStore):
            def _normalize_update(self, existing, update, *args, **kwargs):
                if update.session_id == "process-new":
                    replacement_entered.set()
                    release_replacement.wait(timeout=2)
                return super()._normalize_update(existing, update, *args, **kwargs)

        store = PausingStore(stuck_after_seconds=300)
        now = datetime(2026, 7, 2, 9, 0, tzinfo=timezone.utc)
        old = SessionUpdate(
            "process-old",
            "Old",
            ToolKind.CODEX,
            SurfaceKind.TERMINAL,
            SessionStatus.IDLE,
            "old",
            now,
            source="process",
        )
        new = replace(
            old,
            session_id="process-new",
            title="New",
            summary="new",
            updated_at=now + timedelta(seconds=1),
        )
        store.apply_updates([old])
        store._lock = _AttemptTrackingRLock("replace-reader", reader_lock_attempted)

        def replace_source():
            try:
                store.replace_source_updates("process", [new])
            except Exception as exc:
                errors.append(exc)

        def read_sessions():
            try:
                reader_sessions.extend(store.sessions(now=now + timedelta(seconds=1)))
            except Exception as exc:
                errors.append(exc)
            finally:
                reader_finished.set()

        writer = threading.Thread(target=replace_source, name="replace-writer")
        reader = threading.Thread(target=read_sessions, name="replace-reader")
        writer.start()
        self.assertTrue(replacement_entered.wait(timeout=1))
        reader.start()
        self.assertTrue(reader_lock_attempted.wait(timeout=1))
        self.assertFalse(reader_finished.wait(timeout=0.2))
        release_replacement.set()
        writer.join(timeout=2)
        reader.join(timeout=2)

        self.assertFalse(writer.is_alive())
        self.assertFalse(reader.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(
            [session.session_id for session in reader_sessions],
            ["process-new"],
        )

    def test_verified_claude_observation_time_never_moves_backward(self):
        store = SessionStore(stuck_after_seconds=60)
        running_at = datetime(2026, 7, 2, 9, 0, tzinfo=timezone.utc)
        latest_observed_at = running_at + timedelta(minutes=2)
        latest = SessionUpdate(
            "process-27876",
            "Claude Code CLI - checkout-flow",
            ToolKind.CLAUDE_CODE,
            SurfaceKind.TERMINAL,
            SessionStatus.RUNNING,
            "running",
            running_at,
            source="process",
            process_id=27876,
            cwd="/Users/Gao/Documents/projects/checkout-flow",
            status_source="claude-session-verified",
            observed_at=latest_observed_at,
        )
        stale_observation = replace(
            latest,
            observed_at=latest_observed_at - timedelta(seconds=4),
        )

        store.apply_updates([latest])
        store.apply_updates([stale_observation])

        session = store.sessions(now=latest_observed_at + timedelta(seconds=59))[0]
        self.assertEqual(session.status, SessionStatus.RUNNING)
        self.assertEqual(session.observed_at, latest_observed_at)

    def test_out_of_order_terminal_bypass_requires_verified_newer_observation(self):
        running_at = datetime(2026, 7, 2, 9, 0, tzinfo=timezone.utc)
        running_observed_at = running_at + timedelta(minutes=2)
        running = SessionUpdate(
            "process-27876",
            "Claude Code CLI - checkout-flow",
            ToolKind.CLAUDE_CODE,
            SurfaceKind.TERMINAL,
            SessionStatus.RUNNING,
            "running",
            running_at,
            source="process",
            process_id=27876,
            cwd="/Users/Gao/Documents/projects/checkout-flow",
            status_source="claude-session-verified",
            observed_at=running_observed_at,
        )
        cases = (
            ("unverified", None),
            ("older-observation", running_observed_at - timedelta(seconds=1)),
        )
        for label, terminal_observed_at in cases:
            with self.subTest(label=label):
                store = SessionStore(stuck_after_seconds=60)
                store.apply_updates([running])
                store.apply_updates(
                    [
                        replace(
                            running,
                            status=SessionStatus.IDLE,
                            summary="reply complete",
                            updated_at=running_at - timedelta(seconds=1),
                            status_source="claude-session",
                            observed_at=terminal_observed_at,
                        )
                    ]
                )

                session = store.sessions(now=running_observed_at)[0]
                self.assertEqual(session.status, SessionStatus.RUNNING)
                self.assertEqual(session.status_source, "claude-session-verified")

    def test_viewed_verified_terminal_allows_fresh_unverified_new_task_after_grace(self):
        store = SessionStore(stuck_after_seconds=300)
        completed_at = datetime(2026, 7, 2, 9, 0, tzinfo=timezone.utc)
        observed_at = completed_at + timedelta(minutes=2)
        completed = SessionUpdate(
            "process-27876",
            "Claude Code CLI - checkout-flow",
            ToolKind.CLAUDE_CODE,
            SurfaceKind.TERMINAL,
            SessionStatus.NEEDS_ACTION,
            "reply complete",
            completed_at,
            source="process",
            process_id=27876,
            cwd="/Users/Gao/Documents/projects/checkout-flow",
            view_ack_required=True,
            status_source="claude-session",
            observed_at=observed_at,
        )
        early_unverified_running = replace(
            completed,
            status=SessionStatus.RUNNING,
            summary="fresh unverified running",
            updated_at=observed_at + timedelta(seconds=4),
            view_ack_required=False,
            observed_at=None,
        )
        late_unverified_running = replace(
            early_unverified_running,
            updated_at=observed_at + timedelta(minutes=20),
        )

        store.apply_updates([completed])
        store.mark_session_viewed("process-27876", viewed_at=observed_at + timedelta(seconds=1))
        store.apply_updates([early_unverified_running])
        during_grace = store.sessions(now=observed_at + timedelta(seconds=4))[0]
        store.apply_updates([late_unverified_running])
        after_grace = store.sessions(now=observed_at + timedelta(minutes=20))[0]

        self.assertEqual(during_grace.status, SessionStatus.IDLE)
        self.assertEqual(after_grace.status, SessionStatus.RUNNING)
        self.assertEqual(after_grace.status_source, "claude-session")
        self.assertIsNone(store.session_viewed_at("process-27876"))

    def test_old_unverified_terminal_state_does_not_override_process_fallback(self):
        observed_at = datetime(2026, 7, 2, 9, 2, tzinfo=timezone.utc)
        fallback_running = SessionUpdate(
            "process-27876",
            "Claude Code CLI - checkout-flow",
            ToolKind.CLAUDE_CODE,
            SurfaceKind.TERMINAL,
            SessionStatus.RUNNING,
            "process activity",
            observed_at,
            source="process",
            process_id=27876,
            cwd="/Users/Gao/Documents/projects/checkout-flow",
            status_source="process",
        )
        cases = (
            ("idle", SessionStatus.IDLE, "claude-session"),
            ("waiting", SessionStatus.NEEDS_ACTION, "claude-session"),
            ("initial-idle", SessionStatus.IDLE, "claude-session-initial-idle"),
        )
        for label, terminal_status, status_source in cases:
            with self.subTest(label=label):
                store = SessionStore(stuck_after_seconds=60)
                store.apply_updates([fallback_running])
                store.apply_updates(
                    [
                        replace(
                            fallback_running,
                            status=terminal_status,
                            summary=label,
                            updated_at=observed_at - timedelta(minutes=1),
                            status_source=status_source,
                        )
                    ]
                )

                session = store.sessions(now=observed_at)[0]
                self.assertEqual(session.status, SessionStatus.RUNNING)
                self.assertEqual(session.status_source, "process")

    def test_verified_claude_running_accepts_equal_or_older_explicit_terminal_states(self):
        running_at = datetime(2026, 7, 2, 9, 0, tzinfo=timezone.utc)
        cases = (
            ("idle", SessionStatus.IDLE, "claude-session", True),
            ("prompt", SessionStatus.IDLE, "claude-session-prompt", True),
            ("waiting", SessionStatus.NEEDS_ACTION, "claude-session", False),
        )
        for label, terminal_status, status_source, view_ack_required in cases:
            for offset_seconds in (0, -1):
                with self.subTest(label=label, offset_seconds=offset_seconds):
                    store = SessionStore(stuck_after_seconds=60)
                    store.apply_updates(
                        [
                            SessionUpdate(
                                "process-27876",
                                "Claude Code CLI - checkout-flow",
                                ToolKind.CLAUDE_CODE,
                                SurfaceKind.TERMINAL,
                                SessionStatus.RUNNING,
                                "running",
                                running_at,
                                source="process",
                                process_id=27876,
                                cwd="/Users/Gao/Documents/projects/checkout-flow",
                                status_source="claude-session-verified",
                                observed_at=running_at + timedelta(minutes=5),
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
                                terminal_status,
                                label,
                                running_at + timedelta(seconds=offset_seconds),
                                source="process",
                                process_id=27876,
                                cwd="/Users/Gao/Documents/projects/checkout-flow",
                                status_source=status_source,
                                observed_at=running_at + timedelta(minutes=5, seconds=1),
                            )
                        ]
                    )

                    session = store.sessions(now=running_at + timedelta(minutes=5))[0]
                    self.assertEqual(session.status, SessionStatus.NEEDS_ACTION)
                    self.assertEqual(session.view_ack_required, view_ack_required)
                    self.assertEqual(session.updated_at, running_at + timedelta(seconds=offset_seconds))
                    self.assertNotIn(
                        "process-27876",
                        store._verified_running_observed_at_by_session,
                    )

    def test_verified_claude_running_rejects_materially_older_terminal_snapshot(self):
        store = SessionStore(stuck_after_seconds=60)
        running_at = datetime(2026, 7, 2, 9, 0, tzinfo=timezone.utc)
        store.apply_updates(
            [
                SessionUpdate(
                    "process-27876",
                    "Claude Code CLI - checkout-flow",
                    ToolKind.CLAUDE_CODE,
                    SurfaceKind.TERMINAL,
                    SessionStatus.RUNNING,
                    "running",
                    running_at,
                    source="process",
                    process_id=27876,
                    cwd="/Users/Gao/Documents/projects/checkout-flow",
                    status_source="claude-session-verified",
                    observed_at=running_at + timedelta(minutes=5),
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
                    "stale reply snapshot",
                    running_at - timedelta(minutes=1),
                    source="process",
                    process_id=27876,
                    cwd="/Users/Gao/Documents/projects/checkout-flow",
                    status_source="claude-session",
                )
            ]
        )

        session = store.sessions(now=running_at + timedelta(minutes=5))[0]

        self.assertEqual(session.status, SessionStatus.RUNNING)
        self.assertEqual(session.status_source, "claude-session-verified")

    def test_viewed_verified_claude_terminal_ignores_repeated_older_terminal_snapshot(self):
        store = SessionStore(stuck_after_seconds=60)
        running_at = datetime(2026, 7, 2, 9, 0, tzinfo=timezone.utc)
        terminal_at = running_at - timedelta(seconds=1)
        running = SessionUpdate(
            "process-27876",
            "Claude Code CLI - checkout-flow",
            ToolKind.CLAUDE_CODE,
            SurfaceKind.TERMINAL,
            SessionStatus.RUNNING,
            "running",
            running_at,
            source="process",
            process_id=27876,
            cwd="/Users/Gao/Documents/projects/checkout-flow",
            status_source="claude-session-verified",
            observed_at=running_at + timedelta(seconds=1),
        )
        terminal = SessionUpdate(
            "process-27876",
            "Claude Code CLI - checkout-flow",
            ToolKind.CLAUDE_CODE,
            SurfaceKind.TERMINAL,
            SessionStatus.IDLE,
            "reply complete",
            terminal_at,
            source="process",
            process_id=27876,
            cwd="/Users/Gao/Documents/projects/checkout-flow",
            status_source="claude-session",
            observed_at=running_at + timedelta(seconds=2),
        )
        store.apply_updates([running])
        store.apply_updates([terminal])
        needs_action = store.sessions(now=running_at + timedelta(seconds=2))[0]
        self.assertEqual(needs_action.status, SessionStatus.NEEDS_ACTION)
        self.assertEqual(needs_action.updated_at, terminal_at)

        store.mark_session_viewed("process-27876", viewed_at=running_at + timedelta(seconds=3))
        store.apply_updates([terminal])
        store.apply_updates([terminal])
        viewed = store.sessions(now=running_at + timedelta(seconds=4))[0]
        new_running = replace(
            running,
            updated_at=running_at - timedelta(milliseconds=500),
            observed_at=running_at + timedelta(seconds=5),
        )
        store.apply_updates([new_running])

        restarted = store.sessions(now=running_at + timedelta(seconds=5))[0]
        self.assertEqual(viewed.status, SessionStatus.IDLE)
        self.assertEqual(restarted.status, SessionStatus.RUNNING)
        self.assertIsNone(store.session_viewed_at("process-27876"))

    def test_removed_process_session_does_not_reuse_viewed_state_for_same_id(self):
        store = SessionStore(stuck_after_seconds=60)
        completed_at = datetime(2026, 7, 2, 9, 0, tzinfo=timezone.utc)
        completed = SessionUpdate(
            "process-27876",
            "Claude Code CLI - checkout-flow",
            ToolKind.CLAUDE_CODE,
            SurfaceKind.TERMINAL,
            SessionStatus.NEEDS_ACTION,
            "reply complete",
            completed_at,
            source="process",
            process_id=27876,
            cwd="/Users/Gao/Documents/projects/checkout-flow",
            view_ack_required=True,
            status_source="claude-session",
        )
        store.replace_source_updates("process", [completed])
        store.mark_session_viewed("process-27876", viewed_at=completed_at + timedelta(seconds=1))

        store.replace_source_updates("process", [])
        store.replace_source_updates("process", [completed])

        session = store.sessions(now=completed_at + timedelta(seconds=2))[0]
        self.assertEqual(session.status, SessionStatus.NEEDS_ACTION)
        self.assertIsNone(store.session_viewed_at("process-27876"))

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
