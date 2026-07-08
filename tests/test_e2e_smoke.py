import unittest
from io import StringIO

from scripts.e2e_smoke import API_TIMEOUT_SECONDS, start_output_drain, wrapper_command


class E2ESmokeTests(unittest.TestCase):
    def test_uses_shell_wrapper_on_posix(self):
        command = wrapper_command("claude_code", ["python3", "child.py"], os_name="posix")

        self.assertEqual(command, ["sh", "scripts/monitor_claude.sh", "python3", "child.py"])

    def test_uses_batch_wrapper_on_windows(self):
        command = wrapper_command("claude_code", ["python", "child.py"], os_name="nt")

        self.assertEqual(command, ["cmd", "/c", "scripts\\monitor_claude.bat", "python", "child.py"])

    def test_uses_codex_wrappers(self):
        self.assertEqual(
            wrapper_command("codex", ["codex"], os_name="posix"),
            ["sh", "scripts/monitor_codex.sh", "codex"],
        )
        self.assertEqual(
            wrapper_command("codex", ["codex"], os_name="nt"),
            ["cmd", "/c", "scripts\\monitor_codex.bat", "codex"],
        )

    def test_api_timeout_allows_slow_release_poll(self):
        self.assertGreaterEqual(API_TIMEOUT_SECONDS, 6)

    def test_drains_service_output_after_startup_token(self):
        class FakeProcess:
            stdout = StringIO("line one\nline two\n")

        drained = []
        thread = start_output_drain(FakeProcess(), sink=drained.append)
        thread.join(timeout=1)

        self.assertEqual(drained, ["line one\n", "line two\n"])


if __name__ == "__main__":
    unittest.main()
