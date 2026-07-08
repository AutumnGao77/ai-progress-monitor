import tempfile
import unittest
from pathlib import Path

from ai_progress_monitor.actions import ActionExecutor, is_low_risk_action
from ai_progress_monitor.models import ActionKind, SafeAction


class ActionTests(unittest.TestCase):
    def test_allows_known_button_actions(self):
        self.assertTrue(is_low_risk_action(SafeAction(ActionKind.YES_NO, ("Yes", "No"), "Continue?")))
        self.assertTrue(is_low_risk_action(SafeAction(ActionKind.ALLOW_DENY, ("Allow", "Deny"), "Allow?")))
        self.assertTrue(is_low_risk_action(SafeAction(ActionKind.CONTINUE_STOP, ("Continue", "Stop"), "Continue?")))

    def test_blocks_free_text_or_many_options(self):
        self.assertFalse(is_low_risk_action(SafeAction(ActionKind.FREE_TEXT, ("Send",), "Write a reply")))
        self.assertFalse(is_low_risk_action(ActionKind.YES_NO if False else SafeAction(ActionKind.UNKNOWN, ("A", "B", "C"), "Choose")))

    def test_response_file_executor_writes_action(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            executor = ActionExecutor(response_dir=Path(temp_dir), direct_os_actions=False)
            result = executor.execute_response_file("session-1", "Yes")

            self.assertTrue(result.ok)
            self.assertEqual(Path(result.detail).read_text().strip(), "Yes")


if __name__ == "__main__":
    unittest.main()
