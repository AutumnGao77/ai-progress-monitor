import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ai_progress_monitor.models import SessionStatus
from ai_progress_monitor.sources import ChatGPTSessionSource
from tests.test_sources import write_codex_jsonl


class ChatGPTEventCompatibilityTests(unittest.TestCase):
    def read_events(self, events, age_seconds=1):
        current = datetime(2026, 9, 7, tzinfo=timezone.utc)
        records = [{"type": "session_meta", "payload": {"id": "sample", "cwd": "/projects/sample"}}]
        records.extend(events)
        for index, record in enumerate(records):
            record["timestamp"] = (current + timedelta(seconds=index)).isoformat()
        with tempfile.TemporaryDirectory() as directory:
            write_codex_jsonl(Path(directory) / "rollout-sample.jsonl", records)
            return ChatGPTSessionSource(
                Path(directory), now=lambda: current + timedelta(seconds=len(records) + age_seconds)
            ).poll()

    def test_completed_modern_reply_stays_available_for_review(self):
        for reply in [
            {"type": "event_msg", "payload": {"type": "item_completed", "item": {"type": "AgentMessage", "phase": "final_answer", "content": []}}},
            {"type": "response_item", "payload": {"type": "message", "role": "assistant", "phase": "final_answer", "content": []}},
        ]:
            with self.subTest(reply=reply):
                updates = self.read_events([
                    {"type": "event_msg", "payload": {"type": "task_started"}},
                    reply,
                    {"type": "event_msg", "payload": {"type": "task_complete"}},
                ], age_seconds=1200)
                self.assertEqual(len(updates), 1)
                self.assertEqual(updates[0].status, SessionStatus.NEEDS_ACTION)
                self.assertTrue(updates[0].view_ack_required)

    def test_abort_clears_running_and_unanswered_request(self):
        updates = self.read_events([
            {"type": "event_msg", "payload": {"type": "task_started"}},
            {"type": "event_msg", "payload": {"type": "approval_requested"}},
            {"type": "response_item", "payload": {"type": "function_call", "name": "request_user_input", "call_id": "question"}},
            {"type": "event_msg", "payload": {"type": "turn_aborted"}},
        ])
        self.assertEqual(updates[0].status, SessionStatus.IDLE)
        self.assertFalse(updates[0].view_ack_required)

    def test_restart_after_abort_is_running(self):
        updates = self.read_events([
            {"type": "event_msg", "payload": {"type": "task_started"}},
            {"type": "event_msg", "payload": {"type": "turn_aborted"}},
            {"type": "event_msg", "payload": {"type": "task_started"}},
        ])
        self.assertEqual(updates[0].status, SessionStatus.RUNNING)

    def test_modern_activity_after_previous_completion_is_running(self):
        updates = self.read_events([
            {"type": "event_msg", "payload": {"type": "task_complete"}},
            {"type": "event_msg", "payload": {"type": "item_completed", "item": {"type": "AgentMessage", "phase": "commentary"}}},
        ])
        self.assertEqual(updates[0].status, SessionStatus.RUNNING)

    def test_user_message_is_not_a_completed_agent_reply(self):
        updates = self.read_events([
            {"type": "event_msg", "payload": {"type": "task_started"}},
            {"type": "response_item", "payload": {"type": "message", "role": "user"}},
            {"type": "event_msg", "payload": {"type": "item_completed", "item": {"type": "UserMessage"}}},
            {"type": "event_msg", "payload": {"type": "task_complete"}},
        ])
        self.assertEqual(updates[0].status, SessionStatus.IDLE)

    def test_commentary_then_abort_does_not_require_review(self):
        updates = self.read_events([
            {"type": "event_msg", "payload": {"type": "task_started"}},
            {"type": "event_msg", "payload": {"type": "item_completed", "item": {"type": "AgentMessage", "phase": "commentary"}}},
            {"type": "event_msg", "payload": {"type": "turn_aborted"}},
        ])
        self.assertEqual(updates[0].status, SessionStatus.IDLE)

    def test_abort_without_retained_start_event_is_idle(self):
        updates = self.read_events([
            {"type": "event_msg", "payload": {"type": "turn_aborted"}},
        ])
        self.assertEqual(updates[0].status, SessionStatus.IDLE)
        self.assertFalse(updates[0].view_ack_required)

    def test_new_turn_clears_previous_unanswered_requests(self):
        for request in [
            {"type": "event_msg", "payload": {"type": "approval_requested"}},
            {"type": "response_item", "payload": {"type": "function_call", "name": "request_user_input", "call_id": "old-question"}},
        ]:
            with self.subTest(request=request):
                updates = self.read_events([
                    {"type": "event_msg", "payload": {"type": "task_started"}},
                    request,
                    {"type": "event_msg", "payload": {"type": "task_started"}},
                ])
                self.assertEqual(updates[0].status, SessionStatus.RUNNING)

    def test_current_turn_request_survives_agent_commentary(self):
        updates = self.read_events([
            {"type": "event_msg", "payload": {"type": "task_started"}},
            {"type": "response_item", "payload": {"type": "function_call", "name": "request_user_input", "call_id": "question"}},
            {"type": "event_msg", "payload": {"type": "item_completed", "item": {"type": "AgentMessage", "phase": "commentary"}}},
        ])
        self.assertEqual(updates[0].status, SessionStatus.NEEDS_ACTION)
        self.assertFalse(updates[0].view_ack_required)

    def test_large_log_tail_preserves_completion_and_abort(self):
        for ending, expected in [
            ([{"type": "event_msg", "payload": {"type": "turn_aborted"}}], SessionStatus.IDLE),
            ([
                {"type": "event_msg", "payload": {"type": "item_completed", "item": {"type": "AgentMessage", "phase": "final_answer"}}},
                {"type": "event_msg", "payload": {"type": "task_complete"}},
            ], SessionStatus.NEEDS_ACTION),
        ]:
            with self.subTest(expected=expected):
                # Put the start event outside both retained head and tail.
                updates = self.read_events([
                    {"type": "response_item", "payload": {"type": "function_call_output", "output": "x" * (70 * 1024)}},
                    {"type": "event_msg", "payload": {"type": "task_started"}},
                    {"type": "response_item", "payload": {"type": "function_call_output", "output": "x" * (300 * 1024)}},
                ] + ending)
                self.assertEqual(len(updates), 1)
                self.assertEqual(updates[0].status, expected)
