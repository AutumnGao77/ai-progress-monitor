import json
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from pathlib import Path
from types import SimpleNamespace
from typing import Optional
from unittest import mock

from ai_progress_monitor.actions import ActionExecutor
from ai_progress_monitor.notifier import NotificationManager
from ai_progress_monitor.service import MonitorService
from ai_progress_monitor.store import SessionStore
from ai_progress_monitor.preferences import MonitorPreferences
from ai_progress_monitor import web
from ai_progress_monitor.web import (
    build_launch_url,
    configured_pet_asset_urls,
    create_server_with_port_fallback,
    focus_snapshot_line,
    maybe_open_browser,
    pet_asset_urls,
    pet_appearance_snapshot_line,
    read_configured_pet_asset,
    render_html,
    resolve_response_dir,
    resolve_session_dir,
    session_snapshot_line,
)


class WebLaunchTests(unittest.TestCase):
    def test_main_persists_notification_state_next_to_preferences(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            preferences = MonitorPreferences(Path(temp_dir) / "preferences.json")
            server = mock.Mock()
            with (
                mock.patch.object(web, "MonitorPreferences", return_value=preferences),
                mock.patch.object(web, "NotificationManager") as notifier_type,
                mock.patch.object(web, "build_sources", return_value=[]),
                mock.patch.object(web, "create_server_with_port_fallback", return_value=(server, 8765)),
                mock.patch.object(web, "generate_token", return_value="secret"),
            ):
                result = web.main(["--no-windows"])

            self.assertEqual(result, 0)
            notifier_type.assert_called_once_with(state_path=Path(temp_dir) / "notification-state.json")
            server.serve_forever.assert_called_once_with()

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
                "themes": {
                    "default": {
                        "idle": "/assets/pet/idle.png",
                        "running": "/assets/pet/running.png",
                        "needs_action": "/assets/pet/needs-action.png",
                    },
                    "shirt": {
                        "idle": "/assets/pet/shirt.png",
                        "running": "/assets/pet/shirt.png",
                        "needs_action": "/assets/pet/shirt.png",
                    },
                },
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
        self.assertIn('window.PET_APPEARANCE = "default"', html)
        self.assertIn('window.PET_ASSET_OVERRIDE_KEYS = ["app_avatar", "idle", "needs_action", "running"]', html)
        self.assertIn('window.PET_THEMES = {"default":', html)
        self.assertIn('"/assets/pet/shirt.png"', html)
        self.assertIn('window.MONITOR_TOKEN = "secret"', html)

    def test_render_html_does_not_mark_defaults_as_pet_asset_overrides(self):
        html = render_html("secret")

        self.assertIn("window.PET_ASSETS = {}", html)
        self.assertIn("window.PET_ASSET_OVERRIDE_KEYS = []", html)

    def test_configured_pet_asset_urls_marks_only_configured_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "preferences.json"
            idle_asset = Path(directory) / "idle.png"
            idle_asset.write_bytes(_tiny_png())
            path.write_text(
                json.dumps(
                    {
                        "pet_assets": {
                            "idle": str(idle_asset),
                            "needs_action": "/custom/needs-action.png",
                        }
                    }
                ),
                encoding="utf-8",
            )
            prefs = MonitorPreferences(path)

            self.assertEqual(
                configured_pet_asset_urls(prefs),
                {
                    "idle": "/assets/pet/idle.png",
                },
            )

    def test_configured_pet_asset_urls_ignores_invalid_configured_assets(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "preferences.json"
            path.write_text(
                json.dumps(
                    {
                        "pet_assets": {
                            "idle": str(Path(directory) / "missing.png"),
                            "running": str(Path(directory) / "running.txt"),
                        }
                    }
                ),
                encoding="utf-8",
            )
            (Path(directory) / "running.txt").write_text("not an image", encoding="utf-8")
            prefs = MonitorPreferences(path)

            self.assertEqual(configured_pet_asset_urls(prefs), {})

    def test_configured_pet_asset_urls_ignores_invalid_image_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "preferences.json"
            broken_asset = Path(directory) / "idle.png"
            broken_asset.write_bytes(b"not really a png")
            path.write_text(
                json.dumps({"pet_assets": {"idle": str(broken_asset)}}),
                encoding="utf-8",
            )
            prefs = MonitorPreferences(path)

            self.assertEqual(configured_pet_asset_urls(prefs), {})

    def test_configured_pet_asset_urls_ignores_truncated_png_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "preferences.json"
            broken_asset = Path(directory) / "idle.png"
            broken_asset.write_bytes(b"\x89PNG\r\n\x1a\n")
            path.write_text(
                json.dumps({"pet_assets": {"idle": str(broken_asset)}}),
                encoding="utf-8",
            )
            prefs = MonitorPreferences(path)

            self.assertEqual(configured_pet_asset_urls(prefs), {})

    def test_configured_pet_asset_urls_ignores_png_with_bad_crc(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "preferences.json"
            broken_asset = Path(directory) / "idle.png"
            broken_png = bytearray(_tiny_png())
            broken_png[32] ^= 0xFF
            broken_asset.write_bytes(bytes(broken_png))
            path.write_text(
                json.dumps({"pet_assets": {"idle": str(broken_asset)}}),
                encoding="utf-8",
            )
            prefs = MonitorPreferences(path)

            self.assertEqual(configured_pet_asset_urls(prefs), {})

    def test_read_configured_pet_asset_rechecks_size_after_read(self):
        class GrowingAsset:
            suffix = ".jpg"

            def is_file(self):
                return True

            def stat(self):
                return SimpleNamespace(st_size=64)

            def read_bytes(self):
                return b"\xff\xd8\xff" + (b"\x00" * (web.MAX_CONFIGURED_PET_ASSET_BYTES + 1)) + b"\xff\xd9"

        result = read_configured_pet_asset(GrowingAsset())
        self.assertTrue(result is None, "oversized asset should be rejected after read")

    def test_read_configured_pet_asset_rejects_empty_webp_chunk(self):
        with tempfile.TemporaryDirectory() as directory:
            asset = Path(directory) / "empty.webp"
            asset.write_bytes(b"RIFF\x0c\x00\x00\x00WEBPVP8 \x00\x00\x00\x00")

            self.assertIsNone(read_configured_pet_asset(asset))

    def test_read_configured_pet_asset_rejects_empty_jpeg_shell(self):
        with tempfile.TemporaryDirectory() as directory:
            asset = Path(directory) / "empty.jpg"
            asset.write_bytes(b"\xff\xd8\xff\xd9")

            self.assertIsNone(read_configured_pet_asset(asset))

    def test_read_configured_pet_asset_accepts_structured_jpeg(self):
        with tempfile.TemporaryDirectory() as directory:
            asset = Path(directory) / "structured.jpg"
            asset.write_bytes(_minimal_structured_jpeg())

            result = read_configured_pet_asset(asset)

            self.assertIsNotNone(result)
            self.assertEqual(result[1], "image/jpeg")

    def test_render_html_injects_current_pet_appearance(self):
        html = render_html("secret", pet_appearance="shirt")

        self.assertIn('window.PET_APPEARANCE = "shirt"', html)

    def test_render_html_injects_system_notification_state(self):
        html = render_html("secret", notifications_enabled=False, notifications_locked=True)

        self.assertIn("window.NOTIFICATIONS_ENABLED = false", html)
        self.assertIn("window.NOTIFICATIONS_LOCKED = true", html)

    def test_preferences_api_requires_token(self):
        with _running_server() as base_url:
            with self.assertRaises(HTTPError) as error:
                urlopen(f"{base_url}/api/preferences", timeout=5)

            self.assertEqual(error.exception.code, 403)

    def test_root_page_does_not_mark_default_pet_assets_as_overrides(self):
        with _running_server() as base_url:
            response = urlopen(base_url, timeout=5)
            html = response.read().decode("utf-8")

            self.assertIn("window.PET_ASSETS = {}", html)
            self.assertIn("window.PET_ASSET_OVERRIDE_KEYS = []", html)
            self.assertEqual(response.headers.get("cache-control"), "no-store")

    def test_root_page_marks_configured_pet_assets_as_overrides(self):
        with tempfile.TemporaryDirectory() as directory:
            idle_asset = Path(directory) / "idle.png"
            idle_asset.write_bytes(_tiny_png())
            with _running_server({"pet_assets": {"idle": str(idle_asset)}}) as base_url:
                html = urlopen(base_url, timeout=5).read().decode("utf-8")

                self.assertIn('window.PET_ASSETS = {"idle": "/assets/pet/idle.png"}', html)
                self.assertIn('window.PET_ASSET_OVERRIDE_KEYS = ["idle"]', html)

    def test_shirt_pet_asset_route_serves_approved_source_image(self):
        root = Path(__file__).resolve().parents[1]
        approved_source = root / "docs" / "promo" / "assets" / "sloth-mascot-transparent.png"
        idle_asset = root / "src" / "ai_progress_monitor" / "assets" / "sloth-pet-idle.png"

        with _running_server() as base_url:
            response = urlopen(f"{base_url}/assets/pet/shirt.png", timeout=5)
            body = response.read()

        self.assertEqual(body, approved_source.read_bytes())
        self.assertNotEqual(body, idle_asset.read_bytes())
        self.assertEqual(response.headers.get("cache-control"), "no-store")

    def test_preferences_api_reads_and_updates_pet_appearance(self):
        with _running_server() as base_url:
            first = _json_request(f"{base_url}/api/preferences?token=secret")
            self.assertEqual(first["pet_appearance"], "default")

            with mock.patch("builtins.print") as print_mock:
                updated = _json_request(
                    f"{base_url}/api/preferences/pet-appearance?token=secret",
                    data={"theme": "shirt"},
                )

            self.assertEqual(updated, {"ok": True, "pet_appearance": "shirt"})
            print_mock.assert_any_call("AI Progress Monitor pet appearance: shirt", flush=True)
            second = _json_request(f"{base_url}/api/preferences?token=secret")
            self.assertEqual(second["pet_appearance"], "shirt")

    def test_preferences_api_reads_and_updates_system_notifications(self):
        with _running_server() as base_url:
            first = _json_request(f"{base_url}/api/preferences?token=secret")
            self.assertTrue(first["notifications_enabled"])
            self.assertFalse(first["notifications_locked"])

            updated = _json_request(
                f"{base_url}/api/preferences/notifications?token=secret",
                data={"enabled": False},
            )

            self.assertEqual(
                updated,
                {"ok": True, "notifications_enabled": False, "notifications_locked": False},
            )
            second = _json_request(f"{base_url}/api/preferences?token=secret")
            self.assertFalse(second["notifications_enabled"])

    def test_native_project_windows_api_accepts_companion_inventory(self):
        with _running_server() as base_url:
            updated = _json_request(
                f"{base_url}/api/native/project-windows?token=secret",
                data={
                    "available": True,
                    "applications": [
                        {
                            "process_id": 478,
                            "available": True,
                            "windows": [{"window_id": "42", "title": "日报推送 — SKILL.md"}],
                        }
                    ],
                },
            )
            cleared = _json_request(
                f"{base_url}/api/native/project-windows?token=secret",
                data={"available": False, "applications": []},
            )

        self.assertEqual(updated, {"ok": True})
        self.assertEqual(cleared, {"ok": True})

    def test_native_project_windows_api_rejects_missing_token_and_invalid_payload(self):
        with _running_server() as base_url:
            with self.assertRaises(HTTPError) as unauthorized:
                _json_request(
                    f"{base_url}/api/native/project-windows",
                    data={"available": True, "applications": []},
                )
            self.assertEqual(unauthorized.exception.code, 403)

            for payload in [
                {},
                {"available": "yes", "applications": []},
                {"available": False, "applications": [{"process_id": 478}]},
                {"available": True, "applications": {}},
                {"available": True, "applications": [{"process_id": 478, "available": True, "windows": {}}]},
            ]:
                with self.subTest(payload=payload):
                    with self.assertRaises(HTTPError) as invalid:
                        _json_request(
                            f"{base_url}/api/native/project-windows?token=secret",
                            data=payload,
                        )
                    self.assertEqual(invalid.exception.code, 400)
                    self.assertEqual(
                        json.loads(invalid.exception.read()),
                        {"ok": False, "error": "invalid_project_window_inventory"},
                    )

    def test_preferences_api_rejects_system_notification_update_without_token(self):
        with _running_server() as base_url:
            with self.assertRaises(HTTPError) as error:
                _json_request(
                    f"{base_url}/api/preferences/notifications",
                    data={"enabled": False},
                )

            self.assertEqual(error.exception.code, 403)
            self.assertEqual(json.loads(error.exception.read()), {"error": "forbidden"})

    def test_preferences_api_rejects_invalid_system_notification_value(self):
        with _running_server() as base_url:
            for payload in [
                {},
                {"enabled": "false"},
                {"enabled": 0},
                {"enabled": None},
                {"enabled": False, "unexpected": True},
                [],
                True,
            ]:
                with self.subTest(payload=payload):
                    with self.assertRaises(HTTPError) as error:
                        _json_request(
                            f"{base_url}/api/preferences/notifications?token=secret",
                            data=payload,
                        )

                    self.assertEqual(error.exception.code, 400)
                    self.assertEqual(json.loads(error.exception.read()), {"ok": False, "error": "invalid_notifications_enabled"})

    def test_preferences_api_rejects_system_notification_update_when_forced_off(self):
        with _running_server({"notifications_enabled": True}, notifications_forced_off=True) as base_url:
            current = _json_request(f"{base_url}/api/preferences?token=secret")
            self.assertFalse(current["notifications_enabled"])
            self.assertTrue(current["notifications_locked"])

            with self.assertRaises(HTTPError) as error:
                _json_request(
                    f"{base_url}/api/preferences/notifications?token=secret",
                    data={"enabled": True},
                )

            self.assertEqual(error.exception.code, 409)
            self.assertEqual(json.loads(error.exception.read()), {"ok": False, "error": "notifications_forced_disabled"})

    def test_preferences_api_reports_system_notification_write_failure(self):
        with _running_server() as base_url:
            with mock.patch.object(MonitorPreferences, "set_notifications_enabled", side_effect=OSError("disk full")):
                with self.assertRaises(HTTPError) as error:
                    _json_request(
                        f"{base_url}/api/preferences/notifications?token=secret",
                        data={"enabled": False},
                    )

            self.assertEqual(error.exception.code, 500)
            self.assertEqual(json.loads(error.exception.read()), {"ok": False, "error": "preferences_write_failed"})

    def test_preferences_api_rejects_unknown_pet_appearance(self):
        with _running_server() as base_url:
            with self.assertRaises(HTTPError) as error:
                _json_request(
                    f"{base_url}/api/preferences/pet-appearance?token=secret",
                    data={"theme": "unknown"},
                )

            self.assertEqual(error.exception.code, 400)

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

    def test_pet_appearance_snapshot_line_logs_only_safe_theme(self):
        self.assertEqual(
            pet_appearance_snapshot_line("shirt"),
            "AI Progress Monitor pet appearance: shirt",
        )
        self.assertEqual(
            pet_appearance_snapshot_line("SECRET-folder"),
            "AI Progress Monitor pet appearance: default",
        )


class _running_server:
    def __init__(self, preferences_payload: Optional[dict] = None, notifications_forced_off: bool = False):
        self.preferences_payload = preferences_payload
        self.notifications_forced_off = notifications_forced_off

    def __enter__(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        preferences_path = Path(self.temp_dir.name) / "preferences.json"
        if self.preferences_payload is not None:
            preferences_path.write_text(json.dumps(self.preferences_payload), encoding="utf-8")
        preferences = MonitorPreferences(preferences_path)
        service = MonitorService(
            [],
            SessionStore(),
            ActionExecutor(),
            notifier=NotificationManager(sender=lambda _title, _message: None),
            preferences=preferences,
            notifications_forced_off=self.notifications_forced_off,
        )
        self.server = web.create_server("127.0.0.1", 0, service, "secret")
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        host, port = self.server.server_address
        return f"http://{host}:{port}"

    def __exit__(self, exc_type, exc, tb):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.temp_dir.cleanup()


def _json_request(url: str, data: Optional[dict] = None) -> dict:
    body = None
    headers = {}
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        headers["content-type"] = "application/json"
    request = Request(url, data=body, headers=headers)
    with urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def _tiny_png() -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x04\x00\x00\x00\xb5\x1c\x0c\x02"
        b"\x00\x00\x00\x0bIDATx\xdac\xfc\xff\x1f\x00\x03\x03\x02\x00"
        b"\xef\xa2\xa7\x5b"
        b"\x00\x00\x00\x00IEND\xaeB`\x82"
    )


def _minimal_structured_jpeg() -> bytes:
    return (
        b"\xff\xd8"
        b"\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00"
        b"\xff\xda\x00\x08\x01\x01\x00\x00\x3f\x00"
        b"\x00"
        b"\xff\xd9"
    )


if __name__ == "__main__":
    unittest.main()
