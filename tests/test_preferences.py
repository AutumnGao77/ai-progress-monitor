import tempfile
import unittest
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


if __name__ == "__main__":
    unittest.main()
