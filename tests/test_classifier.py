import unittest

from ai_progress_monitor.classifier import classify_session_text
from ai_progress_monitor.models import ActionKind, SessionStatus, ToolKind


class ClassifierTests(unittest.TestCase):
    def test_detects_low_risk_yes_no_prompt(self):
        result = classify_session_text(
            title="Claude Code - pricing-page",
            text="Do you want to continue? (yes/no)",
            source_id="terminal-1",
        )

        self.assertEqual(result.tool, ToolKind.CLAUDE_CODE)
        self.assertEqual(result.status, SessionStatus.NEEDS_ACTION)
        self.assertIsNotNone(result.safe_action)
        self.assertEqual(result.safe_action.kind, ActionKind.YES_NO)
        self.assertEqual(result.safe_action.options, ("Yes", "No"))

    def test_detects_numbered_yes_no_prompt_split_across_lines(self):
        result = classify_session_text(
            title="Claude Code - pricing-page",
            text="Do you want to continue?\n1. Yes\n2. No",
            source_id="terminal-1",
        )

        self.assertEqual(result.status, SessionStatus.NEEDS_ACTION)
        self.assertIsNotNone(result.safe_action)
        self.assertEqual(result.safe_action.kind, ActionKind.YES_NO)
        self.assertEqual(result.safe_action.options, ("Yes", "No"))

    def test_detects_codex_running_from_title(self):
        result = classify_session_text(
            title="Codex - running command",
            text="Executing tests...",
            source_id="codex-1",
        )

        self.assertEqual(result.tool, ToolKind.CODEX)
        self.assertEqual(result.status, SessionStatus.RUNNING)
        self.assertIsNone(result.safe_action)

    def test_detects_chatgpt_desktop_running_from_title(self):
        result = classify_session_text(
            title="ChatGPT Desktop - running command",
            text="Executing tests...",
            source_id="chatgpt-1",
        )

        self.assertEqual(result.tool, ToolKind.CHATGPT)
        self.assertEqual(result.status, SessionStatus.RUNNING)
        self.assertIsNone(result.safe_action)

    def test_detects_completed_state(self):
        result = classify_session_text(
            title="Claude Code",
            text="Done. All tests passed.",
            source_id="terminal-2",
        )

        self.assertEqual(result.status, SessionStatus.IDLE)

    def test_detects_chinese_claude_idle_response(self):
        result = classify_session_text(
            title="Claude Code",
            text="你好 Gao，有什么可以帮你的吗？\n* Crunched for 10s",
            source_id="terminal-cn",
        )

        self.assertEqual(result.status, SessionStatus.IDLE)

    def test_blocks_high_risk_prompt_from_pet_actions(self):
        result = classify_session_text(
            title="Claude Code",
            text="Run rm -rf ./build? (yes/no)",
            source_id="terminal-3",
        )

        self.assertEqual(result.status, SessionStatus.NEEDS_ACTION)
        self.assertIsNone(result.safe_action)

    def test_unknown_when_no_signal(self):
        result = classify_session_text(
            title="Terminal",
            text="",
            source_id="terminal-4",
        )

        self.assertEqual(result.status, SessionStatus.UNKNOWN)
        self.assertEqual(result.tool, ToolKind.UNKNOWN)


if __name__ == "__main__":
    unittest.main()
