import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from ai_progress_monitor.models import SessionStatus, SessionUpdate, SurfaceKind, ToolKind
from ai_progress_monitor.state_trace import SessionStateTrace


class SessionStateTraceTests(unittest.TestCase):
    def setUp(self):
        self.trace = SessionStateTrace()
        self.session = SessionUpdate(session_id='private-session-identifier', title='Private title',
            tool=ToolKind.CHATGPT, surface=SurfaceKind.DESKTOP, status=SessionStatus.RUNNING,
            summary='Private content', updated_at=datetime(2026, 10, 19, tzinfo=timezone.utc),
            source='chatgpt-session', cwd='/projects/private-folder')

    def test_status_changes_are_logged_without_content_and_unchanged_polls_are_silent(self):
        with self.assertLogs('ai_progress_monitor.state', level='INFO') as captured:
            self.trace.observe([self.session])
            self.trace.observe([replace(self.session, updated_at=self.session.updated_at + timedelta(seconds=2))])
            self.trace.observe([replace(self.session, status=SessionStatus.NEEDS_ACTION, view_ack_required=True)])
            self.trace.observe([replace(self.session, status=SessionStatus.IDLE, view_ack_required=True)])
        self.assertEqual(len(captured.output), 3)
        text = '\n'.join(captured.output)
        for private in ('private-session-identifier', 'Private title', 'Private content', 'private-folder'):
            self.assertNotIn(private, text)
        self.assertIn('needs_action', text)
        self.assertIn('idle', text)

    def test_removal_is_logged_once_and_old_entries_are_not_retained(self):
        with self.assertLogs('ai_progress_monitor.state', level='INFO') as captured:
            self.trace.observe([self.session])
            self.trace.observe([])
            self.trace.observe([])
        self.assertEqual(len(captured.output), 2)
        self.assertIn('not_visible', captured.output[-1])
        self.assertEqual(self.trace.states, {})

    def test_new_result_is_distinguished_from_previous_pending_result(self):
        result = replace(self.session, status=SessionStatus.NEEDS_ACTION, view_ack_required=True)
        with self.assertLogs('ai_progress_monitor.state', level='INFO') as captured:
            self.trace.observe([result])
            self.trace.observe([result])
            self.trace.observe([replace(result, updated_at=result.updated_at + timedelta(minutes=3))])
        self.assertEqual(len(captured.output), 2)
        self.assertIn('result_at', captured.output[-1])
