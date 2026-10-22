import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from ai_progress_monitor.models import SessionStatus
from ai_progress_monitor.qoder_desktop import QoderDesktopReader
from ai_progress_monitor.sources import _classify_process_rows


class QoderDesktopTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = self.root / "main.sqlite"
        self.now = datetime(2026, 10, 22, 1, 24, tzinfo=timezone.utc)
        self.reader = QoderDesktopReader()
        with sqlite3.connect(self.db) as connection:
            connection.executescript("""
                CREATE TABLE chat_sessions (
                    session_id TEXT PRIMARY KEY, title TEXT, cwd TEXT,
                    execution_kind TEXT, archived INTEGER DEFAULT 0,
                    deleted_at INTEGER, created_at INTEGER, updated_at INTEGER
                );
                CREATE TABLE chat_session_messages (
                    session_id TEXT, message_id TEXT, turn_id TEXT, sequence INTEGER,
                    role TEXT, subtype TEXT, status TEXT, runtime_input_state TEXT,
                    has_visible_content INTEGER, created_at INTEGER, updated_at INTEGER,
                    turn_started_at INTEGER, payload_json TEXT
                );
                CREATE INDEX message_sequence ON chat_session_messages(session_id, sequence);
            """)
            connection.execute(
                "INSERT INTO chat_sessions VALUES (?, ?, ?, 'local', 0, NULL, ?, ?)",
                ("test-session", "Synthetic sum", "/Users/Gao/Test", self.ms(-10), self.ms()),
            )
        self.message("user", "completed", 1, -10, {"parts": [{"type": "text", "text": "Synthetic test"}]})

    def ms(self, seconds=0):
        return int((self.now + timedelta(seconds=seconds)).timestamp() * 1000)

    def message(self, role, status, sequence, seconds=0, payload=None, **extra):
        with sqlite3.connect(self.db) as connection:
            connection.execute(
                "INSERT INTO chat_session_messages VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("test-session", "message-" + str(sequence), extra.get("turn_id", "turn-one"), sequence,
                 role, extra.get("subtype"), status, extra.get("runtime_input_state"),
                 extra.get("has_visible_content", 1), self.ms(seconds), self.ms(seconds),
                 self.ms(extra.get("started", -10)), json.dumps(payload or {})),
            )

    def completed(self, sequence=2, seconds=0, text="Synthetic answer"):
        self.message("assistant", "completed", sequence, seconds, {
            "completedAt": (self.now + timedelta(seconds=seconds)).isoformat(),
            "parts": [{"type": "text", "text": text}],
        })

    def read(self, **kwargs):
        return self.reader.read(self.db, now=self.now, **kwargs)

    def log(self, lines, append=False):
        path = self.root / "logs" / "test-launch" / "qodercli" / "sessions" / "test-session.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a" if append else "w") as handle:
            for seconds, message in lines:
                handle.write((self.now + timedelta(seconds=seconds)).isoformat() + " [QueryRunner] " + message + "\n")
        return path

    def test_new_user_and_streaming_assistant_are_running(self):
        self.assertEqual(self.read()[0].status, SessionStatus.RUNNING)
        self.message("assistant", "streaming", 2, -1)
        self.assertEqual(self.read()[0].status, SessionStatus.RUNNING)

    def test_completed_reply_requires_view_and_metadata_does_not_refresh_result(self):
        self.completed()
        with sqlite3.connect(self.db) as connection:
            connection.execute("UPDATE chat_sessions SET updated_at=?, title='Renamed test'", (self.ms(60),))
            connection.execute("UPDATE chat_session_messages SET updated_at=? WHERE role='assistant'", (self.ms(30),))
        self.message("system", "completed", 3, 40, {"parts": [{"type": "text", "text": "Usage"}]}, subtype="usage")
        state = self.read()[0]
        self.assertEqual(state.status, SessionStatus.NEEDS_ACTION)
        self.assertFalse(state.user_attention_signal)
        self.assertEqual(state.updated_at, self.now)
        self.assertEqual(state.title, "Renamed test")

    def test_empty_completed_reply_is_idle(self):
        self.completed(text="  \n ")
        self.assertEqual(self.read()[0].status, SessionStatus.IDLE)

    def test_next_user_turn_supersedes_previous_completion(self):
        self.completed(seconds=-5)
        self.message("user", "completed", 3, -1, turn_id="turn-two", started=-1)
        self.assertEqual(self.read()[0].status, SessionStatus.RUNNING)

    def test_cancelled_and_interrupted_turns_are_idle(self):
        for status in ["cancelled", "interrupted", "aborted"]:
            with self.subTest(status=status):
                self.message("assistant", status, 2)
                self.assertEqual(self.read()[0].status, SessionStatus.IDLE)
                with sqlite3.connect(self.db) as connection:
                    connection.execute("DELETE FROM chat_session_messages WHERE role='assistant'")

    def test_explicit_input_state_cannot_be_view_acknowledged(self):
        self.message("assistant", "waiting_for_input", 2)
        self.assertTrue(self.read()[0].user_attention_signal)

    def test_ordinary_error_is_a_result_but_account_blocker_requires_action(self):
        self.message("assistant", "error", 2, payload={"appErrorCode": "request_timeout"})
        self.assertFalse(self.read()[0].user_attention_signal)
        with sqlite3.connect(self.db) as connection:
            connection.execute("UPDATE chat_session_messages SET payload_json=? WHERE role='assistant'",
                               (json.dumps({"appErrorCode": "insufficient_quota"}),))
        self.assertTrue(self.read()[0].user_attention_signal)

    def test_deleted_archived_and_remote_sessions_do_not_reappear(self):
        self.completed()
        for clause in ["deleted_at=1", "archived=1", "execution_kind='remote'"]:
            with self.subTest(clause=clause):
                with sqlite3.connect(self.db) as connection:
                    connection.execute("UPDATE chat_sessions SET deleted_at=NULL, archived=0, execution_kind='local'")
                    connection.execute("UPDATE chat_sessions SET " + clause)
                self.assertEqual(self.read(), [])

    def test_old_completion_does_not_open_on_monitor_start(self):
        self.completed(seconds=-30)
        self.assertEqual(self.read(source_started_at=self.now), [])

    def test_failed_read_preserves_previous_complete_snapshot(self):
        self.completed()
        before = self.read()
        with mock.patch("ai_progress_monitor.qoder_desktop.sqlite3.connect", side_effect=sqlite3.OperationalError("busy")):
            self.assertEqual(self.read(), before)
        self.assertEqual(QoderDesktopReader().read(self.root / "missing.sqlite", now=self.now), None)

    def test_pending_permission_log_and_matching_response(self):
        self.message("assistant", "streaming", 2, -2)
        self.log([(-10, "outbound session_message sent type=user uuid=input"),
                  (-4, "inbound control_request received request_id=permission-one subtype=can_use_tool")])
        waiting = self.read()[0]
        self.assertEqual(waiting.status, SessionStatus.NEEDS_ACTION)
        self.assertTrue(waiting.user_attention_signal)
        self.log([(-1, "inbound control_response sent request_id=unrelated subtype=can_use_tool status=success")], append=True)
        self.assertTrue(self.read()[0].user_attention_signal)
        self.log([(0, "inbound control_response sent request_id=permission-one subtype=can_use_tool status=success")], append=True)
        self.assertEqual(self.read()[0].status, SessionStatus.RUNNING)

    def test_completion_and_new_turn_clear_old_log_permission(self):
        self.log([(-10, "outbound session_message sent type=user uuid=input"),
                  (-4, "inbound control_request received request_id=permission-one subtype=can_use_tool")])
        self.completed()
        self.assertFalse(self.read()[0].user_attention_signal)
        self.message("user", "completed", 3, 1, turn_id="turn-two", started=1)
        self.now += timedelta(seconds=2)
        self.assertEqual(self.read()[0].status, SessionStatus.RUNNING)

    def test_context_usage_and_model_policy_are_not_attention(self):
        self.message("assistant", "streaming", 2, -2)
        self.log([(-1, "inbound control_request received request_id=policy subtype=get_model_policy"),
                  (0, "control_request sent request_id=usage subtype=get_context_usage")])
        self.assertEqual(self.read()[0].status, SessionStatus.RUNNING)

    def test_restart_replays_answered_permission_without_reopening_it(self):
        self.message("assistant", "streaming", 2, -2)
        self.log([(-10, "outbound session_message sent type=user uuid=input"),
                  (-4, "inbound control_request received request_id=permission-one subtype=can_use_tool"),
                  (-1, "inbound control_response sent request_id=permission-one subtype=can_use_tool status=success")])
        first = self.read()
        self.reader = QoderDesktopReader()
        self.assertEqual(self.read(), first)
        self.assertFalse(first[0].user_attention_signal)

    def test_matching_answer_resumes_older_waiting_database_projection(self):
        self.message("assistant", "waiting_for_permission", 2, -2)
        self.log([(-10, "outbound session_message sent type=user uuid=input"),
                  (-4, "inbound control_request received request_id=permission-one subtype=can_use_tool"),
                  (-1, "inbound control_response sent request_id=permission-one subtype=can_use_tool status=success")])
        self.assertEqual(self.read()[0].status, SessionStatus.RUNNING)

    def test_two_pending_questions_need_two_matching_answers(self):
        self.message("assistant", "streaming", 2, -2)
        self.log([(-10, "outbound session_message sent type=user uuid=input"),
                  (-4, "inbound control_request received request_id=one subtype=ask_user_question"),
                  (-3, "inbound control_request received request_id=two subtype=ask_user_question"),
                  (-1, "inbound control_response sent request_id=one subtype=ask_user_question status=success")])
        self.assertTrue(self.read()[0].user_attention_signal)
        self.log([(0, "inbound control_response sent request_id=two subtype=ask_user_question status=success")], append=True)
        self.assertFalse(self.read()[0].user_attention_signal)

    def test_new_logged_turn_supersedes_old_completed_projection(self):
        self.completed(seconds=-20)
        self.log([(-1, "outbound session_message sent type=user uuid=new-input")])
        self.assertEqual(self.read()[0].status, SessionStatus.RUNNING)

    def test_delayed_same_turn_sdk_completion_does_not_move_result_timestamp(self):
        self.completed()
        self.log([(-10, "outbound session_message sent type=user uuid=input"),
                  (-1, 'inbound session_message received type=assistant subtype=none uuid=reply preview="Synthetic answer"'),
                  (3, "inbound session_message received type=result subtype=success uuid=result")])
        self.now += timedelta(seconds=4)
        self.assertEqual(self.read()[0].updated_at, self.now - timedelta(seconds=4))

    def test_partial_log_record_preserves_prior_snapshot_and_does_not_cache_text(self):
        self.message("assistant", "streaming", 2, -2)
        path = self.log([(-10, "outbound session_message sent type=user uuid=input preview=private-marker")])
        before = self.read()
        with path.open("a") as handle:
            handle.write(self.now.isoformat() + " [QueryRunner] inbound control_request received request_id=one subtype=can_use_tool")
        self.assertEqual(self.read(), before)
        self.assertNotIn("private-marker", repr(self.reader.__dict__))
        with path.open("a") as handle:
            handle.write("\n")
        self.assertTrue(self.read()[0].user_attention_signal)

    def test_deleted_current_database_is_not_replaced_by_legacy_results(self):
        row = "process_id=123\tprocess_name=Qoder CN\tcommand=/Applications/Qoder CN.app/Contents/MacOS/Qoder CN"
        with mock.patch("ai_progress_monitor.sources.QoderDesktopReader.read", return_value=None), \
                mock.patch("ai_progress_monitor.sources._read_qoder_active_task_states") as legacy:
            updates = list(_classify_process_rows([row], qoder_logs_dirs=[self.root], now=self.now))
        legacy.assert_not_called()
        self.assertEqual(updates[0].status_source, "desktop-process")

    def test_replay_is_incremental_and_does_not_publish_half_answered_permission(self):
        self.reader = QoderDesktopReader(log_byte_budget=180)
        self.message("assistant", "streaming", 2, -2)
        self.log([(-10, "outbound session_message sent type=user uuid=input"),
                  (-4, "inbound control_request received request_id=permission-one subtype=can_use_tool"),
                  (-3, "inbound session_message received type=system subtype=usage " + "x" * 100),
                  (-1, "inbound control_response sent request_id=permission-one subtype=can_use_tool status=success")])
        for _ in range(12):
            snapshot = self.read()
            if snapshot:
                self.assertFalse(snapshot[0].user_attention_signal)
        self.assertEqual(self.read()[0].status, SessionStatus.RUNNING)

    def test_oversized_log_line_makes_bounded_progress_without_caching_content(self):
        self.reader = QoderDesktopReader(log_byte_budget=65536)
        self.message("assistant", "streaming", 2, -2)
        self.log([(-10, "outbound session_message sent type=user uuid=input"),
                  (-3, "inbound session_message received type=system preview=" + "private-marker" * 30000),
                  (-1, "inbound control_request received request_id=one subtype=can_use_tool")])
        snapshot = None
        for _ in range(20):
            snapshot = self.read()
            self.assertNotIn("private-marker", repr(self.reader.__dict__))
            if snapshot:
                break
        self.assertIsNotNone(snapshot)
        self.assertTrue(snapshot[0].user_attention_signal)

    def test_current_binary_uses_new_store_instead_of_old_blocker(self):
        self.completed()
        states = self.read()
        row = "process_id=123\tprocess_name=Qoder CN\tcommand=/Applications/Qoder CN.app/Contents/MacOS/Qoder CN"
        with mock.patch("ai_progress_monitor.sources.QoderDesktopReader.read", return_value=states), \
                mock.patch("ai_progress_monitor.sources._read_qoder_active_task_states") as legacy:
            updates = list(_classify_process_rows([row], now=self.now))
        legacy.assert_not_called()
        self.assertEqual(updates[0].status_source, "qoder-desktop")
        self.assertEqual(updates[0].title, "Qoder CN Desktop - Synthetic sum")
        self.assertTrue(updates[0].view_ack_required)

    def test_legacy_binary_keeps_legacy_reader(self):
        row = "process_id=123\tprocess_name=Electron\tcommand=/Applications/Qoder CN.app/Contents/MacOS/Electron"
        with mock.patch("ai_progress_monitor.sources.QoderDesktopReader.read") as modern, \
                mock.patch("ai_progress_monitor.sources._read_qoder_active_task_states", return_value=[]):
            list(_classify_process_rows([row], qoder_logs_dirs=[self.root], now=self.now))
        modern.assert_not_called()


if __name__ == "__main__":
    unittest.main()
