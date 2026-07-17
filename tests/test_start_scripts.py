import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _add_fake_shirt_asset_curl(env: dict, temp_dir: str) -> None:
    fake_bin = Path(temp_dir) / "bin"
    fake_bin.mkdir(exist_ok=True)
    fake_curl = fake_bin / "curl"
    fake_curl.write_text(
        """#!/bin/sh
headers=""
body=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    -D) headers="$2"; shift 2 ;;
    -o) body="$2"; shift 2 ;;
    -*) shift ;;
    *) shift ;;
  esac
done
printf 'HTTP/1.0 200 OK\\r\\ncache-control: no-store\\r\\n\\r\\n' > "$headers"
cat "$APPROVED_SHIRT_ASSET" > "$body"
""",
        encoding="utf-8",
    )
    fake_curl.chmod(0o755)
    env["PATH"] = str(fake_bin) + os.pathsep + env.get("PATH", "")


class StartScriptTests(unittest.TestCase):
    def test_shell_start_script_writes_log_and_shows_failure_hint(self):
        script = (ROOT / "scripts" / "start_monitor.sh").read_text()

        self.assertIn("AI Progress Monitor", script)
        self.assertIn("monitor.log", script)
        self.assertIn("mkdir -p", script)
        self.assertIn("tee -a", script)
        self.assertIn("Monitor failed", script)
        self.assertIn("Monitor stopped", script)

    def test_macos_dev_floating_runner_builds_stable_signed_app_without_release_packaging(self):
        script_path = ROOT / "scripts" / "run_macos_floating_dev.sh"
        self.assertTrue(script_path.exists())
        script = script_path.read_text()

        self.assertIn("build/macos-dev", script)
        self.assertIn("zipapp", script)
        self.assertIn("native/macos/FloatingMonitor.swift", script)
        self.assertIn("native/macos/FloatingMonitorGeometry.swift", script)
        self.assertIn("swiftc", script)
        self.assertIn("codesign --force --deep --sign -", script)
        self.assertIn("AI Progress Monitor Floating Dev.app", script)
        self.assertIn("app-avatar.png", script)
        self.assertIn("AppIcon.icns", script)
        self.assertIn("CFBundleIconFile", script)
        self.assertIn("menu bar icon -> Show Monitor", script)
        self.assertNotIn("menu bar AI -> Show Monitor", script)
        self.assertIn("--build-only", script)
        self.assertIn("--launch-only", script)
        self.assertIn("LAUNCH_ONLY=1", script)
        self.assertIn('pkill -x "AI Progress Monitor Floating"', script)
        self.assertIn("/usr/bin/open -n", script)
        self.assertNotIn("scripts/build_release.py", script)
        self.assertNotIn("ai-progress-monitor-release.zip", script)
        self.assertNotIn("dist/ai-progress-monitor", script)

    def test_macos_dev_floating_runner_can_reopen_without_rebuild_or_resign(self):
        script = (ROOT / "scripts" / "run_macos_floating_dev.sh").read_text()
        launch_only_branch = script[script.index('if [ "$LAUNCH_ONLY" = "1" ]; then'):]
        launch_only_branch = launch_only_branch[:launch_only_branch.index("fi\n\ncommand -v python3")]

        self.assertIn("launch_app", launch_only_branch)
        self.assertNotIn("zipapp", launch_only_branch)
        self.assertNotIn("swiftc", launch_only_branch)
        self.assertNotIn("codesign", launch_only_branch)
        self.assertIn("Existing development app not found", launch_only_branch)

    def test_macos_dev_acceptance_helper_reads_logs_without_gui_control(self):
        script_path = ROOT / "scripts" / "check_macos_floating_dev.sh"
        self.assertTrue(script_path.exists())
        script = script_path.read_text()

        self.assertIn("AI Progress Monitor Floating Dev", script)
        self.assertIn("~/Library/Logs/AI Progress Monitor/native-monitor.log", script)
        self.assertIn("AI Progress Monitor running at", script)
        self.assertIn("token=[REDACTED]", script)
        self.assertIn("AI Progress Monitor sessions:", script)
        self.assertIn("Received host message", script)
        self.assertIn("Show monitor requested", script)
        self.assertIn("Hide monitor requested", script)
        self.assertIn("Pet appearance asset check", script)
        self.assertIn("/assets/pet/shirt.png", script)
        self.assertIn("sloth-mascot-transparent.png", script)
        self.assertIn("cache-control: no-store", script)
        self.assertIn("Recent pet appearance changes", script)
        self.assertIn("Recent monitor service recovery", script)
        self.assertIn("Scheduling monitor service restart", script)
        self.assertIn("AI Progress Monitor pet appearance:", script)
        self.assertIn("matching AI tool window", script)
        self.assertIn("without accessibility permission", script)
        self.assertIn("pgrep", script)
        self.assertNotIn('LOG_FILE="${HOME}/Library/Logs/AI Progress Monitor/monitor.log"', script)
        self.assertNotIn("/usr/bin/open", script)
        self.assertNotIn("osascript", script)
        self.assertNotIn("cliclick", script)
        self.assertNotIn("corresponding Claude/Codex window", script)

    @unittest.skipUnless(os.name == "posix", "Shell helper execution is only available on POSIX systems")
    def test_macos_dev_acceptance_helper_redacts_monitor_token_in_output(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)
            log_dir = home / "Library" / "Logs" / "AI Progress Monitor"
            log_dir.mkdir(parents=True)
            (log_dir / "native-monitor.log").write_text(
                "AI Progress Monitor running at http://127.0.0.1:8765/?token=secret-token\n"
                "AI Progress Monitor sessions: total=4 needs_action=0 running=1 idle=3 process_only=4 full=0\n",
                encoding="utf-8",
            )
            env = os.environ.copy()
            env["HOME"] = str(home)

            completed = subprocess.run(
                ["sh", str(ROOT / "scripts" / "check_macos_floating_dev.sh")],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                timeout=10,
            )

            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            self.assertIn("token=[REDACTED]", completed.stdout)
            self.assertIn("AI Progress Monitor sessions: total=4", completed.stdout)
            self.assertNotIn("secret-token", completed.stdout)

    @unittest.skipUnless(os.name == "posix", "Shell helper execution is only available on POSIX systems")
    def test_macos_dev_acceptance_helper_checks_running_app_shirt_asset_route(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir) / "home"
            log_dir = home / "Library" / "Logs" / "AI Progress Monitor"
            log_dir.mkdir(parents=True)
            (log_dir / "native-monitor.log").write_text(
                "AI Progress Monitor running at http://127.0.0.1:8765/?token=secret-token\n"
                "AI Progress Monitor sessions: total=4 needs_action=0 running=1 idle=3 process_only=4 full=0\n",
                encoding="utf-8",
            )
            env = os.environ.copy()
            env["HOME"] = str(home)
            _add_fake_shirt_asset_curl(env, temp_dir)

            completed = subprocess.run(
                ["sh", str(ROOT / "scripts" / "check_macos_floating_dev.sh")],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                timeout=10,
            )

            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            self.assertIn("[OK] shirt asset route serves approved source image", completed.stdout)
            self.assertIn("[OK] shirt asset route disables caching", completed.stdout)
            self.assertNotIn("secret-token", completed.stdout)

    @unittest.skipUnless(os.name == "posix", "Shell helper execution is only available on POSIX systems")
    def test_macos_dev_acceptance_helper_reports_recent_pet_appearance_changes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir) / "home"
            log_dir = home / "Library" / "Logs" / "AI Progress Monitor"
            log_dir.mkdir(parents=True)
            (log_dir / "native-monitor.log").write_text(
                "AI Progress Monitor running at http://127.0.0.1:8765/?token=secret-token\n"
                "AI Progress Monitor sessions: total=4 needs_action=0 running=1 idle=3 process_only=4 full=0\n"
                "AI Progress Monitor pet appearance: shirt\n"
                "AI Progress Monitor pet appearance: default\n",
                encoding="utf-8",
            )
            env = os.environ.copy()
            env["HOME"] = str(home)
            _add_fake_shirt_asset_curl(env, temp_dir)

            completed = subprocess.run(
                ["sh", str(ROOT / "scripts" / "check_macos_floating_dev.sh")],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                timeout=10,
            )

            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            self.assertIn("Recent pet appearance changes:", completed.stdout)
            self.assertIn("AI Progress Monitor pet appearance: shirt", completed.stdout)
            self.assertIn("AI Progress Monitor pet appearance: default", completed.stdout)
            self.assertNotIn("secret-token", completed.stdout)

    @unittest.skipUnless(os.name == "posix", "Shell helper execution is only available on POSIX systems")
    def test_macos_dev_acceptance_helper_reports_prd_manual_evidence(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)
            log_dir = home / "Library" / "Logs" / "AI Progress Monitor"
            log_dir.mkdir(parents=True)
            (log_dir / "native-monitor.log").write_text(
                "AI Progress Monitor running at http://127.0.0.1:8765/?token=secret-token\n"
                "AI Progress Monitor sessions: total=4 needs_action=0 running=1 idle=3 process_only=4 full=0\n"
                "Received host resize mode: bubbles\n"
                "Received host resize mode: compact\n"
                "Started window drag\n"
                "Moved window frame: (10, 10, 170, 150)\n"
                "Stopped window drag\n"
                "Hide monitor requested\n"
                "Show monitor requested from menu\n"
                "Restored pet web state\n"
                "AI Progress Monitor focus: ok=true\n",
                encoding="utf-8",
            )
            env = os.environ.copy()
            env["HOME"] = str(home)

            completed = subprocess.run(
                ["sh", str(ROOT / "scripts" / "check_macos_floating_dev.sh")],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                timeout=10,
            )

            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            self.assertIn("[OK] sessions visible", completed.stdout)
            self.assertIn("[OK] left-click open/close evidence", completed.stdout)
            self.assertIn("[OK] drag evidence", completed.stdout)
            self.assertIn("[OK] hide evidence", completed.stdout)
            self.assertIn("[OK] menu restore evidence", completed.stdout)
            self.assertIn("[OK] bubble focus evidence", completed.stdout)
            self.assertNotIn("secret-token", completed.stdout)

    @unittest.skipUnless(os.name == "posix", "Shell helper execution is only available on POSIX systems")
    def test_macos_dev_acceptance_helper_accepts_native_focus_evidence(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)
            log_dir = home / "Library" / "Logs" / "AI Progress Monitor"
            log_dir.mkdir(parents=True)
            (log_dir / "native-monitor.log").write_text(
                "AI Progress Monitor running at http://127.0.0.1:8765/?token=secret-token\n"
                "AI Progress Monitor sessions: total=4 needs_action=0 running=1 idle=3 process_only=4 full=0\n"
                "Native focus result: ok=true method=focused-project-window\n",
                encoding="utf-8",
            )
            env = os.environ.copy()
            env["HOME"] = str(home)

            completed = subprocess.run(
                ["sh", str(ROOT / "scripts" / "check_macos_floating_dev.sh")],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                timeout=10,
            )

            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            self.assertIn("[OK] bubble focus evidence", completed.stdout)
            self.assertIn("Native focus result: ok=true method=focused-project-window", completed.stdout)
            self.assertNotIn("secret-token", completed.stdout)

    @unittest.skipUnless(os.name == "posix", "Shell helper execution is only available on POSIX systems")
    def test_macos_dev_acceptance_helper_treats_recent_snapshots_as_running_evidence(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)
            log_dir = home / "Library" / "Logs" / "AI Progress Monitor"
            log_dir.mkdir(parents=True)
            (log_dir / "native-monitor.log").write_text(
                "AI Progress Monitor running at http://127.0.0.1:8765/?token=secret-token\n"
                "AI Progress Monitor sessions: total=3 needs_action=0 running=1 idle=2 process_only=3 full=0\n",
                encoding="utf-8",
            )
            env = os.environ.copy()
            env["HOME"] = str(home)

            completed = subprocess.run(
                ["sh", str(ROOT / "scripts" / "check_macos_floating_dev.sh")],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                timeout=10,
            )

            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            self.assertIn("service has recent session snapshots", completed.stdout)
            self.assertNotIn("process is not running", completed.stdout)
            self.assertNotIn("secret-token", completed.stdout)

    @unittest.skipUnless(os.name == "posix", "Shell helper execution is only available on POSIX systems")
    def test_macos_dev_acceptance_helper_rejects_failed_focus_as_manual_evidence(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)
            log_dir = home / "Library" / "Logs" / "AI Progress Monitor"
            log_dir.mkdir(parents=True)
            (log_dir / "native-monitor.log").write_text(
                "AI Progress Monitor running at http://127.0.0.1:8765/?token=secret-token\n"
                "AI Progress Monitor sessions: total=4 needs_action=0 running=1 idle=3 process_only=4 full=0\n"
                "Received host resize mode: bubbles\n"
                "Received host resize mode: compact\n"
                "Started window drag\n"
                "Moved window frame: (10, 10, 170, 150)\n"
                "Stopped window drag\n"
                "Hide monitor requested\n"
                "Show monitor requested from menu\n"
                "Restored pet web state\n"
                "AI Progress Monitor focus: ok=false\n",
                encoding="utf-8",
            )
            env = os.environ.copy()
            env["HOME"] = str(home)
            _add_fake_shirt_asset_curl(env, temp_dir)

            completed = subprocess.run(
                ["sh", str(ROOT / "scripts" / "check_macos_floating_dev.sh"), "--strict"],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                timeout=10,
            )

            self.assertEqual(completed.returncode, 1, completed.stdout + completed.stderr)
            self.assertIn("[TODO] bubble focus evidence", completed.stdout)
            self.assertIn("Manual acceptance incomplete", completed.stdout)
            self.assertNotIn("secret-token", completed.stdout)

    @unittest.skipUnless(os.name == "posix", "Shell helper execution is only available on POSIX systems")
    def test_macos_dev_acceptance_helper_strict_fails_until_all_manual_evidence_exists(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)
            log_dir = home / "Library" / "Logs" / "AI Progress Monitor"
            log_dir.mkdir(parents=True)
            (log_dir / "native-monitor.log").write_text(
                "AI Progress Monitor running at http://127.0.0.1:8765/?token=secret-token\n"
                "AI Progress Monitor sessions: total=4 needs_action=0 running=1 idle=3 process_only=4 full=0\n",
                encoding="utf-8",
            )
            env = os.environ.copy()
            env["HOME"] = str(home)
            _add_fake_shirt_asset_curl(env, temp_dir)

            completed = subprocess.run(
                ["sh", str(ROOT / "scripts" / "check_macos_floating_dev.sh"), "--strict"],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                timeout=10,
            )

            self.assertEqual(completed.returncode, 1, completed.stdout + completed.stderr)
            self.assertIn("Manual acceptance incomplete", completed.stdout)
            self.assertIn("[TODO] left-click open/close evidence", completed.stdout)
            self.assertNotIn("secret-token", completed.stdout)

    @unittest.skipUnless(os.name == "posix", "Shell helper execution is only available on POSIX systems")
    def test_macos_dev_acceptance_helper_strict_ignores_evidence_before_latest_launch(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)
            log_dir = home / "Library" / "Logs" / "AI Progress Monitor"
            log_dir.mkdir(parents=True)
            (log_dir / "native-monitor.log").write_text(
                "Starting native companion\n"
                "AI Progress Monitor sessions: total=4 needs_action=0 running=1 idle=3 process_only=4 full=0\n"
                "Received host resize mode: bubbles\n"
                "Received host resize mode: compact\n"
                "Started window drag\n"
                "Moved window frame: (10, 10, 170, 150)\n"
                "Stopped window drag\n"
                "Hide monitor requested\n"
                "Show monitor requested from menu\n"
                "Restored pet web state\n"
                "AI Progress Monitor focus: ok=true\n"
                "Starting native companion\n"
                "AI Progress Monitor running at http://127.0.0.1:8765/?token=secret-token\n"
                "AI Progress Monitor sessions: total=4 needs_action=0 running=1 idle=3 process_only=4 full=0\n",
                encoding="utf-8",
            )
            env = os.environ.copy()
            env["HOME"] = str(home)

            completed = subprocess.run(
                ["sh", str(ROOT / "scripts" / "check_macos_floating_dev.sh"), "--strict"],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                timeout=10,
            )

            self.assertEqual(completed.returncode, 1, completed.stdout + completed.stderr)
            self.assertIn("Manual acceptance incomplete", completed.stdout)
            self.assertIn("[OK] sessions visible", completed.stdout)
            self.assertIn("[TODO] left-click open/close evidence", completed.stdout)
            self.assertIn("[TODO] hide evidence", completed.stdout)
            self.assertNotIn("secret-token", completed.stdout)

    @unittest.skipUnless(os.name == "posix", "Shell helper execution is only available on POSIX systems")
    def test_macos_dev_acceptance_helper_strict_passes_when_all_manual_evidence_exists(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)
            log_dir = home / "Library" / "Logs" / "AI Progress Monitor"
            log_dir.mkdir(parents=True)
            (log_dir / "native-monitor.log").write_text(
                "AI Progress Monitor running at http://127.0.0.1:8765/?token=secret-token\n"
                "AI Progress Monitor sessions: total=4 needs_action=0 running=1 idle=3 process_only=4 full=0\n"
                "Received host resize mode: bubbles\n"
                "Received host resize mode: compact\n"
                "Started window drag\n"
                "Moved window frame: (10, 10, 170, 150)\n"
                "Stopped window drag\n"
                "Hide monitor requested\n"
                "Show monitor requested from menu\n"
                "Restored pet web state\n"
                "AI Progress Monitor focus: ok=true\n",
                encoding="utf-8",
            )
            env = os.environ.copy()
            env["HOME"] = str(home)
            _add_fake_shirt_asset_curl(env, temp_dir)

            completed = subprocess.run(
                ["sh", str(ROOT / "scripts" / "check_macos_floating_dev.sh"), "--strict"],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                timeout=10,
            )

            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            self.assertIn("Manual acceptance complete", completed.stdout)
            self.assertNotIn("[TODO]", completed.stdout)
            self.assertNotIn("secret-token", completed.stdout)

    def test_windows_start_script_writes_log_and_pauses_on_failure(self):
        script = (ROOT / "scripts" / "start_monitor.bat").read_text()

        self.assertIn("AI Progress Monitor", script)
        self.assertIn("monitor.log", script)
        self.assertIn("Monitor failed", script)
        self.assertIn("Monitor stopped", script)
        self.assertIn("pause", script.lower())
        self.assertIn("Python 3 was not found", script)
        self.assertIn("where python >nul", script)

    def test_windows_terminal_wrappers_fall_back_across_python_launchers(self):
        for relative in (
            "scripts/monitor_claude.bat",
            "scripts/monitor_codex.bat",
            "scripts/monitor_qoder.bat",
            "scripts/monitor_workbuddy.bat",
        ):
            script = (ROOT / relative).read_text()

            self.assertIn("set PYTHON_CMD=python", script)
            self.assertIn("where py", script)
            self.assertIn("set PYTHON_ARGS=-3", script)
            self.assertIn("where python3", script)
            self.assertIn("Python 3 was not found", script)
            self.assertIn("%PYTHON_CMD% %PYTHON_ARGS% scripts\\monitor_command.py", script)

    def test_shell_terminal_wrappers_keep_launch_directory_and_unique_default_sessions(self):
        expected_prefixes = {
            "scripts/monitor_claude.sh": "claude-code-",
            "scripts/monitor_codex.sh": "codex-",
            "scripts/monitor_qoder.sh": "qoder-",
            "scripts/monitor_workbuddy.sh": "workbuddy-",
        }
        for relative, prefix in expected_prefixes.items():
            script = (ROOT / relative).read_text()

            self.assertIn("LAUNCH_DIR=$(pwd)", script)
            self.assertIn("RUN_ID=\"$(date +%Y%m%d%H%M%S)-$$\"", script)
            self.assertIn(f"${{AI_MONITOR_SESSION_ID:-{prefix}", script)
            self.assertIn('cd "$LAUNCH_DIR"', script)
            self.assertIn('"$ROOT_DIR/scripts/monitor_command.py"', script)
            self.assertNotIn('cd "$(dirname "$0")/.."', script)
        self.assertIn("--tool-display-name Qoder", (ROOT / "scripts" / "monitor_qoder.sh").read_text())
        self.assertIn("--tool-display-name WorkBuddy", (ROOT / "scripts" / "monitor_workbuddy.sh").read_text())

    @unittest.skipUnless(os.name == "posix", "Shell wrapper execution is only available on POSIX systems")
    def test_shell_wrapper_runs_command_from_user_project_and_writes_unique_session(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = root / "checkout-flow"
            monitor_home = root / "monitor-home"
            project.mkdir()
            child_script = root / "write_cwd.py"
            child_script.write_text(
                "import pathlib, sys\n"
                "pathlib.Path(sys.argv[1]).write_text(str(pathlib.Path.cwd()), encoding='utf-8')\n"
                "print('child complete', flush=True)\n",
                encoding="utf-8",
            )
            env = os.environ.copy()
            env["AI_PROGRESS_MONITOR_HOME"] = str(monitor_home)
            env.pop("AI_MONITOR_SESSION_ID", None)
            env.pop("AI_MONITOR_TITLE", None)

            for index in range(2):
                cwd_file = root / f"cwd-{index}.txt"
                completed = subprocess.run(
                    ["sh", str(ROOT / "scripts" / "monitor_codex.sh"), sys.executable, str(child_script), str(cwd_file)],
                    cwd=project,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
                self.assertEqual(Path(cwd_file.read_text(encoding="utf-8")).resolve(), project.resolve())

            session_files = sorted((monitor_home / "sessions").glob("codex-checkout-flow-*.json"))
            self.assertEqual(len(session_files), 2)
            payloads = [json.loads(path.read_text(encoding="utf-8")) for path in session_files]
            session_ids = {payload["session_id"] for payload in payloads}
            self.assertEqual(len(session_ids), 2)
            for payload in payloads:
                self.assertTrue(payload["session_id"].startswith("codex-checkout-flow-"))
                self.assertTrue(payload["title"].startswith("Codex - checkout-flow #"))
                self.assertEqual(payload["tool"], "codex")

    @unittest.skipUnless(os.name == "posix", "Shell wrapper execution is only available on POSIX systems")
    def test_generic_shell_wrapper_writes_tool_display_name(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = root / "product-ops"
            monitor_home = root / "monitor-home"
            project.mkdir()
            env = os.environ.copy()
            env["AI_PROGRESS_MONITOR_HOME"] = str(monitor_home)
            env.pop("AI_MONITOR_SESSION_ID", None)
            env.pop("AI_MONITOR_TITLE", None)

            completed = subprocess.run(
                [
                    "sh",
                    str(ROOT / "scripts" / "monitor_workbuddy.sh"),
                    sys.executable,
                    "-u",
                    "-c",
                    "print('Do you want to continue? (yes/no)', flush=True)",
                ],
                cwd=project,
                env=env,
                capture_output=True,
                text=True,
                timeout=10,
            )

            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            session_files = sorted((monitor_home / "sessions").glob("workbuddy-product-ops-*.json"))
            self.assertEqual(len(session_files), 1)
            payload = json.loads(session_files[0].read_text(encoding="utf-8"))
            self.assertTrue(payload["title"].startswith("WorkBuddy - product-ops #"))
            self.assertEqual(payload["tool"], "unknown")
            self.assertEqual(payload["tool_display_name"], "WorkBuddy")


if __name__ == "__main__":
    unittest.main()
