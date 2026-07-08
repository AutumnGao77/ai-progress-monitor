import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from scripts import build_release
from scripts import validate_release


class ReleaseBundleTests(unittest.TestCase):
    def test_validate_release_js_syntax_accepts_rendered_html_template(self):
        env = os.environ.copy()
        env["PYTHONPATH"] = "src"

        validate_release.check_js_syntax(env)

    def test_release_readme_mentions_direct_cli_and_wrapper_boundary(self):
        source = (Path(__file__).resolve().parents[1] / "scripts" / "build_release.py").read_text()

        self.assertIn("Direct Claude/Codex CLI detection", source)
        self.assertNotIn("green running bubble", source)
        self.assertIn("process-only bubble", source)
        self.assertIn("quiet idle stays idle", source)
        self.assertIn("Codex CLI is currently classified conservatively", source)
        self.assertIn("15 minutes", source)
        self.assertNotIn("weak-detection bubble", source)
        self.assertIn("a freshly completed reply becomes needs-action until you click its bubble", source)
        self.assertIn("Clicking the bubble and successfully returning to the terminal marks that reply as viewed", source)
        self.assertIn("does not display terminal content", source)
        self.assertIn("Run wrapper commands from the project folder you want Claude/Codex to work in", source)
        self.assertIn("If AI_MONITOR_SESSION_ID is omitted, wrappers generate a unique session ID per run", source)
        self.assertIn("--response-dir writes wrapper response files", source)
        self.assertIn("Run release smoke test", source)
        self.assertIn("scripts/e2e_smoke.py --artifact", source)
        self.assertIn("Python 3.9+ is required", source)
        self.assertIn("Pet visual assets", source)
        self.assertIn("/assets/pet/idle.png", source)
        self.assertIn("/assets/pet/running.png", source)
        self.assertIn("/assets/pet/needs-action.png", source)
        self.assertIn("/assets/app-avatar.png", source)
        self.assertIn("the menu bar item uses the avatar icon instead of AI text", source)
        self.assertIn("pet_assets.idle", source)
        self.assertIn("pet_assets.needs_action", source)
        self.assertIn("Pet image backgrounds transparent", source)
        self.assertIn("This package is built locally and is not notarized by Apple", source)
        self.assertIn("does not upload session content", source)
        self.assertNotIn("/Users/", source)
        self.assertNotIn("infer needs-action prompts", source)

    def test_zipapp_filter_excludes_candidate_assets_and_system_files(self):
        src = Path(__file__).resolve().parents[1] / "src"

        self.assertTrue(build_release.include_pyz_path(src / "ai_progress_monitor" / "web.py"))
        self.assertTrue(
            build_release.include_pyz_path(
                src / "ai_progress_monitor" / "assets" / "sloth-pet-idle.png"
            )
        )
        self.assertFalse(
            build_release.include_pyz_path(
                src / "ai_progress_monitor" / "assets" / "sloth-candidates" / "idle.png"
            )
        )
        self.assertFalse(build_release.include_pyz_path(src / ".DS_Store"))

    def test_verify_release_bundle_requires_bridge_scripts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            release_zip = Path(temp_dir) / "release.zip"
            with zipfile.ZipFile(release_zip, "w") as archive:
                archive.writestr("ai-progress-monitor/ai-progress-monitor.pyz", "")
                archive.writestr("ai-progress-monitor/README.txt", "")
                archive.writestr("ai-progress-monitor/AI Progress Monitor.app/Contents/Info.plist", "")
                archive.writestr("ai-progress-monitor/AI Progress Monitor.app/Contents/MacOS/AI Progress Monitor", "")
                archive.writestr("ai-progress-monitor/AI Progress Monitor.app/Contents/Resources/ai-progress-monitor.pyz", "")
                archive.writestr("ai-progress-monitor/AI Progress Monitor.app/Contents/Resources/app-avatar.png", "")
                archive.writestr("ai-progress-monitor/AI Progress Monitor.app/Contents/Resources/AppIcon.icns", "")
                archive.writestr("ai-progress-monitor/AI Progress Monitor Floating.app/Contents/Info.plist", "")
                archive.writestr("ai-progress-monitor/AI Progress Monitor Floating.app/Contents/MacOS/AI Progress Monitor Floating", "")
                archive.writestr("ai-progress-monitor/AI Progress Monitor Floating.app/Contents/Resources/ai-progress-monitor.pyz", "")
                archive.writestr("ai-progress-monitor/AI Progress Monitor Floating.app/Contents/Resources/app-avatar.png", "")
                archive.writestr("ai-progress-monitor/AI Progress Monitor Floating.app/Contents/Resources/AppIcon.icns", "")
                archive.writestr("ai-progress-monitor/AI Progress Monitor Floating.app/Contents/Resources/FloatingMonitor.swift", "")
                archive.writestr("ai-progress-monitor/AI Progress Monitor Floating.app/Contents/Resources/FloatingMonitorGeometry.swift", "")
                archive.writestr("ai-progress-monitor/native/windows/FloatingMonitor.ps1", "")
                archive.writestr("ai-progress-monitor/scripts/doctor.py", "")
                archive.writestr("ai-progress-monitor/scripts/e2e_smoke.py", "")
                archive.writestr("ai-progress-monitor/scripts/monitor_command.py", "")
                archive.writestr("ai-progress-monitor/scripts/monitor_claude.sh", "")
                archive.writestr("ai-progress-monitor/scripts/monitor_codex.sh", "")
                archive.writestr("ai-progress-monitor/scripts/monitor_claude.bat", "")
                archive.writestr("ai-progress-monitor/scripts/monitor_codex.bat", "")
                archive.writestr("ai-progress-monitor/scripts/start_floating_monitor.bat", "")
                archive.writestr("ai-progress-monitor/scripts/start_monitor.sh", "")
                archive.writestr("ai-progress-monitor/scripts/start_monitor.bat", "")

            with mock.patch.object(build_release, "RELEASE_ZIP", release_zip):
                build_release.verify_release_bundle()

    def test_verify_release_bundle_fails_when_bridge_script_missing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            release_zip = Path(temp_dir) / "release.zip"
            with zipfile.ZipFile(release_zip, "w") as archive:
                archive.writestr("ai-progress-monitor/ai-progress-monitor.pyz", "")
                archive.writestr("ai-progress-monitor/README.txt", "")

            with mock.patch.object(build_release, "RELEASE_ZIP", release_zip):
                with self.assertRaises(SystemExit):
                    build_release.verify_release_bundle()


if __name__ == "__main__":
    unittest.main()
