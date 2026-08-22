import tempfile
import threading
import time
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from ai_progress_monitor.actions import ActionExecutor
from ai_progress_monitor.demo import DemoSource
from ai_progress_monitor.models import SessionStatus, SessionUpdate, SurfaceKind, ToolKind
from ai_progress_monitor.notifier import NotificationManager
from ai_progress_monitor.preferences import MonitorPreferences
from ai_progress_monitor.service import MonitorService
from ai_progress_monitor.sources import JsonSessionSource
from ai_progress_monitor.store import SessionStore
from ai_progress_monitor.window_focus import FocusResult, WindowFocusManager


class MonitorServiceTests(unittest.TestCase):
    def test_sessions_payload_contains_demo_sessions(self):
        service = MonitorService([DemoSource()], SessionStore(), ActionExecutor())

        payload = service.sessions_payload()

        self.assertEqual(len(payload), 3)
        self.assertEqual(payload[0]["status"], "needs_action")
        self.assertEqual(payload[0]["safe_action"]["options"], ["Yes", "No"])

    def test_sessions_payload_exposes_status_source_for_monitoring_diagnostics(self):
        store = SessionStore()
        store.apply_updates(
            [
                SessionUpdate(
                    session_id="process-51005",
                    title="Qoder Desktop",
                    tool=ToolKind.UNKNOWN,
                    surface=SurfaceKind.DESKTOP,
                    status=SessionStatus.RUNNING,
                    summary="Qoder 正在处理任务。",
                    updated_at=datetime.now(timezone.utc),
                    source="process",
                    process_id=51005,
                    status_source="qoder-log",
                    tool_display_name="Qoder",
                )
            ]
        )
        service = MonitorService([], store, ActionExecutor())

        payload = service.sessions_payload()

        self.assertEqual(payload[0]["status_source"], "qoder-log")
        self.assertEqual(payload[0]["tool_display_name"], "Qoder")
        self.assertNotIn("observed_at", payload[0])
        self.assertNotIn("process_started_at", payload[0])
        self.assertNotIn("observation_sequence", payload[0])
        self.assertNotIn("observed_monotonic", payload[0])
        self.assertNotIn("observation_clock_adjusted", payload[0])
        self.assertNotIn("observation_wall_at", payload[0])

    def test_qoder_log_desktop_session_payload_is_full_and_view_acknowledged_after_focus(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SessionStore(audit_dir=Path(temp_dir))
            store.apply_updates(
                [
                    SessionUpdate(
                        session_id="qoder-task-alpha",
                        title="Qoder Desktop - 围棋游戏开发",
                        tool=ToolKind.UNKNOWN,
                        surface=SurfaceKind.DESKTOP,
                        status=SessionStatus.NEEDS_ACTION,
                        summary="Qoder 任务已完成，等待查看。",
                        updated_at=datetime(2026, 7, 13, 11, 10, 8, tzinfo=timezone.utc),
                        source="process",
                        process_id=51005,
                        focus_process_id=51005,
                        focus_app_name="Qoder",
                        cwd="/Users/Gao/Documents/QoderCN/2026-07-13/chat-1",
                        view_ack_required=True,
                        status_source="qoder-log",
                        tool_display_name="Qoder",
                        generated_conversation_path=True,
                    )
                ]
            )
            focus_manager = WindowFocusManager(sender=lambda target: FocusResult(True, "focused-qoder"))
            service = MonitorService([], store, ActionExecutor(), focus_manager=focus_manager)

            before = service.sessions_payload()[0]
            result = service.focus_session("qoder-task-alpha")
            after = service.sessions_payload()[0]

            self.assertEqual(before["monitoring_level"], "full")
            self.assertEqual(before["status"], "needs_action")
            self.assertTrue(before["view_ack_required"])
            self.assertTrue(result.ok)
            self.assertEqual(after["status"], "idle")

    def test_qoder_view_acknowledged_action_required_stays_idle_after_refresh(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            updated_at = datetime(2026, 7, 15, 10, 18, 54, tzinfo=timezone.utc)
            clock = FakeDateTimeClock(datetime(2026, 7, 15, 10, 19, 0, tzinfo=timezone.utc))
            qoder_action_required = SessionUpdate(
                session_id="qoder-task-hello",
                title="Qoder Desktop - Hello",
                tool=ToolKind.UNKNOWN,
                surface=SurfaceKind.DESKTOP,
                status=SessionStatus.NEEDS_ACTION,
                summary="Qoder 任务已完成，等待查看。",
                updated_at=updated_at,
                source="process",
                process_id=51005,
                focus_process_id=51005,
                focus_app_name="Qoder",
                cwd="/Users/Gao/Documents/StudyCC",
                view_ack_required=True,
                status_source="qoder-log",
                tool_display_name="Qoder",
            )
            source = VolatileProcessSource([[qoder_action_required], [qoder_action_required]])
            store = SessionStore(audit_dir=Path(temp_dir))
            focus_manager = WindowFocusManager(sender=lambda target: FocusResult(True, "focused-qoder"))
            service = MonitorService(
                [source],
                store,
                ActionExecutor(),
                focus_manager=focus_manager,
                now=clock.now,
            )

            before = service.sessions_payload()[0]
            result = service.focus_session("qoder-task-hello")
            after_refresh = service.sessions_payload()[0]

            self.assertEqual(before["status"], "needs_action")
            self.assertTrue(before["view_ack_required"])
            self.assertTrue(result.ok)
            self.assertEqual(after_refresh["status"], "idle")

    def test_qoder_persistent_blocker_stays_needs_action_after_focus_and_refresh(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            updated_at = datetime(2026, 7, 24, 7, 21, 59, tzinfo=timezone.utc)
            qoder_plan_blocker = SessionUpdate(
                session_id="qoder-task-plan-blocked",
                title="Qoder CN Desktop - 测试任务",
                tool=ToolKind.UNKNOWN,
                surface=SurfaceKind.DESKTOP,
                status=SessionStatus.NEEDS_ACTION,
                summary="Qoder 任务需要用户处理。",
                updated_at=updated_at,
                source="process",
                process_id=51005,
                focus_process_id=51005,
                focus_app_name="Qoder CN",
                cwd="/Users/Gao/Documents/QoderCN/2026-07-24/chat-1",
                view_ack_required=False,
                status_source="qoder-log",
                tool_display_name="Qoder CN",
            )
            source = VolatileProcessSource([[qoder_plan_blocker], [qoder_plan_blocker]])
            store = SessionStore(audit_dir=Path(temp_dir))
            focus_manager = WindowFocusManager(sender=lambda target: FocusResult(True, "focused-qoder"))
            service = MonitorService(
                [source],
                store,
                ActionExecutor(),
                focus_manager=focus_manager,
            )

            before = service.sessions_payload()[0]
            result = service.focus_session("qoder-task-plan-blocked")
            after_refresh = service.sessions_payload()[0]

            self.assertEqual(before["status"], "needs_action")
            self.assertFalse(before["view_ack_required"])
            self.assertTrue(result.ok)
            self.assertEqual(after_refresh["status"], "needs_action")

    def test_generic_full_session_is_view_acknowledged_after_focus(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SessionStore(audit_dir=Path(temp_dir))
            store.apply_updates(
                [
                    SessionUpdate(
                        session_id="workbuddy-json",
                        title="WorkBuddy - product-ops",
                        tool=ToolKind.UNKNOWN,
                        surface=SurfaceKind.DESKTOP,
                        status=SessionStatus.NEEDS_ACTION,
                        summary="WorkBuddy 需要处理。",
                        updated_at=datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc),
                        source="json",
                        focus_app_name="WorkBuddy",
                        view_ack_required=True,
                        tool_display_name="WorkBuddy",
                    )
                ]
            )
            focus_manager = WindowFocusManager(sender=lambda target: FocusResult(True, "focused-workbuddy"))
            service = MonitorService([], store, ActionExecutor(), focus_manager=focus_manager)

            before = service.sessions_payload()[0]
            result = service.focus_session("workbuddy-json")
            after = service.sessions_payload()[0]

            self.assertEqual(before["monitoring_level"], "full")
            self.assertEqual(before["tool_display_name"], "WorkBuddy")
            self.assertEqual(before["status"], "needs_action")
            self.assertTrue(result.ok)
            self.assertEqual(after["status"], "idle")

    def test_verified_claude_running_to_reply_and_view_is_stable_across_refresh(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            running_at = datetime(2026, 7, 31, 5, 23, tzinfo=timezone.utc)
            clock = FakeDateTimeClock(datetime(2026, 7, 31, 5, 25, tzinfo=timezone.utc))
            running = SessionUpdate(
                session_id="process-24645",
                title="Claude Code CLI - long-task",
                tool=ToolKind.CLAUDE_CODE,
                surface=SurfaceKind.TERMINAL,
                status=SessionStatus.RUNNING,
                summary="Claude Code is running.",
                updated_at=running_at,
                source="process",
                process_id=24645,
                focus_process_id=75407,
                focus_app_name="Zed",
                cwd="/Users/Gao/Documents/projects/long-task",
                status_source="claude-session-verified",
                observed_at=clock.now(),
            )
            reply = replace(
                running,
                status=SessionStatus.IDLE,
                summary="Claude Code reply is ready.",
                updated_at=running_at - timedelta(seconds=1),
                status_source="claude-session-prompt",
            )
            source = VolatileProcessSource([[running], [reply], [reply]])
            sent = []
            notifier = NotificationManager(
                sender=lambda title, message: sent.append((title, message)),
                cooldown_seconds=60,
            )
            service = MonitorService(
                [source],
                SessionStore(stuck_after_seconds=60, audit_dir=Path(temp_dir) / "audit"),
                ActionExecutor(),
                notifier=notifier,
                focus_manager=WindowFocusManager(sender=lambda target: FocusResult(True, "focused-claude")),
                preferences=MonitorPreferences(Path(temp_dir) / "preferences.json"),
                now=clock.now,
            )

            first = service.sessions_payload()[0]
            second = service.sessions_payload()[0]
            focus_result = service.focus_session("process-24645")
            after_focus = service.visible_sessions()[0]
            after_repeated_reply = service.sessions_payload()[0]

            self.assertEqual(first["status"], "running")
            self.assertEqual(second["status"], "needs_action")
            self.assertTrue(second["view_ack_required"])
            self.assertTrue(focus_result.ok)
            self.assertEqual(after_focus.status, SessionStatus.IDLE)
            self.assertEqual(after_repeated_reply["status"], "idle")
            self.assertEqual(len(sent), 1)
            self.assertIn("需要处理", sent[0][0])

    def test_verified_claude_running_becomes_stuck_during_source_failure_and_recovers(self):
        observed_at = datetime(2026, 7, 31, 5, 25, tzinfo=timezone.utc)
        clock = FakeDateTimeClock(observed_at)
        monotonic_clock = FakeClock()
        running = SessionUpdate(
            session_id="process-24645",
            title="Claude Code CLI - long-task",
            tool=ToolKind.CLAUDE_CODE,
            surface=SurfaceKind.TERMINAL,
            status=SessionStatus.RUNNING,
            summary="Claude Code is running.",
            updated_at=observed_at - timedelta(minutes=2),
            source="process",
            process_id=24645,
            cwd="/Users/Gao/Documents/projects/long-task",
            status_source="claude-session-verified",
            observed_at=observed_at,
        )
        recovered = replace(running, observed_at=observed_at + timedelta(seconds=62))
        service = MonitorService(
            [VolatileProcessSource([[running], None, [recovered]])],
            SessionStore(stuck_after_seconds=60),
            ActionExecutor(),
            clock=monotonic_clock.now,
            now=clock.now,
        )

        first = service.sessions_payload()[0]
        clock.advance(61)
        monotonic_clock.advance(61)
        during_failure = service.sessions_payload()[0]
        clock.advance(1)
        monotonic_clock.advance(1)
        after_recovery = service.sessions_payload()[0]

        self.assertEqual(first["status"], "running")
        self.assertEqual(during_failure["status"], "stuck")
        self.assertEqual(after_recovery["status"], "running")

    def test_workbuddy_db_desktop_session_payload_is_full_and_view_acknowledged_after_focus(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SessionStore(audit_dir=Path(temp_dir))
            store.apply_updates(
                [
                    SessionUpdate(
                        session_id="workbuddy-wb-done",
                        title="WorkBuddy Desktop - 需求复盘",
                        tool=ToolKind.UNKNOWN,
                        surface=SurfaceKind.DESKTOP,
                        status=SessionStatus.NEEDS_ACTION,
                        summary="WorkBuddy 任务已完成，等待查看。",
                        updated_at=datetime(2026, 7, 13, 12, 10, tzinfo=timezone.utc),
                        source="process",
                        process_id=51007,
                        focus_process_id=51007,
                        focus_app_name="WorkBuddy",
                        cwd="/Users/Gao/Documents/product-ops",
                        view_ack_required=True,
                        status_source="workbuddy-db",
                        tool_display_name="WorkBuddy",
                    )
                ]
            )
            focus_manager = WindowFocusManager(sender=lambda target: FocusResult(True, "focused-workbuddy"))
            service = MonitorService([], store, ActionExecutor(), focus_manager=focus_manager)

            before = service.sessions_payload()[0]
            result = service.focus_session("workbuddy-wb-done")
            after = service.sessions_payload()[0]

            self.assertEqual(before["monitoring_level"], "full")
            self.assertEqual(before["status_source"], "workbuddy-db")
            self.assertEqual(before["tool_display_name"], "WorkBuddy")
            self.assertTrue(before["view_ack_required"])
            self.assertTrue(result.ok)
            self.assertEqual(after["status"], "idle")

    def test_execute_demo_yes_action_writes_response_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            service = MonitorService(
                [DemoSource()],
                SessionStore(audit_dir=Path(temp_dir) / "audit"),
                ActionExecutor(response_dir=Path(temp_dir) / "responses"),
            )
            service.refresh()

            result = service.execute_action("demo-claude-1", "Yes")

            self.assertTrue(result.ok)
            self.assertEqual(Path(result.detail).read_text().strip(), "Yes")

    def test_blocks_unknown_session_action(self):
        service = MonitorService([DemoSource()], SessionStore(), ActionExecutor())

        result = service.execute_action("missing", "Yes")

        self.assertFalse(result.ok)

    def test_refresh_sends_needs_action_notification(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            sent = []
            notifier = NotificationManager(sender=lambda title, message: sent.append((title, message)), cooldown_seconds=60)
            preferences = MonitorPreferences(Path(temp_dir) / "preferences.json")
            service = MonitorService(
                [DemoSource()],
                SessionStore(),
                ActionExecutor(),
                notifier=notifier,
                preferences=preferences,
            )

            service.refresh()
            service.refresh()

            self.assertEqual(len(sent), 1)
            self.assertIn("需要处理", sent[0][0])

    def test_notification_preference_controls_notifier_immediately(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            preferences = MonitorPreferences(Path(temp_dir) / "preferences.json")
            preferences.set_notifications_enabled(False)
            notifier = NotificationManager(sender=lambda _title, _message: None)
            service = MonitorService([], SessionStore(), ActionExecutor(), notifier=notifier, preferences=preferences)

            self.assertFalse(service.notifications_enabled())
            self.assertFalse(service.notifications_locked())
            self.assertFalse(notifier.enabled)

            self.assertTrue(service.set_notifications_enabled(True))
            self.assertTrue(service.notifications_enabled())
            self.assertTrue(notifier.enabled)
            self.assertTrue(MonitorPreferences(preferences.path).notifications_enabled())

    def test_notification_toggle_cannot_be_overwritten_by_stale_refresh(self):
        class PausingPreferences:
            def __init__(self):
                self.enabled = True
                self.refresh_read_started = threading.Event()
                self.allow_refresh_read_to_finish = threading.Event()

            def notifications_enabled(self):
                value = self.enabled
                if threading.current_thread().name == "notification-refresh":
                    self.refresh_read_started.set()
                    self.allow_refresh_read_to_finish.wait(timeout=2)
                return value

            def set_notifications_enabled(self, enabled):
                self.enabled = enabled
                return True

            def is_hidden(self, _session_id):
                return False

        preferences = PausingPreferences()
        notifier = NotificationManager(sender=lambda _title, _message: None)
        service = MonitorService(
            [],
            SessionStore(),
            ActionExecutor(),
            notifier=notifier,
            preferences=preferences,
        )
        refresh_thread = threading.Thread(target=service.refresh, name="notification-refresh")
        refresh_thread.start()
        self.assertTrue(preferences.refresh_read_started.wait(timeout=1))

        toggle_finished = threading.Event()
        toggle_result = []

        def disable_notifications():
            toggle_result.append(service.set_notifications_enabled(False))
            toggle_finished.set()

        toggle_thread = threading.Thread(target=disable_notifications)
        toggle_thread.start()
        returned_before_refresh_finished = toggle_finished.wait(timeout=0.1)
        preferences.allow_refresh_read_to_finish.set()
        refresh_thread.join(timeout=2)
        toggle_thread.join(timeout=2)

        self.assertFalse(returned_before_refresh_finished)
        self.assertEqual(toggle_result, [True])
        self.assertFalse(preferences.enabled)
        self.assertFalse(notifier.enabled)

    def test_no_notifications_argument_locks_runtime_without_changing_preference(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            preferences = MonitorPreferences(Path(temp_dir) / "preferences.json")
            preferences.set_notifications_enabled(True)
            notifier = NotificationManager(sender=lambda _title, _message: None)
            service = MonitorService(
                [],
                SessionStore(),
                ActionExecutor(),
                notifier=notifier,
                preferences=preferences,
                notifications_forced_off=True,
            )

            self.assertFalse(service.notifications_enabled())
            self.assertTrue(service.notifications_locked())
            self.assertFalse(notifier.enabled)
            self.assertFalse(service.set_notifications_enabled(False))
            self.assertTrue(MonitorPreferences(preferences.path).notifications_enabled())

    def test_refresh_keeps_process_sessions_during_empty_poll_grace_window(self):
        clock = FakeClock()
        now_source = VolatileProcessSource(
            [
                [
                    SessionUpdate(
                        "process-1",
                        "Claude Code CLI",
                        ToolKind.CLAUDE_CODE,
                        SurfaceKind.TERMINAL,
                        SessionStatus.RUNNING,
                        "Process detected",
                        SessionUpdate.now(),
                        source="process",
                    )
                ],
                [],
                [],
                [],
            ]
        )
        service = MonitorService(
            [now_source],
            SessionStore(),
            ActionExecutor(),
            process_empty_grace_seconds=10,
            clock=clock.now,
        )

        first = service.sessions_payload()
        second = service.sessions_payload()
        clock.advance(5)
        third = service.sessions_payload()
        clock.advance(6)
        fourth = service.sessions_payload()

        self.assertEqual([session["session_id"] for session in first], ["process-1"])
        self.assertEqual(first[0]["monitoring_level"], "process_only")
        self.assertEqual([session["session_id"] for session in second], ["process-1"])
        self.assertEqual([session["session_id"] for session in third], ["process-1"])
        self.assertEqual(fourth, [])

    def test_refresh_preserves_process_sessions_when_process_poll_fails(self):
        clock = FakeClock()
        source = VolatileProcessSource(
            [
                [
                    SessionUpdate(
                        "process-1",
                        "Claude Code CLI",
                        ToolKind.CLAUDE_CODE,
                        SurfaceKind.TERMINAL,
                        SessionStatus.RUNNING,
                        "Process detected",
                        SessionUpdate.now(),
                        source="process",
                    )
                ],
                None,
                None,
                [],
            ]
        )
        service = MonitorService(
            [source],
            SessionStore(),
            ActionExecutor(),
            process_empty_grace_seconds=10,
            clock=clock.now,
        )

        first = service.sessions_payload()
        failed_once = service.sessions_payload()
        clock.advance(30)
        failed_twice = service.sessions_payload()
        empty_started = service.sessions_payload()

        self.assertEqual([session["session_id"] for session in first], ["process-1"])
        self.assertEqual([session["session_id"] for session in failed_once], ["process-1"])
        self.assertEqual([session["session_id"] for session in failed_twice], ["process-1"])
        self.assertEqual([session["session_id"] for session in empty_started], ["process-1"])

    def test_refresh_removes_ide_terminal_session_without_matching_project_window(self):
        seller_books = SessionUpdate(
            "process-101",
            "Claude Code CLI - SellerBooks",
            ToolKind.CLAUDE_CODE,
            SurfaceKind.TERMINAL,
            SessionStatus.IDLE,
            "Process detected",
            SessionUpdate.now(),
            source="process",
            process_id=101,
            focus_process_id=478,
            focus_app_name="Zed",
            cwd="/Users/Gao/Documents/SellerBooks",
        )
        daily_report = SessionUpdate(
            "process-102",
            "Claude Code CLI - 日报推送",
            ToolKind.CLAUDE_CODE,
            SurfaceKind.TERMINAL,
            SessionStatus.IDLE,
            "Process detected",
            SessionUpdate.now(),
            source="process",
            process_id=102,
            focus_process_id=478,
            focus_app_name="Zed",
            cwd="/Users/Gao/Documents/日报推送",
        )
        window_source = FakeProjectWindowSource(
            {
                (478, "Zed", "/Users/Gao/Documents/日报推送"): "window-42",
            }
        )
        service = MonitorService(
            [VolatileProcessSource([[seller_books, daily_report]]), window_source],
            SessionStore(),
            ActionExecutor(),
        )

        payload = service.sessions_payload()

        self.assertEqual([session["session_id"] for session in payload], ["process-102"])
        self.assertEqual(payload[0]["window_id"], "window-42")

    def test_refresh_reconciles_process_sessions_for_every_supported_ide_family(self):
        app_names = [
            "Android Studio",
            "CLion",
            "Code",
            "Cursor",
            "Eclipse",
            "Fleet",
            "GoLand 2026.1",
            "IntelliJ IDEA Ultimate",
            "Kiro",
            "Nova",
            "PhpStorm",
            "PyCharm CE",
            "Rider",
            "RubyMine",
            "Sublime Text",
            "Trae",
            "Trae CN",
            "VSCodium",
            "Visual Studio Code",
            "Visual Studio Code - Insiders",
            "WebStorm",
            "Windsurf",
            "Xcode",
            "Zed",
        ]

        for index, app_name in enumerate(app_names):
            with self.subTest(app_name=app_name):
                process_id = 5000 + index
                cwd = "/Users/Gao/Documents/ProjectAlpha"
                session = SessionUpdate(
                    f"process-{index}",
                    "Claude Code CLI - ProjectAlpha",
                    ToolKind.CLAUDE_CODE,
                    SurfaceKind.TERMINAL,
                    SessionStatus.IDLE,
                    "Process detected",
                    SessionUpdate.now(),
                    source="process",
                    process_id=1000 + index,
                    focus_process_id=process_id,
                    focus_app_name=app_name,
                    cwd=cwd,
                )
                window_source = FakeProjectWindowSource(
                    {(process_id, app_name, cwd): f"window-{index}"}
                )
                service = MonitorService(
                    [VolatileProcessSource([[session]]), window_source],
                    SessionStore(),
                    ActionExecutor(),
                )

                payload = service.sessions_payload()

                self.assertEqual([item["session_id"] for item in payload], [f"process-{index}"])
                self.assertEqual(payload[0]["window_id"], f"window-{index}")

    def test_refresh_removes_last_stale_ide_session_without_empty_poll_grace(self):
        session = SessionUpdate(
            "process-101",
            "Claude Code CLI - SellerBooks",
            ToolKind.CLAUDE_CODE,
            SurfaceKind.TERMINAL,
            SessionStatus.IDLE,
            "Process detected",
            SessionUpdate.now(),
            source="process",
            process_id=101,
            focus_process_id=478,
            focus_app_name="Zed",
            cwd="/Users/Gao/Documents/SellerBooks",
        )
        process_source = VolatileProcessSource([[session], [session]])
        window_source = FakeProjectWindowSource(
            {
                (478, "Zed", "/Users/Gao/Documents/SellerBooks"): "window-41",
            }
        )
        service = MonitorService(
            [process_source, window_source],
            SessionStore(),
            ActionExecutor(),
            process_empty_grace_seconds=60,
        )

        first = service.sessions_payload()
        window_source.matches.clear()
        second = service.sessions_payload()

        self.assertEqual([item["session_id"] for item in first], ["process-101"])
        self.assertEqual(second, [])

    def test_refresh_preserves_ide_terminal_session_when_window_inventory_fails(self):
        session = SessionUpdate(
            "process-101",
            "Claude Code CLI - SellerBooks",
            ToolKind.CLAUDE_CODE,
            SurfaceKind.TERMINAL,
            SessionStatus.IDLE,
            "Process detected",
            SessionUpdate.now(),
            source="process",
            process_id=101,
            focus_process_id=478,
            focus_app_name="Zed",
            cwd="/Users/Gao/Documents/SellerBooks",
        )
        service = MonitorService(
            [VolatileProcessSource([[session]]), FakeProjectWindowSource({}, available=False)],
            SessionStore(),
            ActionExecutor(),
        )

        payload = service.sessions_payload()

        self.assertEqual([item["session_id"] for item in payload], ["process-101"])

    def test_refresh_does_not_require_project_window_for_supported_terminal_hosts(self):
        terminal_names = [
            "Terminal",
            "iTerm",
            "Warp",
            "WezTerm",
            "kitty",
            "Alacritty",
            "Ghostty",
            "Hyper",
            "Tabby",
            "Rio",
        ]

        for index, app_name in enumerate(terminal_names):
            with self.subTest(app_name=app_name):
                session = SessionUpdate(
                    f"process-{index}",
                    "Claude Code CLI - ProjectAlpha",
                    ToolKind.CLAUDE_CODE,
                    SurfaceKind.TERMINAL,
                    SessionStatus.IDLE,
                    "Process detected",
                    SessionUpdate.now(),
                    source="process",
                    process_id=100 + index,
                    focus_process_id=900 + index,
                    focus_app_name=app_name,
                    cwd="/Users/Gao/Documents/ProjectAlpha",
                )
                service = MonitorService(
                    [VolatileProcessSource([[session]]), FakeProjectWindowSource({})],
                    SessionStore(),
                    ActionExecutor(),
                )

                payload = service.sessions_payload()

                self.assertEqual([item["session_id"] for item in payload], [f"process-{index}"])

    def test_refresh_prefers_native_project_window_inventory_from_macos_companion(self):
        seller_books = SessionUpdate(
            "process-101",
            "Claude Code CLI - SellerBooks",
            ToolKind.CLAUDE_CODE,
            SurfaceKind.TERMINAL,
            SessionStatus.IDLE,
            "Process detected",
            SessionUpdate.now(),
            source="process",
            process_id=101,
            focus_process_id=478,
            focus_app_name="Zed",
            cwd="/Users/Gao/Documents/SellerBooks",
        )
        daily_report = SessionUpdate(
            "process-102",
            "Claude Code CLI - 日报推送",
            ToolKind.CLAUDE_CODE,
            SurfaceKind.TERMINAL,
            SessionStatus.IDLE,
            "Process detected",
            SessionUpdate.now(),
            source="process",
            process_id=102,
            focus_process_id=478,
            focus_app_name="Zed",
            cwd="/Users/Gao/Documents/日报推送",
        )
        service = MonitorService(
            [VolatileProcessSource([[seller_books, daily_report]])],
            SessionStore(),
            ActionExecutor(),
        )

        accepted = service.set_native_project_window_inventory(
            [
                {
                    "process_id": 478,
                    "available": True,
                    "windows": [
                        {"window_id": "42", "title": "日报推送 — SKILL.md"},
                    ],
                }
            ]
        )
        payload = service.sessions_payload()

        self.assertTrue(accepted)
        self.assertEqual([item["session_id"] for item in payload], ["process-102"])
        self.assertEqual(payload[0]["window_id"], "42")

    def test_native_inventory_prefers_exact_project_segment_over_prefix_window(self):
        session = SessionUpdate(
            "process-101",
            "Claude Code CLI - SellerBooks",
            ToolKind.CLAUDE_CODE,
            SurfaceKind.TERMINAL,
            SessionStatus.IDLE,
            "Process detected",
            SessionUpdate.now(),
            source="process",
            process_id=101,
            focus_process_id=478,
            focus_app_name="Zed",
            cwd="/Users/Gao/Documents/SellerBooks",
        )
        service = MonitorService(
            [VolatileProcessSource([[session]])],
            SessionStore(),
            ActionExecutor(),
        )
        self.assertTrue(
            service.set_native_project_window_inventory(
                [
                    {
                        "process_id": 478,
                        "available": True,
                        "windows": [
                            {"window_id": "wrong", "title": "SellerBooks-old — README.md"},
                            {"window_id": "correct", "title": "SellerBooks — app.py"},
                        ],
                    }
                ]
            )
        )

        payload = service.sessions_payload()

        self.assertEqual([item["session_id"] for item in payload], ["process-101"])
        self.assertEqual(payload[0]["window_id"], "correct")

    def test_native_inventory_does_not_treat_prefixed_project_as_open_session(self):
        session = SessionUpdate(
            "process-101",
            "Claude Code CLI - SellerBooks",
            ToolKind.CLAUDE_CODE,
            SurfaceKind.TERMINAL,
            SessionStatus.IDLE,
            "Process detected",
            SessionUpdate.now(),
            source="process",
            process_id=101,
            focus_process_id=478,
            focus_app_name="Zed",
            cwd="/Users/Gao/Documents/SellerBooks",
        )
        service = MonitorService(
            [VolatileProcessSource([[session]])],
            SessionStore(),
            ActionExecutor(),
        )
        self.assertTrue(
            service.set_native_project_window_inventory(
                [
                    {
                        "process_id": 478,
                        "available": True,
                        "windows": [
                            {"window_id": "other", "title": "SellerBooks-old — README.md"},
                        ],
                    }
                ]
            )
        )

        self.assertEqual(service.sessions_payload(), [])

    def test_refresh_treats_empty_native_inventory_as_no_open_project_windows(self):
        session = SessionUpdate(
            "process-101",
            "Claude Code CLI - 日报推送",
            ToolKind.CLAUDE_CODE,
            SurfaceKind.TERMINAL,
            SessionStatus.IDLE,
            "Process detected",
            SessionUpdate.now(),
            source="process",
            process_id=101,
            focus_process_id=478,
            focus_app_name="Zed",
            cwd="/Users/Gao/Documents/日报推送",
        )
        service = MonitorService(
            [VolatileProcessSource([[session]])],
            SessionStore(),
            ActionExecutor(),
        )

        self.assertTrue(service.set_native_project_window_inventory([]))

        self.assertEqual(service.sessions_payload(), [])

    def test_refresh_preserves_ide_session_when_native_app_window_list_is_unavailable(self):
        session = SessionUpdate(
            "process-101",
            "Claude Code CLI - 日报推送",
            ToolKind.CLAUDE_CODE,
            SurfaceKind.TERMINAL,
            SessionStatus.IDLE,
            "Process detected",
            SessionUpdate.now(),
            source="process",
            process_id=101,
            focus_process_id=478,
            focus_app_name="Zed",
            cwd="/Users/Gao/Documents/日报推送",
        )
        service = MonitorService(
            [VolatileProcessSource([[session]])],
            SessionStore(),
            ActionExecutor(),
        )

        self.assertTrue(
            service.set_native_project_window_inventory(
                [
                    {
                        "process_id": 478,
                        "available": False,
                        "windows": [],
                    }
                ]
            )
        )

        self.assertEqual([item["session_id"] for item in service.sessions_payload()], ["process-101"])

    def test_refresh_ignores_expired_native_project_window_inventory(self):
        clock = FakeClock()
        session = SessionUpdate(
            "process-101",
            "Claude Code CLI - 日报推送",
            ToolKind.CLAUDE_CODE,
            SurfaceKind.TERMINAL,
            SessionStatus.IDLE,
            "Process detected",
            SessionUpdate.now(),
            source="process",
            process_id=101,
            focus_process_id=478,
            focus_app_name="Zed",
            cwd="/Users/Gao/Documents/日报推送",
        )
        service = MonitorService(
            [VolatileProcessSource([[session]])],
            SessionStore(),
            ActionExecutor(),
            clock=clock.now,
            native_window_inventory_ttl_seconds=5,
        )
        self.assertTrue(service.set_native_project_window_inventory([]))
        clock.advance(6)

        payload = service.sessions_payload()

        self.assertEqual([item["session_id"] for item in payload], ["process-101"])

    def test_native_project_window_inventory_rejects_malformed_payload(self):
        service = MonitorService([], SessionStore(), ActionExecutor())

        for payload in [
            None,
            {},
            [{"process_id": True, "available": True, "windows": []}],
            [{"process_id": 478, "available": "yes", "windows": []}],
            [{"process_id": 478, "available": True, "windows": {}}],
            [{"process_id": 478, "available": True, "windows": [{"window_id": 42, "title": "日报推送"}]}],
            [{"process_id": 478, "available": True, "windows": [{"window_id": "42"}]}],
        ]:
            with self.subTest(payload=payload):
                self.assertFalse(service.set_native_project_window_inventory(payload))

    def test_refresh_polls_independent_sources_concurrently_for_visibility_budget(self):
        barrier = threading.Barrier(2)
        sources = [
            CoordinatedEmptySource(barrier),
            CoordinatedEmptySource(barrier),
        ]
        service = MonitorService(sources, SessionStore(), ActionExecutor())

        payload = service.sessions_payload()

        self.assertEqual(payload, [])
        self.assertTrue(all(source.polled for source in sources))
        self.assertTrue(all(source.overlapped for source in sources))

    def test_source_poll_timeout_keeps_healthy_source_visible_within_global_budget(self):
        blocker_started = threading.Event()
        release_blocker = threading.Event()
        blocker_finished = threading.Event()
        now = datetime(2026, 8, 4, 8, 0, tzinfo=timezone.utc)
        healthy = SessionUpdate(
            "healthy-session",
            "Healthy source",
            ToolKind.CODEX,
            SurfaceKind.TERMINAL,
            SessionStatus.RUNNING,
            "healthy",
            now,
            source="healthy",
        )

        class BlockingSource:
            def poll(self):
                blocker_started.set()
                release_blocker.wait()
                blocker_finished.set()
                return []

        class HealthySource:
            def poll(self):
                return [healthy]

        service = MonitorService(
            [BlockingSource(), HealthySource()],
            SessionStore(),
            ActionExecutor(),
            source_poll_timeout_seconds=0.05,
        )

        try:
            started_at = time.monotonic()
            with mock.patch("builtins.print") as printer:
                payload = service.sessions_payload()
            elapsed = time.monotonic() - started_at

            self.assertTrue(blocker_started.wait(timeout=0.2))
            self.assertLess(elapsed, 0.5)
            self.assertEqual([item["session_id"] for item in payload], ["healthy-session"])
            printer.assert_called_once_with(
                "AI Progress Monitor source timed out: BlockingSource",
                flush=True,
            )
        finally:
            release_blocker.set()
            self.assertTrue(blocker_finished.wait(timeout=1))

    def test_timed_out_source_is_not_repolled_or_waited_for_while_worker_is_blocked(self):
        blocker_started = threading.Event()
        release_blocker = threading.Event()
        blocker_finished = threading.Event()

        class BlockingSource:
            def __init__(self):
                self.calls = 0
                self.lock = threading.Lock()

            def poll(self):
                with self.lock:
                    self.calls += 1
                blocker_started.set()
                release_blocker.wait()
                blocker_finished.set()
                return []

        source = BlockingSource()
        service = MonitorService(
            [source],
            SessionStore(),
            ActionExecutor(),
            source_poll_timeout_seconds=0.08,
        )

        try:
            with mock.patch("builtins.print"):
                service.refresh()
            flight = service._source_poll_flights[id(source)]
            with mock.patch.object(flight.done, "wait", wraps=flight.done.wait) as old_wait:
                with mock.patch("builtins.print"):
                    service.refresh()
                old_wait.assert_not_called()

            self.assertTrue(blocker_started.wait(timeout=0.2))
            self.assertEqual(source.calls, 1)
        finally:
            release_blocker.set()
            self.assertTrue(blocker_finished.wait(timeout=1))

    def test_late_timed_out_result_is_discarded_and_next_poll_recovers(self):
        first_started = threading.Event()
        release_first = threading.Event()
        first_finished = threading.Event()
        now = datetime(2026, 8, 4, 8, 0, tzinfo=timezone.utc)
        stale = SessionUpdate(
            "stale-session",
            "Stale",
            ToolKind.CODEX,
            SurfaceKind.TERMINAL,
            SessionStatus.IDLE,
            "stale",
            now,
            source="test-source",
        )
        fresh = replace(
            stale,
            session_id="fresh-session",
            title="Fresh",
            summary="fresh",
            updated_at=now + timedelta(seconds=1),
        )

        class RecoveringSource:
            def __init__(self):
                self.calls = 0
                self.lock = threading.Lock()

            def poll(self):
                with self.lock:
                    self.calls += 1
                    call = self.calls
                if call == 1:
                    first_started.set()
                    release_first.wait()
                    first_finished.set()
                    return [stale]
                return [fresh]

        source = RecoveringSource()
        service = MonitorService(
            [source],
            SessionStore(),
            ActionExecutor(),
            source_poll_timeout_seconds=0.05,
        )

        try:
            with mock.patch("builtins.print"):
                self.assertEqual(service.refresh(), [])
            self.assertTrue(first_started.wait(timeout=0.2))
            flight = service._source_poll_flights[id(source)]
            release_first.set()
            self.assertTrue(first_finished.wait(timeout=1))
            self.assertTrue(flight.done.wait(timeout=1))

            recovered = service.refresh()

            self.assertEqual(source.calls, 2)
            self.assertEqual([session.session_id for session in recovered], ["fresh-session"])
            self.assertNotIn("stale-session", [session.session_id for session in service.store.sessions()])
        finally:
            release_first.set()

    def test_completed_and_failed_source_flights_are_repolled_next_round(self):
        now = datetime(2026, 8, 4, 8, 0, tzinfo=timezone.utc)
        recovered = SessionUpdate(
            "recovered-session",
            "Recovered",
            ToolKind.CODEX,
            SurfaceKind.TERMINAL,
            SessionStatus.IDLE,
            "recovered",
            now,
            source="recovering",
        )

        class CountingSource:
            def __init__(self):
                self.calls = 0

            def poll(self):
                self.calls += 1
                return []

        class FailingThenRecoveringSource:
            def __init__(self):
                self.calls = 0

            def poll(self):
                self.calls += 1
                if self.calls == 1:
                    raise RuntimeError("private failure")
                return [recovered]

        counting = CountingSource()
        recovering = FailingThenRecoveringSource()
        service = MonitorService(
            [counting, recovering],
            SessionStore(),
            ActionExecutor(),
            source_poll_timeout_seconds=0.2,
        )

        with mock.patch("builtins.print"):
            first = service.refresh()
            second = service.refresh()

        self.assertEqual(first, [])
        self.assertEqual(counting.calls, 2)
        self.assertEqual(recovering.calls, 2)
        self.assertEqual([session.session_id for session in second], ["recovered-session"])

    def test_partial_source_thread_start_failure_discards_started_flight_and_removes_unstarted_flight(self):
        first_started = threading.Event()
        release_first = threading.Event()
        now = datetime(2026, 8, 4, 8, 0, tzinfo=timezone.utc)
        healthy = SessionUpdate(
            "healthy-after-start-failure",
            "Healthy",
            ToolKind.CODEX,
            SurfaceKind.TERMINAL,
            SessionStatus.IDLE,
            "healthy",
            now,
            source="healthy",
        )

        class FirstSource:
            def __init__(self):
                self.calls = 0

            def poll(self):
                self.calls += 1
                if self.calls == 1:
                    first_started.set()
                    release_first.wait()
                return []

        class SecondSource:
            def __init__(self):
                self.calls = 0

            def poll(self):
                self.calls += 1
                return [healthy]

        first_source = FirstSource()
        second_source = SecondSource()
        service = MonitorService(
            [first_source, second_source],
            SessionStore(),
            ActionExecutor(),
            source_poll_timeout_seconds=0.2,
        )
        original_start = threading.Thread.start
        start_calls = 0
        first_flight = None

        def flaky_start(thread):
            nonlocal start_calls
            start_calls += 1
            if start_calls == 2:
                raise RuntimeError("thread start failed")
            return original_start(thread)

        try:
            with mock.patch("ai_progress_monitor.service.Thread.start", new=flaky_start):
                with self.assertRaisesRegex(RuntimeError, "thread start failed"):
                    service.refresh()
            self.assertTrue(first_started.wait(timeout=1))
            first_flight = service._source_poll_flights[id(first_source)]
            with first_flight.lock:
                self.assertTrue(first_flight.discard)
            self.assertNotIn(id(second_source), service._source_poll_flights)
        finally:
            release_first.set()
            if first_flight is not None:
                self.assertTrue(first_flight.done.wait(timeout=1))

        recovered = service.refresh()

        self.assertEqual(first_source.calls, 2)
        self.assertEqual(second_source.calls, 1)
        self.assertEqual(
            [session.session_id for session in recovered],
            ["healthy-after-start-failure"],
        )

    def test_concurrent_refresh_timeout_returns_last_successful_snapshot(self):
        notify_started = threading.Event()
        release_notify = threading.Event()
        alias_read_after_initial = threading.Event()
        release_alias_read = threading.Event()
        leader_finished = threading.Event()
        follower_finished = threading.Event()
        errors = []
        follower_result = []
        now = datetime(2026, 8, 4, 8, 0, tzinfo=timezone.utc)
        idle = SessionUpdate(
            "process-321",
            "Claude Code CLI - timeout-test",
            ToolKind.CLAUDE_CODE,
            SurfaceKind.TERMINAL,
            SessionStatus.IDLE,
            "idle",
            now,
            source="process",
            process_id=321,
            status_source="claude-session-prompt",
        )
        needs_action = replace(
            idle,
            status=SessionStatus.NEEDS_ACTION,
            summary="needs action",
            updated_at=now + timedelta(seconds=1),
            view_ack_required=False,
            status_source="claude-session",
        )

        def blocking_sender(_title, _message):
            notify_started.set()
            release_notify.wait()

        with tempfile.TemporaryDirectory() as temp_dir:
            class BlockingAliasPreferences(MonitorPreferences):
                def __init__(self, path):
                    super().__init__(path)
                    self.alias_calls = 0
                    self.alias_lock = threading.Lock()

                def session_alias(self, session_id):
                    with self.alias_lock:
                        self.alias_calls += 1
                        call = self.alias_calls
                    if call > 1:
                        alias_read_after_initial.set()
                        release_alias_read.wait()
                    return super().session_alias(session_id)

            preferences = BlockingAliasPreferences(Path(temp_dir) / "preferences.json")
            service = MonitorService(
                [VolatileProcessSource([[idle], [needs_action]])],
                SessionStore(audit_dir=Path(temp_dir) / "audit"),
                ActionExecutor(),
                notifier=NotificationManager(sender=blocking_sender),
                preferences=preferences,
                source_poll_timeout_seconds=0.2,
                concurrent_refresh_wait_timeout_seconds=0.05,
            )
            service.preferences.set_notifications_enabled(True)
            first = service.sessions_payload()

            def run_leader():
                try:
                    service.refresh()
                except BaseException as error:
                    errors.append(error)
                finally:
                    leader_finished.set()

            def run_follower():
                try:
                    follower_result.extend(service.sessions_payload())
                except BaseException as error:
                    errors.append(error)
                finally:
                    follower_finished.set()

            leader = threading.Thread(target=run_leader)
            follower = threading.Thread(target=run_follower)
            try:
                leader.start()
                self.assertTrue(notify_started.wait(timeout=1))
                follower.start()
                completed_before_release = follower_finished.wait(timeout=0.3)

                self.assertTrue(completed_before_release)
                self.assertEqual(errors, [])
                self.assertEqual(follower_result, first)
                self.assertIsNot(follower_result[0], first[0])
                self.assertEqual(follower_result[0]["status"], "idle")
                self.assertFalse(alias_read_after_initial.is_set())
                self.assertEqual(preferences.alias_calls, 1)
                follower_result[0]["title"] = "mutated follower payload"
                self.assertNotEqual(follower_result[0]["title"], first[0]["title"])
            finally:
                release_notify.set()
                release_alias_read.set()
                leader.join(timeout=1)
                follower.join(timeout=1)
                self.assertTrue(leader_finished.is_set())
                self.assertTrue(follower_finished.is_set())
                self.assertFalse(leader.is_alive())
                self.assertFalse(follower.is_alive())
                self.assertEqual(errors, [])

    def test_older_payload_mapping_cannot_overwrite_newer_fallback_cache(self):
        old_alias_started = threading.Event()
        release_old_alias = threading.Event()
        third_poll_started = threading.Event()
        release_third_poll = threading.Event()
        old_request_finished = threading.Event()
        blocked_refresh_finished = threading.Event()
        errors = []
        now = datetime(2026, 8, 4, 8, 0, tzinfo=timezone.utc)
        old = SessionUpdate(
            "process-101",
            "Old session",
            ToolKind.CODEX,
            SurfaceKind.TERMINAL,
            SessionStatus.IDLE,
            "old",
            now,
            source="process",
            process_id=101,
        )
        new = replace(
            old,
            session_id="process-202",
            title="New session",
            summary="new",
            updated_at=now + timedelta(seconds=1),
            process_id=202,
        )

        class SequencedSource:
            volatile_source = "process"

            def __init__(self):
                self.calls = 0

            def poll(self):
                self.calls += 1
                if self.calls == 1:
                    return [old]
                if self.calls == 2:
                    return [new]
                third_poll_started.set()
                release_third_poll.wait()
                return [new]

        with tempfile.TemporaryDirectory() as temp_dir:
            class BlockingOldAliasPreferences(MonitorPreferences):
                def __init__(self, path):
                    super().__init__(path)
                    self.alias_calls = 0
                    self.alias_lock = threading.Lock()

                def session_alias(self, session_id):
                    with self.alias_lock:
                        self.alias_calls += 1
                    if session_id == "process-101":
                        old_alias_started.set()
                        release_old_alias.wait()
                    return super().session_alias(session_id)

            source = SequencedSource()
            preferences = BlockingOldAliasPreferences(Path(temp_dir) / "preferences.json")
            service = MonitorService(
                [source],
                SessionStore(audit_dir=Path(temp_dir) / "audit"),
                ActionExecutor(),
                preferences=preferences,
                source_poll_timeout_seconds=0.5,
                concurrent_refresh_wait_timeout_seconds=0.05,
            )
            old_result = []

            def run_old_request():
                try:
                    old_result.extend(service.sessions_payload())
                except BaseException as error:
                    errors.append(error)
                finally:
                    old_request_finished.set()

            old_request = threading.Thread(target=run_old_request)
            old_request.start()
            self.assertTrue(old_alias_started.wait(timeout=1))

            new_result = service.sessions_payload()
            self.assertEqual([item["session_id"] for item in new_result], ["process-202"])

            release_old_alias.set()
            old_request.join(timeout=1)
            self.assertTrue(old_request_finished.is_set())
            self.assertEqual([item["session_id"] for item in old_result], ["process-101"])

            def run_blocked_refresh():
                try:
                    service.refresh()
                except BaseException as error:
                    errors.append(error)
                finally:
                    blocked_refresh_finished.set()

            blocked_refresh = threading.Thread(target=run_blocked_refresh)
            try:
                blocked_refresh.start()
                self.assertTrue(third_poll_started.wait(timeout=1))

                fallback = service.sessions_payload()

                self.assertEqual([item["session_id"] for item in fallback], ["process-202"])
                self.assertEqual(preferences.alias_calls, 2)
                self.assertIsNot(fallback[0], new_result[0])
                fallback[0]["title"] = "mutated fallback"
                self.assertEqual(new_result[0]["title"], "New session")
                self.assertEqual(errors, [])
            finally:
                release_third_poll.set()
                blocked_refresh.join(timeout=1)
                self.assertTrue(blocked_refresh_finished.is_set())
                self.assertFalse(blocked_refresh.is_alive())
                self.assertEqual(errors, [])

    def test_concurrent_refresh_timeout_without_successful_snapshot_returns_empty(self):
        read_started = threading.Event()
        release_read = threading.Event()
        leader_finished = threading.Event()
        follower_finished = threading.Event()
        follower_result = []
        errors = []

        class BlockingPreferences:
            def notifications_enabled(self):
                return True

            def is_hidden(self, _session_id):
                read_started.set()
                release_read.wait()
                return False

        service = MonitorService(
            [DemoSource()],
            SessionStore(),
            ActionExecutor(),
            preferences=BlockingPreferences(),
            concurrent_refresh_wait_timeout_seconds=0.05,
        )

        def run_leader():
            try:
                service.refresh()
            except BaseException as error:
                errors.append(error)
            finally:
                leader_finished.set()

        def run_follower():
            try:
                follower_result.extend(service.sessions_payload())
            except BaseException as error:
                errors.append(error)
            finally:
                follower_finished.set()

        leader = threading.Thread(target=run_leader)
        follower = threading.Thread(target=run_follower)
        try:
            leader.start()
            self.assertTrue(read_started.wait(timeout=1))
            follower.start()
            self.assertTrue(follower_finished.wait(timeout=0.3))
            self.assertEqual(follower_result, [])
        finally:
            release_read.set()
            leader.join(timeout=1)
            follower.join(timeout=1)
            self.assertTrue(leader_finished.is_set())
            self.assertTrue(follower_finished.is_set())
            self.assertFalse(leader.is_alive())
            self.assertFalse(follower.is_alive())
            self.assertEqual(errors, [])

    def test_source_and_follower_timeout_configuration_rejects_non_finite_or_non_positive_values(self):
        invalid_values = [0, -1, float("inf"), float("nan")]
        for parameter in ["source_poll_timeout_seconds", "concurrent_refresh_wait_timeout_seconds"]:
            for value in invalid_values:
                with self.subTest(parameter=parameter, value=value):
                    with self.assertRaises(ValueError):
                        MonitorService(
                            [],
                            SessionStore(),
                            ActionExecutor(),
                            **{parameter: value},
                        )

    def test_failed_poll_generation_gap_does_not_confirm_verified_running_restart(self):
        third_started = threading.Event()
        release_third = threading.Event()
        third_finished = threading.Event()
        wall_clock = FakeDateTimeClock(datetime(2026, 8, 4, 10, 0, tzinfo=timezone.utc))
        monotonic_clock = FakeClock()
        monotonic_clock.value = 100.0
        terminal = SessionUpdate(
            "process-24645",
            "Claude Code CLI - generation-test",
            ToolKind.CLAUDE_CODE,
            SurfaceKind.TERMINAL,
            SessionStatus.NEEDS_ACTION,
            "terminal",
            wall_clock.now(),
            source="process",
            process_id=24645,
            view_ack_required=True,
            status_source="claude-session",
            observed_at=wall_clock.now(),
        )
        rolled_back_wall = wall_clock.now() - timedelta(hours=1)
        running = replace(
            terminal,
            status=SessionStatus.RUNNING,
            summary="running candidate",
            updated_at=rolled_back_wall,
            view_ack_required=False,
            status_source="claude-session-verified",
            observed_at=rolled_back_wall,
        )

        class GapSource:
            volatile_source = "process"

            def __init__(self):
                self.calls = 0

            def poll(self):
                self.calls += 1
                if self.calls == 1:
                    return [terminal]
                if self.calls == 3:
                    third_started.set()
                    release_third.wait()
                    third_finished.set()
                return [running]

        with tempfile.TemporaryDirectory() as temp_dir:
            source = GapSource()
            service = MonitorService(
                [source],
                SessionStore(stuck_after_seconds=60, audit_dir=Path(temp_dir) / "audit"),
                ActionExecutor(),
                preferences=MonitorPreferences(Path(temp_dir) / "preferences.json"),
                clock=monotonic_clock.now,
                now=wall_clock.now,
                source_poll_timeout_seconds=0.05,
            )

            try:
                first = service.refresh()[0]
                monotonic_clock.advance(1)
                wall_clock.value = rolled_back_wall
                second = service.refresh()[0]
                monotonic_clock.advance(1)
                wall_clock.advance(1)
                with mock.patch("builtins.print"):
                    after_timeout = service.refresh()[0]
                self.assertTrue(third_started.wait(timeout=0.2))
                flight = service._source_poll_flights[id(source)]
                release_third.set()
                self.assertTrue(third_finished.wait(timeout=1))
                self.assertTrue(flight.done.wait(timeout=1))
                monotonic_clock.advance(1)
                wall_clock.advance(1)
                after_gap = service.refresh()[0]
                monotonic_clock.advance(1)
                wall_clock.advance(1)
                after_consecutive = service.refresh()[0]

                self.assertEqual(first.status, SessionStatus.NEEDS_ACTION)
                self.assertEqual(second.status, SessionStatus.NEEDS_ACTION)
                self.assertEqual(after_timeout.status, SessionStatus.NEEDS_ACTION)
                self.assertEqual(after_gap.status, SessionStatus.NEEDS_ACTION)
                self.assertEqual(after_consecutive.status, SessionStatus.RUNNING)
                self.assertEqual(source.calls, 5)
            finally:
                release_third.set()

    def test_service_stamps_only_identity_verified_claude_process_observations(self):
        observed_at = datetime(2026, 8, 4, 10, 0, tzinfo=timezone.utc)
        monotonic_clock = FakeClock()
        monotonic_clock.value = 50.0
        claude = SessionUpdate(
            "process-24645",
            "Claude Code CLI - metadata-test",
            ToolKind.CLAUDE_CODE,
            SurfaceKind.TERMINAL,
            SessionStatus.RUNNING,
            "running",
            observed_at,
            source="process",
            process_id=24645,
            status_source="claude-session-verified",
            observed_at=observed_at,
        )
        qoder = SessionUpdate(
            "qoder-task-1",
            "Qoder Desktop - metadata-test",
            ToolKind.UNKNOWN,
            SurfaceKind.DESKTOP,
            SessionStatus.RUNNING,
            "running",
            observed_at,
            source="process",
            process_id=51005,
            status_source="qoder-log",
            tool_display_name="Qoder",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            service = MonitorService(
                [VolatileProcessSource([[claude, qoder]])],
                SessionStore(audit_dir=Path(temp_dir) / "audit"),
                ActionExecutor(),
                preferences=MonitorPreferences(Path(temp_dir) / "preferences.json"),
                clock=monotonic_clock.now,
                now=lambda: observed_at,
            )

            sessions = {session.session_id: session for session in service.refresh()}

        stamped = sessions["process-24645"]
        untouched = sessions["qoder-task-1"]
        self.assertEqual(stamped.observation_sequence, 1)
        self.assertEqual(stamped.observed_monotonic, 50.0)
        self.assertFalse(stamped.observation_clock_adjusted)
        self.assertEqual(stamped.observation_wall_at, observed_at)
        self.assertIsNone(untouched.observation_sequence)
        self.assertIsNone(untouched.observed_monotonic)
        self.assertFalse(untouched.observation_clock_adjusted)
        self.assertIsNone(untouched.observation_wall_at)

    def test_service_detects_wall_clock_rollback_and_accepts_verified_prompt(self):
        wall_clock = FakeDateTimeClock(datetime(2026, 8, 4, 10, 0, tzinfo=timezone.utc))
        monotonic_clock = FakeClock()
        monotonic_clock.value = 100.0
        running = SessionUpdate(
            "process-24645",
            "Claude Code CLI - rollback-test",
            ToolKind.CLAUDE_CODE,
            SurfaceKind.TERMINAL,
            SessionStatus.RUNNING,
            "running",
            wall_clock.now(),
            source="process",
            process_id=24645,
            status_source="claude-session-verified",
            observed_at=wall_clock.now(),
        )
        rolled_back_wall = wall_clock.now() - timedelta(hours=1)
        prompt = replace(
            running,
            status=SessionStatus.IDLE,
            summary="prompt after rollback",
            updated_at=rolled_back_wall,
            status_source="claude-session-prompt",
            observed_at=rolled_back_wall,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            service = MonitorService(
                [VolatileProcessSource([[running], [prompt]])],
                SessionStore(stuck_after_seconds=60, audit_dir=Path(temp_dir) / "audit"),
                ActionExecutor(),
                preferences=MonitorPreferences(Path(temp_dir) / "preferences.json"),
                clock=monotonic_clock.now,
                now=wall_clock.now,
            )

            first = service.refresh()[0]
            monotonic_clock.advance(1)
            wall_clock.value = rolled_back_wall
            second = service.refresh()[0]

        self.assertEqual(first.status, SessionStatus.RUNNING)
        self.assertEqual(second.status, SessionStatus.NEEDS_ACTION)
        self.assertEqual(second.observation_sequence, 2)
        self.assertEqual(second.observed_monotonic, 101.0)
        self.assertTrue(second.observation_clock_adjusted)
        self.assertEqual(second.observation_wall_at, rolled_back_wall)

    def test_service_uses_monotonic_age_for_verified_running_source_failure_and_recovery(self):
        wall_clock = FakeDateTimeClock(datetime(2026, 8, 4, 10, 0, tzinfo=timezone.utc))
        monotonic_clock = FakeClock()
        monotonic_clock.value = 100.0
        running = SessionUpdate(
            "process-24645",
            "Claude Code CLI - stuck-test",
            ToolKind.CLAUDE_CODE,
            SurfaceKind.TERMINAL,
            SessionStatus.RUNNING,
            "running",
            wall_clock.now(),
            source="process",
            process_id=24645,
            status_source="claude-session-verified",
            observed_at=wall_clock.now(),
        )
        rolled_back_wall = wall_clock.now() - timedelta(hours=1)
        recovered = replace(
            running,
            summary="recovered",
            updated_at=rolled_back_wall,
            observed_at=rolled_back_wall,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            service = MonitorService(
                [VolatileProcessSource([[running], None, [recovered]])],
                SessionStore(stuck_after_seconds=60, audit_dir=Path(temp_dir) / "audit"),
                ActionExecutor(),
                preferences=MonitorPreferences(Path(temp_dir) / "preferences.json"),
                clock=monotonic_clock.now,
                now=wall_clock.now,
            )

            first = service.refresh()[0]
            monotonic_clock.advance(60)
            wall_clock.value = rolled_back_wall
            during_failure = service.refresh()[0]
            monotonic_clock.advance(1)
            wall_clock.advance(1)
            after_recovery = service.refresh()[0]

        self.assertEqual(first.status, SessionStatus.RUNNING)
        self.assertEqual(during_failure.status, SessionStatus.STUCK)
        self.assertEqual(after_recovery.status, SessionStatus.RUNNING)
        self.assertEqual(
            service.store._verified_running_monotonic_by_session["process-24645"],
            161.0,
        )

    def test_concurrent_refreshes_share_inflight_snapshot_then_next_refresh_advances(self):
        first_started = threading.Event()
        release_first = threading.Event()
        second_call_attempted = threading.Event()
        second_polled = threading.Event()
        second_finished = threading.Event()
        errors = []
        now = datetime(2026, 7, 31, 5, 25, tzinfo=timezone.utc)
        old = SessionUpdate(
            "process-old",
            "Old process",
            ToolKind.CODEX,
            SurfaceKind.TERMINAL,
            SessionStatus.IDLE,
            "old",
            now,
            source="process",
            process_id=101,
        )
        new = replace(
            old,
            session_id="process-new",
            title="New process",
            summary="new",
            updated_at=now + timedelta(seconds=1),
            process_id=202,
        )

        class OutOfOrderProcessSource:
            volatile_source = "process"

            def __init__(self):
                self._lock = threading.Lock()
                self._calls = 0

            def poll(self):
                with self._lock:
                    self._calls += 1
                    call = self._calls
                if call == 1:
                    first_started.set()
                    release_first.wait(timeout=2)
                    return [old]
                second_polled.set()
                return [new]

        source = OutOfOrderProcessSource()
        store = SessionStore(stuck_after_seconds=300)
        service = MonitorService([source], store, ActionExecutor())

        def refresh(first=False):
            if not first:
                second_call_attempted.set()
            try:
                service.refresh()
            except Exception as exc:
                errors.append(exc)
            finally:
                if not first:
                    second_finished.set()

        first_thread = threading.Thread(target=refresh, kwargs={"first": True})
        second_thread = threading.Thread(target=refresh)
        first_thread.start()
        self.assertTrue(first_started.wait(timeout=1))
        second_thread.start()
        self.assertTrue(second_call_attempted.wait(timeout=1))
        second_entered_before_release = second_polled.wait(timeout=0.2)
        second_completed_before_release = second_finished.wait(timeout=0.2)
        release_first.set()
        first_thread.join(timeout=2)
        second_thread.join(timeout=2)

        self.assertFalse(first_thread.is_alive())
        self.assertFalse(second_thread.is_alive())
        self.assertEqual(errors, [])
        self.assertFalse(second_entered_before_release)
        self.assertFalse(second_completed_before_release)
        self.assertFalse(second_polled.is_set())
        self.assertEqual(
            [session.session_id for session in store.sessions(now=now + timedelta(seconds=2))],
            ["process-old"],
        )

        service.refresh()

        self.assertTrue(second_polled.is_set())
        self.assertEqual(
            [session.session_id for session in store.sessions(now=now + timedelta(seconds=2))],
            ["process-new"],
        )

    def test_concurrent_refresh_failure_releases_waiter_and_next_refresh_recovers(self):
        first_read_started = threading.Event()
        release_first_read = threading.Event()

        class FailingOncePreferences:
            def __init__(self):
                self._lock = threading.Lock()
                self._failed = False

            def is_hidden(self, _session_id):
                with self._lock:
                    should_fail = not self._failed
                    if should_fail:
                        self._failed = True
                if should_fail:
                    first_read_started.set()
                    release_first_read.wait(timeout=2)
                    raise ValueError("first refresh failed")
                return False

        service = MonitorService(
            [DemoSource()],
            SessionStore(),
            ActionExecutor(),
            preferences=FailingOncePreferences(),
        )
        errors = {}

        def refresh(label):
            try:
                service.refresh()
            except BaseException as error:
                errors[label] = error

        leader = threading.Thread(target=refresh, args=("leader",))
        waiter = threading.Thread(target=refresh, args=("waiter",))
        leader.start()
        self.assertTrue(first_read_started.wait(timeout=1))
        flight = service._refresh_flight
        self.assertIsNotNone(flight)
        waiter_started_waiting = threading.Event()
        original_wait = flight.done.wait

        def wait_for_flight(timeout=None):
            waiter_started_waiting.set()
            return original_wait(timeout)

        with mock.patch.object(flight.done, "wait", side_effect=wait_for_flight):
            waiter.start()
            self.assertTrue(waiter_started_waiting.wait(timeout=1))
            release_first_read.set()
            leader.join(timeout=2)
            waiter.join(timeout=2)

        self.assertFalse(leader.is_alive())
        self.assertFalse(waiter.is_alive())
        self.assertIsInstance(errors["leader"], ValueError)
        self.assertIsInstance(errors["waiter"], RuntimeError)
        self.assertIsInstance(errors["waiter"].__cause__, ValueError)
        self.assertEqual(len(service.refresh()), 3)

    def test_recursive_refresh_from_notifier_fails_without_deadlock(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            service_holder = {}
            notifier = NotificationManager(sender=lambda _title, _message: service_holder["service"].refresh())
            preferences = MonitorPreferences(Path(temp_dir) / "preferences.json")
            preferences.set_notifications_enabled(True)
            service = MonitorService(
                [DemoSource()],
                SessionStore(audit_dir=Path(temp_dir) / "audit"),
                ActionExecutor(),
                notifier=notifier,
                preferences=preferences,
            )
            service_holder["service"] = service

            with self.assertRaisesRegex(RuntimeError, "cannot be called recursively"):
                service.refresh()

    def test_refresh_isolates_one_failed_source_and_keeps_other_sessions_visible(self):
        class BrokenSource:
            def poll(self):
                raise RuntimeError("private source detail")

        service = MonitorService([BrokenSource(), DemoSource()], SessionStore(), ActionExecutor())

        with mock.patch("builtins.print") as printer:
            payload = service.sessions_payload()

        self.assertEqual(len(payload), 3)
        printer.assert_called_once_with(
            "AI Progress Monitor source failed: BrokenSource (RuntimeError)",
            flush=True,
        )

    def test_visible_sessions_hide_process_only_duplicate_when_full_session_has_same_process_id(self):
        full = SessionUpdate(
            "json-claude",
            "Claude Code - task",
            ToolKind.CLAUDE_CODE,
            SurfaceKind.TERMINAL,
            SessionStatus.RUNNING,
            "full",
            SessionUpdate.now(),
            source="json:task.json",
            process_id=1234,
        )
        process_only = SessionUpdate(
            "process-1234",
            "Claude Code CLI",
            ToolKind.CLAUDE_CODE,
            SurfaceKind.TERMINAL,
            SessionStatus.RUNNING,
            "process",
            SessionUpdate.now(),
            source="process",
            process_id=1234,
        )
        store = SessionStore()
        store.apply_updates([full, process_only])
        service = MonitorService([], store, ActionExecutor())

        payload = service.sessions_payload()

        self.assertEqual([session["session_id"] for session in payload], ["json-claude"])
        self.assertEqual(payload[0]["monitoring_level"], "full")

    def test_visible_sessions_hide_desktop_process_only_duplicate_when_window_scan_has_same_process_id(self):
        full_window = SessionUpdate(
            "window-42",
            "Codex Desktop - PRD",
            ToolKind.CODEX,
            SurfaceKind.DESKTOP,
            SessionStatus.RUNNING,
            "window",
            SessionUpdate.now(),
            source="os-window",
            window_id="42",
            process_id=38434,
        )
        process_only = SessionUpdate(
            "process-38434",
            "Codex Desktop",
            ToolKind.CODEX,
            SurfaceKind.DESKTOP,
            SessionStatus.RUNNING,
            "process",
            SessionUpdate.now(),
            source="process",
            process_id=38434,
            focus_process_id=38434,
            focus_app_name="Codex",
        )
        store = SessionStore()
        store.apply_updates([process_only, full_window])
        service = MonitorService([], store, ActionExecutor())

        payload = service.sessions_payload()

        self.assertEqual([session["session_id"] for session in payload], ["window-42"])
        self.assertEqual(payload[0]["monitoring_level"], "full")

    def test_workbuddy_runtime_log_session_remains_visible_with_db_session_on_same_process(self):
        updated_at = datetime(2026, 7, 24, 5, 18, 51, tzinfo=timezone.utc)
        completed = SessionUpdate(
            "workbuddy-completed",
            "WorkBuddy Desktop - Test session",
            ToolKind.UNKNOWN,
            SurfaceKind.DESKTOP,
            SessionStatus.NEEDS_ACTION,
            "WorkBuddy 任务已完成或需要用户处理。",
            updated_at,
            source="process",
            process_id=46529,
            focus_process_id=46529,
            focus_app_name="WorkBuddy",
            view_ack_required=True,
            status_source="workbuddy-db",
            tool_display_name="WorkBuddy",
        )
        running = SessionUpdate(
            "workbuddy-running",
            "WorkBuddy Desktop - Test again",
            ToolKind.UNKNOWN,
            SurfaceKind.DESKTOP,
            SessionStatus.RUNNING,
            "WorkBuddy 正在处理任务。",
            updated_at,
            source="process",
            process_id=46529,
            focus_process_id=46529,
            focus_app_name="WorkBuddy",
            status_source="workbuddy-log",
            tool_display_name="WorkBuddy",
        )
        service = MonitorService(
            [VolatileProcessSource([[completed, running]])],
            SessionStore(),
            ActionExecutor(),
            now=lambda: updated_at,
        )

        payload = service.sessions_payload()

        self.assertEqual(
            [(session["session_id"], session["status"]) for session in payload],
            [
                ("workbuddy-completed", "needs_action"),
                ("workbuddy-running", "running"),
            ],
        )
        self.assertEqual({session["monitoring_level"] for session in payload}, {"full"})

    def test_workbuddy_runtime_log_session_survives_one_missing_poll_and_accepts_completion(self):
        running_at = datetime(2026, 7, 24, 5, 18, 51, tzinfo=timezone.utc)
        completed_at = datetime(2026, 7, 24, 5, 19, 26, tzinfo=timezone.utc)
        existing = SessionUpdate(
            "workbuddy-existing",
            "WorkBuddy Desktop - Test session",
            ToolKind.UNKNOWN,
            SurfaceKind.DESKTOP,
            SessionStatus.NEEDS_ACTION,
            "WorkBuddy 任务已完成或需要用户处理。",
            running_at,
            source="process",
            process_id=46529,
            focus_process_id=46529,
            focus_app_name="WorkBuddy",
            view_ack_required=True,
            status_source="workbuddy-db",
            tool_display_name="WorkBuddy",
        )
        running = SessionUpdate(
            "workbuddy-running",
            "WorkBuddy Desktop - Test again",
            ToolKind.UNKNOWN,
            SurfaceKind.DESKTOP,
            SessionStatus.RUNNING,
            "WorkBuddy 正在处理任务。",
            running_at,
            source="process",
            process_id=46529,
            focus_process_id=46529,
            focus_app_name="WorkBuddy",
            status_source="workbuddy-log",
            tool_display_name="WorkBuddy",
        )
        completed = replace(
            running,
            status=SessionStatus.NEEDS_ACTION,
            summary="WorkBuddy 任务已完成或需要用户处理。",
            updated_at=completed_at,
            view_ack_required=True,
            status_source="workbuddy-db",
        )
        source = VolatileProcessSource(
            [
                [existing, running],
                [existing],
                [existing, completed],
            ]
        )
        clock = FakeDateTimeClock(running_at)
        service = MonitorService([source], SessionStore(), ActionExecutor(), now=clock.now)

        first = service.sessions_payload()
        retained = service.sessions_payload()
        clock.advance(seconds=35)
        finished = service.sessions_payload()

        self.assertEqual(
            [(session["session_id"], session["status"]) for session in first],
            [
                ("workbuddy-existing", "needs_action"),
                ("workbuddy-running", "running"),
            ],
        )
        self.assertEqual(
            [(session["session_id"], session["status"]) for session in retained],
            [
                ("workbuddy-existing", "needs_action"),
                ("workbuddy-running", "running"),
            ],
        )
        self.assertEqual(
            [(session["session_id"], session["status"]) for session in finished],
            [
                ("workbuddy-running", "needs_action"),
                ("workbuddy-existing", "needs_action"),
            ],
        )
        self.assertEqual({session["monitoring_level"] for session in retained}, {"full"})

    def test_visible_sessions_hide_generic_desktop_fallback_when_full_desktop_session_exists(self):
        full_session = SessionUpdate(
            "codex-session-1",
            "Codex Desktop - 20260703AICoding",
            ToolKind.CODEX,
            SurfaceKind.DESKTOP,
            SessionStatus.RUNNING,
            "codex session",
            SessionUpdate.now(),
            source="codex-session",
        )
        process_only = SessionUpdate(
            "process-38434",
            "Codex Desktop",
            ToolKind.CODEX,
            SurfaceKind.DESKTOP,
            SessionStatus.IDLE,
            "desktop fallback",
            SessionUpdate.now(),
            source="process",
            process_id=38434,
            focus_process_id=38434,
            focus_app_name="Codex",
            tool_display_name="Codex",
        )
        store = SessionStore()
        store.apply_updates([process_only, full_session])
        service = MonitorService([], store, ActionExecutor())

        payload = service.sessions_payload()

        self.assertEqual([session["session_id"] for session in payload], ["codex-session-1"])
        self.assertEqual(payload[0]["monitoring_level"], "full")

    def test_chatgpt_full_session_replaces_idle_fallback_and_focuses_chatgpt(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            full_session = SessionUpdate(
                "chatgpt-session-1",
                "ChatGPT Desktop - 20260703AIcoding",
                ToolKind.CHATGPT,
                SurfaceKind.DESKTOP,
                SessionStatus.NEEDS_ACTION,
                "ChatGPT 回复已完成，等待查看。",
                SessionUpdate.now(),
                source="chatgpt-session",
                focus_app_name="ChatGPT",
                tool_display_name="ChatGPT",
                view_ack_required=True,
            )
            app_fallback = SessionUpdate(
                "process-40001",
                "ChatGPT Desktop",
                ToolKind.CHATGPT,
                SurfaceKind.DESKTOP,
                SessionStatus.IDLE,
                "desktop fallback",
                SessionUpdate.now(),
                source="process",
                process_id=40001,
                focus_process_id=40001,
                focus_app_name="ChatGPT",
                tool_display_name="ChatGPT",
            )
            store = SessionStore(audit_dir=Path(temp_dir))
            store.apply_updates([app_fallback, full_session])
            focused = []
            focus_manager = WindowFocusManager(sender=lambda target: focused.append(target) or FocusResult(True, "focused"))
            service = MonitorService([], store, ActionExecutor(), focus_manager=focus_manager)

            payload = service.sessions_payload()
            result = service.focus_session("chatgpt-session-1")

            self.assertEqual([session["session_id"] for session in payload], ["chatgpt-session-1"])
            self.assertEqual(payload[0]["monitoring_level"], "full")
            self.assertTrue(result.ok)
            self.assertEqual(focused[0].app_name, "ChatGPT")
            self.assertEqual(service.sessions_payload()[0]["status"], "idle")

    def test_process_only_payload_includes_focus_metadata_for_bubble_navigation(self):
        source = VolatileProcessSource(
            [
                [
                    SessionUpdate(
                        "process-38434",
                        "Codex Desktop",
                        ToolKind.CODEX,
                        SurfaceKind.DESKTOP,
                        SessionStatus.RUNNING,
                        "process",
                        SessionUpdate.now(),
                        source="process",
                        process_id=38434,
                        focus_process_id=38434,
                        focus_app_name="Codex",
                    )
                ]
            ]
        )
        service = MonitorService([source], SessionStore(), ActionExecutor())

        payload = service.sessions_payload()

        self.assertEqual(payload[0]["monitoring_level"], "process_only")
        self.assertEqual(payload[0]["focus_process_id"], 38434)
        self.assertEqual(payload[0]["focus_app_name"], "Codex")

    def test_payload_marks_configured_generated_desktop_conversation_paths(self):
        generated = SessionUpdate(
            "codex-generated",
            "Codex Desktop - hello",
            ToolKind.CODEX,
            SurfaceKind.DESKTOP,
            SessionStatus.IDLE,
            "generated",
            SessionUpdate.now(),
            source="codex-session",
            cwd="/Users/Gao/Documents/Codex/2026-07-07/hello",
            generated_conversation_path=True,
        )
        project = SessionUpdate(
            "codex-project",
            "Codex Desktop - 20260703AIcoding",
            ToolKind.CODEX,
            SurfaceKind.DESKTOP,
            SessionStatus.RUNNING,
            "project",
            SessionUpdate.now(),
            source="codex-session",
            cwd="/Users/Gao/Documents/20260703AIcoding",
        )
        store = SessionStore()
        store.apply_updates([generated, project])
        service = MonitorService([], store, ActionExecutor())

        payload = {session["session_id"]: session for session in service.sessions_payload()}

        self.assertTrue(payload["codex-generated"]["generated_conversation_path"])
        self.assertFalse(payload["codex-project"]["generated_conversation_path"])

    def test_visible_sessions_keep_multiple_running_process_only_sessions_in_same_folder(self):
        first_running = SessionUpdate(
            "process-100",
            "Claude Code CLI - checkout-flow",
            ToolKind.CLAUDE_CODE,
            SurfaceKind.TERMINAL,
            SessionStatus.RUNNING,
            "process",
            datetime(2026, 7, 2, 8, 0, tzinfo=timezone.utc),
            source="process",
            process_id=100,
            focus_process_id=75407,
            focus_app_name="Zed",
            cwd="/Users/Gao/Documents/projects/checkout-flow",
        )
        second_running = SessionUpdate(
            "process-101",
            "Claude Code CLI - checkout-flow",
            ToolKind.CLAUDE_CODE,
            SurfaceKind.TERMINAL,
            SessionStatus.RUNNING,
            "process",
            datetime(2026, 7, 2, 8, 1, tzinfo=timezone.utc),
            source="process",
            process_id=101,
            focus_process_id=75407,
            focus_app_name="Zed",
            cwd="/Users/Gao/Documents/projects/checkout-flow",
        )
        store = SessionStore()
        store.apply_updates([first_running, second_running])
        service = MonitorService([], store, ActionExecutor())

        payload = service.sessions_payload()

        self.assertCountEqual([session["session_id"] for session in payload], ["process-100", "process-101"])

    def test_focus_session_uses_session_title(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            focused = []
            focus_manager = WindowFocusManager(sender=lambda target: focused.append(target.title) or FocusResult(True, "focused"))
            service = MonitorService(
                [DemoSource()],
                SessionStore(audit_dir=Path(temp_dir)),
                ActionExecutor(),
                focus_manager=focus_manager,
            )
            service.refresh()

            result = service.focus_session("demo-claude-1")

            self.assertTrue(result.ok)
            self.assertEqual(focused, ["Claude Code - checkout-flow"])

    def test_focus_session_marks_view_ack_session_viewed_on_success(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SessionStore(audit_dir=Path(temp_dir))
            store.apply_updates(
                [
                    SessionUpdate(
                        "codex-1",
                        "Codex Desktop - checkout-flow",
                        ToolKind.CODEX,
                        SurfaceKind.DESKTOP,
                        SessionStatus.NEEDS_ACTION,
                        "reply",
                        datetime(2026, 7, 2, 9, 0, tzinfo=timezone.utc),
                        view_ack_required=True,
                    )
                ]
            )
            focus_manager = WindowFocusManager(sender=lambda target: FocusResult(True, "focused"))
            service = MonitorService([], store, ActionExecutor(), focus_manager=focus_manager)

            result = service.focus_session("codex-1")

            self.assertTrue(result.ok)
            self.assertEqual(service.sessions_payload()[0]["status"], "idle")

    def test_viewed_desktop_conversation_expires_after_fifteen_minutes_and_reveals_app_fallback(self):
        clock = FakeDateTimeClock(datetime(2026, 7, 2, 9, 0, tzinfo=timezone.utc))
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SessionStore(audit_dir=Path(temp_dir))
            specific_session = SessionUpdate(
                "codex-session-1",
                "Codex Desktop - hello",
                ToolKind.CODEX,
                SurfaceKind.DESKTOP,
                SessionStatus.NEEDS_ACTION,
                "reply",
                datetime(2026, 7, 2, 8, 59, tzinfo=timezone.utc),
                source="codex-session",
                view_ack_required=True,
            )
            app_fallback = SessionUpdate(
                "process-codex",
                "Codex Desktop",
                ToolKind.CODEX,
                SurfaceKind.DESKTOP,
                SessionStatus.IDLE,
                "app alive",
                datetime(2026, 7, 2, 8, 59, tzinfo=timezone.utc),
                source="process",
                process_id=38434,
                focus_process_id=38434,
                focus_app_name="Codex",
                tool_display_name="Codex",
            )
            store.apply_updates([app_fallback, specific_session])
            focus_manager = WindowFocusManager(sender=lambda target: FocusResult(True, "focused"))
            service = MonitorService(
                [],
                store,
                ActionExecutor(),
                focus_manager=focus_manager,
                now=clock.now,
            )

            self.assertEqual([session["session_id"] for session in service.sessions_payload()], ["codex-session-1"])

            result = service.focus_session("codex-session-1")

            self.assertTrue(result.ok)
            self.assertEqual(
                [(session["session_id"], session["status"]) for session in service.sessions_payload()],
                [("codex-session-1", "idle")],
            )

            clock.advance(seconds=14 * 60 + 59)
            self.assertEqual([session["session_id"] for session in service.sessions_payload()], ["codex-session-1"])

            clock.advance(seconds=1)
            payload = service.sessions_payload()

            self.assertEqual([session["session_id"] for session in payload], ["process-codex"])
            self.assertEqual(payload[0]["status"], "idle")
            self.assertEqual(payload[0]["monitoring_level"], "process_only")

    def test_viewed_chatgpt_conversation_survives_source_dropout_while_app_is_running(self):
        clock = FakeDateTimeClock(datetime(2026, 7, 2, 9, 0, tzinfo=timezone.utc))
        chatgpt_session = SessionUpdate(
            "chatgpt-session-alpha",
            "ChatGPT Desktop - Test again",
            ToolKind.CHATGPT,
            SurfaceKind.DESKTOP,
            SessionStatus.NEEDS_ACTION,
            "ChatGPT reply",
            datetime(2026, 7, 2, 9, 0, tzinfo=timezone.utc),
            source="chatgpt-session",
            focus_app_name="ChatGPT",
            view_ack_required=True,
            tool_display_name="ChatGPT",
        )
        app_fallback = SessionUpdate(
            "process-40001",
            "ChatGPT Desktop",
            ToolKind.CHATGPT,
            SurfaceKind.DESKTOP,
            SessionStatus.IDLE,
            "ChatGPT app is running",
            datetime(2026, 7, 2, 9, 0, tzinfo=timezone.utc),
            source="process",
            process_id=40001,
            focus_process_id=40001,
            focus_app_name="ChatGPT",
            status_source="desktop-process",
            tool_display_name="ChatGPT",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            service = MonitorService(
                [
                    VolatileChatGPTSource([[chatgpt_session], [], []]),
                    VolatileProcessSource([[app_fallback], [app_fallback], [app_fallback]]),
                ],
                SessionStore(audit_dir=Path(temp_dir)),
                ActionExecutor(),
                focus_manager=WindowFocusManager(sender=lambda target: FocusResult(True, "focused-chatgpt")),
                now=clock.now,
            )

            self.assertEqual(
                [session["session_id"] for session in service.sessions_payload()],
                ["chatgpt-session-alpha"],
            )
            self.assertTrue(service.focus_session("chatgpt-session-alpha").ok)

            clock.advance(seconds=14 * 60 + 59)
            retained_payload = service.sessions_payload()

            self.assertEqual(
                [(session["session_id"], session["status"]) for session in retained_payload],
                [("chatgpt-session-alpha", "idle")],
            )

            clock.advance(seconds=1)
            expired_payload = service.sessions_payload()

            self.assertEqual([session["session_id"] for session in expired_payload], ["process-40001"])
            self.assertEqual(expired_payload[0]["monitoring_level"], "process_only")

    def test_viewed_chatgpt_conversation_does_not_survive_after_app_exits(self):
        clock = FakeDateTimeClock(datetime(2026, 7, 2, 9, 0, tzinfo=timezone.utc))
        process_clock = FakeClock()
        chatgpt_session = SessionUpdate(
            "chatgpt-session-alpha",
            "ChatGPT Desktop - Test again",
            ToolKind.CHATGPT,
            SurfaceKind.DESKTOP,
            SessionStatus.NEEDS_ACTION,
            "ChatGPT reply",
            datetime(2026, 7, 2, 9, 0, tzinfo=timezone.utc),
            source="chatgpt-session",
            focus_app_name="ChatGPT",
            view_ack_required=True,
            tool_display_name="ChatGPT",
        )
        app_fallback = SessionUpdate(
            "process-40001",
            "ChatGPT Desktop",
            ToolKind.CHATGPT,
            SurfaceKind.DESKTOP,
            SessionStatus.IDLE,
            "ChatGPT app is running",
            datetime(2026, 7, 2, 9, 0, tzinfo=timezone.utc),
            source="process",
            process_id=40001,
            focus_process_id=40001,
            focus_app_name="ChatGPT",
            status_source="desktop-process",
            tool_display_name="ChatGPT",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            service = MonitorService(
                [
                    VolatileChatGPTSource([[chatgpt_session], [], []]),
                    VolatileProcessSource([[app_fallback], [], []]),
                ],
                SessionStore(audit_dir=Path(temp_dir)),
                ActionExecutor(),
                focus_manager=WindowFocusManager(sender=lambda target: FocusResult(True, "focused-chatgpt")),
                now=clock.now,
                clock=process_clock.now,
                process_empty_grace_seconds=0,
            )

            self.assertEqual(
                [session["session_id"] for session in service.sessions_payload()],
                ["chatgpt-session-alpha"],
            )
            self.assertTrue(service.focus_session("chatgpt-session-alpha").ok)

            clock.advance(seconds=60)
            self.assertEqual(
                [session["session_id"] for session in service.sessions_payload()],
                ["chatgpt-session-alpha"],
            )
            process_clock.advance(seconds=1)

            self.assertEqual(service.sessions_payload(), [])

    def test_viewed_qoder_process_conversation_survives_process_fallback_for_retention_window(self):
        clock = FakeDateTimeClock(datetime(2026, 7, 14, 9, 0, tzinfo=timezone.utc))
        qoder_session = SessionUpdate(
            "qoder-task-alpha",
            "Qoder CN Desktop - 围棋游戏开发",
            ToolKind.UNKNOWN,
            SurfaceKind.DESKTOP,
            SessionStatus.NEEDS_ACTION,
            "Qoder 任务已完成，等待查看。",
            datetime(2026, 7, 14, 9, 0, tzinfo=timezone.utc),
            source="process",
            process_id=11063,
            focus_process_id=11063,
            focus_app_name="Qoder CN",
            cwd="/Users/Gao/Documents/QoderCN/2026-07-14/chat-1",
            view_ack_required=True,
            status_source="qoder-log",
            tool_display_name="Qoder CN",
            generated_conversation_path=True,
        )
        qoder_fallback = SessionUpdate(
            "process-11063",
            "Qoder CN Desktop",
            ToolKind.UNKNOWN,
            SurfaceKind.DESKTOP,
            SessionStatus.IDLE,
            "Qoder CN 桌面 App 正在运行；尚未识别具体对话，先作为空闲入口。",
            datetime(2026, 7, 14, 9, 0, tzinfo=timezone.utc),
            source="process",
            process_id=11063,
            focus_process_id=11063,
            focus_app_name="Qoder CN",
            status_source="desktop-process",
            tool_display_name="Qoder CN",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            source = VolatileProcessSource([[qoder_session], [qoder_fallback], [qoder_fallback], [qoder_fallback]])
            focus_manager = WindowFocusManager(sender=lambda target: FocusResult(True, "focused-qoder"))
            service = MonitorService(
                [source],
                SessionStore(audit_dir=Path(temp_dir)),
                ActionExecutor(),
                focus_manager=focus_manager,
                now=clock.now,
            )

            self.assertEqual([session["session_id"] for session in service.sessions_payload()], ["qoder-task-alpha"])
            self.assertTrue(service.focus_session("qoder-task-alpha").ok)

            clock.advance(seconds=60)
            retained_payload = service.sessions_payload()

            self.assertEqual(
                [(session["session_id"], session["status"]) for session in retained_payload],
                [("qoder-task-alpha", "idle")],
            )
            self.assertEqual(retained_payload[0]["monitoring_level"], "full")

            clock.advance(seconds=14 * 60 - 1)
            self.assertEqual([session["session_id"] for session in service.sessions_payload()], ["qoder-task-alpha"])

            clock.advance(seconds=1)
            expired_payload = service.sessions_payload()

            self.assertEqual([session["session_id"] for session in expired_payload], ["process-11063"])
            self.assertEqual(expired_payload[0]["monitoring_level"], "process_only")

    def test_viewed_workbuddy_process_conversation_reveals_app_fallback_even_when_db_keeps_reporting_it(self):
        clock = FakeDateTimeClock(datetime(2026, 7, 15, 13, 0, tzinfo=timezone.utc))
        workbuddy_session = SessionUpdate(
            "workbuddy-session-alpha",
            "WorkBuddy Desktop - 需求评审",
            ToolKind.UNKNOWN,
            SurfaceKind.DESKTOP,
            SessionStatus.NEEDS_ACTION,
            "WorkBuddy 任务已完成，等待查看。",
            datetime(2026, 7, 15, 13, 0, tzinfo=timezone.utc),
            source="process",
            process_id=22001,
            focus_process_id=22001,
            focus_app_name="WorkBuddy",
            cwd="/Users/Gao/Documents/WorkBuddy/2026-07-15-13-12-11",
            view_ack_required=True,
            status_source="workbuddy-db",
            tool_display_name="WorkBuddy",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            source = VolatileProcessSource(
                [[workbuddy_session], [workbuddy_session], [workbuddy_session], [workbuddy_session]]
            )
            focus_manager = WindowFocusManager(sender=lambda target: FocusResult(True, "focused-workbuddy"))
            service = MonitorService(
                [source],
                SessionStore(audit_dir=Path(temp_dir)),
                ActionExecutor(),
                focus_manager=focus_manager,
                now=clock.now,
            )

            self.assertEqual([session["session_id"] for session in service.sessions_payload()], ["workbuddy-session-alpha"])
            self.assertTrue(service.focus_session("workbuddy-session-alpha").ok)

            clock.advance(seconds=60)
            retained_payload = service.sessions_payload()

            self.assertEqual(
                [(session["session_id"], session["status"]) for session in retained_payload],
                [("workbuddy-session-alpha", "idle")],
            )
            self.assertEqual(retained_payload[0]["monitoring_level"], "full")

            clock.advance(seconds=14 * 60)
            expired_payload = service.sessions_payload()

            self.assertEqual([session["session_id"] for session in expired_payload], ["process-22001"])
            self.assertEqual(expired_payload[0]["monitoring_level"], "process_only")
            self.assertEqual(expired_payload[0]["tool_display_name"], "WorkBuddy")
            self.assertEqual(expired_payload[0]["status"], "idle")

    def test_qoder_process_conversation_disappears_after_app_exits(self):
        clock = FakeDateTimeClock(datetime(2026, 7, 14, 9, 0, tzinfo=timezone.utc))
        process_clock = FakeClock()
        qoder_session = SessionUpdate(
            "qoder-task-alpha",
            "Qoder Desktop - 围棋游戏开发",
            ToolKind.UNKNOWN,
            SurfaceKind.DESKTOP,
            SessionStatus.NEEDS_ACTION,
            "Qoder 任务已完成，等待查看。",
            datetime(2026, 7, 14, 9, 0, tzinfo=timezone.utc),
            source="process",
            process_id=11063,
            focus_process_id=11063,
            focus_app_name="Qoder",
            view_ack_required=True,
            status_source="qoder-log",
            tool_display_name="Qoder",
        )
        source = VolatileProcessSource([[qoder_session], [], []])
        service = MonitorService(
            [source],
            SessionStore(),
            ActionExecutor(),
            now=clock.now,
            clock=process_clock.now,
            process_empty_grace_seconds=0,
        )

        self.assertEqual([session["session_id"] for session in service.sessions_payload()], ["qoder-task-alpha"])
        self.assertEqual([session["session_id"] for session in service.sessions_payload()], ["qoder-task-alpha"])
        process_clock.advance(seconds=1)

        self.assertEqual(service.sessions_payload(), [])

    def test_full_process_desktop_session_hides_matching_process_fallback(self):
        qoder_session = SessionUpdate(
            "qoder-task-alpha",
            "Qoder CN Desktop - 围棋游戏开发",
            ToolKind.UNKNOWN,
            SurfaceKind.DESKTOP,
            SessionStatus.RUNNING,
            "Qoder 正在处理任务。",
            datetime(2026, 7, 14, 9, 0, tzinfo=timezone.utc),
            source="process",
            process_id=11063,
            focus_process_id=11063,
            focus_app_name="Qoder CN",
            status_source="qoder-log",
            tool_display_name="Qoder CN",
        )
        qoder_fallback = SessionUpdate(
            "process-11063",
            "Qoder CN Desktop",
            ToolKind.UNKNOWN,
            SurfaceKind.DESKTOP,
            SessionStatus.IDLE,
            "Qoder CN 桌面 App 正在运行；尚未识别具体对话，先作为空闲入口。",
            datetime(2026, 7, 14, 9, 0, tzinfo=timezone.utc),
            source="process",
            process_id=11063,
            focus_process_id=11063,
            focus_app_name="Qoder CN",
            status_source="desktop-process",
            tool_display_name="Qoder CN",
        )
        store = SessionStore()
        store.apply_updates([qoder_session, qoder_fallback])
        service = MonitorService([], store, ActionExecutor())

        payload = service.sessions_payload()

        self.assertEqual([session["session_id"] for session in payload], ["qoder-task-alpha"])
        self.assertEqual(payload[0]["monitoring_level"], "full")

    def test_unviewed_desktop_idle_conversation_does_not_expire_by_idle_retention(self):
        clock = FakeDateTimeClock(datetime(2026, 7, 2, 9, 16, tzinfo=timezone.utc))
        store = SessionStore()
        store.apply_updates(
            [
                SessionUpdate(
                    "desktop-idle",
                    "Codex Desktop - hello",
                    ToolKind.CODEX,
                    SurfaceKind.DESKTOP,
                    SessionStatus.IDLE,
                    "idle but not viewed",
                    datetime(2026, 7, 2, 9, 0, tzinfo=timezone.utc),
                    source="codex-session",
                )
            ]
        )
        service = MonitorService([], store, ActionExecutor(), now=clock.now)

        self.assertEqual([session["session_id"] for session in service.sessions_payload()], ["desktop-idle"])

    def test_focus_session_does_not_mark_viewed_on_failure(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SessionStore(audit_dir=Path(temp_dir))
            store.apply_updates(
                [
                    SessionUpdate(
                        "codex-1",
                        "Codex Desktop - checkout-flow",
                        ToolKind.CODEX,
                        SurfaceKind.DESKTOP,
                        SessionStatus.NEEDS_ACTION,
                        "reply",
                        datetime(2026, 7, 2, 9, 0, tzinfo=timezone.utc),
                        view_ack_required=True,
                    )
                ]
            )
            focus_manager = WindowFocusManager(sender=lambda target: FocusResult(False, "not-found"))
            service = MonitorService([], store, ActionExecutor(), focus_manager=focus_manager)

            result = service.focus_session("codex-1")

            self.assertFalse(result.ok)
            self.assertEqual(service.sessions_payload()[0]["status"], "needs_action")

    def test_focus_session_marks_claude_terminal_reply_viewed_in_ide_terminal(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SessionStore(audit_dir=Path(temp_dir))
            store.apply_updates(
                [
                    SessionUpdate(
                        "process-27876",
                        "Claude Code CLI - checkout-flow",
                        ToolKind.CLAUDE_CODE,
                        SurfaceKind.TERMINAL,
                        SessionStatus.RUNNING,
                        "running",
                        datetime(2026, 7, 2, 9, 0, tzinfo=timezone.utc),
                        source="process",
                        process_id=27876,
                        focus_process_id=75407,
                        focus_app_name="Zed",
                        cwd="/Users/Gao/Documents/projects/checkout-flow",
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
                        datetime(2026, 7, 2, 9, 1, tzinfo=timezone.utc),
                        source="process",
                        process_id=27876,
                        focus_process_id=75407,
                        focus_app_name="Zed",
                        cwd="/Users/Gao/Documents/projects/checkout-flow",
                    )
                ]
            )
            focused = []
            focus_manager = WindowFocusManager(sender=lambda target: focused.append(target) or FocusResult(True, "focused-project-window"))
            service = MonitorService([], store, ActionExecutor(), focus_manager=focus_manager)

            before = service.sessions_payload()[0]
            result = service.focus_session("process-27876")
            after = service.sessions_payload()[0]

            self.assertEqual(before["status"], "needs_action")
            self.assertTrue(before["view_ack_required"])
            self.assertEqual(before["focus_app_name"], "Zed")
            self.assertTrue(result.ok)
            self.assertEqual(after["status"], "idle")
            self.assertEqual(focused[0].process_id, 75407)
            self.assertEqual(focused[0].app_name, "Zed")

    def test_session_alias_changes_payload_title_but_not_focus_target(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            focused = []
            preferences = MonitorPreferences(Path(temp_dir) / "preferences.json")
            preferences.rename_session("demo-claude-1", "Checkout rewrite")
            focus_manager = WindowFocusManager(sender=lambda target: focused.append(target.title) or FocusResult(True, "focused"))
            service = MonitorService(
                [DemoSource()],
                SessionStore(audit_dir=Path(temp_dir) / "audit"),
                ActionExecutor(),
                focus_manager=focus_manager,
                preferences=preferences,
            )

            payload = service.sessions_payload()
            result = service.focus_session("demo-claude-1")

            self.assertEqual(payload[0]["title"], "Checkout rewrite")
            self.assertEqual(payload[0]["original_title"], "Claude Code - checkout-flow")
            self.assertTrue(result.ok)
            self.assertEqual(focused, ["Claude Code - checkout-flow"])

    def test_pid_reuse_does_not_inherit_hidden_or_alias_preferences(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            now = datetime(2026, 7, 31, 5, 25, tzinfo=timezone.utc)
            old_started_at = now - timedelta(days=1)
            new_started_at = now - timedelta(hours=1)
            old = SessionUpdate(
                session_id="process-24645",
                title="Claude Code CLI - old-task",
                tool=ToolKind.CLAUDE_CODE,
                surface=SurfaceKind.TERMINAL,
                status=SessionStatus.IDLE,
                summary="old process",
                updated_at=now,
                source="process",
                process_id=24645,
                cwd="/Users/Gao/Documents/projects/old-task",
                status_source="process",
                process_started_at=old_started_at,
            )
            new = replace(
                old,
                title="Claude Code CLI - new-task",
                summary="new process",
                updated_at=now + timedelta(seconds=5),
                cwd="/Users/Gao/Documents/projects/new-task",
                process_started_at=new_started_at,
            )
            preferences = MonitorPreferences(Path(temp_dir) / "preferences.json")
            store = SessionStore(audit_dir=Path(temp_dir) / "audit")
            service = MonitorService([], store, ActionExecutor(), preferences=preferences)

            store.apply_updates([old])
            self.assertTrue(service.rename_session(old.session_id, "Old task alias").ok)
            self.assertEqual(service.sessions_payload()[0]["title"], "Old task alias")
            self.assertTrue(service.hide_session(old.session_id).ok)
            self.assertEqual(service.sessions_payload(), [])

            store.apply_updates([new])
            payload = service.sessions_payload()

            self.assertEqual([session["session_id"] for session in payload], [new.session_id])
            self.assertEqual(payload[0]["title"], new.title)

    def test_legacy_process_preferences_are_visible_during_first_identity_migration(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            now = datetime(2026, 7, 31, 5, 25, tzinfo=timezone.utc)
            session = SessionUpdate(
                session_id="process-24645",
                title="Claude Code CLI - old-task",
                tool=ToolKind.CLAUDE_CODE,
                surface=SurfaceKind.TERMINAL,
                status=SessionStatus.IDLE,
                summary="old process",
                updated_at=now,
                source="process",
                process_id=24645,
                cwd="/Users/Gao/Documents/projects/old-task",
                status_source="process",
                process_started_at=now - timedelta(days=1),
            )
            preferences = MonitorPreferences(Path(temp_dir) / "preferences.json")
            preferences.hide_session(session.session_id)
            preferences.rename_session(session.session_id, "Legacy alias")
            store = SessionStore(audit_dir=Path(temp_dir) / "audit")
            store.apply_updates([session])
            service = MonitorService([], store, ActionExecutor(), preferences=preferences)

            hidden_payload = service.hidden_sessions_payload()

            self.assertEqual([item["session_id"] for item in hidden_payload], [session.session_id])
            self.assertEqual(hidden_payload[0]["title"], "Legacy alias")

    def test_preference_identity_migration_write_failure_degrades_to_legacy_key(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            now = datetime(2026, 7, 31, 5, 25, tzinfo=timezone.utc)
            session = SessionUpdate(
                session_id="process-24645",
                title="Claude Code CLI - old-task",
                tool=ToolKind.CLAUDE_CODE,
                surface=SurfaceKind.TERMINAL,
                status=SessionStatus.IDLE,
                summary="old process",
                updated_at=now,
                source="process",
                process_id=24645,
                cwd="/Users/Gao/Documents/projects/old-task",
                status_source="process",
                process_started_at=now - timedelta(days=1),
            )
            preferences = MonitorPreferences(Path(temp_dir) / "preferences.json")
            preferences.hide_session(session.session_id)
            preferences.rename_session(session.session_id, "Legacy alias")
            store = SessionStore(audit_dir=Path(temp_dir) / "audit")
            store.apply_updates([session])
            service = MonitorService([], store, ActionExecutor(), preferences=preferences)

            with mock.patch.object(preferences, "_write_payload", side_effect=OSError("read-only")):
                hidden_during_failure = service.hidden_sessions_payload()

            hidden_after_recovery = service.hidden_sessions_payload()

            self.assertEqual(
                [item["session_id"] for item in hidden_during_failure],
                [session.session_id],
            )
            self.assertEqual(hidden_during_failure[0]["title"], "Legacy alias")
            self.assertEqual(
                [item["session_id"] for item in hidden_after_recovery],
                [session.session_id],
            )
            self.assertEqual(hidden_after_recovery[0]["title"], "Legacy alias")

    def test_rename_and_reset_session_title(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            service = MonitorService(
                [DemoSource()],
                SessionStore(audit_dir=Path(temp_dir) / "audit"),
                ActionExecutor(),
                preferences=MonitorPreferences(Path(temp_dir) / "preferences.json"),
            )
            service.refresh()

            rename = service.rename_session("demo-claude-1", "Checkout rewrite")
            reset = service.reset_session_title("demo-claude-1")

            self.assertTrue(rename.ok)
            self.assertTrue(reset.ok)
            self.assertEqual(service.sessions_payload()[0]["title"], "Claude Code - checkout-flow")

    def test_focus_session_uses_window_metadata_when_available(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "desktop.json"
            path.write_text(
                """{
  "session_id": "desktop-1",
  "title": "Codex Desktop - PRD",
  "tool": "codex",
  "surface": "desktop",
  "status": "needs_action",
  "summary": "Waiting",
  "updated_at": "2026-06-30T00:00:00+00:00",
  "window_id": "42",
  "process_id": 1234,
  "focus_process_id": 75407,
  "focus_app_name": "Zed"
}"""
            )
            focused = []
            focus_manager = WindowFocusManager(sender=lambda target: focused.append(target) or FocusResult(True, "focused"))
            service = MonitorService(
                [JsonSessionSource(Path(temp_dir))],
                SessionStore(audit_dir=Path(temp_dir) / "audit"),
                ActionExecutor(),
                focus_manager=focus_manager,
            )
            service.refresh()

            result = service.focus_session("desktop-1")

            self.assertTrue(result.ok)
            self.assertEqual(focused[0].window_id, "42")
            self.assertEqual(focused[0].process_id, 75407)
            self.assertEqual(focused[0].app_name, "Zed")

    def test_focus_session_passes_process_cwd_for_precise_terminal_navigation(self):
        session = SessionUpdate(
            session_id="process-16173",
            title="Claude Code CLI - 网点抛扔",
            tool=ToolKind.CLAUDE_CODE,
            surface=SurfaceKind.TERMINAL,
            status=SessionStatus.IDLE,
            summary="process only",
            updated_at=datetime.now(timezone.utc),
            source="process",
            process_id=16173,
            focus_process_id=75407,
            focus_app_name="Zed",
            cwd="/Users/Gao/Documents/projects/网点抛扔",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            focused = []
            focus_manager = WindowFocusManager(sender=lambda target: focused.append(target) or FocusResult(True, "focused"))
            service = MonitorService(
                [],
                SessionStore(audit_dir=Path(temp_dir) / "audit"),
                ActionExecutor(),
                focus_manager=focus_manager,
            )
            service.store.apply_updates([session])

            result = service.focus_session("process-16173")

        self.assertTrue(result.ok)
        self.assertEqual(focused[0].process_id, 75407)
        self.assertEqual(focused[0].app_name, "Zed")
        self.assertEqual(focused[0].cwd, "/Users/Gao/Documents/projects/网点抛扔")

    def test_hidden_session_is_removed_from_payload_until_restored(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            service = MonitorService(
                [DemoSource()],
                SessionStore(audit_dir=Path(temp_dir) / "audit"),
                ActionExecutor(),
                preferences=MonitorPreferences(Path(temp_dir) / "preferences.json"),
            )
            service.refresh()

            result = service.hide_session("demo-claude-1")

            self.assertTrue(result.ok)
            self.assertNotIn("demo-claude-1", [session["session_id"] for session in service.sessions_payload()])

            restore = service.unhide_session("demo-claude-1")

            self.assertTrue(restore.ok)
            self.assertIn("demo-claude-1", [session["session_id"] for session in service.sessions_payload()])

    def test_hidden_needs_action_session_does_not_notify(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            sent = []
            notifier = NotificationManager(sender=lambda title, message: sent.append((title, message)), cooldown_seconds=60)
            preferences = MonitorPreferences(Path(temp_dir) / "preferences.json")
            preferences.hide_session("demo-claude-1")
            service = MonitorService(
                [DemoSource()],
                SessionStore(),
                ActionExecutor(),
                notifier=notifier,
                preferences=preferences,
            )

            payload = service.sessions_payload()

            self.assertNotIn("demo-claude-1", [session["session_id"] for session in payload])
            self.assertEqual(sent, [])

    def test_sessions_payload_cleans_legacy_terminal_fragments(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "legacy.json"
            path.write_text(
                """{
  "session_id": "legacy-1",
  "title": "Claude Code - legacy",
  "tool": "claude_code",
  "surface": "terminal",
  "status": "unknown",
  "summary": "�[1B�[39m �[38;2;153;153;153m20260703AIcoding | MiniMax-M3�[m | ctx:6%�[39m �[K",
  "updated_at": "2026-06-30T00:00:00+00:00"
}"""
            )
            service = MonitorService(
                [JsonSessionSource(Path(temp_dir), cleanup_after_seconds=0)],
                SessionStore(),
                ActionExecutor(),
            )

            payload = service.sessions_payload()

            self.assertEqual(payload[0]["summary"], "20260703AIcoding | MiniMax-M3 | ctx:6%")

    def test_removed_json_session_file_disappears_from_payload(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "stale.json"
            path.write_text(
                """{
  "session_id": "stale-1",
  "title": "Codex - stale",
  "tool": "codex",
  "surface": "desktop",
  "status": "running",
  "summary": "Should disappear",
  "updated_at": "2026-06-30T00:00:00+00:00"
}"""
            )
            service = MonitorService([JsonSessionSource(Path(temp_dir))], SessionStore(), ActionExecutor())

            first_payload = service.sessions_payload()
            path.unlink()
            second_payload = service.sessions_payload()

            self.assertEqual([session["session_id"] for session in first_payload], ["stale-1"])
            self.assertEqual(second_payload, [])


class VolatileProcessSource:
    volatile_source = "process"

    def __init__(self, batches):
        self.batches = list(batches)

    def poll(self):
        if not self.batches:
            return []
        return self.batches.pop(0)


class VolatileChatGPTSource(VolatileProcessSource):
    volatile_source = "chatgpt-session"


class FakeProjectWindowSource:
    volatile_source = "os-window"

    def __init__(self, matches, available=True):
        self.matches = dict(matches)
        self.available = available

    def poll(self):
        return [] if self.available else None

    def project_window_match(self, process_id, app_name, cwd):
        if not self.available:
            return None
        key = (process_id, app_name, cwd)
        window_id = self.matches.get(key)
        return window_id is not None, window_id


class CoordinatedEmptySource:
    def __init__(self, barrier):
        self.barrier = barrier
        self.polled = False
        self.overlapped = False

    def poll(self):
        self.polled = True
        try:
            self.barrier.wait(timeout=1)
        except threading.BrokenBarrierError:
            return []
        self.overlapped = True
        return []


class FakeClock:
    def __init__(self):
        self.value = 0.0

    def now(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


class FakeDateTimeClock:
    def __init__(self, value):
        self.value = value

    def now(self):
        return self.value

    def advance(self, seconds):
        self.value += timedelta(seconds=seconds)


if __name__ == "__main__":
    unittest.main()
