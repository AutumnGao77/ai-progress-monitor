import tempfile
import unittest
from pathlib import Path

from ai_progress_monitor.doctor import CheckStatus, run_diagnostics


class DoctorTests(unittest.TestCase):
    def test_run_diagnostics_reports_core_checks(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            result = run_diagnostics(session_dir=Path(temp_dir) / "sessions", response_dir=Path(temp_dir) / "responses")

        names = [check.name for check in result.checks]
        self.assertIn("python_version", names)
        self.assertIn("platform", names)
        self.assertIn("session_dir_writable", names)
        self.assertIn("response_dir_writable", names)
        self.assertIn("notification_adapter", names)
        self.assertIn("window_focus_adapter", names)

    def test_directory_checks_are_ok_for_writable_temp_paths(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            result = run_diagnostics(session_dir=Path(temp_dir) / "sessions", response_dir=Path(temp_dir) / "responses")

        status_by_name = {check.name: check.status for check in result.checks}
        self.assertEqual(status_by_name["session_dir_writable"], CheckStatus.OK)
        self.assertEqual(status_by_name["response_dir_writable"], CheckStatus.OK)

    def test_result_exit_code_is_zero_when_no_errors(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            result = run_diagnostics(session_dir=Path(temp_dir) / "sessions", response_dir=Path(temp_dir) / "responses")

        self.assertEqual(result.exit_code(), 0)

    def test_result_serializes_to_json_ready_dict(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            result = run_diagnostics(session_dir=Path(temp_dir) / "sessions", response_dir=Path(temp_dir) / "responses")

        payload = result.to_dict()

        self.assertIn("checks", payload)
        self.assertIn("ok", payload)
        self.assertIsInstance(payload["checks"][0]["name"], str)


if __name__ == "__main__":
    unittest.main()
