import contextlib
import io
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from scripts import build_release
from scripts import validate_release


def write_archive(path: Path, names: set[str]) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        for name in sorted(names):
            archive.writestr(name, "")


def required_macos_names() -> set[str]:
    root = build_release.MACOS_RELEASE_DIR.name
    app = f"{root}/AI Progress Monitor.app/Contents"
    return {
        f"{root}/README.txt",
        f"{root}/LICENSE",
        f"{app}/Info.plist",
        f"{app}/MacOS/AI Progress Monitor",
        f"{app}/Resources/ai-progress-monitor.pyz",
        f"{app}/Resources/app-avatar.png",
        f"{app}/Resources/AppIcon.icns",
    }


def required_portable_names() -> set[str]:
    root = build_release.PORTABLE_RELEASE_DIR.name
    return {
        f"{root}/ai-progress-monitor.pyz",
        f"{root}/README.txt",
        f"{root}/LICENSE",
        f"{root}/native/windows/FloatingMonitor.ps1",
        f"{root}/scripts/doctor.py",
        f"{root}/scripts/e2e_smoke.py",
        f"{root}/scripts/monitor_command.py",
        f"{root}/scripts/monitor_claude.sh",
        f"{root}/scripts/monitor_codex.sh",
        f"{root}/scripts/monitor_qoder.sh",
        f"{root}/scripts/monitor_workbuddy.sh",
        f"{root}/scripts/monitor_claude.bat",
        f"{root}/scripts/monitor_codex.bat",
        f"{root}/scripts/monitor_qoder.bat",
        f"{root}/scripts/monitor_workbuddy.bat",
        f"{root}/scripts/start_floating_monitor.bat",
        f"{root}/scripts/start_monitor.sh",
        f"{root}/scripts/start_monitor.bat",
    }


class ReleaseBundleTests(unittest.TestCase):
    def test_validate_release_js_syntax_accepts_rendered_html_template(self):
        env = os.environ.copy()
        env["PYTHONPATH"] = "src"

        validate_release.check_js_syntax(env)

    def test_validate_release_js_syntax_checks_rendered_html_not_raw_template(self):
        env = os.environ.copy()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            package_dir = root / "src" / "ai_progress_monitor"
            package_dir.mkdir(parents=True)
            (package_dir / "__init__.py").write_text("", encoding="utf-8")
            (package_dir / "web.py").write_text(
                '\n'.join(
                    [
                        "def render_html(token):",
                        '    return """<script>window.PET_THEMES = ;</script>"""',
                        "",
                        'HTML_TEMPLATE = """<script>window.PET_THEMES = __PET_THEMES__;</script>"""',
                        "",
                        'HTML = render_html("token")',
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            env["PYTHONPATH"] = str(root / "src")

            with mock.patch.object(validate_release, "ROOT", root):
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit):
                        validate_release.check_js_syntax(env)

    def test_sensitive_scan_includes_github_workflows(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workflow_dir = root / ".github" / "workflows"
            workflow_dir.mkdir(parents=True)
            (workflow_dir / "validate.yml").write_text("owner: " + ("s" "to"), encoding="utf-8")

            with mock.patch.object(validate_release, "ROOT", root):
                with self.assertRaises(SystemExit):
                    validate_release.check_sensitive_text()

    def test_sensitive_scan_allows_common_words_containing_token(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            scripts_dir = root / "scripts"
            scripts_dir.mkdir()
            (scripts_dir / "sample.py").write_text(
                "restore = store = custom = stop = 'ordinary words'\n",
                encoding="utf-8",
            )

            with mock.patch.object(validate_release, "ROOT", root):
                validate_release.check_sensitive_text()

    def test_release_readme_mentions_direct_cli_and_wrapper_boundary(self):
        source = (Path(__file__).resolve().parents[1] / "scripts" / "build_release.py").read_text()

        self.assertIn("Direct configured AI CLI detection", source)
        self.assertNotIn("green running bubble", source)
        self.assertIn("process-only bubble", source)
        self.assertIn("quiet idle stays idle", source)
        self.assertIn("Qoder, WorkBuddy, codebuddy, and other generic CLI tools are currently classified conservatively", source)
        self.assertIn("Qoder Desktop sessions are read from local Qoder/Qoder CN logs", source)
        self.assertIn("WorkBuddy Desktop sessions are read from explicit local WorkBuddy session database states", source)
        self.assertIn("15 minutes", source)
        self.assertNotIn("weak-detection bubble", source)
        self.assertIn("a freshly completed reply becomes needs-action until you click its bubble", source)
        self.assertIn("Clicking the bubble and successfully returning to the terminal marks that reply as viewed", source)
        self.assertIn("does not display terminal content", source)
        self.assertIn("Run wrapper commands from the project folder you want the AI tool to work in", source)
        self.assertIn("monitor_qoder.sh", source)
        self.assertIn("monitor_workbuddy.sh", source)
        self.assertIn("If AI_MONITOR_SESSION_ID is omitted, wrappers generate a unique session ID per run", source)
        self.assertIn("--response-dir writes wrapper response files", source)
        self.assertIn("Run release smoke test", source)
        self.assertIn("scripts/e2e_smoke.py --artifact", source)
        self.assertIn("Python 3.9+ is required", source)
        self.assertIn("Pet visual assets", source)
        self.assertIn("/assets/pet/idle.png", source)
        self.assertIn("/assets/pet/running.png", source)
        self.assertIn("/assets/pet/needs-action.png", source)
        self.assertIn("/assets/pet/shirt.png", source)
        self.assertIn("/assets/app-avatar.png", source)
        self.assertIn("the menu bar item uses the avatar icon instead of AI text", source)
        self.assertIn("pet_assets.idle", source)
        self.assertIn("pet_assets.needs_action", source)
        self.assertIn("Pet image backgrounds transparent", source)
        self.assertIn("ad-hoc signed and is not notarized by Apple", source)
        self.assertIn("Do not disable Gatekeeper globally", source)
        self.assertIn("macOS desktop users should download the separate macOS arm64 package", source)
        self.assertNotIn("Double-click AI Progress Monitor Floating.app", source)
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
        self.assertTrue(
            build_release.include_pyz_path(
                src / "ai_progress_monitor" / "assets" / "sloth-pet-shirt.png"
            )
        )
        self.assertFalse(
            build_release.include_pyz_path(
                src / "ai_progress_monitor" / "assets" / "sloth-candidates" / "idle.png"
            )
        )
        self.assertFalse(build_release.include_pyz_path(src / ".DS_Store"))

    def test_verify_macos_release_bundle_accepts_only_primary_app_and_documents(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            release_zip = Path(temp_dir) / "macos.zip"
            write_archive(release_zip, required_macos_names())

            with mock.patch.object(build_release, "MACOS_RELEASE_ZIP", release_zip):
                build_release.verify_macos_release_bundle()

    def test_verify_macos_release_bundle_rejects_portable_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            release_zip = Path(temp_dir) / "macos.zip"
            root = build_release.MACOS_RELEASE_DIR.name
            names = required_macos_names() | {f"{root}/scripts/doctor.py"}
            write_archive(release_zip, names)

            with mock.patch.object(build_release, "MACOS_RELEASE_ZIP", release_zip):
                with self.assertRaises(SystemExit):
                    build_release.verify_macos_release_bundle()

    def test_verify_macos_release_bundle_rejects_build_sources(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            release_zip = Path(temp_dir) / "macos.zip"
            root = build_release.MACOS_RELEASE_DIR.name
            names = required_macos_names() | {
                f"{root}/AI Progress Monitor.app/Contents/Resources/FloatingMonitor.swift"
            }
            write_archive(release_zip, names)

            with mock.patch.object(build_release, "MACOS_RELEASE_ZIP", release_zip):
                with self.assertRaises(SystemExit):
                    build_release.verify_macos_release_bundle()

    def test_verify_portable_release_bundle_requires_integration_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            release_zip = Path(temp_dir) / "portable.zip"
            write_archive(release_zip, required_portable_names())

            with mock.patch.object(build_release, "PORTABLE_RELEASE_ZIP", release_zip):
                build_release.verify_portable_release_bundle()

    def test_verify_portable_release_bundle_rejects_macos_apps(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            release_zip = Path(temp_dir) / "portable.zip"
            root = build_release.PORTABLE_RELEASE_DIR.name
            names = required_portable_names() | {
                f"{root}/AI Progress Monitor.app/Contents/Info.plist"
            }
            write_archive(release_zip, names)

            with mock.patch.object(build_release, "PORTABLE_RELEASE_ZIP", release_zip):
                with self.assertRaises(SystemExit):
                    build_release.verify_portable_release_bundle()


if __name__ == "__main__":
    unittest.main()
