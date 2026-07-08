import subprocess
import unittest
from unittest.mock import patch

from ai_progress_monitor.window_focus import (
    FOCUS_FALLBACK_TIMEOUT_SECONDS,
    FocusTarget,
    FocusResult,
    WindowFocusManager,
    build_macos_focus_command,
    focus_fallback_command,
    focus_native_window,
    build_windows_focus_command,
)


class WindowFocusTests(unittest.TestCase):
    def test_builds_macos_focus_command(self):
        command = build_macos_focus_command("Claude Code - task")

        self.assertEqual(command[0], "osascript")
        self.assertIn("Claude Code - task", command[-1])
        self.assertIn('perform action "AXRaise" of win', command[-1])

    def test_builds_windows_focus_command(self):
        command = build_windows_focus_command("Codex - task")

        self.assertEqual(command[0], "powershell")
        self.assertIn("Codex - task", command[-1])
        self.assertIn("SetForegroundWindow", command[-1])

    def test_focus_manager_uses_custom_sender(self):
        calls = []
        manager = WindowFocusManager(sender=lambda target: calls.append(target) or FocusResult(True, "focused"))

        result = manager.focus("Claude Code - task")

        self.assertTrue(result.ok)
        self.assertEqual(result.detail, "focused")
        self.assertEqual(calls, [FocusTarget(title="Claude Code - task")])

    def test_focus_manager_blocks_empty_title(self):
        manager = WindowFocusManager(sender=lambda target: FocusResult(True, "focused"))

        result = manager.focus("")

        self.assertFalse(result.ok)

    def test_focus_manager_passes_window_id_when_available(self):
        calls = []
        manager = WindowFocusManager(sender=lambda target: calls.append(target) or FocusResult(True, "focused"))

        result = manager.focus("Codex Desktop - PRD", window_id="42", process_id=1234, app_name="Codex")

        self.assertTrue(result.ok)
        self.assertEqual(calls, [FocusTarget(title="Codex Desktop - PRD", window_id="42", process_id=1234, app_name="Codex")])

    def test_macos_focus_command_can_target_window_id(self):
        command = build_macos_focus_command(FocusTarget(title="Codex Desktop", window_id="42"))

        self.assertIn("id of win as string is \"42\"", command[-1])
        self.assertIn('perform action "AXRaise" of win', command[-1])
        self.assertNotIn('if id of win as string is "42" then\nset frontmost of proc to true', command[-1])

    def test_macos_focus_command_can_target_gui_process_id(self):
        command = build_macos_focus_command(FocusTarget(title="Claude Code CLI - checkout", process_id=75407))

        self.assertIn("unix id of proc as string is \"75407\"", command[-1])
        self.assertIn("AXRaise", command[-1])

    def test_macos_focus_command_directly_targets_known_app_instead_of_scanning_all_processes(self):
        command = build_macos_focus_command(
            FocusTarget(
                title="Claude Code CLI - 6SAI",
                process_id=75407,
                app_name="Zed",
                cwd="/Users/Gao/Documents/projects/6SAI",
            )
        )

        self.assertIn('tell application process "Zed"', command[-1])
        self.assertNotIn("repeat with proc in application processes", command[-1])

    def test_macos_process_only_terminal_fallback_does_not_activate_project_editor_group(self):
        command = focus_fallback_command(
            FocusTarget(
                title="Claude Code CLI - 网点抛扔",
                process_id=75407,
                app_name="Zed",
                cwd="/Users/Gao/Documents/projects/网点抛扔",
            )
        )

        self.assertIsNone(command)

    def test_macos_project_editor_fallback_does_not_activate_all_windows_when_cwd_is_available(self):
        for app_name in ["Zed", "Cursor", "Visual Studio Code", "IntelliJ IDEA Ultimate", "PyCharm CE"]:
            with self.subTest(app_name=app_name):
                command = focus_fallback_command(
                    FocusTarget(
                        title=f"Claude Code CLI - 6SAI",
                        process_id=75407,
                        app_name=app_name,
                        cwd="/Users/Gao/Documents/projects/6SAI",
                    )
                )

                self.assertIsNone(command)

    def test_macos_project_editor_focus_failure_does_not_run_open_fallback(self):
        calls = []

        def fake_run(command, **_kwargs):
            calls.append(command)
            return subprocess.CompletedProcess(command, 1, stdout="", stderr="not found")

        with patch("ai_progress_monitor.window_focus.platform.system", return_value="Darwin"):
            with patch("ai_progress_monitor.window_focus.subprocess.run", side_effect=fake_run):
                result = focus_native_window(
                    FocusTarget(
                        title="Claude Code CLI - 6SAI",
                        process_id=75407,
                        app_name="Zed",
                        cwd="/Users/Gao/Documents/projects/6SAI",
                    )
                )

        self.assertFalse(result.ok)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], "osascript")

    def test_focus_fallback_timeout_allows_slow_project_activation(self):
        self.assertGreaterEqual(FOCUS_FALLBACK_TIMEOUT_SECONDS, 12)

    def test_macos_focus_command_does_not_raise_parent_app_first_when_cwd_is_available(self):
        command = build_macos_focus_command(
            FocusTarget(
                title="Claude Code CLI - 网点抛扔",
                process_id=75407,
                app_name="Zed",
                cwd="/Users/Gao/Documents/projects/网点抛扔",
            )
        )

        self.assertNotIn('unix id of proc as string is "75407"', command[-1])
        self.assertIn('if name of win contains "Claude Code CLI - 网点抛扔"', command[-1])

    def test_macos_focus_command_matches_project_folder_window_when_cwd_is_available(self):
        command = build_macos_focus_command(
            FocusTarget(
                title="Claude Code CLI - 网点清场",
                process_id=75407,
                app_name="Zed",
                cwd="/Users/Gao/Documents/projects/网点清场",
            )
        )

        self.assertIn('tell application process "Zed"', command[-1])
        self.assertIn('if name of win is "网点清场" or name of win contains "网点清场" then', command[-1])
        self.assertIn('perform action "AXRaise" of win', command[-1])
        self.assertNotIn('if name of win is "网点清场" then\nset frontmost of proc to true', command[-1])

    def test_macos_focus_command_matches_real_editor_title_containing_project_folder(self):
        command = build_macos_focus_command(
            FocusTarget(
                title="Claude Code CLI - 6SAI",
                process_id=75407,
                app_name="Zed",
                cwd="/Users/Gao/Documents/projects/6SAI",
            )
        )

        self.assertIn('if name of win is "6SAI" or name of win contains "6SAI" then', command[-1])
        self.assertIn('return "focused-project-window"', command[-1])

    def test_macos_focus_success_reports_safe_method(self):
        def fake_run(command, **_kwargs):
            return subprocess.CompletedProcess(command, 0, stdout="focused-project-window\n", stderr="")

        with patch("ai_progress_monitor.window_focus.platform.system", return_value="Darwin"):
            with patch("ai_progress_monitor.window_focus.subprocess.run", side_effect=fake_run):
                result = focus_native_window(
                    FocusTarget(
                        title="Claude Code CLI - 6SAI",
                        process_id=75407,
                        app_name="Zed",
                        cwd="/Users/Gao/Documents/projects/6SAI",
                    )
                )

        self.assertTrue(result.ok)
        self.assertEqual(result.detail, "focused-project-window")

    def test_macos_focus_command_reports_not_found_as_failure(self):
        command = build_macos_focus_command(FocusTarget(title="Claude Code CLI - missing"))

        self.assertIn('error "not found" number 1', command[-1])

    def test_windows_focus_command_can_target_process_id(self):
        command = build_windows_focus_command(FocusTarget(title="Codex Desktop", process_id=1234))

        self.assertIn("$p = Get-Process -Id 1234", command[-1])


if __name__ == "__main__":
    unittest.main()
