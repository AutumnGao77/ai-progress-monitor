import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

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
        sent = []
        notifier = NotificationManager(sender=lambda title, message: sent.append((title, message)), cooldown_seconds=60)
        service = MonitorService([DemoSource()], SessionStore(), ActionExecutor(), notifier=notifier)

        service.refresh()
        service.refresh()

        self.assertEqual(len(sent), 1)
        self.assertIn("需要处理", sent[0][0])

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

    def test_refresh_polls_independent_sources_concurrently_for_visibility_budget(self):
        sources = [DelayedEmptySource(0.2), DelayedEmptySource(0.2)]
        service = MonitorService(sources, SessionStore(), ActionExecutor())

        start = time.monotonic()
        payload = service.sessions_payload()
        elapsed = time.monotonic() - start

        self.assertEqual(payload, [])
        self.assertLess(elapsed, 0.35)
        self.assertTrue(all(source.polled for source in sources))

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


class DelayedEmptySource:
    def __init__(self, delay_seconds):
        self.delay_seconds = delay_seconds
        self.polled = False

    def poll(self):
        time.sleep(self.delay_seconds)
        self.polled = True
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
