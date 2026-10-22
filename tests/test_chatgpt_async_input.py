import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from ai_progress_monitor.chatgpt_approvals import DesktopApprovalLog
from ai_progress_monitor.models import SessionStatus
from ai_progress_monitor.sources import ChatGPTSessionSource


class ChatGPTAsyncInputTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.sessions = self.root / "sessions"
        self.sessions.mkdir()
        self.path = self.sessions / "rollout-sample.jsonl"
        self.log_path = self.root / "codex-desktop-00000000-0000-0000-0000-000000000001-123-t0-i1-000000-0.log"
        self.base = datetime(2026, 10, 16, tzinfo=timezone.utc)
        self.tick = 0
        self.alive = True
        self.reader = DesktopApprovalLog(self.root, process_alive=lambda pid: self.alive)
        self.source = ChatGPTSessionSource(self.sessions, approval_log=self.reader,
            now=lambda: self.base + timedelta(seconds=self.tick + 10))
        self.append({"id": "sample", "originator": "ChatGPT Desktop", "cwd": "/projects/sample"}, "session_meta")
        self.append({"type": "task_started"}, "event_msg")

    def timestamp(self):
        self.tick += 1
        return (self.base + timedelta(seconds=self.tick)).isoformat()

    def append(self, payload, kind="response_item"):
        with self.path.open("a") as handle:
            handle.write(json.dumps({"timestamp": self.timestamp(), "type": kind, "payload": payload}) + "\n")

    def log(self, message, component="electron-message-handler"):
        with self.log_path.open("a") as handle:
            handle.write(f"{self.timestamp()} info [{component}] {message}\n")

    def ask(self, call="question", count=1):
        self.append({"type": "function_call", "name": "functions.request_user_input_async", "call_id": call,
                     "arguments": json.dumps({"questions": [{"title": "Choose an option"}] * count})})

    def accepted(self, call="question", accepted=True):
        self.append({"type": "function_call_output", "call_id": call, "output": json.dumps({"accepted": accepted})})

    def question_id(self, index=0, call="question"):
        return json.dumps(["request_user_input_async", call, index], separators=(",", ":"))

    def show_question(self, index=0, call="question"):
        notification = json.dumps(["instance", "account", "local", "sample", "turn", self.question_id(index, call)], separators=(",", ":"))
        self.log("[desktop-notifications] forward show kind=question notificationId=async-question-" + notification, "notifications-service")

    def answer(self, indices=(0,), call="question", kind="event_msg", role="user"):
        answers = [{"questionItemId": self.question_id(index, call), "question": "Choose an option", "answer": "A"} for index in indices]
        text = "<send_user_message_question_reply>\n" + json.dumps(answers) + "\n</send_user_message_question_reply>"
        if kind == "event_msg":
            self.append({"type": "user_message", "message": text}, kind)
        else:
            self.append({"type": "message", "role": role, "content": [{"type": "input_text", "text": text}]}, kind)

    def approval(self):
        self.log("[desktop-notifications] received approval conversationId=sample kind=commandExecution requestId=135")

    def approve(self):
        self.log('Sending server response id=135 method=item/commandExecution/requestApproval response={"decision":"accept"}')

    def assert_status(self, expected, view_ack=False):
        updates = self.source.poll()
        self.assertIsNotNone(updates)
        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0].status, expected)
        self.assertEqual(updates[0].view_ack_required, view_ack)

    def test_accepted_async_call_is_still_waiting_while_agent_keeps_working(self):
        self.ask()
        self.accepted()
        self.append({"type": "reasoning"})
        self.append({"type": "function_call", "name": "exec_command", "call_id": "work"})
        self.assert_status(SessionStatus.NEEDS_ACTION)

    def test_async_agent_message_without_function_call_is_waiting(self):
        self.append({"type": "item_completed", "item": {"type": "AgentMessage", "id": "question", "delivery": "async", "questions": [{"title": "Choose"}]}}, "event_msg")
        self.assert_status(SessionStatus.NEEDS_ACTION)

    def test_rejected_async_request_does_not_leave_waiting_state(self):
        self.ask()
        self.accepted(accepted=False)
        self.assert_status(SessionStatus.RUNNING)

    def test_matching_answer_resumes_running_for_both_user_message_formats(self):
        for kind in ("event_msg", "response_item"):
            with self.subTest(kind=kind):
                self.ask(call=kind)
                self.accepted(call=kind)
                self.answer(call=kind, kind=kind)
                self.assert_status(SessionStatus.RUNNING)

    def test_partial_answer_keeps_other_questions_pending(self):
        self.ask(count=2)
        self.accepted()
        self.answer(indices=(0,))
        self.assert_status(SessionStatus.NEEDS_ACTION)
        self.answer(indices=(1,))
        self.assert_status(SessionStatus.RUNNING)

    def test_unrelated_or_assistant_quoted_answer_does_not_clear_question(self):
        self.ask()
        self.accepted()
        self.answer(call="other")
        self.answer(kind="response_item", role="assistant")
        self.assert_status(SessionStatus.NEEDS_ACTION)

    def test_approval_response_does_not_clear_unanswered_async_question(self):
        self.ask()
        self.accepted()
        self.approval()
        self.approve()
        self.assert_status(SessionStatus.NEEDS_ACTION)

    def test_answer_does_not_clear_pending_command_approval(self):
        self.approval()
        self.ask()
        self.accepted()
        self.assert_status(SessionStatus.NEEDS_ACTION)
        self.answer()
        self.assert_status(SessionStatus.NEEDS_ACTION)
        self.approve()
        self.assert_status(SessionStatus.RUNNING)

    def test_log_question_recovers_without_rollout_request_after_restart(self):
        self.show_question()
        self.source.source_started_at = self.base + timedelta(hours=1)
        self.assert_status(SessionStatus.NEEDS_ACTION)

    def test_log_question_survives_other_approval_and_clears_on_matching_answer(self):
        self.show_question()
        self.approval()
        self.approve()
        self.assert_status(SessionStatus.NEEDS_ACTION)
        self.answer()
        self.assert_status(SessionStatus.RUNNING)

    def test_log_multiple_questions_clear_individually(self):
        self.show_question(0)
        self.show_question(1)
        self.answer(indices=(0,))
        self.assert_status(SessionStatus.NEEDS_ACTION)
        self.answer(indices=(1,))
        self.assert_status(SessionStatus.RUNNING)

    def test_log_completion_ends_question_without_new_rollout(self):
        self.ask()
        self.accepted()
        self.show_question()
        self.log("[desktop-notifications] received turn-complete conversationId=sample turnId=turn")
        self.assert_status(SessionStatus.NEEDS_ACTION, view_ack=True)

    def test_new_turn_supersedes_old_log_question(self):
        self.show_question()
        self.append({"type": "task_started"}, "event_msg")
        self.assert_status(SessionStatus.RUNNING)

    def test_abort_clears_async_question(self):
        self.ask()
        self.accepted()
        self.show_question()
        self.append({"type": "turn_aborted"}, "event_msg")
        self.assert_status(SessionStatus.IDLE)

    def test_question_log_state_dies_with_app(self):
        self.show_question()
        self.path.unlink()
        self.assert_status(SessionStatus.NEEDS_ACTION)
        self.alive = False
        self.assertEqual(self.source.poll(), [])

    def test_plain_notification_or_malformed_question_does_not_create_pending(self):
        self.log('[desktop-notifications] forward show kind=question notificationId=async-question-["invalid"]', "notifications-service")
        self.log('[desktop-notifications] show notification conversationId=sample kind=question requestId=undefined')
        self.assert_status(SessionStatus.RUNNING)

    def test_log_recovers_request_outside_rollout_head_and_tail(self):
        self.append({"type": "token_count", "padding": "x" * 70000}, "event_msg")
        self.ask()
        self.accepted()
        self.show_question()
        self.append({"type": "token_count", "padding": "x" * 300000}, "event_msg")
        self.assert_status(SessionStatus.NEEDS_ACTION)
        self.answer()
        self.assert_status(SessionStatus.RUNNING)
        self.assert_status(SessionStatus.RUNNING)

    def test_duplicate_agent_message_and_notification_do_not_reopen_answered_question(self):
        self.ask()
        self.accepted()
        self.show_question()
        self.answer()
        self.assert_status(SessionStatus.RUNNING)
        self.append({"type": "item_completed", "item": {"type": "AgentMessage", "id": "question", "delivery": "async", "questions": [{"title": "Choose"}]}}, "event_msg")
        self.show_question()
        self.assert_status(SessionStatus.RUNNING)

    def test_question_answer_with_clock_rollback_still_matches_identity(self):
        self.ask()
        self.show_question()
        self.tick -= 100
        self.answer()
        self.assert_status(SessionStatus.RUNNING)

    def test_completed_turn_clears_question_and_becomes_view_acknowledgeable(self):
        self.ask()
        self.accepted()
        self.append({"type": "agent_message", "message": "Finished"}, "event_msg")
        self.append({"type": "task_complete"}, "event_msg")
        self.assert_status(SessionStatus.NEEDS_ACTION, view_ack=True)

    def test_custom_tool_async_request_is_waiting(self):
        self.append({"type": "custom_tool_call", "name": "request_user_input_async", "call_id": "question",
                     "input": json.dumps({"questions": [{"title": "Choose"}]})})
        self.assert_status(SessionStatus.NEEDS_ACTION)

    def test_empty_or_malformed_question_list_does_not_create_pending(self):
        for arguments in ('{"questions": []}', '{"questions": [null]}', 'invalid'):
            self.append({"type": "function_call", "name": "request_user_input_async", "call_id": "question", "arguments": arguments})
        self.assert_status(SessionStatus.RUNNING)

    def test_answer_outside_rollout_tail_does_not_reopen_question_after_restart(self):
        self.ask()
        self.accepted()
        self.show_question()
        self.append({"type": "token_count", "padding": "x" * 70000}, "event_msg")
        self.answer()
        self.append({"type": "token_count", "padding": "x" * 300000}, "event_msg")
        self.assert_status(SessionStatus.RUNNING)

    def test_answer_stays_resolved_as_more_records_leave_tail(self):
        self.ask()
        self.show_question()
        self.answer()
        self.assert_status(SessionStatus.RUNNING)
        for _ in range(2):
            self.append({"type": "token_count", "padding": "x" * 300000}, "event_msg")
            self.assert_status(SessionStatus.RUNNING)

    def test_large_question_history_publishes_only_after_complete_replay(self):
        self.ask()
        self.show_question()
        self.append({"type": "token_count", "padding": "x" * (9 * 1024 * 1024)}, "event_msg")
        self.answer()
        self.append({"type": "token_count", "padding": "x" * 300000}, "event_msg")
        with patch('ai_progress_monitor.sources.CHATGPT_HISTORY_POLL_BYTE_BUDGET', 8 * 1024 * 1024):
            self.assertIsNone(self.source.poll())
        self.assert_status(SessionStatus.RUNNING)

    def test_truncated_rollout_discards_old_answer_history(self):
        prefix = self.path.read_text()
        self.ask()
        self.append({"type": "token_count", "padding": "x" * 70000}, "event_msg")
        self.answer()
        self.append({"type": "token_count", "padding": "x" * 300000}, "event_msg")
        self.assert_status(SessionStatus.RUNNING)
        self.path.write_text(prefix)
        self.ask()
        self.assert_status(SessionStatus.NEEDS_ACTION)

    def test_question_history_does_not_retain_question_or_answer_text(self):
        self.ask()
        self.append({"type": "token_count", "padding": "x" * 70000}, "event_msg")
        self.answer()
        self.append({"type": "token_count", "padding": "x" * 300000}, "event_msg")
        self.assert_status(SessionStatus.RUNNING)
        records = self.source._session_histories[self.path].records
        self.assertTrue(records)
        self.assertNotIn("Choose an option", json.dumps(records))
        self.assertNotIn('"answer": "A"', json.dumps(records))
