import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import build_release


class MacOSAppBundleTests(unittest.TestCase):
    def test_create_macos_app_bundle_contains_launcher_and_pyz(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            artifact = root / "ai-progress-monitor.pyz"
            artifact.write_text("pyz")
            app_path = root / "AI Progress Monitor.app"

            with mock.patch.object(build_release, "ARTIFACT", artifact):
                build_release.create_macos_app_bundle(app_path)

            self.assertTrue((app_path / "Contents/Info.plist").exists())
            self.assertTrue((app_path / "Contents/MacOS/AI Progress Monitor").exists())
            self.assertTrue((app_path / "Contents/Resources/ai-progress-monitor.pyz").exists())

    def test_macos_app_bundles_include_app_icon_resources(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            artifact = root / "ai-progress-monitor.pyz"
            artifact.write_text("pyz")
            app_path = root / "AI Progress Monitor.app"
            floating_path = root / "AI Progress Monitor Floating.app"

            with (
                mock.patch.object(build_release, "ARTIFACT", artifact),
                mock.patch.object(build_release, "sign_macos_app_bundle"),
                mock.patch("scripts.build_release.shutil.which", return_value=None),
            ):
                build_release.create_macos_app_bundle(app_path)
                build_release.create_macos_floating_app_bundle(floating_path)

            for bundle in (app_path, floating_path):
                with self.subTest(bundle=bundle.name):
                    resources = bundle / "Contents" / "Resources"
                    plist = (bundle / "Contents" / "Info.plist").read_text()
                    icon = resources / "AppIcon.icns"

                    self.assertTrue((resources / "app-avatar.png").exists())
                    self.assertTrue(icon.exists())
                    self.assertEqual(icon.read_bytes()[:4], b"icns")
                    self.assertIn("<key>CFBundleIconFile</key>", plist)
                    self.assertIn("<string>AppIcon</string>", plist)
                    self.assertEqual(
                        plist.count(f"<string>{build_release.RELEASE_VERSION}</string>"),
                        2,
                    )

    def test_release_version_matches_python_and_project_metadata(self):
        from ai_progress_monitor import __version__

        pyproject = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text()

        self.assertEqual(build_release.RELEASE_VERSION, __version__)
        self.assertIn(f'version = "{__version__}"', pyproject)

    def test_launcher_opens_pyz_with_open_flag(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            artifact = root / "ai-progress-monitor.pyz"
            artifact.write_text("pyz")
            app_path = root / "AI Progress Monitor.app"

            with mock.patch.object(build_release, "ARTIFACT", artifact):
                build_release.create_macos_app_bundle(app_path)

            launcher = (app_path / "Contents/MacOS/AI Progress Monitor").read_text()
            self.assertIn("--open", launcher)
            self.assertIn("ai-progress-monitor.pyz", launcher)

    def test_launcher_writes_user_visible_log(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            artifact = root / "ai-progress-monitor.pyz"
            artifact.write_text("pyz")
            app_path = root / "AI Progress Monitor.app"

            with mock.patch.object(build_release, "ARTIFACT", artifact):
                build_release.create_macos_app_bundle(app_path)

            launcher = (app_path / "Contents/MacOS/AI Progress Monitor").read_text()
            self.assertIn("AI Progress Monitor", launcher)
            self.assertIn("monitor.log", launcher)
            self.assertIn("mkdir -p", launcher)
            self.assertIn("exec", launcher)
            self.assertIn('>>"$LOG_FILE" 2>&1', launcher)

    def test_bundle_creation_signs_macos_app_bundles(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            artifact = root / "ai-progress-monitor.pyz"
            artifact.write_text("pyz")
            app_path = root / "AI Progress Monitor.app"
            floating_path = root / "AI Progress Monitor Floating.app"

            with (
                mock.patch.object(build_release, "ARTIFACT", artifact),
                mock.patch.object(build_release, "sign_macos_app_bundle") as sign_bundle,
                mock.patch("scripts.build_release.shutil.which", return_value=None),
            ):
                build_release.create_macos_app_bundle(app_path)
                build_release.create_macos_floating_app_bundle(floating_path)

            sign_bundle.assert_has_calls([mock.call(app_path), mock.call(floating_path)])


if __name__ == "__main__":
    unittest.main()
