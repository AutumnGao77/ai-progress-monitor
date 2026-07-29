import json
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ai_progress_monitor.preferences import MonitorPreferences


class MonitorPreferencesTests(unittest.TestCase):
    def test_hidden_sessions_persist_to_disk(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "preferences.json"
            prefs = MonitorPreferences(path)

            prefs.hide_session("claude-1")

            reloaded = MonitorPreferences(path)
            self.assertTrue(reloaded.is_hidden("claude-1"))

    def test_unhide_session_persists_to_disk(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "preferences.json"
            prefs = MonitorPreferences(path)
            prefs.hide_session("codex-1")

            prefs.unhide_session("codex-1")

            reloaded = MonitorPreferences(path)
            self.assertFalse(reloaded.is_hidden("codex-1"))

    def test_session_alias_persists_to_disk(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "preferences.json"
            prefs = MonitorPreferences(path)

            prefs.rename_session("codex-1", "PRD polish")

            reloaded = MonitorPreferences(path)
            self.assertEqual(reloaded.session_alias("codex-1"), "PRD polish")

    def test_reset_session_alias_removes_only_that_alias(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "preferences.json"
            prefs = MonitorPreferences(path)
            prefs.rename_session("codex-1", "PRD polish")
            prefs.rename_session("claude-1", "Checkout")

            prefs.reset_session_alias("codex-1")

            reloaded = MonitorPreferences(path)
            self.assertIsNone(reloaded.session_alias("codex-1"))
            self.assertEqual(reloaded.session_alias("claude-1"), "Checkout")

    def test_pet_asset_paths_are_read_from_preferences(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "preferences.json"
            path.write_text(
                """
                {
                  "pet_assets": {
                    "idle": "/tmp/idle.png",
                    "running": "/tmp/running.png",
                    "needs_action": "/tmp/needs-action.png",
                    "app_avatar": "/tmp/app-avatar.png",
                    "unknown": "/tmp/ignored.png"
                  }
                }
                """,
                encoding="utf-8",
            )

            prefs = MonitorPreferences(path)

            self.assertEqual(prefs.pet_asset_path("idle"), Path("/tmp/idle.png"))
            self.assertEqual(prefs.pet_asset_path("running"), Path("/tmp/running.png"))
            self.assertEqual(prefs.pet_asset_path("needs_action"), Path("/tmp/needs-action.png"))
            self.assertEqual(prefs.pet_asset_path("app_avatar"), Path("/tmp/app-avatar.png"))
            self.assertIsNone(prefs.pet_asset_path("unknown"))

    def test_pet_asset_paths_ignore_blank_and_non_string_values(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "preferences.json"
            path.write_text(
                '{"pet_assets": {"idle": "", "running": 123, "needs_action": null}}',
                encoding="utf-8",
            )

            prefs = MonitorPreferences(path)

            self.assertIsNone(prefs.pet_asset_path("idle"))
            self.assertIsNone(prefs.pet_asset_path("running"))
            self.assertIsNone(prefs.pet_asset_path("needs_action"))

    def test_pet_appearance_defaults_to_default_theme(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            prefs = MonitorPreferences(Path(temp_dir) / "preferences.json")

            self.assertEqual(prefs.pet_appearance(), "default")

    def test_pet_appearance_reads_shirt_theme(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "preferences.json"
            path.write_text('{"pet_appearance": "shirt"}', encoding="utf-8")

            prefs = MonitorPreferences(path)

            self.assertEqual(prefs.pet_appearance(), "shirt")

    def test_pet_appearance_rejects_unknown_theme(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "preferences.json"
            path.write_text('{"pet_appearance": "unknown"}', encoding="utf-8")

            prefs = MonitorPreferences(path)

            self.assertEqual(prefs.pet_appearance(), "default")

    def test_set_pet_appearance_preserves_existing_preferences(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "preferences.json"
            path.write_text(
                """
                {
                  "hidden_sessions": ["codex-1"],
                  "session_aliases": {"codex-1": "PRD"},
                  "pet_assets": {"idle": "/tmp/idle.png"}
                }
                """,
                encoding="utf-8",
            )
            prefs = MonitorPreferences(path)

            self.assertTrue(prefs.set_pet_appearance("shirt"))

            reloaded = MonitorPreferences(path)
            self.assertEqual(reloaded.pet_appearance(), "shirt")
            self.assertTrue(reloaded.is_hidden("codex-1"))
            self.assertEqual(reloaded.session_alias("codex-1"), "PRD")
            self.assertEqual(reloaded.pet_asset_path("idle"), Path("/tmp/idle.png"))

    def test_notifications_enabled_defaults_to_true(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            prefs = MonitorPreferences(Path(temp_dir) / "preferences.json")

            self.assertTrue(prefs.notifications_enabled())

    def test_notifications_enabled_reads_false(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "preferences.json"
            path.write_text('{"notifications_enabled": false}', encoding="utf-8")

            self.assertFalse(MonitorPreferences(path).notifications_enabled())

    def test_notifications_enabled_uses_safe_default_for_invalid_values(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "preferences.json"
            for value in [None, 0, 1, "false", [], {}]:
                with self.subTest(value=value):
                    path.write_text(json.dumps({"notifications_enabled": value}), encoding="utf-8")
                    self.assertTrue(MonitorPreferences(path).notifications_enabled())

            path.write_text("{broken", encoding="utf-8")
            self.assertTrue(MonitorPreferences(path).notifications_enabled())

    def test_set_notifications_enabled_preserves_existing_preferences(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "preferences.json"
            original = {
                "hidden_sessions": ["codex-1"],
                "session_aliases": {"codex-1": "PRD"},
                "pet_appearance": "shirt",
                "pet_assets": {"idle": "/tmp/idle.png"},
                "future_preference": {"keep": True},
            }
            path.write_text(json.dumps(original), encoding="utf-8")
            prefs = MonitorPreferences(path)

            self.assertTrue(prefs.set_notifications_enabled(False))

            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertFalse(payload["notifications_enabled"])
            for key, value in original.items():
                self.assertEqual(payload[key], value)

    def test_set_notifications_enabled_rejects_non_boolean_without_writing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "preferences.json"
            prefs = MonitorPreferences(path)

            self.assertFalse(prefs.set_notifications_enabled("false"))
            self.assertFalse(path.exists())

    def test_set_notifications_enabled_does_not_rewrite_effectively_unchanged_value(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "preferences.json"
            prefs = MonitorPreferences(path)
            writes = []
            prefs._write_payload = lambda payload: writes.append(payload)

            self.assertTrue(prefs.set_notifications_enabled(True))

            path.write_text('{"notifications_enabled": false}', encoding="utf-8")
            self.assertTrue(prefs.set_notifications_enabled(False))
            self.assertEqual(writes, [])

    def test_concurrent_appearance_and_notification_writes_preserve_both_fields(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "preferences.json"
            path.write_text('{"future_preference": {"keep": true}}', encoding="utf-8")
            prefs = MonitorPreferences(path)
            role = threading.local()
            notification_read = threading.Event()
            appearance_read = threading.Event()
            appearance_written = threading.Event()
            original_read = prefs._read
            original_write = prefs._write_payload

            def controlled_read():
                payload = original_read()
                if getattr(role, "value", "") == "notifications":
                    notification_read.set()
                    appearance_read.wait(0.4)
                elif getattr(role, "value", "") == "appearance":
                    appearance_read.set()
                return payload

            def controlled_write(payload):
                if getattr(role, "value", "") == "notifications":
                    appearance_written.wait(0.4)
                original_write(payload)
                if getattr(role, "value", "") == "appearance":
                    appearance_written.set()

            prefs._read = controlled_read
            prefs._write_payload = controlled_write

            def set_notifications():
                role.value = "notifications"
                return prefs.set_notifications_enabled(False)

            def set_appearance():
                role.value = "appearance"
                return prefs.set_pet_appearance("shirt")

            with ThreadPoolExecutor(max_workers=2) as executor:
                notification_future = executor.submit(set_notifications)
                self.assertTrue(notification_read.wait(1))
                appearance_future = executor.submit(set_appearance)
                self.assertTrue(notification_future.result(timeout=2))
                self.assertTrue(appearance_future.result(timeout=2))

            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertFalse(payload["notifications_enabled"])
            self.assertEqual(payload["pet_appearance"], "shirt")
            self.assertEqual(payload["future_preference"], {"keep": True})


if __name__ == "__main__":
    unittest.main()
