import unittest

from ai_progress_monitor.web import generate_token, is_authorized


class WebSecurityTests(unittest.TestCase):
    def test_generated_token_is_not_empty(self):
        token = generate_token()

        self.assertGreaterEqual(len(token), 32)

    def test_allows_matching_header_token(self):
        self.assertTrue(is_authorized("secret", {"x-monitor-token": "secret"}, ""))

    def test_allows_matching_query_token(self):
        self.assertTrue(is_authorized("secret", {}, "token=secret"))

    def test_blocks_missing_token(self):
        self.assertFalse(is_authorized("secret", {}, ""))

    def test_blocks_wrong_token(self):
        self.assertFalse(is_authorized("secret", {"x-monitor-token": "wrong"}, "token=wrong"))


if __name__ == "__main__":
    unittest.main()
