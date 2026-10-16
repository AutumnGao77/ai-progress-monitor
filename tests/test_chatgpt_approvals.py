import tempfile
import unittest
from unittest.mock import patch
from datetime import datetime, timezone
from pathlib import Path

from ai_progress_monitor.chatgpt_approvals import DesktopApprovalLog
from ai_progress_monitor.models import SessionStatus
from ai_progress_monitor.sources import ChatGPTSessionSource


class DesktopApprovalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / 'codex-desktop-00000000-0000-0000-0000-000000000001-123-t0-i1-000000-0.log'
        self.alive = True
        self.reader = DesktopApprovalLog(self.root, process_alive=lambda pid: self.alive)

    def append(self, text, timestamp='2026-10-13T07:20:02.066Z'):
        with self.path.open('a') as handle:
            handle.write(timestamp + ' info [electron-message-handler] ' + text + '\n')

    def request(self, request='135', thread='sample'):
        self.append('[desktop-notifications] received approval conversationId=' + thread + ' kind=commandExecution requestId=' + request)

    def respond(self, request='135', decision='accept'):
        self.append('Sending server response id=' + request + ' method=item/commandExecution/requestApproval response={"decision":"' + decision + '"}')

    def test_pending_survives_polling_and_unrelated_response(self):
        self.request()
        self.respond('136')
        self.assertIn('sample', self.reader.poll())
        self.assertIn('sample', self.reader.poll())
        self.respond()
        self.assertEqual(self.reader.poll(), {})

    def test_denial_and_multiple_pending_requests(self):
        self.request()
        self.request('136')
        self.respond(decision='decline')
        self.assertIn('sample', self.reader.poll())
        self.respond('136')
        self.assertEqual(self.reader.poll(), {})

    def test_response_in_rotated_log_clears_request(self):
        self.request()
        self.reader.poll()
        self.path = self.path.with_name(self.path.name.replace('-0.log', '-1.log'))
        self.respond()
        self.assertEqual(self.reader.poll(), {})

    def test_exited_app_clears_pending(self):
        self.request()
        self.assertIn('sample', self.reader.poll())
        self.alive = False
        self.assertEqual(self.reader.poll(), {})

    def test_restart_reads_already_answered_request_as_resolved(self):
        self.request()
        self.respond()
        self.assertEqual(self.reader.poll(), {})

    def test_unrelated_text_does_not_create_approval(self):
        self.append('command="require_escalated"')
        self.assertEqual(self.reader.poll(), {})

    def test_pending_is_visible_without_fresh_rollout_and_not_view_acknowledgeable(self):
        self.request()
        sessions = self.root / 'sessions'
        sessions.mkdir()
        source = ChatGPTSessionSource(sessions, approval_log=self.reader,
            now=lambda: datetime(2026, 10, 13, 8, tzinfo=timezone.utc))
        updates = source.poll()
        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0].status, SessionStatus.NEEDS_ACTION)
        self.assertFalse(updates[0].view_ack_required)
        self.respond()
        self.assertEqual(source.poll(), [])

    def test_matching_session_keeps_context_and_resumes_after_response(self):
        import json
        from datetime import timedelta
        sessions = self.root / 'sessions'
        sessions.mkdir()
        records = [
            {'timestamp': '2026-10-13T07:19:00Z', 'type': 'session_meta',
             'payload': {'id': 'sample', 'originator': 'Codex Desktop', 'cwd': '/projects/example'}},
            {'timestamp': '2026-10-13T07:20:00Z', 'type': 'event_msg', 'payload': {'type': 'task_started'}},
        ]
        path = sessions / 'sample.jsonl'
        path.write_text('\n'.join(json.dumps(record) for record in records))
        current = datetime(2026, 10, 13, 7, 21, tzinfo=timezone.utc)
        source = ChatGPTSessionSource(sessions, approval_log=self.reader, now=lambda: current)
        self.request()
        update = source.poll()[0]
        self.assertEqual(update.status, SessionStatus.NEEDS_ACTION)
        self.assertEqual(update.cwd, '/projects/example')
        self.assertFalse(update.view_ack_required)
        self.respond()
        self.assertEqual(source.poll()[0].status, SessionStatus.RUNNING)
        self.request('136')
        self.assertEqual(source.poll()[0].status, SessionStatus.NEEDS_ACTION)
        with path.open('a') as handle:
            handle.write('\n' + json.dumps({'timestamp': current.isoformat(), 'type': 'event_msg',
                                          'payload': {'type': 'turn_aborted'}}))
        self.assertEqual(source.poll()[0].status, SessionStatus.IDLE)
        current += timedelta(hours=1)
        self.assertEqual(source.poll(), [])

    def test_partial_line_is_read_only_when_complete(self):
        line = ('2026-10-13T07:20:02.066Z info [electron-message-handler] '
                '[desktop-notifications] received approval conversationId=sample '
                'kind=commandExecution requestId=135\n')
        self.path.write_text(line[:-8])
        self.assertIsNone(self.reader.poll())
        with self.path.open('a') as handle:
            handle.write(line[-8:])
        self.assertIn('sample', self.reader.poll())

    def test_request_ids_are_scoped_to_app_process(self):
        self.request()
        self.path = self.path.with_name(self.path.name.replace('000000000001', '000000000002').replace('-123-', '-124-'))
        self.respond()
        self.assertIn('sample', self.reader.poll())

    def test_log_burst_does_not_skip_response(self):
        self.request()
        self.reader.poll()
        self.respond()
        with self.path.open('a') as handle:
            handle.write('unrelated log line\n' * 120000)
        self.assertNotIn('sample', self.reader.poll())

    def test_restart_recovers_approval_before_old_tail_boundary(self):
        self.request()
        with self.path.open('a') as handle:
            handle.write('unrelated log line\n' * 120000)
        self.assertIn('sample', self.reader.poll())

    def test_approved_conversation_without_rollout_runs_until_completion(self):
        self.request()
        source = ChatGPTSessionSource(self.root / 'sessions', approval_log=self.reader,
            now=lambda: datetime(2026, 10, 13, 7, 21, tzinfo=timezone.utc))
        self.assertEqual(source.poll()[0].status, SessionStatus.NEEDS_ACTION)
        self.respond()
        updates = source.poll()
        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0].status, SessionStatus.RUNNING)
        self.assertFalse(updates[0].view_ack_required)
        self.append('[desktop-notifications] received turn-complete conversationId=sample turnId=turn-1')
        updates = source.poll()
        self.assertEqual(updates[0].status, SessionStatus.NEEDS_ACTION)
        self.assertTrue(updates[0].view_ack_required)

    def test_backlog_is_bounded_and_never_publishes_partial_replay(self):
        self.request()
        with self.path.open('a') as handle:
            handle.write('irrelevant\n' * 10000)
        self.respond()
        with patch('ai_progress_monitor.chatgpt_approvals._POLL_BYTE_BUDGET', 32000):
            result = self.reader.poll()
            self.assertIsNone(result)
            self.assertEqual(self.reader.session_signals, {})
            for _ in range(10):
                result = self.reader.poll()
                if result is not None:
                    break
        self.assertEqual(result, {})
        self.assertEqual(self.reader.session_signals['sample'].status, SessionStatus.RUNNING)

    def test_source_preserves_existing_snapshot_while_replaying(self):
        self.request()
        source = ChatGPTSessionSource(self.root / 'sessions', approval_log=self.reader)
        with patch('ai_progress_monitor.chatgpt_approvals._POLL_BYTE_BUDGET', 20):
            self.assertIsNone(source.poll())
        self.assertEqual(source.poll()[0].status, SessionStatus.NEEDS_ACTION)

    def test_pending_survives_restart_with_many_rotated_files_and_startup_filter(self):
        self.request()
        original = self.path
        for index in range(1, 12):
            self.path = original.with_name(original.name.replace('-0.log', '-' + str(index) + '.log'))
            self.append('irrelevant')
        source = ChatGPTSessionSource(self.root / 'sessions', approval_log=self.reader,
            source_started_at=datetime(2026, 10, 14, tzinfo=timezone.utc),
            now=lambda: datetime(2026, 10, 14, tzinfo=timezone.utc))
        update = source.poll()[0]
        self.assertEqual(update.status, SessionStatus.NEEDS_ACTION)
        self.assertFalse(update.view_ack_required)
        self.respond()
        self.assertEqual(self.reader.poll(), {})

    def test_unknown_response_does_not_create_running_conversation(self):
        self.respond()
        self.reader.poll()
        self.assertEqual(self.reader.session_signals, {})

    def test_aborted_approval_becomes_idle_and_app_exit_removes_it(self):
        self.request()
        self.respond(decision='abort')
        self.reader.poll()
        self.assertEqual(self.reader.session_signals['sample'].status, SessionStatus.IDLE)
        self.alive = False
        self.reader.poll()
        self.assertEqual(self.reader.session_signals, {})

    def test_completed_conversation_can_request_approval_again(self):
        self.request()
        self.respond()
        self.append('[desktop-notifications] received turn-complete conversationId=sample turnId=turn-1')
        self.reader.poll()
        self.assertTrue(self.reader.session_signals['sample'].view_ack_required)
        self.request('136')
        self.reader.poll()
        self.assertFalse(self.reader.session_signals['sample'].view_ack_required)
        self.assertEqual(self.reader.session_signals['sample'].status, SessionStatus.NEEDS_ACTION)

    def test_truncated_log_clears_stale_pending(self):
        self.request()
        self.reader.poll()
        self.path.write_text('rotated\n')
        self.assertEqual(self.reader.poll(), {})
        self.assertEqual(self.reader.session_signals, {})

    def test_incomplete_rotated_line_does_not_block_new_file(self):
        self.request()
        self.reader.poll()
        with self.path.open('a') as handle:
            handle.write('partial log')
        self.path = self.path.with_name(self.path.name.replace('-0.log', '-1.log'))
        self.respond()
        self.assertEqual(self.reader.poll(), {})

    def test_long_unrelated_line_is_bounded_and_does_not_hide_response(self):
        self.request()
        self.reader.poll()
        with self.path.open('a') as handle:
            handle.write('x' * (2 * 1024 * 1024) + '\n')
        self.respond()
        self.assertEqual(self.reader.poll(), {})

    def test_unavailable_process_probe_preserves_state(self):
        self.request()
        self.reader.poll()
        self.reader.process_alive = lambda pid: None
        self.assertIsNone(self.reader.poll())
        self.assertEqual(self.reader.session_signals['sample'].status, SessionStatus.NEEDS_ACTION)

    def test_latest_app_identity_wins_when_pid_is_reused(self):
        import os
        self.request()
        self.reader.poll()
        old = self.path
        old_time = old.stat().st_mtime
        self.path = old.with_name(old.name.replace('000000000001', '000000000002'))
        self.append('irrelevant')
        os.utime(old, (old_time - 10, old_time - 10))
        self.assertEqual(self.reader.poll(), {})
        self.assertEqual(self.reader.session_signals, {})

    def test_completion_survives_newer_rollout_activity_taking_priority(self):
        self.request()
        self.respond()
        self.reader.poll()
        when = datetime(2026, 10, 13, 7, 20, 3, tzinfo=timezone.utc)
        self.reader.dismiss_through('sample', when)
        self.append('[desktop-notifications] received turn-complete conversationId=sample turnId=turn-1',
                    timestamp='2026-10-13T07:20:04Z')
        self.reader.poll()
        self.assertTrue(self.reader.session_signals['sample'].view_ack_required)

    def test_older_pending_does_not_hide_new_rollout_turn(self):
        import json
        sessions = self.root / 'sessions'
        sessions.mkdir()
        path = sessions / 'sample.jsonl'
        records = [
            {'timestamp': '2026-10-13T07:19:00Z', 'type': 'session_meta',
             'payload': {'id': 'sample', 'originator': 'ChatGPT Desktop', 'cwd': '/projects/example'}},
            {'timestamp': '2026-10-13T07:21:00Z', 'type': 'event_msg', 'payload': {'type': 'task_started'}},
        ]
        path.write_text('\n'.join(json.dumps(record) for record in records))
        self.request()
        source = ChatGPTSessionSource(sessions, approval_log=self.reader,
            now=lambda: datetime(2026, 10, 13, 7, 22, tzinfo=timezone.utc))
        self.assertEqual(source.poll()[0].status, SessionStatus.RUNNING)
        self.assertEqual(self.reader.poll(), {})

    def test_old_rollout_completion_and_new_token_record_do_not_clear_approval(self):
        import json
        sessions = self.root / 'sessions'
        sessions.mkdir()
        records = [
            {'timestamp': '2026-10-13T07:19:00Z', 'type': 'session_meta',
             'payload': {'id': 'sample', 'originator': 'ChatGPT Desktop', 'cwd': '/projects/example'}},
            {'timestamp': '2026-10-13T07:19:01Z', 'type': 'event_msg', 'payload': {'type': 'task_complete'}},
            {'timestamp': '2026-10-13T07:21:00Z', 'type': 'event_msg', 'payload': {'type': 'token_count'}},
        ]
        (sessions / 'sample.jsonl').write_text('\n'.join(json.dumps(record) for record in records))
        self.request()
        source = ChatGPTSessionSource(sessions, approval_log=self.reader,
            now=lambda: datetime(2026, 10, 13, 7, 22, tzinfo=timezone.utc))
        update = source.poll()[0]
        self.assertEqual(update.status, SessionStatus.NEEDS_ACTION)
        self.assertFalse(update.view_ack_required)
        self.assertEqual(update.cwd, '/projects/example')

    def test_resumed_fallback_expires_without_further_activity(self):
        self.request()
        self.respond()
        self.reader.poll()
        source = ChatGPTSessionSource(self.root / 'sessions', approval_log=self.reader,
            now=lambda: datetime(2026, 10, 13, 8, tzinfo=timezone.utc))
        self.assertEqual(source.poll(), [])

    def test_non_macos_probe_does_not_signal_processes(self):
        from ai_progress_monitor.chatgpt_approvals import _process_alive
        with patch('ai_progress_monitor.chatgpt_approvals.platform.system', return_value='Windows'), \
                patch('ai_progress_monitor.chatgpt_approvals.subprocess.run') as run:
            self.assertFalse(_process_alive(123))
        run.assert_not_called()

    def test_clock_rollback_does_not_reorder_response_before_request(self):
        self.append('[desktop-notifications] received approval conversationId=sample kind=commandExecution requestId=135',
                    timestamp='2026-10-13T07:20:02Z')
        self.append('Sending server response id=135 method=item/commandExecution/requestApproval response={"decision":"accept"}',
                    timestamp='2026-10-13T07:20:01Z')
        self.assertEqual(self.reader.poll(), {})
        self.assertEqual(self.reader.session_signals['sample'].status, SessionStatus.RUNNING)
        self.assertGreaterEqual(self.reader.session_signals['sample'].updated_at,
                                datetime(2026, 10, 13, 7, 20, 2, tzinfo=timezone.utc))

    def test_clock_rollback_completion_clears_outstanding_request(self):
        self.append('[desktop-notifications] received approval conversationId=sample kind=commandExecution requestId=135',
                    timestamp='2026-10-13T07:20:02Z')
        self.reader.poll()
        self.append('[desktop-notifications] received turn-complete conversationId=sample turnId=turn-1',
                    timestamp='2026-10-13T07:20:01Z')
        self.assertEqual(self.reader.poll(), {})
        self.assertTrue(self.reader.session_signals['sample'].view_ack_required)
