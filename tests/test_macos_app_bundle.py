import contextlib
import io
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import build_release


def write_stub_executable(executable: Path) -> None:
    executable.write_text("native executable", encoding="utf-8")
    executable.chmod(0o755)


class MacOSAppBundleTests(unittest.TestCase):
    def test_create_macos_app_bundle_contains_native_executable_and_pyz(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            artifact = root / "ai-progress-monitor.pyz"
            artifact.write_text("pyz", encoding="utf-8")
            app_path = root / "AI Progress Monitor.app"

            with (
                mock.patch.object(build_release, "ARTIFACT", artifact),
                mock.patch.object(
                    build_release,
                    "compile_macos_app_executable",
                    side_effect=write_stub_executable,
                ) as compile_app,
                mock.patch.object(build_release, "sign_macos_app_bundle"),
            ):
                build_release.create_macos_app_bundle(app_path)

            executable = app_path / "Contents/MacOS/AI Progress Monitor"
            self.assertTrue((app_path / "Contents/Info.plist").exists())
            self.assertTrue(executable.exists())
            self.assertTrue((app_path / "Contents/Resources/ai-progress-monitor.pyz").exists())
            compile_app.assert_called_once_with(executable)

    def test_macos_app_bundle_has_release_identity_version_and_icon(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            artifact = root / "ai-progress-monitor.pyz"
            artifact.write_text("pyz", encoding="utf-8")
            app_path = root / "AI Progress Monitor.app"

            with (
                mock.patch.object(build_release, "ARTIFACT", artifact),
                mock.patch.object(
                    build_release,
                    "compile_macos_app_executable",
                    side_effect=write_stub_executable,
                ),
                mock.patch.object(build_release, "sign_macos_app_bundle"),
            ):
                build_release.create_macos_app_bundle(app_path)

            resources = app_path / "Contents/Resources"
            plist = (app_path / "Contents/Info.plist").read_text(encoding="utf-8")
            icon = resources / "AppIcon.icns"

            self.assertTrue((resources / "app-avatar.png").exists())
            self.assertTrue(icon.exists())
            self.assertEqual(icon.read_bytes()[:4], b"icns")
            self.assertIn("<string>AI Progress Monitor</string>", plist)
            self.assertNotIn("AI Progress Monitor Floating", plist)
            self.assertIn("<string>local.ai-progress-monitor</string>", plist)
            self.assertEqual(
                plist.count(f"<string>{build_release.RELEASE_VERSION}</string>"),
                2,
            )
            self.assertIn(
                f"<string>{build_release.MACOS_MINIMUM_VERSION}</string>",
                plist,
            )

    def test_macos_release_app_does_not_embed_build_sources(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            artifact = root / "ai-progress-monitor.pyz"
            artifact.write_text("pyz", encoding="utf-8")
            app_path = root / "AI Progress Monitor.app"

            with (
                mock.patch.object(build_release, "ARTIFACT", artifact),
                mock.patch.object(
                    build_release,
                    "compile_macos_app_executable",
                    side_effect=write_stub_executable,
                ),
                mock.patch.object(build_release, "sign_macos_app_bundle"),
            ):
                build_release.create_macos_app_bundle(app_path)

            resources = app_path / "Contents/Resources"
            self.assertFalse((resources / "FloatingMonitor.swift").exists())
            self.assertFalse((resources / "FloatingMonitorGeometry.swift").exists())
            self.assertFalse((resources / "BUILD_FLOATING_APP.txt").exists())

    def test_native_compile_targets_arm64_and_supported_macos(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            executable = Path(temp_dir) / "AI Progress Monitor"

            def fake_run(command, **_kwargs):
                output = Path(command[command.index("-o") + 1])
                write_stub_executable(output)
                return subprocess.CompletedProcess(command, 0, "", "")

            with (
                mock.patch("scripts.build_release.shutil.which", return_value="/usr/bin/swiftc"),
                mock.patch("scripts.build_release.subprocess.run", side_effect=fake_run) as run_compile,
            ):
                build_release.compile_macos_app_executable(executable)

            command = run_compile.call_args.args[0]
            self.assertIn("-target", command)
            self.assertIn(
                f"arm64-apple-macos{build_release.MACOS_MINIMUM_VERSION}",
                command,
            )
            self.assertTrue(executable.exists())

    def test_native_compile_fails_when_swiftc_is_missing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            executable = Path(temp_dir) / "AI Progress Monitor"

            with mock.patch("scripts.build_release.shutil.which", return_value=None):
                with self.assertRaises(SystemExit):
                    build_release.compile_macos_app_executable(executable)

            self.assertFalse(executable.exists())

    def test_native_compile_failure_cannot_create_placeholder_app(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            executable = Path(temp_dir) / "AI Progress Monitor"
            failed = subprocess.CompletedProcess(["swiftc"], 1, "", "compile failed")

            with (
                mock.patch("scripts.build_release.shutil.which", return_value="/usr/bin/swiftc"),
                mock.patch("scripts.build_release.subprocess.run", return_value=failed),
            ):
                with contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit):
                        build_release.compile_macos_app_executable(executable)

            self.assertFalse(executable.exists())

    def test_bundle_creation_signs_macos_app(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            artifact = root / "ai-progress-monitor.pyz"
            artifact.write_text("pyz", encoding="utf-8")
            app_path = root / "AI Progress Monitor.app"

            with (
                mock.patch.object(build_release, "ARTIFACT", artifact),
                mock.patch.object(
                    build_release,
                    "compile_macos_app_executable",
                    side_effect=write_stub_executable,
                ),
                mock.patch.object(build_release, "sign_macos_app_bundle") as sign_bundle,
            ):
                build_release.create_macos_app_bundle(app_path)

            sign_bundle.assert_called_once_with(app_path)

    def test_macos_release_fails_when_codesign_is_missing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            app_path = Path(temp_dir) / "AI Progress Monitor.app"

            with mock.patch("scripts.build_release.shutil.which", return_value=None):
                with self.assertRaises(SystemExit):
                    build_release.sign_macos_app_bundle(app_path)

    def test_release_version_matches_python_and_project_metadata(self):
        from ai_progress_monitor import __version__

        pyproject = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text()

        self.assertEqual(build_release.RELEASE_VERSION, __version__)
        self.assertIn(f'version = "{__version__}"', pyproject)


if __name__ == "__main__":
    unittest.main()
