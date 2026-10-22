import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from dataclasses import replace

from ai_progress_monitor.actions import ActionExecutor
from ai_progress_monitor.chatgpt_approvals import DesktopApprovalLog
from ai_progress_monitor.models import SessionStatus, SessionUpdate, SurfaceKind, ToolKind
from ai_progress_monitor.service import MonitorService
from ai_progress_monitor.sources import ChatGPTSessionSource, OsWindowSource
from ai_progress_monitor.chatgpt_history import LifecycleHistory
from ai_progress_monitor.store import SessionStore


class ChatGPTLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / 'rollout-sample.jsonl'
        self.time = datetime(2026, 10, 19, 10, tzinfo=timezone.utc)
        self.append('session_meta', {'id': 'sample', 'originator': 'ChatGPT Desktop', 'cwd': '/projects/sample'})
        self.source = ChatGPTSessionSource(self.root, now=lambda: self.time)
        self.store = SessionStore()

    def append(self, kind, payload):
        self.time += timedelta(seconds=1)
        with self.path.open('a') as handle:
            handle.write(json.dumps({'timestamp': self.time.isoformat(), 'type': kind, 'payload': payload}) + '\n')

    def event(self, kind):
        self.append('event_msg', {'type': kind})

    def padding(self, size):
        self.append('response_item', {'type': 'function_call_output', 'call_id': 'work', 'output': 'x' * size})

    def complete(self):
        self.append('response_item', {'type': 'message', 'role': 'assistant', 'phase': 'final_answer', 'content': [{'type': 'output_text', 'text': 'Finished'}]})
        self.event('task_complete')

    def status(self):
        updates = self.source.poll()
        self.assertIsNotNone(updates)
        self.assertEqual(len(updates), 1)
        return updates[0]


    def reply(self, representation, text):
        if representation == 'legacy':
            self.append('event_msg', {'type': 'agent_message', 'message': text})
        elif representation == 'item':
            self.append('event_msg', {'type': 'item_completed', 'item': {
                'type': 'AgentMessage', 'phase': 'final_answer',
                'content': [{'type': 'Text', 'text': text}]}})
        else:
            self.append('response_item', {'type': 'message', 'role': 'assistant',
                'phase': 'final_answer', 'content': [{'type': 'output_text', 'text': text}]})

    def test_empty_and_whitespace_replies_complete_idle_in_all_formats(self):
        for representation in ('legacy', 'item', 'response'):
            for text in ('', ' \n\t'):
                with self.subTest(representation=representation, text=text):
                    self.event('task_started')
                    self.reply(representation, text)
                    self.event('task_complete')
                    result = self.status()
                    self.assertEqual(result.status, SessionStatus.IDLE)
                    self.assertFalse(result.view_ack_required)

    def test_nonempty_replies_still_require_review_in_all_formats(self):
        for representation in ('legacy', 'item', 'response'):
            with self.subTest(representation=representation):
                self.event('task_started')
                self.reply(representation, 'A result to review')
                self.event('task_complete')
                self.assertEqual(self.status().status, SessionStatus.NEEDS_ACTION)
                self.assertTrue(self.status().view_ack_required)

    def test_missing_or_empty_content_is_not_a_visible_reply(self):
        for content in (None, [], [{'type': 'output_text', 'text': ''}]):
            with self.subTest(content=content):
                self.event('task_started')
                self.append('response_item', {'type': 'message', 'role': 'assistant', 'content': content})
                self.event('task_complete')
                self.assertEqual(self.status().status, SessionStatus.IDLE)

    def test_middle_replay_and_restart_preserve_empty_reply_semantics(self):
        self.event('task_started')
        self.padding(70000)
        for representation in ('legacy', 'item', 'response'):
            self.event('task_started')
            self.reply(representation, ' \n')
            self.event('task_complete')
        self.padding(300000)
        for _ in range(2):
            self.source = ChatGPTSessionSource(self.root, now=lambda: self.time)
            self.assertEqual(self.status().status, SessionStatus.IDLE)

    def test_middle_replay_empty_final_does_not_erase_visible_content(self):
        self.event('task_started')
        self.padding(70000)
        self.event('task_started')
        self.reply('item', 'Actual visible content')
        self.reply('response', '')
        self.event('task_complete')
        self.padding(300000)
        self.assertEqual(self.status().status, SessionStatus.NEEDS_ACTION)
        self.assertNotIn('Actual visible content', json.dumps(self.source._session_histories[self.path].records))

    def test_empty_message_does_not_clear_real_approval(self):
        self.event('task_started')
        self.event('exec_approval_requested')
        self.reply('response', '')
        self.assertEqual(self.status().status, SessionStatus.NEEDS_ACTION)
        self.assertFalse(self.status().view_ack_required)

    def test_visible_media_without_text_still_requires_review(self):
        self.event('task_started')
        self.append('response_item', {'type': 'message', 'role': 'assistant',
            'content': [{'type': 'image_url', 'image_url': {'url': 'https://example.com/result.png'}}]})
        self.event('task_complete')
        self.assertEqual(self.status().status, SessionStatus.NEEDS_ACTION)

    def test_late_log_completion_cannot_reopen_same_empty_turn(self):
        self.event('task_started')
        self.padding(70000)
        self.append('event_msg', {'type': 'task_started', 'turn_id': 'empty-turn'})
        self.reply('response', '')
        self.append('event_msg', {'type': 'task_complete', 'turn_id': 'empty-turn'})
        self.padding(300000)
        log_path = self.root / 'codex-desktop-00000000-0000-0000-0000-000000000001-123-t0-i1-000000-0.log'
        messages = [
            '[desktop-notifications] received approval conversationId=sample kind=commandExecution requestId=12',
            'Sending server response id=12 method=item/commandExecution/requestApproval response={"decision":"accept"}',
            '[desktop-notifications] received turn-complete conversationId=sample turnId=empty-turn',
        ]
        for message in messages:
            self.time += timedelta(seconds=1)
            with log_path.open('a') as handle:
                handle.write(self.time.isoformat() + ' info [electron-message-handler] ' + message + '\n')
        self.source.approval_log = DesktopApprovalLog(self.root, process_alive=lambda pid: True)
        self.assertEqual(self.status().status, SessionStatus.IDLE)
        # A different, newer completion must not be discarded using an older turn.
        self.time += timedelta(seconds=1)
        with log_path.open('a') as handle:
            handle.write(self.time.isoformat() + ' info [electron-message-handler] '
                '[desktop-notifications] received turn-complete conversationId=sample turnId=new-turn\n')
        self.assertEqual(self.status().status, SessionStatus.NEEDS_ACTION)

    def test_settings_change_does_not_reopen_viewed_completion(self):
        self.event('task_started')
        self.complete()
        complete = self.status()
        self.store.apply_updates([complete])
        self.store.mark_session_viewed(complete.session_id, self.time)
        self.time += timedelta(hours=1)
        self.event('thread_settings_applied')
        update = self.status()
        self.store.apply_updates([update])
        self.assertEqual(update.updated_at, complete.updated_at)
        self.assertEqual(self.store.sessions(now=self.time)[0].status, SessionStatus.IDLE)

    def test_token_usage_after_completion_does_not_create_a_new_review(self):
        self.event('task_started')
        self.complete()
        complete = self.status()
        self.event('token_count')
        self.assertEqual(self.status().updated_at, complete.updated_at)

    def test_settings_change_does_not_revive_stale_running_session(self):
        self.event('task_started')
        self.time += timedelta(minutes=11)
        self.event('thread_settings_applied')
        self.assertEqual(self.source.poll(), [])

    def test_current_turn_in_middle_supersedes_old_approval(self):
        self.event('task_started')
        log_path = self.root / 'codex-desktop-00000000-0000-0000-0000-000000000001-123-t0-i1-000000-0.log'
        self.time += timedelta(seconds=1)
        log_path.write_text(self.time.isoformat() + ' info [electron-message-handler] [desktop-notifications] received approval conversationId=sample kind=commandExecution requestId=12\n')
        self.source.approval_log = DesktopApprovalLog(self.root, process_alive=lambda pid: True)
        self.padding(70000)
        self.event('task_started')
        self.padding(300000)
        self.assertEqual(self.status().status, SessionStatus.RUNNING)

    def test_visible_result_in_middle_still_requires_review(self):
        self.event('task_started')
        self.padding(70000)
        self.append('response_item', {'type': 'message', 'role': 'assistant', 'phase': 'final_answer', 'content': [{'type': 'output_text', 'text': 'Finished'}]})
        self.padding(300000)
        self.event('task_complete')
        result = self.status()
        self.assertEqual(result.status, SessionStatus.NEEDS_ACTION)
        self.assertTrue(result.view_ack_required)

    def test_completed_empty_turn_does_not_inherit_an_older_reply(self):
        self.event('task_started')
        self.complete()
        self.padding(70000)
        self.event('task_started')
        self.padding(300000)
        self.event('task_complete')
        self.assertEqual(self.status().status, SessionStatus.IDLE)

    def test_sync_input_in_middle_survives_unrelated_activity(self):
        self.event('task_started')
        self.padding(70000)
        self.append('response_item', {'type': 'function_call', 'name': 'request_user_input', 'call_id': 'input'})
        self.padding(300000)
        self.assertEqual(self.status().status, SessionStatus.NEEDS_ACTION)
        self.append('response_item', {'type': 'function_call_output', 'call_id': 'input', 'output': '{}'})
        self.assertEqual(self.status().status, SessionStatus.RUNNING)

    def test_duplicate_rollouts_emit_one_current_session(self):
        self.event('task_started')
        old = self.root / 'older-sample.jsonl'
        old.write_bytes(self.path.read_bytes())
        self.complete()
        os.utime(old, None)
        result = self.source.poll()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].status, SessionStatus.NEEDS_ACTION)

    def test_new_turn_and_result_are_not_acknowledged_by_old_click(self):
        self.event('task_started')
        self.complete()
        old = self.status()
        self.store.apply_updates([old])
        self.store.mark_session_viewed(old.session_id, self.time)
        self.event('task_started')
        self.store.apply_updates([self.status()])
        self.complete()
        self.store.apply_updates([self.status()])
        self.assertEqual(self.store.sessions(now=self.time)[0].status, SessionStatus.NEEDS_ACTION)

    def test_middle_cache_discards_finished_turns_and_conversation_content(self):
        self.event('task_started')
        self.padding(70000)
        for _ in range(40):
            self.event('task_started')
            self.append('response_item', {'type': 'message', 'role': 'assistant',
                'content': [{'type': 'output_text', 'text': 'private answer text'}]})
            self.event('task_complete')
        self.padding(300000)
        self.assertEqual(self.status().status, SessionStatus.NEEDS_ACTION)
        records = self.source._session_histories[self.path].records
        self.assertLessEqual(len(records), 4)
        self.assertNotIn('private answer text', json.dumps(records))

    def test_log_completion_timestamp_is_stable_across_late_usage_reports(self):
        self.event('task_started')
        log_path = self.root / 'codex-desktop-00000000-0000-0000-0000-000000000001-123-t0-i1-000000-0.log'
        messages = [
            '[desktop-notifications] received approval conversationId=sample kind=commandExecution requestId=12',
            'Sending server response id=12 method=item/commandExecution/requestApproval response={"decision":"accept"}',
            '[desktop-notifications] received turn-complete conversationId=sample turnId=turn',
        ]
        for message in messages:
            self.time += timedelta(seconds=1)
            with log_path.open('a') as handle:
                handle.write(self.time.isoformat() + ' info [electron-message-handler] ' + message + '\n')
        self.source.approval_log = DesktopApprovalLog(self.root, process_alive=lambda pid: True)
        result = self.status()
        self.assertTrue(result.view_ack_required)
        self.event('token_count')
        self.assertEqual(self.status().updated_at, result.updated_at)

    def test_append_during_replay_preserves_prior_snapshot_until_next_poll(self):
        self.event('task_started')
        self.complete()
        original = LifecycleHistory.read_middle
        appended = []
        def append_after_read(history, path, *args):
            result = original(history, path, *args)
            if not appended:
                appended.append(True)
                self.event('task_started')
            return result
        with patch.object(LifecycleHistory, 'read_middle', append_after_read):
            self.assertIsNone(self.source.poll())
        self.assertEqual(self.status().status, SessionStatus.RUNNING)

    def test_expired_replay_time_budget_does_not_publish_incomplete_state(self):
        self.event('task_started')
        self.padding(70000)
        self.complete()
        self.padding(300000)
        with patch('ai_progress_monitor.sources.CHATGPT_HISTORY_POLL_TIME_BUDGET', 0):
            self.assertIsNone(self.source.poll())
        self.assertEqual(self.status().status, SessionStatus.NEEDS_ACTION)

    def quiet_service(self):
        app = SessionUpdate('app', 'ChatGPT', ToolKind.CHATGPT, SurfaceKind.DESKTOP,
                            SessionStatus.IDLE, '', self.time, source='process', process_id=123)
        class Processes:
            volatile_source = 'process'
            updates = [app]
            def poll(self):
                return self.updates
        processes = Processes()
        service = MonitorService([self.source, processes], self.store, ActionExecutor(),
                                 now=lambda: self.time, process_empty_grace_seconds=0)
        self.event('task_started')
        service.refresh()
        return service, processes

    def test_observed_turn_stays_running_through_hours_without_logs(self):
        service, _ = self.quiet_service()
        for _ in range(120):
            self.time += timedelta(minutes=1)
            visible = service.refresh()
            self.assertEqual([item.session_id for item in visible], ['chatgpt-session-sample'])
            self.assertIn(visible[0].status, {SessionStatus.RUNNING, SessionStatus.STUCK})
        self.complete()
        self.assertEqual(service.refresh()[0].status, SessionStatus.NEEDS_ACTION)

    def test_quiet_turn_explicit_abort_is_not_retained_as_running(self):
        service, _ = self.quiet_service()
        self.time += timedelta(hours=2)
        service.refresh()
        self.event('turn_aborted')
        self.assertEqual(service.refresh()[0].status, SessionStatus.IDLE)

    def test_quiet_turn_retention_ends_after_confirmed_app_exit(self):
        service, processes = self.quiet_service()
        self.time += timedelta(hours=2)
        service.refresh()
        processes.updates = []
        service.refresh()
        self.assertEqual(service.refresh(), [])

    def test_quiet_turn_does_not_transfer_to_replacement_app_process(self):
        service, processes = self.quiet_service()
        self.time += timedelta(hours=2)
        processes.updates = [replace(processes.updates[0], process_id=456)]
        self.assertEqual([item.session_id for item in service.refresh()], ['app'])

    def test_quiet_turn_survives_uncertain_process_scan(self):
        service, processes = self.quiet_service()
        self.time += timedelta(hours=2)
        processes.updates = None
        self.assertEqual([item.session_id for item in service.refresh()], ['chatgpt-session-sample'])

    def test_renaming_app_window_does_not_add_an_idle_conversation(self):
        service, _ = self.quiet_service()
        service.sources.append(OsWindowSource())
        for title in ['Old conversation', 'AI · Introduction', 'ChatGPT - renamed']:
            rows = [f'window_id=42\tprocess_id=123\tprocess_name=ChatGPT\ttitle={title}']
            with patch('ai_progress_monitor.sources.platform.system', return_value='Darwin'), \
                    patch('ai_progress_monitor.sources._run_command', return_value=rows):
                self.assertEqual([item.session_id for item in service.refresh()], ['chatgpt-session-sample'])

    def test_app_without_recent_conversations_keeps_only_process_idle_fallback(self):
        self.event('task_started')
        self.time += timedelta(hours=2)
        app = SessionUpdate('app', 'ChatGPT', ToolKind.CHATGPT, SurfaceKind.DESKTOP,
                            SessionStatus.IDLE, '', self.time, source='process', process_id=123)
        class Processes:
            volatile_source = 'process'
            def poll(self):
                return [app]
        service = MonitorService([self.source, Processes(), OsWindowSource()],
                                 self.store, ActionExecutor(), now=lambda: self.time)
        rows = ['window_id=42\tprocess_id=123\tprocess_name=ChatGPT\ttitle=AI · Introduction']
        with patch('ai_progress_monitor.sources.platform.system', return_value='Darwin'), \
                patch('ai_progress_monitor.sources._run_command', return_value=rows):
            sessions = service.refresh()
        self.assertEqual([(item.session_id, item.status) for item in sessions], [('app', SessionStatus.IDLE)])
