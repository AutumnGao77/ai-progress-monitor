import unittest
import inspect

from ai_progress_monitor.web import HTML, MonitorRequestHandler, doctor_payload, is_authorized


class WebDoctorApiTests(unittest.TestCase):
    def test_doctor_api_requires_token(self):
        self.assertFalse(is_authorized("secret", {}, ""))

    def test_doctor_api_returns_checks_with_token(self):
        payload = doctor_payload()

        self.assertIn("checks", payload)
        self.assertIn("ok", payload)

    def test_rename_endpoints_remain_server_side_only(self):
        post_source = inspect.getsource(MonitorRequestHandler.do_POST)

        self.assertIn("/api/rename-session", post_source)
        self.assertIn("/api/reset-session-title", post_source)
        self.assertNotIn("/api/rename-session", HTML)
        self.assertNotIn("/api/reset-session-title", HTML)


if __name__ == "__main__":
    unittest.main()
