import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from ai_progress_monitor.actions import ActionExecutor
from ai_progress_monitor.service import MonitorService
from ai_progress_monitor.store import SessionStore
from ai_progress_monitor import web
from ai_progress_monitor.web import (
    build_launch_url,
    create_server_with_port_fallback,
    focus_snapshot_line,
    maybe_open_browser,
    pet_asset_urls,
    render_html,
    resolve_response_dir,
    resolve_session_dir,
    session_snapshot_line,
)


class WebLaunchTests(unittest.TestCase):
    def test_build_launch_url_contains_token(self):
        self.assertEqual(
            build_launch_url("127.0.0.1", 8765, "secret"),
            "http://127.0.0.1:8765/?token=secret",
        )

    def test_pet_asset_urls_are_stable_routes(self):
        self.assertEqual(
            pet_asset_urls(),
            {
                "idle": "/assets/pet/idle.png",
                "running": "/assets/pet/running.png",
                "needs_action": "/assets/pet/needs-action.png",
                "app_avatar": "/assets/app-avatar.png",
            },
        )

    def test_render_html_injects_configured_pet_assets(self):
        html = render_html(
            "secret",
            {
                "idle": "/custom/idle.png",
                "running": "/custom/running.png",
                "needs_action": "/custom/needs-action.png",
                "app_avatar": "/custom/avatar.png",
            },
        )

        self.assertIn('"idle": "/custom/idle.png"', html)
        self.assertIn('"running": "/custom/running.png"', html)
        self.assertIn('"needs_action": "/custom/needs-action.png"', html)
        self.assertIn('"app_avatar": "/custom/avatar.png"', html)
        self.assertIn('window.MONITOR_TOKEN = "secret"', html)

    def test_open_browser_when_enabled(self):
        with mock.patch("webbrowser.open") as open_mock:
            maybe_open_browser("http://127.0.0.1:8765/?token=secret", enabled=True)

        open_mock.assert_called_once_with("http://127.0.0.1:8765/?token=secret")

    def test_does_not_open_browser_when_disabled(self):
        with mock.patch("webbrowser.open") as open_mock:
            maybe_open_browser("http://127.0.0.1:8765/?token=secret", enabled=False)

        open_mock.assert_not_called()

    def test_create_server_falls_back_when_requested_port_is_busy(self):
        busy_port = 8765
        service = MonitorService([], SessionStore(), ActionExecutor())
        busy_error = OSError("Address already in use")
        busy_error.errno = 48
        fake_server = SimpleNamespace(server_address=("127.0.0.1", busy_port + 1))

        with mock.patch.object(web, "create_server", side_effect=[busy_error, fake_server]) as create_mock:
            server, selected_port = create_server_with_port_fallback("127.0.0.1", busy_port, service, "secret", attempts=2)

        self.assertEqual(selected_port, busy_port + 1)
        self.assertEqual(server.server_address[1], busy_port + 1)
        self.assertEqual(create_mock.call_args_list[0].args[1], busy_port)
        self.assertEqual(create_mock.call_args_list[1].args[1], busy_port + 1)

    def test_monitor_home_maps_to_sessions_and_responses_children(self):
        args = SimpleNamespace(session_dir=None, response_dir=None)

        with mock.patch.dict("os.environ", {"AI_PROGRESS_MONITOR_HOME": "/tmp/ai-monitor-home"}):
            self.assertEqual(resolve_session_dir(args), Path("/tmp/ai-monitor-home/sessions"))
            self.assertEqual(resolve_response_dir(args), Path("/tmp/ai-monitor-home/responses"))

    def test_response_dir_defaults_to_sibling_of_explicit_session_dir(self):
        args = SimpleNamespace(session_dir="/tmp/ai-monitor-home/sessions", response_dir=None)

        self.assertEqual(resolve_response_dir(args), Path("/tmp/ai-monitor-home/responses"))

    def test_explicit_response_dir_wins(self):
        args = SimpleNamespace(session_dir="/tmp/ai-monitor-home/sessions", response_dir="/tmp/custom-responses")

        self.assertEqual(resolve_response_dir(args), Path("/tmp/custom-responses"))

    def test_session_snapshot_line_logs_counts_without_sensitive_content(self):
        sessions = [
            {
                "session_id": "process-1",
                "title": "Claude Code CLI - SECRET-folder",
                "status": "running",
                "monitoring_level": "process_only",
                "summary": "SECRET terminal output",
            },
            {
                "session_id": "codex-1",
                "title": "Codex - checkout-flow",
                "status": "needs_action",
                "monitoring_level": "full",
                "summary": "Do not log this",
            },
        ]

        line = session_snapshot_line(sessions)

        self.assertEqual(
            line,
            "AI Progress Monitor sessions: total=2 needs_action=1 running=1 idle=0 process_only=1 full=1",
        )
        self.assertNotIn("SECRET", line)
        self.assertNotIn("checkout-flow", line)
        self.assertNotIn("terminal output", line)
        self.assertNotIn("token=", line)

    def test_focus_snapshot_line_logs_result_without_session_content(self):
        line = focus_snapshot_line(ok=False, detail="Window not found for SECRET-folder")

        self.assertEqual(line, "AI Progress Monitor focus: ok=false")
        self.assertNotIn("SECRET", line)
        self.assertNotIn("Window not found", line)
        self.assertNotIn("token=", line)

    def test_focus_snapshot_line_logs_only_safe_focus_method(self):
        line = focus_snapshot_line(ok=True, detail="focused-project-window for SECRET-folder")

        self.assertEqual(line, "AI Progress Monitor focus: ok=true method=focused-project-window")
        self.assertNotIn("SECRET", line)
        self.assertNotIn("folder", line)


if __name__ == "__main__":
    unittest.main()
