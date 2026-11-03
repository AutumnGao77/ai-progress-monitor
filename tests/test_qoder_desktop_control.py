import unittest
from ai_progress_monitor.qoder_desktop import _apply_control


class DesktopControlTests(unittest.TestCase):
    def test_ignores_mentions_of_control_event_inside_message_preview(self):
        controls = {}
        _apply_control(controls, '[2026-11-02T06:39:00Z] [INFO] [main] [ChatSession] message preview: '
                       'Main ChatSession control state committed {"sessionId":"sample","activeTurnState":"running"}')
        self.assertFalse(controls)
