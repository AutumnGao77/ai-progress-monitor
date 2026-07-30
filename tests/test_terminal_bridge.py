import json
import contextlib
import io
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import os
from pathlib import Path

from ai_progress_monitor.models import SessionStatus
from ai_progress_monitor.terminal_bridge import TerminalBridge, clean_terminal_text
from scripts.monitor_command import (
    default_response_dir,
    default_session_dir,
    detect_focus_app_from_process_rows,
    focus_app_name_from_args,
    runtime_import_path,
    run_monitored_command,
)


def write_response_when_prompt_seen(root: Path, session_id: str, response: str) -> None:
    session_path = root / "sessions" / f"{session_id}.json"
    response_dir = root / "responses"
    response_dir.mkdir(parents=True, exist_ok=True)
    deadline = time.time() + 5
    while time.time() < deadline:
        if session_path.exists():
            payload = json.loads(session_path.read_text())
            if payload.get("safe_action"):
                (response_dir / f"{session_id}.response").write_text(response)
                return
        time.sleep(0.05)


class TerminalBridgeTests(unittest.TestCase):
    def test_monitor_command_uses_sibling_pyz_without_source_tree(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            artifact = root / "ai-progress-monitor.pyz"
            artifact.touch()

            self.assertEqual(runtime_import_path(root), artifact)

    def test_monitor_command_defaults_follow_monitor_home(self):
        root = Path("/tmp/ai-monitor-test-home")

        self.assertEqual(default_session_dir(root), root / "sessions")
        self.assertEqual(default_response_dir(root), root / "responses")

    def test_writes_running_event_on_start(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            bridge = TerminalBridge(
                session_id="claude-1",
                title="Claude Code - demo",
                tool="claude_code",
                session_dir=Path(temp_dir) / "sessions",
                response_dir=Path(temp_dir) / "responses",
            )

            bridge.mark_running("Starting Claude Code")

            payload = json.loads((Path(temp_dir) / "sessions" / "claude-1.json").read_text())
            self.assertEqual(payload["status"], SessionStatus.RUNNING.value)
            self.assertEqual(payload["summary"], "Starting Claude Code")

    def test_detects_safe_yes_no_from_output(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            bridge = TerminalBridge(
                session_id="codex-1",
                title="Codex terminal",
                tool="codex",
                session_dir=Path(temp_dir) / "sessions",
                response_dir=Path(temp_dir) / "responses",
            )

            bridge.process_output("Do you want to continue? (yes/no)")

            payload = json.loads((Path(temp_dir) / "sessions" / "codex-1.json").read_text())
            self.assertEqual(payload["status"], SessionStatus.NEEDS_ACTION.value)
            self.assertEqual(payload["safe_action"]["kind"], "yes_no")
            self.assertEqual(payload["safe_action"]["options"], ["Yes", "No"])

    def test_detects_split_yes_no_prompt_from_recent_terminal_output(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            bridge = TerminalBridge(
                session_id="claude-split",
                title="Claude Code - split",
                tool="claude_code",
                session_dir=Path(temp_dir) / "sessions",
                response_dir=Path(temp_dir) / "responses",
            )

            bridge.process_output("Do you want to continue?\n")
            bridge.process_output("1. Yes\n")
            bridge.process_output("2. No\n")

            payload = json.loads((Path(temp_dir) / "sessions" / "claude-split.json").read_text())
            self.assertEqual(payload["status"], SessionStatus.NEEDS_ACTION.value)
            self.assertEqual(payload["safe_action"]["kind"], "yes_no")
            self.assertEqual(payload["safe_action"]["options"], ["Yes", "No"])
            self.assertIn("Do you want to continue?", payload["summary"])

    def test_strips_ansi_control_sequences_from_output_summary(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            bridge = TerminalBridge(
                session_id="claude-ansi",
                title="Claude Code - ansi",
                tool="claude_code",
                session_dir=Path(temp_dir) / "sessions",
                response_dir=Path(temp_dir) / "responses",
            )

            bridge.process_output("\x1b[39m\x1b[38;2;153;153;153m20260703AIcoding | MiniMax-M3\x1b[m | ctx:6% \x1b[39m\x1b[K")

            payload = json.loads((Path(temp_dir) / "sessions" / "claude-ansi.json").read_text())
            self.assertNotIn("\x1b", payload["summary"])
            self.assertNotIn("[K", payload["summary"])
            self.assertEqual(payload["summary"], "20260703AIcoding | MiniMax-M3 | ctx:6%")

    def test_strips_visible_replacement_ansi_fragments_from_output_summary(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            bridge = TerminalBridge(
                session_id="claude-visible-ansi",
                title="Claude Code - visible ansi",
                tool="claude_code",
                session_dir=Path(temp_dir) / "sessions",
                response_dir=Path(temp_dir) / "responses",
            )

            bridge.process_output("�[1B�[39m �[38;2;153;153;153m20260703AIcoding | MiniMax-M3�[m | ctx:6%�[39m �[K")

            payload = json.loads((Path(temp_dir) / "sessions" / "claude-visible-ansi.json").read_text())
            self.assertNotIn("�[", payload["summary"])
            self.assertNotIn("[39m", payload["summary"])
            self.assertNotIn("[K", payload["summary"])
            self.assertEqual(payload["summary"], "20260703AIcoding | MiniMax-M3 | ctx:6%")

    def test_strips_stale_ansi_fragments_after_replacement_characters_are_removed(self):
        cleaned = clean_terminal_text("�[1B�[39m title [38;2;153;153;153mctx:6% [K")

        self.assertEqual(cleaned, "title ctx:6%")

    def test_keeps_normal_bracketed_text_when_cleaning_terminal_output(self):
        cleaned = clean_terminal_text("[OK] compile passed; see docs/[notes].md")

        self.assertEqual(cleaned, "[OK] compile passed; see docs/[notes].md")

    def test_keeps_question_marks_when_cleaning_terminal_output(self):
        cleaned = clean_terminal_text("Do you want to continue?")

        self.assertEqual(cleaned, "Do you want to continue?")

    def test_consumes_response_once(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            response_dir = Path(temp_dir) / "responses"
            response_dir.mkdir()
            (response_dir / "codex-1.response").write_text("Yes")
            bridge = TerminalBridge(
                session_id="codex-1",
                title="Codex terminal",
                tool="codex",
                session_dir=Path(temp_dir) / "sessions",
                response_dir=response_dir,
            )

            self.assertEqual(bridge.consume_response(), "Yes")
            self.assertIsNone(bridge.consume_response())

    def test_marks_idle_on_exit_code_zero(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            bridge = TerminalBridge(
                session_id="codex-1",
                title="Codex terminal",
                tool="codex",
                session_dir=Path(temp_dir) / "sessions",
                response_dir=Path(temp_dir) / "responses",
            )

            bridge.mark_finished(0)

            payload = json.loads((Path(temp_dir) / "sessions" / "codex-1.json").read_text())
            self.assertEqual(payload["status"], SessionStatus.IDLE.value)
            self.assertEqual(payload["summary"], "Process exited with code 0")

    def test_marks_stuck_on_nonzero_exit(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            bridge = TerminalBridge(
                session_id="codex-1",
                title="Codex terminal",
                tool="codex",
                session_dir=Path(temp_dir) / "sessions",
                response_dir=Path(temp_dir) / "responses",
            )

            bridge.mark_finished(2)

            payload = json.loads((Path(temp_dir) / "sessions" / "codex-1.json").read_text())
            self.assertEqual(payload["status"], SessionStatus.STUCK.value)
            self.assertEqual(payload["summary"], "Process exited with code 2")

    def test_monitored_command_receives_pet_response(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            reply_path = root / "reply.txt"
            bridge = TerminalBridge(
                session_id="codex-1",
                title="Codex terminal",
                tool="codex",
                session_dir=root / "sessions",
                response_dir=root / "responses",
            )
            writer = threading.Thread(target=write_response_when_prompt_seen, args=(root, "codex-1", "Yes"), daemon=True)
            writer.start()

            with contextlib.redirect_stdout(io.StringIO()):
                exit_code = run_monitored_command(
                    [
                        sys.executable,
                        "-u",
                        "-c",
                        "import pathlib, sys; print('Do you want to continue? (yes/no)', flush=True); reply=input(); pathlib.Path(sys.argv[1]).write_text(reply)",
                        str(reply_path),
                    ],
                    bridge,
                )

            writer.join(timeout=2)
            self.assertEqual(exit_code, 0)
            self.assertEqual(reply_path.read_text(), "Yes")

    def test_monitored_command_records_child_process_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bridge = TerminalBridge(
                session_id="codex-process",
                title="Codex terminal",
                tool="codex",
                session_dir=root / "sessions",
                response_dir=root / "responses",
            )

            with contextlib.redirect_stdout(io.StringIO()):
                exit_code = run_monitored_command(
                    [sys.executable, "-u", "-c", "print('running', flush=True)"],
                    bridge,
                    use_pty=False,
                )

            payload = json.loads((root / "sessions" / "codex-process.json").read_text())
            self.assertEqual(exit_code, 0)
            self.assertIsInstance(payload["process_id"], int)
            self.assertEqual(payload["process_name"], Path(sys.executable).name)

    def test_terminal_bridge_writes_focus_metadata_when_available(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bridge = TerminalBridge(
                session_id="claude-focus",
                title="Claude Code - focus",
                tool="claude_code",
                session_dir=root / "sessions",
                response_dir=root / "responses",
            )
            bridge.set_process_metadata(27876, "claude", focus_process_id=75407, focus_app_name="Zed")

            bridge.mark_running("Starting command")

            payload = json.loads((root / "sessions" / "claude-focus.json").read_text())
            self.assertEqual(payload["process_id"], 27876)
            self.assertEqual(payload["process_name"], "claude")
            self.assertEqual(payload["focus_process_id"], 75407)
            self.assertEqual(payload["focus_app_name"], "Zed")

    def test_terminal_bridge_writes_generic_tool_display_name_for_full_monitoring(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bridge = TerminalBridge(
                session_id="workbuddy-full",
                title="WorkBuddy - product-ops",
                tool="unknown",
                tool_display_name="WorkBuddy",
                session_dir=root / "sessions",
                response_dir=root / "responses",
            )
            bridge.set_process_metadata(51001, "workbuddy", focus_process_id=51003, focus_app_name="WorkBuddy")

            bridge.process_output("Do you want to continue? (yes/no)")

            payload = json.loads((root / "sessions" / "workbuddy-full.json").read_text())
            self.assertEqual(payload["tool"], "unknown")
            self.assertEqual(payload["tool_display_name"], "WorkBuddy")
            self.assertEqual(payload["status"], SessionStatus.NEEDS_ACTION.value)
            self.assertTrue(payload["view_ack_required"])
            self.assertEqual(payload["focus_process_id"], 51003)
            self.assertEqual(payload["focus_app_name"], "WorkBuddy")

    def test_emit_event_default_session_dir_follows_monitor_home_and_writes_atomically(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            monitor_home = Path(temp_dir) / "monitor-home"
            env = os.environ.copy()
            env["AI_PROGRESS_MONITOR_HOME"] = str(monitor_home)

            completed = subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).resolve().parents[1] / "scripts" / "emit_event.py"),
                    "--session-id",
                    "workbuddy-home",
                    "--title",
                    "WorkBuddy - product-ops",
                    "--tool",
                    "unknown",
                    "--tool-display-name",
                    "WorkBuddy",
                    "--surface",
                    "desktop",
                    "--status",
                    "running",
                ],
                check=False,
                capture_output=True,
                text=True,
                env=env,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
            self.assertTrue((monitor_home / "sessions" / "workbuddy-home.json").exists())
            self.assertFalse((monitor_home / "sessions" / "workbuddy-home.json.tmp").exists())

    def test_emit_event_can_publish_generic_ai_tool_full_session(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            session_dir = Path(temp_dir) / "sessions"

            completed = subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).resolve().parents[1] / "scripts" / "emit_event.py"),
                    "--session-id",
                    "workbuddy-json",
                    "--title",
                    "WorkBuddy - product-ops",
                    "--tool",
                    "unknown",
                    "--tool-display-name",
                    "WorkBuddy",
                    "--surface",
                    "desktop",
                    "--status",
                    "needs_action",
                    "--summary",
                    "Needs user attention",
                    "--view-ack-required",
                    "--focus-app-name",
                    "WorkBuddy",
                    "--cwd",
                    "/Users/Gao/Documents/product-ops",
                    "--session-dir",
                    str(session_dir),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
            payload = json.loads((session_dir / "workbuddy-json.json").read_text())
            self.assertEqual(payload["tool"], "unknown")
            self.assertEqual(payload["tool_display_name"], "WorkBuddy")
            self.assertEqual(payload["status"], SessionStatus.NEEDS_ACTION.value)
            self.assertTrue(payload["view_ack_required"])
            self.assertEqual(payload["focus_app_name"], "WorkBuddy")
            self.assertEqual(payload["cwd"], "/Users/Gao/Documents/product-ops")

    def test_detects_focus_app_from_terminal_process_ancestry(self):
        rows = [
            "27876 27748 claude",
            "27748 27744 -zsh",
            "27744 75407 /usr/bin/login -qflp Gao /bin/zsh -fc exec -a -zsh /bin/zsh",
            "75407 1 /Applications/Zed.app/Contents/MacOS/zed",
        ]

        focus_pid, app_name = detect_focus_app_from_process_rows(27876, rows)

        self.assertEqual(focus_pid, 75407)
        self.assertEqual(app_name, "Zed")

    def test_focus_detection_climbs_past_electron_helper_to_main_ide(self):
        rows = [
            "100 200 /tmp/codex 300",
            "200 300 /bin/zsh -il",
            "300 400 /Applications/Visual Studio Code.app/Contents/Frameworks/Code Helper.app/Contents/MacOS/Code Helper --type=utility",
            "400 1 /Applications/Visual Studio Code.app/Contents/MacOS/Code",
        ]

        focus_pid, app_name = detect_focus_app_from_process_rows(100, rows)

        self.assertEqual(focus_pid, 400)
        self.assertEqual(app_name, "Visual Studio Code")

    def test_wrapper_focus_registry_covers_supported_ide_and_terminal_hosts(self):
        cases = [
            ("/Applications/Terminal.app/Contents/MacOS/Terminal", "Terminal"),
            ("/Applications/iTerm.app/Contents/MacOS/iTerm2", "iTerm"),
            ("/Applications/Warp.app/Contents/MacOS/stable", "Warp"),
            ("/Applications/WezTerm.app/Contents/MacOS/wezterm-gui", "WezTerm"),
            ("/Applications/kitty.app/Contents/MacOS/kitty", "kitty"),
            ("/Applications/Alacritty.app/Contents/MacOS/alacritty", "Alacritty"),
            ("/Applications/Ghostty.app/Contents/MacOS/ghostty", "Ghostty"),
            ("/Applications/Hyper.app/Contents/MacOS/Hyper", "Hyper"),
            ("/Applications/Tabby.app/Contents/MacOS/Tabby", "Tabby"),
            ("/Applications/Rio.app/Contents/MacOS/rio", "Rio"),
            ("/Applications/Zed.app/Contents/MacOS/zed", "Zed"),
            ("/Applications/Cursor.app/Contents/MacOS/Cursor", "Cursor"),
            ("/Applications/Visual Studio Code - Insiders.app/Contents/MacOS/Electron", "Visual Studio Code"),
            ("/Applications/VSCodium.app/Contents/MacOS/Electron", "VSCodium"),
            ("/Applications/Windsurf.app/Contents/MacOS/Electron", "Windsurf"),
            ("/Applications/Sublime Text.app/Contents/MacOS/sublime_text", "Sublime Text"),
            ("/Applications/Nova.app/Contents/MacOS/Nova", "Nova"),
            ("/Applications/Xcode.app/Contents/MacOS/Xcode", "Xcode"),
            ("/Applications/Kiro.app/Contents/MacOS/Kiro", "Kiro"),
            ("/Applications/Trae CN.app/Contents/MacOS/Trae CN", "Trae"),
            ("/Applications/Eclipse.app/Contents/MacOS/eclipse", "Eclipse"),
            ("/Applications/Fleet.app/Contents/MacOS/Fleet", "Fleet"),
            ("/Applications/Android Studio.app/Contents/MacOS/studio", "Android Studio"),
            ("/Applications/CLion.app/Contents/MacOS/clion", "CLion"),
            ("/Applications/GoLand.app/Contents/MacOS/goland", "GoLand"),
            ("/Applications/IntelliJ IDEA CE.app/Contents/MacOS/idea", "IntelliJ IDEA"),
            ("/Applications/PhpStorm.app/Contents/MacOS/phpstorm", "PhpStorm"),
            ("/Applications/PyCharm CE.app/Contents/MacOS/pycharm", "PyCharm"),
            ("/Applications/Rider.app/Contents/MacOS/rider", "Rider"),
            ("/Applications/RubyMine.app/Contents/MacOS/rubymine", "RubyMine"),
            ("/Applications/WebStorm.app/Contents/MacOS/webstorm", "WebStorm"),
        ]

        for command, expected in cases:
            with self.subTest(command=command):
                self.assertEqual(focus_app_name_from_args(command), expected)

    def test_focus_app_detection_does_not_treat_project_path_as_trae(self):
        command = "/usr/bin/python3 /Users/Gao/Documents/TraeProject/scripts/worker.py"

        self.assertIsNone(focus_app_name_from_args(command))

    @unittest.skipUnless(os.name == "posix", "PTY behavior is only available on POSIX systems")
    def test_monitored_command_runs_child_in_terminal_on_posix(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            tty_path = root / "isatty.txt"
            bridge = TerminalBridge(
                session_id="claude-tty",
                title="Claude Code - tty",
                tool="claude_code",
                session_dir=root / "sessions",
                response_dir=root / "responses",
            )

            with contextlib.redirect_stdout(io.StringIO()):
                exit_code = run_monitored_command(
                    [
                        sys.executable,
                        "-u",
                        "-c",
                        "import pathlib, sys; pathlib.Path(sys.argv[1]).write_text(str(sys.stdin.isatty()))",
                        str(tty_path),
                    ],
                    bridge,
                )

            self.assertEqual(exit_code, 0)
            self.assertEqual(tty_path.read_text(), "True")

    @unittest.skipUnless(os.name == "posix", "PTY behavior is only available on POSIX systems")
    def test_monitored_command_gives_child_a_controlling_terminal_on_posix(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            tty_path = root / "controlling-tty.txt"
            bridge = TerminalBridge(
                session_id="claude-controlling-tty",
                title="Claude Code - controlling tty",
                tool="claude_code",
                session_dir=root / "sessions",
                response_dir=root / "responses",
            )

            with contextlib.redirect_stdout(io.StringIO()):
                exit_code = run_monitored_command(
                    [
                        sys.executable,
                        "-u",
                        "-c",
                        (
                            "import os, pathlib, sys\n"
                            "try:\n"
                            "    value = f'{os.isatty(0)}:{os.tcgetpgrp(0) > 0}'\n"
                            "except OSError as exc:\n"
                            "    value = f'{os.isatty(0)}:error:{exc.errno}'\n"
                            "pathlib.Path(sys.argv[1]).write_text(value)\n"
                        ),
                        str(tty_path),
                    ],
                    bridge,
                )

            self.assertEqual(exit_code, 0)
            self.assertEqual(tty_path.read_text(), "True:True")

    @unittest.skipUnless(os.name == "posix", "PTY behavior is only available on POSIX systems")
    def test_monitored_command_forwards_terminal_keypresses_on_posix(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            keys_path = root / "keys.bin"
            read_fd, write_fd = os.pipe()
            bridge = TerminalBridge(
                session_id="claude-keys",
                title="Claude Code - keys",
                tool="claude_code",
                session_dir=root / "sessions",
                response_dir=root / "responses",
            )

            def write_keys() -> None:
                time.sleep(0.1)
                os.write(write_fd, b"\x1b[B\n")
                os.close(write_fd)

            writer = threading.Thread(target=write_keys, daemon=True)
            writer.start()

            with contextlib.redirect_stdout(io.StringIO()):
                exit_code = run_monitored_command(
                    [
                        sys.executable,
                        "-u",
                        "-c",
                        "import pathlib, sys; data=sys.stdin.buffer.readline(); pathlib.Path(sys.argv[1]).write_bytes(data)",
                        str(keys_path),
                    ],
                    bridge,
                    terminal_input_fd=read_fd,
                )

            os.close(read_fd)
            writer.join(timeout=2)
            self.assertEqual(exit_code, 0)
            self.assertEqual(keys_path.read_bytes(), b"\x1b[B\n")


if __name__ == "__main__":
    unittest.main()
