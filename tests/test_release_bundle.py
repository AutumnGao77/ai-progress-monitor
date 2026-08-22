import contextlib
import io
import os
import subprocess
import tempfile
import unittest
import zipapp
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


def run_git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        check=True,
        text=True,
    )
    return completed.stdout.strip()


def create_release_repository(root: Path, version: str = "0.3.1") -> str:
    package_dir = root / "src" / "ai_progress_monitor"
    package_dir.mkdir(parents=True)
    scripts_dir = root / "scripts"
    scripts_dir.mkdir()
    (package_dir / "__init__.py").write_text(
        f'__version__ = "{version}"\n',
        encoding="utf-8",
    )
    (scripts_dir / "build_release.py").write_text(
        "# release fixture\n",
        encoding="utf-8",
    )
    (scripts_dir / "build_release.py").chmod(0o755)
    (root / "pyproject.toml").write_text(
        "\n".join(
            [
                "[project]",
                'name = "ai-progress-monitor"',
                f'version = "{version}"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    run_git(root, "init", "-q")
    run_git(
        root,
        "add",
        "src/ai_progress_monitor/__init__.py",
        "scripts/build_release.py",
        "pyproject.toml",
    )
    run_git(
        root,
        "-c",
        "user.name=Test User",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "-q",
        "-m",
        "Initial release source",
    )
    return run_git(root, "rev-parse", "HEAD")


class ReleaseBundleTests(unittest.TestCase):
    def test_ci_runs_the_same_complete_release_validation_as_local(self):
        workflow = (
            Path(__file__).resolve().parents[1] / ".github" / "workflows" / "validate.yml"
        ).read_text(encoding="utf-8")

        self.assertEqual(workflow.count("python3 scripts/validate_release.py"), 1)
        self.assertNotIn("python3 -m unittest", workflow)

    def test_main_stops_before_validation_or_dist_cleanup_when_source_is_invalid(self):
        with contextlib.ExitStack() as stack:
            stack.enter_context(
                mock.patch.object(
                    build_release,
                    "validate_release_source",
                    side_effect=SystemExit("invalid release source"),
                )
            )
            run = stack.enter_context(mock.patch.object(build_release, "run"))
            rmtree = stack.enter_context(
                mock.patch.object(build_release.shutil, "rmtree")
            )
            create_archive = stack.enter_context(
                mock.patch.object(build_release.zipapp, "create_archive")
            )
            with self.assertRaisesRegex(SystemExit, "invalid release source"):
                build_release.main(["--source-commit", "0" * 40])

        run.assert_not_called()
        rmtree.assert_not_called()
        create_archive.assert_not_called()

    def test_main_builds_snapshot_then_revalidates_before_replacing_dist(self):
        source_commit = "a" * 40
        events = []

        def validate(*args, **kwargs):
            events.append("validate")
            return source_commit

        def export(*args, **kwargs):
            events.append("export")

        def build(*args, **kwargs):
            events.append("build")

        def replace(*args, **kwargs):
            events.append("replace")

        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.dict(os.environ, {}, clear=True))
            stack.enter_context(
                mock.patch.object(
                    build_release,
                    "validate_release_source",
                    side_effect=validate,
                )
            )
            stack.enter_context(
                mock.patch.object(
                    build_release,
                    "export_release_source",
                    side_effect=export,
                )
            )
            stack.enter_context(
                mock.patch.object(
                    build_release,
                    "run_isolated_source_build",
                    side_effect=build,
                )
            )
            stack.enter_context(
                mock.patch.object(
                    build_release,
                    "replace_release_dist",
                    side_effect=replace,
                )
            )
            with contextlib.redirect_stdout(io.StringIO()):
                result = build_release.main(["--source-commit", source_commit])

        self.assertEqual(result, 0)
        self.assertEqual(events, ["validate", "export", "build", "validate", "replace"])

    def test_main_does_not_replace_dist_when_post_build_validation_fails(self):
        source_commit = "a" * 40
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.dict(os.environ, {}, clear=True))
            stack.enter_context(
                mock.patch.object(
                    build_release,
                    "validate_release_source",
                    side_effect=[source_commit, SystemExit("source changed during build")],
                )
            )
            stack.enter_context(
                mock.patch.object(build_release, "export_release_source")
            )
            stack.enter_context(
                mock.patch.object(build_release, "run_isolated_source_build")
            )
            replace = stack.enter_context(
                mock.patch.object(build_release, "replace_release_dist")
            )

            with self.assertRaisesRegex(SystemExit, "source changed during build"):
                build_release.main(["--source-commit", source_commit])

        replace.assert_not_called()

    def test_dist_replacement_restores_previous_output_when_swap_fails(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_dist = root / "snapshot-dist"
            target_dist = root / "dist"
            source_dist.mkdir()
            target_dist.mkdir()
            (source_dist / "new.txt").write_text("new\n", encoding="utf-8")
            (target_dist / "old.txt").write_text("old\n", encoding="utf-8")
            real_rename = Path.rename
            rename_count = 0

            def fail_new_dist_swap(path, target):
                nonlocal rename_count
                rename_count += 1
                if rename_count == 2:
                    raise OSError("simulated swap failure")
                return real_rename(path, target)

            with mock.patch.object(
                Path,
                "rename",
                autospec=True,
                side_effect=fail_new_dist_swap,
            ):
                with self.assertRaisesRegex(OSError, "simulated swap failure"):
                    build_release.replace_release_dist(source_dist, target_dist)

            self.assertEqual((target_dist / "old.txt").read_text(), "old\n")
            self.assertFalse((target_dist / "new.txt").exists())

    def test_dist_replacement_preserves_backup_when_swap_and_restore_fail(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_dist = root / "snapshot-dist"
            target_dist = root / "dist"
            source_dist.mkdir()
            target_dist.mkdir()
            (source_dist / "new.txt").write_text("new\n", encoding="utf-8")
            (target_dist / "old.txt").write_text("old\n", encoding="utf-8")
            real_rename = Path.rename
            rename_count = 0

            def fail_swap_and_restore(path, target):
                nonlocal rename_count
                rename_count += 1
                if rename_count in {2, 3}:
                    raise OSError(f"simulated rename failure {rename_count}")
                return real_rename(path, target)

            with mock.patch.object(
                Path,
                "rename",
                autospec=True,
                side_effect=fail_swap_and_restore,
            ):
                with self.assertRaisesRegex(RuntimeError, "previous output preserved at"):
                    build_release.replace_release_dist(source_dist, target_dist)

            backups = list(
                (root / "build").glob("release-output-*/previous-dist/old.txt")
            )
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_text(), "old\n")
            self.assertFalse(target_dist.exists())

    def test_release_source_export_uses_only_committed_content(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "repository"
            root.mkdir()
            source_commit = create_release_repository(root)
            (root / ".gitignore").write_text("*.key\n", encoding="utf-8")
            run_git(root, "add", ".gitignore")
            run_git(
                root,
                "-c",
                "user.name=Test User",
                "-c",
                "user.email=test@example.invalid",
                "commit",
                "-q",
                "-m",
                "Ignore private keys",
            )
            source_commit = run_git(root, "rev-parse", "HEAD")
            (root / "src" / "ai_progress_monitor" / "__init__.py").write_text(
                '__version__ = "modified"\n',
                encoding="utf-8",
            )
            (root / "src" / "private.key").write_text(
                "ignored secret\n",
                encoding="utf-8",
            )
            snapshot = Path(temp_dir) / "snapshot"

            build_release.export_release_source(
                source_commit,
                snapshot,
                root=root,
            )

            self.assertEqual(
                (snapshot / "src" / "ai_progress_monitor" / "__init__.py").read_text(),
                '__version__ = "0.3.1"\n',
            )
            self.assertFalse((snapshot / "src" / "private.key").exists())
            self.assertTrue(os.access(snapshot / "scripts" / "build_release.py", os.X_OK))

    def test_project_version_is_read_only_from_project_section(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project_file = Path(temp_dir) / "pyproject.toml"
            project_file.write_text(
                "\n".join(
                    [
                        "[tool.example]",
                        'version = "9.9.9"',
                        "",
                        "[project]",
                        'version = "0.3.1"',
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            self.assertEqual(build_release.load_project_version(project_file), "0.3.1")

    def test_release_source_validation_fails_when_tag_lookup_errors(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_commit = create_release_repository(root)
            real_git = build_release._git

            def failing_tag_lookup(git_root, *args):
                if args and args[0] == "for-each-ref":
                    return subprocess.CompletedProcess(
                        ["git", *args],
                        128,
                        stdout="",
                        stderr="tag database unavailable",
                    )
                return real_git(git_root, *args)

            with mock.patch.object(
                build_release,
                "_git",
                side_effect=failing_tag_lookup,
            ):
                with self.assertRaisesRegex(SystemExit, "release tag lookup failed"):
                    build_release.validate_release_source(
                        source_commit,
                        root=root,
                        release_version="0.3.1",
                        project_file=root / "pyproject.toml",
                    )

    def test_release_git_commands_ignore_external_git_control_environment(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "release-repository"
            other_root = Path(temp_dir) / "other-repository"
            root.mkdir()
            other_root.mkdir()
            source_commit = create_release_repository(root)
            create_release_repository(other_root)

            with mock.patch.dict(
                os.environ,
                {
                    "GIT_DIR": str(other_root / ".git"),
                    "GIT_WORK_TREE": str(other_root),
                    "GIT_INDEX_FILE": str(other_root / ".git" / "index"),
                },
                clear=False,
            ):
                validated = build_release.validate_release_source(
                    source_commit,
                    root=root,
                    release_version="0.3.1",
                    project_file=root / "pyproject.toml",
                )

            self.assertEqual(validated, source_commit)
            with self.assertRaisesRegex(SystemExit, "repository root"):
                build_release.validate_release_source(
                    source_commit,
                    root=root / "src",
                    release_version="0.3.1",
                    project_file=root / "pyproject.toml",
                )

    def test_isolated_build_child_receives_sanitized_environment(self):
        completed = subprocess.CompletedProcess(["python3"], 0, stdout="", stderr="")
        with mock.patch.dict(
            os.environ,
            {
                "GIT_DIR": "/tmp/wrong-git-dir",
                "GIT_WORK_TREE": "/tmp/wrong-work-tree",
                "PYTHONHOME": "/tmp/wrong-python-home",
                "PYTHONPATH": "/tmp/wrong-python-path",
                "RELEASE_TEST_KEEP": "yes",
            },
            clear=True,
        ):
            with mock.patch.object(
                build_release.subprocess,
                "run",
                return_value=completed,
            ) as run:
                build_release.run_isolated_source_build(
                    Path("/tmp/release-source"),
                    "a" * 40,
                )

        child_env = run.call_args.kwargs["env"]
        self.assertEqual(child_env["RELEASE_TEST_KEEP"], "yes")
        self.assertNotIn("GIT_DIR", child_env)
        self.assertNotIn("GIT_WORK_TREE", child_env)
        self.assertNotIn("PYTHONHOME", child_env)
        self.assertNotIn("PYTHONPATH", child_env)

    def test_release_source_validation_accepts_clean_exact_commit_without_candidate_tag(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_commit = create_release_repository(root)

            validated = build_release.validate_release_source(
                source_commit,
                root=root,
                release_version="0.3.1",
                project_file=root / "pyproject.toml",
            )

            self.assertEqual(validated, source_commit)

    def test_release_source_validation_requires_full_commit_and_clean_worktree(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_commit = create_release_repository(root)

            with self.assertRaises(SystemExit):
                build_release.validate_release_source(
                    source_commit[:7],
                    root=root,
                    release_version="0.3.1",
                    project_file=root / "pyproject.toml",
                )

            (root / "untracked.txt").write_text("not part of the release\n", encoding="utf-8")
            with self.assertRaises(SystemExit):
                build_release.validate_release_source(
                    source_commit,
                    root=root,
                    release_version="0.3.1",
                    project_file=root / "pyproject.toml",
                )

    def test_release_source_validation_rejects_wrong_head_or_project_version(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            original_commit = create_release_repository(root)
            (root / "pyproject.toml").write_text(
                '[project]\nname = "ai-progress-monitor"\nversion = "0.3.2"\n',
                encoding="utf-8",
            )
            run_git(root, "add", "pyproject.toml")
            run_git(
                root,
                "-c",
                "user.name=Test User",
                "-c",
                "user.email=test@example.invalid",
                "commit",
                "-q",
                "-m",
                "Change version",
            )
            current_commit = run_git(root, "rev-parse", "HEAD")

            with self.assertRaises(SystemExit):
                build_release.validate_release_source(
                    original_commit,
                    root=root,
                    release_version="0.3.1",
                    project_file=root / "pyproject.toml",
                )
            with self.assertRaises(SystemExit):
                build_release.validate_release_source(
                    current_commit,
                    root=root,
                    release_version="0.3.1",
                    project_file=root / "pyproject.toml",
                )

    def test_release_source_validation_rejects_lightweight_or_conflicting_tag(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            original_commit = create_release_repository(root)
            run_git(root, "tag", "v0.3.1")

            with self.assertRaises(SystemExit):
                build_release.validate_release_source(
                    original_commit,
                    root=root,
                    release_version="0.3.1",
                    project_file=root / "pyproject.toml",
                )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            original_commit = create_release_repository(root)
            run_git(
                root,
                "-c",
                "user.name=Test User",
                "-c",
                "user.email=test@example.invalid",
                "tag",
                "-a",
                "v0.3.1",
                "-m",
                "Candidate tag",
                original_commit,
            )
            (root / "next.txt").write_text("next\n", encoding="utf-8")
            run_git(root, "add", "next.txt")
            run_git(
                root,
                "-c",
                "user.name=Test User",
                "-c",
                "user.email=test@example.invalid",
                "commit",
                "-q",
                "-m",
                "Next source",
            )
            current_commit = run_git(root, "rev-parse", "HEAD")

            with self.assertRaises(SystemExit):
                build_release.validate_release_source(
                    current_commit,
                    root=root,
                    release_version="0.3.1",
                    project_file=root / "pyproject.toml",
                )

    def test_release_source_validation_requires_exact_annotated_tag_for_final_build(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_commit = create_release_repository(root)

            with self.assertRaises(SystemExit):
                build_release.validate_release_source(
                    source_commit,
                    require_tag=True,
                    root=root,
                    release_version="0.3.1",
                    project_file=root / "pyproject.toml",
                )

            run_git(
                root,
                "-c",
                "user.name=Test User",
                "-c",
                "user.email=test@example.invalid",
                "tag",
                "-a",
                "v0.3.1",
                "-m",
                "Accepted release",
                source_commit,
            )

            validated = build_release.validate_release_source(
                source_commit,
                require_tag=True,
                root=root,
                release_version="0.3.1",
                project_file=root / "pyproject.toml",
            )

            self.assertEqual(validated, source_commit)

    def test_portable_runtime_verification_uses_packaged_entries(self):
        with mock.patch.object(build_release, "run") as run:
            build_release.verify_portable_runtime_entries()

        portable = build_release.PORTABLE_RELEASE_DIR
        artifact = portable / "ai-progress-monitor.pyz"
        run.assert_has_calls(
            [
                mock.call(
                    [
                        build_release.sys.executable,
                        str(portable / "scripts" / "monitor_command.py"),
                        "--help",
                    ]
                ),
                mock.call(
                    [
                        build_release.sys.executable,
                        str(portable / "scripts" / "doctor.py"),
                        "--help",
                    ]
                ),
                mock.call(
                    [
                        build_release.sys.executable,
                        str(portable / "scripts" / "e2e_smoke.py"),
                        "--artifact",
                        str(artifact),
                    ]
                ),
            ]
        )

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
        self.assertFalse(build_release.include_pyz_path(src / "private.key"))
        self.assertFalse(build_release.include_pyz_path(src / "backup.bak"))
        self.assertFalse(
            build_release.include_pyz_path(
                src / "ai_progress_monitor" / "compiled.pyc"
            )
        )

    def test_zipapp_filter_builds_expected_runtime_without_unknown_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            archive_path = Path(temp_dir) / "monitor.pyz"
            zipapp.create_archive(
                Path(__file__).resolve().parents[1] / "src",
                target=archive_path,
                main="ai_progress_monitor.web:main",
                filter=build_release.include_pyz_path,
                compressed=True,
            )

            with zipfile.ZipFile(archive_path) as archive:
                names = set(archive.namelist())

        self.assertIn("ai_progress_monitor/web.py", names)
        self.assertIn("ai_progress_monitor/assets/sloth-pet-idle.png", names)
        self.assertNotIn("ai_progress_monitor/compiled.pyc", names)

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
