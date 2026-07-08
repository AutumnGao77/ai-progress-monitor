import unittest
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class WindowsNativeCompanionTests(unittest.TestCase):
    def test_windows_companion_is_topmost_and_tray_restorable(self):
        source = (ROOT / "native" / "windows" / "FloatingMonitor.ps1").read_text()

        self.assertIn("$form.TopMost = $true", source)
        self.assertIn("$form.Width = 260", source)
        self.assertIn("$form.Height = 110", source)
        self.assertIn("WorkingArea.Right - $form.Width - 24", source)
        self.assertIn("WorkingArea.Bottom - $form.Height - 24", source)
        self.assertIn("New-Object System.Windows.Forms.NotifyIcon", source)
        self.assertIn("add_FormClosing", source)
        self.assertIn("$_.Cancel = $true", source)
        self.assertIn("$form.Hide()", source)
        self.assertIn("$form.Show()", source)

    def test_windows_companion_collapses_and_expands_without_staying_large(self):
        source = (ROOT / "native" / "windows" / "FloatingMonitor.ps1").read_text()

        self.assertIn("$isExpanded = $false", source)
        self.assertIn("$list.Visible = $false", source)
        self.assertIn("function Set-CompanionMode", source)
        self.assertIn("$form.Width = 340", source)
        self.assertIn("$form.Height = 240", source)
        self.assertIn("Toggle-CompanionMode", source)

    def test_windows_companion_poll_interval_supports_five_second_visibility(self):
        source = (ROOT / "native" / "windows" / "FloatingMonitor.ps1").read_text()
        match = re.search(r"\$PollIntervalMilliseconds = (\d+)", source)

        self.assertIsNotNone(match)
        self.assertLessEqual(int(match.group(1)), 5000)
        self.assertIn("$timer.Interval = $PollIntervalMilliseconds", source)

    def test_windows_companion_can_poll_focus_and_send_safe_actions(self):
        source = (ROOT / "native" / "windows" / "FloatingMonitor.ps1").read_text()

        self.assertIn("/api/sessions", source)
        self.assertIn("/api/action", source)
        self.assertIn("/api/focus", source)
        self.assertIn("?token={2}", source)
        self.assertIn("safe_action", source)

    def test_windows_companion_labels_process_only_detection_as_basic(self):
        source = (ROOT / "native" / "windows" / "FloatingMonitor.ps1").read_text()

        self.assertIn('$isProcessOnly = $session.monitoring_level -eq "process_only"', source)
        self.assertIn("process only", source)
        self.assertIn("Basic detection only. Use wrapper for content.", source)
        self.assertIn("process-only detections", source)
        self.assertIn("$fullSessions", source)

    def test_windows_companion_falls_back_across_python_launchers(self):
        source = (ROOT / "native" / "windows" / "FloatingMonitor.ps1").read_text()
        start_script = (ROOT / "scripts" / "start_monitor.bat").read_text()

        self.assertIn("Resolve-PythonCommand", source)
        self.assertIn('@("py", "-3")', source)
        self.assertIn('@("python3")', source)
        self.assertIn('@("python")', source)
        self.assertIn("set PYTHON_CMD=python", start_script)
        self.assertIn("where py", start_script)


if __name__ == "__main__":
    unittest.main()
