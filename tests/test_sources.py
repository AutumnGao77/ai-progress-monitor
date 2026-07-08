import json
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import time
from unittest import mock

from ai_progress_monitor.models import SessionStatus, ToolKind
from ai_progress_monitor.sources import (
    AiToolDefinition,
    CodexSessionSource,
    SOURCE_COMMAND_TIMEOUT_SECONDS,
    JsonSessionSource,
    _classify_process_rows,
    _classify_window_rows,
    _is_generated_conversation_path,
    _posix_process_command,
    _run_command,
)


def write_json_session(path: Path, status: str, updated_at: datetime) -> None:
    path.write_text(
        json.dumps(
            {
                "session_id": path.stem,
                "title": path.stem,
                "tool": "codex",
                "surface": "terminal",
                "status": status,
                "summary": status,
                "updated_at": updated_at.isoformat(),
            }
        )
    )


def write_codex_jsonl(path: Path, events: list) -> None:
    path.write_text("\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8")


class SourceTests(unittest.TestCase):
    def test_reads_valid_json_session_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "session.json"
            path.write_text(
                json.dumps(
                    {
                        "session_id": "s1",
                        "title": "Codex terminal",
                        "tool": "codex",
                        "surface": "terminal",
                        "status": "needs_action",
                        "summary": "Waiting for Yes/No",
                        "updated_at": datetime(2026, 6, 30, tzinfo=timezone.utc).isoformat(),
                    }
                )
            )

            updates = JsonSessionSource(Path(temp_dir), cleanup_after_seconds=0).poll()

            self.assertEqual(len(updates), 1)
            self.assertEqual(updates[0].tool, ToolKind.CODEX)
            self.assertEqual(updates[0].status, SessionStatus.NEEDS_ACTION)

    def test_ignores_json_session_files_updated_before_source_start(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            write_json_session(
                Path(temp_dir) / "history.json",
                "needs_action",
                datetime(2026, 7, 2, 13, 59, tzinfo=timezone.utc),
            )

            updates = JsonSessionSource(
                Path(temp_dir),
                source_started_at=datetime(2026, 7, 2, 14, 0, tzinfo=timezone.utc),
            ).poll()

            self.assertEqual(updates, [])

    def test_run_command_distinguishes_failed_scan_from_empty_success(self):
        with mock.patch("ai_progress_monitor.sources.subprocess.run", side_effect=subprocess.TimeoutExpired(["ps"], 2)):
            self.assertIsNone(_run_command(["ps"]))

        completed = subprocess.CompletedProcess(["ps"], 0, stdout="", stderr="")
        with mock.patch("ai_progress_monitor.sources.subprocess.run", return_value=completed):
            self.assertEqual(_run_command(["ps"]), [])

    def test_posix_process_command_uses_portable_ps_columns(self):
        command = _posix_process_command()

        self.assertEqual(command[:2], ["sh", "-c"])
        self.assertNotIn("etimes=", command[-1])
        self.assertIn("ps -axo pid=,ppid=,pgid=,stat=,%cpu=,comm=,args=", command[-1])

    def test_generated_conversation_path_rules_can_match_unknown_tool_by_display_name(self):
        definition = AiToolDefinition(
            key="example-ai",
            display_name="Example AI",
            generated_conversation_path_patterns=(r"(^|/|\\)ExampleAI(/|\\)Chats(/|\\)[^/\\]+$",),
        )

        with mock.patch("ai_progress_monitor.sources.AI_TOOL_DEFINITIONS", (definition,)):
            self.assertTrue(
                _is_generated_conversation_path(
                    ToolKind.UNKNOWN,
                    "/Users/Gao/Library/Application Support/ExampleAI/Chats/hello",
                    tool_display_name="Example AI",
                )
            )

    def test_reads_window_metadata_from_json_session_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "desktop.json"
            path.write_text(
                json.dumps(
                    {
                        "session_id": "desktop-1",
                        "title": "Codex Desktop - PRD",
                        "tool": "codex",
                        "surface": "desktop",
                        "status": "needs_action",
                        "summary": "Waiting",
                        "updated_at": datetime(2026, 6, 30, tzinfo=timezone.utc).isoformat(),
                        "window_id": "win-42",
                        "process_id": 1234,
                        "process_name": "Codex",
                        "focus_process_id": 75407,
                        "focus_app_name": "Zed",
                    }
                )
            )

            updates = JsonSessionSource(Path(temp_dir), cleanup_after_seconds=0).poll()

            self.assertEqual(updates[0].window_id, "win-42")
            self.assertEqual(updates[0].process_id, 1234)
            self.assertEqual(updates[0].process_name, "Codex")
            self.assertEqual(updates[0].focus_process_id, 75407)
            self.assertEqual(updates[0].focus_app_name, "Zed")

    def test_cleans_stale_terminal_control_fragments_from_json_summary(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "dirty.json"
            path.write_text(
                json.dumps(
                    {
                        "session_id": "dirty",
                        "title": "Claude Code - dirty",
                        "tool": "claude_code",
                        "surface": "terminal",
                        "status": "unknown",
                        "summary": "�[1B�[39m �[38;2;153;153;153m20260703AIcoding | MiniMax-M3�[m | ctx:6%�[39m �[K",
                        "updated_at": datetime(2026, 6, 30, tzinfo=timezone.utc).isoformat(),
                    }
                )
            )

            updates = JsonSessionSource(Path(temp_dir), cleanup_after_seconds=0).poll()

            self.assertEqual(updates[0].summary, "20260703AIcoding | MiniMax-M3 | ctx:6%")

    def test_classifies_structured_window_rows_with_stable_id(self):
        rows = ['window_id=42\tprocess_id=1234\tprocess_name=Codex\ttitle=Codex Desktop - PRD polish']

        updates = list(_classify_window_rows(rows))

        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0].session_id, "window-42")
        self.assertEqual(updates[0].window_id, "42")
        self.assertEqual(updates[0].process_id, 1234)
        self.assertEqual(updates[0].process_name, "Codex")
        self.assertEqual(updates[0].title, "Codex Desktop - PRD polish")

    def test_classifies_direct_claude_process_as_idle_when_process_is_quiet(self):
        rows = [
            "process_id=27876\tprocess_name=claude\tcommand=claude\tcwd=/Users/Gao/Documents/checkout-flow\tcpu_percent=0.0\tstat=S+\tactive_child_count=0\tfocus_process_id=75407\tfocus_app_name=Zed"
        ]

        updates = list(_classify_process_rows(rows))

        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0].session_id, "process-27876")
        self.assertEqual(updates[0].title, "Claude Code CLI - checkout-flow")
        self.assertEqual(updates[0].tool, ToolKind.CLAUDE_CODE)
        self.assertEqual(updates[0].status, SessionStatus.IDLE)
        self.assertEqual(updates[0].surface.value, "terminal")
        self.assertEqual(updates[0].focus_process_id, 75407)
        self.assertEqual(updates[0].focus_app_name, "Zed")
        self.assertEqual(updates[0].cwd, "/Users/Gao/Documents/checkout-flow")
        self.assertIn("只能确认 CLI 会话进程存在", updates[0].summary)
        self.assertIn("无法读取终端内容", updates[0].summary)

    def test_keeps_existing_quiet_direct_cli_process_as_idle_after_source_start(self):
        rows = [
            "process_id=27876\tprocess_name=claude\tcommand=claude\tcwd=/Users/Gao/Documents/checkout-flow\tcpu_percent=0.0\tstat=S+\tactive_child_count=0\telapsed_seconds=601"
        ]

        updates = list(
            _classify_process_rows(
                rows,
                source_started_at=datetime(2026, 7, 2, 14, 0, tzinfo=timezone.utc),
                now=datetime(2026, 7, 2, 14, 10, tzinfo=timezone.utc),
            )
        )

        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0].session_id, "process-27876")
        self.assertEqual(updates[0].status, SessionStatus.IDLE)

    def test_keeps_old_direct_cli_process_when_activity_happens_after_source_start(self):
        rows = [
            "process_id=30001\tprocess_name=codex\tcommand=codex\tcwd=/Users/Gao/Documents/prd\tcpu_percent=2.4\tstat=S+\tactive_child_count=0\telapsed_seconds=601"
        ]

        updates = list(
            _classify_process_rows(
                rows,
                source_started_at=datetime(2026, 7, 2, 14, 0, tzinfo=timezone.utc),
                now=datetime(2026, 7, 2, 14, 10, tzinfo=timezone.utc),
            )
        )

        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0].session_id, "process-30001")
        self.assertEqual(updates[0].status, SessionStatus.RUNNING)

    def test_existing_claude_cli_reply_after_source_start_uses_session_timestamp(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            updated_at_ms = int(time() * 1000)
            updated_at = datetime.fromtimestamp(updated_at_ms / 1000.0, timezone.utc)
            source_started_at = updated_at - timedelta(seconds=60)
            Path(temp_dir, "27876.json").write_text(
                json.dumps(
                    {
                        "pid": 27876,
                        "cwd": "/Users/Gao/Documents/checkout-flow",
                        "status": "idle",
                        "updatedAt": updated_at_ms,
                    }
                )
            )
            rows = [
                "process_id=27876\tprocess_name=claude\tcommand=claude\tcwd=/Users/Gao/Documents/checkout-flow\tcpu_percent=0.0\tstat=S+\tactive_child_count=0\telapsed_seconds=601"
            ]

            updates = list(
                _classify_process_rows(
                    rows,
                    claude_sessions_dir=Path(temp_dir),
                    source_started_at=source_started_at,
                    now=updated_at,
                )
            )

            self.assertEqual(len(updates), 1)
            self.assertEqual(updates[0].status, SessionStatus.IDLE)
            self.assertEqual(updates[0].updated_at, updated_at)

    def test_keeps_direct_cli_process_started_after_source_start(self):
        rows = [
            "process_id=27876\tprocess_name=claude\tcommand=claude\tcwd=/Users/Gao/Documents/checkout-flow\tcpu_percent=0.0\tstat=S+\tactive_child_count=0\telapsed_seconds=120"
        ]

        updates = list(
            _classify_process_rows(
                rows,
                source_started_at=datetime(2026, 7, 2, 14, 0, tzinfo=timezone.utc),
                now=datetime(2026, 7, 2, 14, 10, tzinfo=timezone.utc),
            )
        )

        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0].session_id, "process-27876")

    def test_ignores_detached_direct_claude_process_after_terminal_closes(self):
        rows = [
            "process_id=27876\tprocess_name=claude\tcommand=claude\tcwd=/Users/Gao/Documents/projects/网点清场\tcpu_percent=0.0\tstat=S\tactive_child_count=0\tfocus_process_id=75407\tfocus_app_name=Zed"
        ]

        updates = list(_classify_process_rows(rows))

        self.assertEqual(updates, [])

    def test_classifies_direct_claude_process_as_running_when_cpu_or_child_is_active(self):
        rows = [
            "process_id=27876\tprocess_name=claude\tcommand=claude\tcwd=/Users/Gao/Documents/checkout-flow\tcpu_percent=2.4\tstat=S+\tactive_child_count=0",
            "process_id=27877\tprocess_name=claude\tcommand=claude\tcwd=/Users/Gao/Documents/docs\tcpu_percent=0.0\tstat=S+\tactive_child_count=1",
        ]

        updates = list(_classify_process_rows(rows))

        self.assertEqual([update.status for update in updates], [SessionStatus.RUNNING, SessionStatus.RUNNING])

    def test_classifies_direct_claude_process_status_from_claude_session_file_before_cpu(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            Path(temp_dir, "27876.json").write_text(
                json.dumps(
                    {
                        "pid": 27876,
                        "cwd": "/Users/Gao/Documents/projects/网点清场",
                        "status": "idle",
                        "updatedAt": int(time() * 1000),
                    }
                )
            )
            rows = [
                "process_id=27876\tprocess_name=claude\tcommand=claude\tcwd=/Users/Gao/Documents/projects/网点清场\tcpu_percent=3.6\tstat=S+\tactive_child_count=2"
            ]

            updates = list(_classify_process_rows(rows, claude_sessions_dir=Path(temp_dir)))

            self.assertEqual(len(updates), 1)
            self.assertEqual(updates[0].status, SessionStatus.IDLE)
            self.assertEqual(updates[0].cwd, "/Users/Gao/Documents/projects/网点清场")
            self.assertEqual(updates[0].status_source, "claude-session")

    def test_claude_session_file_updated_at_is_used_for_stable_view_ack(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            updated_at_ms = int(time() * 1000)
            updated_at = datetime.fromtimestamp(updated_at_ms / 1000.0, timezone.utc)
            Path(temp_dir, "27876.json").write_text(
                json.dumps(
                    {
                        "pid": 27876,
                        "cwd": "/Users/Gao/Documents/projects/网点清场",
                        "status": "idle",
                        "updatedAt": updated_at_ms,
                    }
                )
            )
            rows = [
                "process_id=27876\tprocess_name=claude\tcommand=claude\tcwd=/Users/Gao/Documents/projects/网点清场\tcpu_percent=3.6\tstat=S+\tactive_child_count=2\tfocus_process_id=75407\tfocus_app_name=Zed"
            ]

            updates = list(_classify_process_rows(rows, claude_sessions_dir=Path(temp_dir)))

            self.assertEqual(updates[0].updated_at, updated_at)
            self.assertEqual(updates[0].focus_process_id, 75407)
            self.assertEqual(updates[0].focus_app_name, "Zed")

    def test_classifies_direct_claude_process_running_from_claude_session_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            Path(temp_dir, "16173.json").write_text(
                json.dumps(
                    {
                        "pid": 16173,
                        "cwd": "/Users/Gao/Documents/projects/网点抛扔",
                        "status": "busy",
                        "updatedAt": int(time() * 1000),
                    }
                )
            )
            rows = [
                "process_id=16173\tprocess_name=claude\tcommand=claude\tcwd=/Users/Gao/Documents/projects/网点抛扔\tcpu_percent=0.0\tstat=S+\tactive_child_count=0"
            ]

            updates = list(_classify_process_rows(rows, claude_sessions_dir=Path(temp_dir)))

            self.assertEqual(len(updates), 1)
            self.assertEqual(updates[0].status, SessionStatus.RUNNING)

    def test_stale_claude_busy_session_file_falls_back_to_quiet_process_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            Path(temp_dir, "27876.json").write_text(
                json.dumps(
                    {
                        "pid": 27876,
                        "cwd": "/Users/Gao/Documents/projects/网点清场",
                        "status": "busy",
                        "updatedAt": int((time() - 120) * 1000),
                    }
                )
            )
            rows = [
                "process_id=27876\tprocess_name=claude\tcommand=claude\tcwd=/Users/Gao/Documents/projects/网点清场\tcpu_percent=0.0\tstat=S+\tactive_child_count=0"
            ]

            updates = list(_classify_process_rows(rows, claude_sessions_dir=Path(temp_dir)))

            self.assertEqual(len(updates), 1)
            self.assertEqual(updates[0].status, SessionStatus.IDLE)
            self.assertEqual(updates[0].status_source, "process")

    def test_stale_claude_session_file_fallback_uses_current_poll_time(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            old = datetime(2026, 7, 2, 8, 0, tzinfo=timezone.utc)
            Path(temp_dir, "27876.json").write_text(
                json.dumps(
                    {
                        "pid": 27876,
                        "cwd": "/Users/Gao/Documents/projects/网点清场",
                        "status": "busy",
                        "updatedAt": int(old.timestamp() * 1000),
                    }
                )
            )
            rows = [
                "process_id=27876\tprocess_name=claude\tcommand=claude\tcwd=/Users/Gao/Documents/projects/网点清场\tcpu_percent=0.0\tstat=S+\tactive_child_count=0"
            ]

            before = datetime.now(timezone.utc)
            updates = list(_classify_process_rows(rows, claude_sessions_dir=Path(temp_dir)))
            after = datetime.now(timezone.utc)

            self.assertEqual(len(updates), 1)
            self.assertGreaterEqual(updates[0].updated_at, before)
            self.assertLessEqual(updates[0].updated_at, after)

    def test_stale_claude_idle_session_file_stays_idle_despite_transient_process_activity(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            Path(temp_dir, "16173.json").write_text(
                json.dumps(
                    {
                        "pid": 16173,
                        "cwd": "/Users/Gao/Documents/projects/网点抛扔",
                        "status": "idle",
                        "updatedAt": int((time() - 120) * 1000),
                    }
                )
            )
            rows = [
                "process_id=16173\tprocess_name=claude\tcommand=claude\tcwd=/Users/Gao/Documents/projects/网点抛扔\tcpu_percent=2.4\tstat=S+\tactive_child_count=0"
            ]

            updates = list(_classify_process_rows(rows, claude_sessions_dir=Path(temp_dir)))

            self.assertEqual(len(updates), 1)
            self.assertEqual(updates[0].status, SessionStatus.IDLE)
            self.assertEqual(updates[0].status_source, "claude-session")

    def test_stale_claude_waiting_session_file_stays_needs_action(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            Path(temp_dir, "5659.json").write_text(
                json.dumps(
                    {
                        "pid": 5659,
                        "cwd": "/Users/Gao/Documents/20260703AIcoding",
                        "status": "waiting",
                        "updatedAt": int((time() - 600) * 1000),
                    }
                )
            )
            rows = [
                "process_id=5659\tprocess_name=claude\tcommand=claude\tcwd=/Users/Gao/Documents/20260703AIcoding\tcpu_percent=0.0\tstat=S+\tactive_child_count=0"
            ]

            updates = list(_classify_process_rows(rows, claude_sessions_dir=Path(temp_dir)))

            self.assertEqual(len(updates), 1)
            self.assertEqual(updates[0].status, SessionStatus.NEEDS_ACTION)

    def test_codex_session_source_marks_unfinished_task_as_running(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            session_file = Path(temp_dir) / "rollout-2026-07-02T22-16-56-codex-active.jsonl"
            write_codex_jsonl(
                session_file,
                [
                    {
                        "type": "session_meta",
                        "timestamp": "2026-07-02T14:00:00+00:00",
                        "payload": {
                            "id": "codex-active",
                            "cwd": "/Users/Gao/Documents/20260703AIcoding",
                            "source": "vscode",
                        },
                    },
                    {
                        "type": "event_msg",
                        "timestamp": "2026-07-02T14:01:00+00:00",
                        "payload": {"type": "task_started", "turn_id": "turn-1"},
                    },
                    {
                        "type": "response_item",
                        "timestamp": "2026-07-02T14:01:04+00:00",
                        "payload": {"type": "function_call", "call_id": "call-1", "name": "exec_command"},
                    },
                ],
            )

            updates = CodexSessionSource(
                Path(temp_dir),
                now=lambda: datetime(2026, 7, 2, 14, 1, 5, tzinfo=timezone.utc),
            ).poll()

            self.assertEqual(len(updates), 1)
            self.assertEqual(updates[0].session_id, "codex-session-codex-active")
            self.assertEqual(updates[0].title, "Codex Desktop - 20260703AIcoding")
            self.assertEqual(updates[0].tool, ToolKind.CODEX)
            self.assertEqual(updates[0].status, SessionStatus.RUNNING)
            self.assertEqual(updates[0].surface.value, "desktop")
            self.assertEqual(updates[0].source, "codex-session")
            self.assertEqual(updates[0].focus_app_name, "Codex")
            self.assertEqual(updates[0].cwd, "/Users/Gao/Documents/20260703AIcoding")
            self.assertFalse(updates[0].generated_conversation_path)

    def test_codex_session_source_marks_generated_conversation_path_from_tool_config(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            session_file = Path(temp_dir) / "rollout-2026-07-02T22-16-56-codex-chat.jsonl"
            write_codex_jsonl(
                session_file,
                [
                    {
                        "type": "session_meta",
                        "timestamp": "2026-07-02T14:00:00+00:00",
                        "payload": {
                            "id": "codex-chat",
                            "cwd": "/Users/Gao/Documents/Codex/2026-07-07/hello",
                            "source": "desktop",
                        },
                    },
                    {
                        "type": "event_msg",
                        "timestamp": "2026-07-02T14:01:00+00:00",
                        "payload": {"type": "task_complete", "turn_id": "turn-1"},
                    },
                ],
            )

            updates = CodexSessionSource(
                Path(temp_dir),
                now=lambda: datetime(2026, 7, 2, 14, 1, 5, tzinfo=timezone.utc),
            ).poll()

            self.assertEqual(len(updates), 1)
            self.assertTrue(updates[0].generated_conversation_path)

    def test_codex_session_source_drops_old_completed_sessions(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            session_file = Path(temp_dir) / "rollout-2026-07-02T22-16-56-codex-done.jsonl"
            write_codex_jsonl(
                session_file,
                [
                    {
                        "type": "session_meta",
                        "timestamp": "2026-07-02T14:00:00+00:00",
                        "payload": {"id": "codex-done", "cwd": "/Users/Gao/Documents/20260703AIcoding"},
                    },
                    {
                        "type": "event_msg",
                        "timestamp": "2026-07-02T14:01:00+00:00",
                        "payload": {"type": "task_started", "turn_id": "turn-1"},
                    },
                    {
                        "type": "event_msg",
                        "timestamp": "2026-07-02T14:02:00+00:00",
                        "payload": {"type": "task_complete", "turn_id": "turn-1"},
                    },
                ],
            )

            updates = CodexSessionSource(
                Path(temp_dir),
                now=lambda: datetime(2026, 7, 2, 14, 5, 1, tzinfo=timezone.utc),
                completed_visible_seconds=120,
            ).poll()

            self.assertEqual(updates, [])

    def test_codex_session_source_marks_completed_visible_reply_as_needs_action(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            session_file = Path(temp_dir) / "rollout-2026-07-02T22-16-56-codex-replied.jsonl"
            write_codex_jsonl(
                session_file,
                [
                    {
                        "type": "session_meta",
                        "timestamp": "2026-07-02T14:00:00+00:00",
                        "payload": {"id": "codex-replied", "cwd": "/Users/Gao/Documents/20260703AIcoding"},
                    },
                    {
                        "type": "event_msg",
                        "timestamp": "2026-07-02T14:01:00+00:00",
                        "payload": {"type": "task_started", "turn_id": "turn-1"},
                    },
                    {
                        "type": "response_item",
                        "timestamp": "2026-07-02T14:01:30+00:00",
                        "payload": {"type": "agent_message"},
                    },
                    {
                        "type": "event_msg",
                        "timestamp": "2026-07-02T14:01:31+00:00",
                        "payload": {"type": "task_complete", "turn_id": "turn-1"},
                    },
                ],
            )

            updates = CodexSessionSource(
                Path(temp_dir),
                now=lambda: datetime(2026, 7, 2, 14, 1, 35, tzinfo=timezone.utc),
            ).poll()

            self.assertEqual(len(updates), 1)
            self.assertEqual(updates[0].status, SessionStatus.NEEDS_ACTION)
            self.assertTrue(updates[0].view_ack_required)

    def test_codex_session_source_ignores_old_needs_action_before_startup_window(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            session_file = Path(temp_dir) / "rollout-2026-07-02T22-16-56-codex-history.jsonl"
            write_codex_jsonl(
                session_file,
                [
                    {
                        "type": "session_meta",
                        "timestamp": "2026-07-02T14:00:00+00:00",
                        "payload": {"id": "codex-history", "cwd": "/Users/Gao/Documents/20260703AIcoding"},
                    },
                    {
                        "type": "event_msg",
                        "timestamp": "2026-07-02T14:01:00+00:00",
                        "payload": {"type": "task_started", "turn_id": "turn-1"},
                    },
                    {
                        "type": "response_item",
                        "timestamp": "2026-07-02T14:01:30+00:00",
                        "payload": {"type": "agent_message"},
                    },
                    {
                        "type": "event_msg",
                        "timestamp": "2026-07-02T14:01:31+00:00",
                        "payload": {"type": "task_complete", "turn_id": "turn-1"},
                    },
                ],
            )

            updates = CodexSessionSource(
                Path(temp_dir),
                now=lambda: datetime(2026, 7, 2, 14, 30, tzinfo=timezone.utc),
                source_started_at=datetime(2026, 7, 2, 14, 30, tzinfo=timezone.utc),
            ).poll()

            self.assertEqual(updates, [])

    def test_codex_session_source_keeps_completed_reply_needs_action_past_stale_window(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            session_file = Path(temp_dir) / "rollout-2026-07-02T22-16-56-codex-replied-old.jsonl"
            write_codex_jsonl(
                session_file,
                [
                    {
                        "type": "session_meta",
                        "timestamp": "2026-07-02T14:00:00+00:00",
                        "payload": {"id": "codex-replied-old", "cwd": "/Users/Gao/Documents/20260703AIcoding"},
                    },
                    {
                        "type": "event_msg",
                        "timestamp": "2026-07-02T14:01:00+00:00",
                        "payload": {"type": "task_started", "turn_id": "turn-1"},
                    },
                    {
                        "type": "response_item",
                        "timestamp": "2026-07-02T14:01:30+00:00",
                        "payload": {"type": "agent_message"},
                    },
                    {
                        "type": "event_msg",
                        "timestamp": "2026-07-02T14:01:31+00:00",
                        "payload": {"type": "task_complete", "turn_id": "turn-1"},
                    },
                ],
            )

            updates = CodexSessionSource(
                Path(temp_dir),
                now=lambda: datetime(2026, 7, 2, 14, 30, tzinfo=timezone.utc),
                running_stale_seconds=600,
                source_started_at=datetime(2026, 7, 2, 14, 0, tzinfo=timezone.utc),
            ).poll()

            self.assertEqual(len(updates), 1)
            self.assertEqual(updates[0].status, SessionStatus.NEEDS_ACTION)
            self.assertTrue(updates[0].view_ack_required)

    def test_codex_session_source_keeps_approval_needs_action_past_stale_window(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            session_file = Path(temp_dir) / "rollout-2026-07-02T22-16-56-codex-approval-old.jsonl"
            write_codex_jsonl(
                session_file,
                [
                    {
                        "type": "session_meta",
                        "timestamp": "2026-07-02T14:00:00+00:00",
                        "payload": {"id": "codex-approval-old", "cwd": "/Users/Gao/Documents/20260703AIcoding"},
                    },
                    {
                        "type": "event_msg",
                        "timestamp": "2026-07-02T14:01:00+00:00",
                        "payload": {"type": "task_started", "turn_id": "turn-1"},
                    },
                    {
                        "type": "event_msg",
                        "timestamp": "2026-07-02T14:01:30+00:00",
                        "payload": {"type": "exec_approval_requested", "turn_id": "turn-1"},
                    },
                ],
            )

            updates = CodexSessionSource(
                Path(temp_dir),
                now=lambda: datetime(2026, 7, 2, 14, 30, tzinfo=timezone.utc),
                running_stale_seconds=600,
                source_started_at=datetime(2026, 7, 2, 14, 0, tzinfo=timezone.utc),
            ).poll()

            self.assertEqual(len(updates), 1)
            self.assertEqual(updates[0].status, SessionStatus.NEEDS_ACTION)
            self.assertFalse(updates[0].view_ack_required)

    def test_codex_session_source_ignores_subagent_sessions(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            session_file = Path(temp_dir) / "rollout-2026-07-02T22-41-33-codex-subagent.jsonl"
            write_codex_jsonl(
                session_file,
                [
                    {
                        "type": "session_meta",
                        "timestamp": "2026-07-02T14:41:33+00:00",
                        "payload": {
                            "id": "codex-subagent",
                            "cwd": "/Users/Gao/Documents/20260703AIcoding",
                            "source": {"subagent": {"other": "guardian"}},
                            "thread_source": "subagent",
                            "parent_thread_id": "codex-parent",
                        },
                    },
                    {
                        "type": "event_msg",
                        "timestamp": "2026-07-02T14:41:34+00:00",
                        "payload": {"type": "task_started", "turn_id": "turn-1"},
                    },
                ],
            )

            updates = CodexSessionSource(
                Path(temp_dir),
                now=lambda: datetime(2026, 7, 2, 14, 41, 35, tzinfo=timezone.utc),
            ).poll()

            self.assertEqual(updates, [])

    def test_classifies_direct_codex_process_as_running_basic_detection_session(self):
        rows = ["process_id=30001\tprocess_name=codex\tcommand=codex\tcwd=/Users/Gao/Documents/prd\tfocus_process_id=38434\tfocus_app_name=Codex"]

        updates = list(_classify_process_rows(rows))

        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0].session_id, "process-30001")
        self.assertEqual(updates[0].title, "Codex CLI - prd")
        self.assertEqual(updates[0].tool, ToolKind.CODEX)
        self.assertEqual(updates[0].status, SessionStatus.RUNNING)
        self.assertEqual(updates[0].focus_process_id, 38434)
        self.assertEqual(updates[0].focus_app_name, "Codex")

    def test_configured_desktop_ai_app_process_creates_idle_fallback_entry(self):
        rows = [
            "process_id=38434\tprocess_name=/Applications/Codex.app/Contents/MacOS/Codex\tcommand=/Applications/Codex.app/Contents/MacOS/Codex"
        ]

        updates = list(_classify_process_rows(rows))

        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0].session_id, "process-38434")
        self.assertEqual(updates[0].title, "Codex Desktop")
        self.assertEqual(updates[0].tool, ToolKind.CODEX)
        self.assertEqual(updates[0].surface.value, "desktop")
        self.assertEqual(updates[0].status, SessionStatus.IDLE)
        self.assertEqual(updates[0].focus_process_id, 38434)
        self.assertEqual(updates[0].focus_app_name, "Codex")
        self.assertEqual(updates[0].tool_display_name, "Codex")

    def test_configured_desktop_ai_app_uses_generic_tool_display_name(self):
        rows = [
            "process_id=40001\tprocess_name=/Applications/ChatGPT.app/Contents/MacOS/ChatGPT\tcommand=/Applications/ChatGPT.app/Contents/MacOS/ChatGPT"
        ]

        updates = list(_classify_process_rows(rows))

        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0].session_id, "process-40001")
        self.assertEqual(updates[0].title, "ChatGPT Desktop")
        self.assertEqual(updates[0].tool, ToolKind.UNKNOWN)
        self.assertEqual(updates[0].surface.value, "desktop")
        self.assertEqual(updates[0].status, SessionStatus.IDLE)
        self.assertEqual(updates[0].focus_app_name, "ChatGPT")
        self.assertEqual(updates[0].tool_display_name, "ChatGPT")

    def test_configured_cli_ai_tool_creates_generic_process_entry(self):
        rows = ["process_id=50001\tprocess_name=gemini\tcommand=gemini\tcwd=/Users/Gao/Documents/research\tcpu_percent=0.0\tstat=S+"]

        updates = list(_classify_process_rows(rows))

        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0].session_id, "process-50001")
        self.assertEqual(updates[0].title, "Gemini CLI - research")
        self.assertEqual(updates[0].tool, ToolKind.UNKNOWN)
        self.assertEqual(updates[0].surface.value, "terminal")
        self.assertEqual(updates[0].status, SessionStatus.IDLE)
        self.assertEqual(updates[0].tool_display_name, "Gemini")

    def test_process_without_cwd_falls_back_to_cli_title(self):
        rows = ["process_id=27876\tprocess_name=claude\tcommand=claude"]

        updates = list(_classify_process_rows(rows))

        self.assertEqual(updates[0].title, "Claude Code CLI")

    def test_posix_process_command_filters_before_cwd_lookup(self):
        script = _posix_process_command()[-1]

        self.assertLess(script.index('case "$exe:$first_arg_lc"'), script.index("lsof -a -p"))
        self.assertLess(script.index("active_child_count=0\\tfocus_process_id"), script.index("lsof -a -p"))
        self.assertIn('first_arg=${args%% *}', script)
        self.assertIn("claude:*", script)
        self.assertIn("codex:*", script)
        self.assertIn('basename -- "$comm"', script)
        self.assertIn("focus_process_id=%s", script)
        self.assertIn("focus_app_name=%s", script)
        self.assertIn("/codex.app/contents/macos/codex", script)
        self.assertIn("/claude.app/contents/macos/claude", script)
        self.assertIn("/Zed.app/", script)
        self.assertIn("/Cursor.app/", script)
        self.assertIn("Visual\\ Studio\\ Code*.app", script)
        self.assertIn("IntelliJ\\ IDEA*.app", script)
        self.assertIn("/PyCharm*.app/", script)
        self.assertIn("/Windsurf.app/", script)

    def test_posix_process_command_includes_configured_ai_tools(self):
        script = _posix_process_command()[-1]

        self.assertIn("gemini:*", script)
        self.assertIn("cursor-agent:*", script)
        self.assertIn("qwen-code:*", script)
        self.assertIn("opencode:*", script)
        self.assertIn("/chatgpt.app/contents/macos/chatgpt", script)
        self.assertIn("/perplexity.app/contents/macos/perplexity", script)

    def test_posix_process_command_skips_lsof_for_claude_cli(self):
        script = _posix_process_command()[-1]

        self.assertIn('case "$exe:$first_arg_lc" in claude:*|claude.exe:*) ;; *) cwd=$(lsof -a -p', script)

    def test_posix_process_command_samples_process_table_once_for_child_activity(self):
        script = _posix_process_command()[-1]

        self.assertIn("all_process_rows=$(ps -axo pid=,ppid=,pgid=,stat=,%cpu=,comm=,args=", script)
        self.assertIn('printf \'%s\\n\' "$all_process_rows" | while read -r pid ppid pgid stat cpu comm args', script)
        self.assertIn('printf \'%s\\n\' "$all_process_rows" | awk', script)

    def test_posix_process_command_uses_cached_rows_for_focus_ancestor_lookup(self):
        script = _posix_process_command()[-1]

        self.assertNotIn('ps -p "$ancestor"', script)
        self.assertIn('ancestor_row=$(printf \'%s\\n\' "$all_process_rows" | awk', script)

    def test_posix_process_command_skips_child_activity_count_for_claude_cli(self):
        script = _posix_process_command()[-1]

        self.assertIn('case "$exe:$first_arg_lc" in claude:*|claude.exe:*) active_children=0 ;; *) active_children=$(printf', script)

    def test_posix_process_command_ignores_background_mcp_helpers_for_activity(self):
        script = _posix_process_command()[-1]

        self.assertIn("background_ai_helper", script)
        self.assertIn("mcp", script)
        self.assertIn("tavily", script)
        self.assertIn("searxng", script)
        self.assertIn("next", script)

    def test_external_source_timeout_allows_macos_cwd_lookup_within_poll_budget(self):
        self.assertGreaterEqual(SOURCE_COMMAND_TIMEOUT_SECONDS, 3.0)
        self.assertLessEqual(SOURCE_COMMAND_TIMEOUT_SECONDS, 4.0)

    def test_ignores_codex_desktop_internal_processes(self):
        rows = [
            "process_id=48890\tprocess_name=codex\tcommand=/Applications/Codex.app/Contents/Resources/codex app-server --listen stdio://",
            "process_id=48887\tprocess_name=codex\tcommand=/Applications/Codex.app/Contents/Resources/codex sandbox -- /bin/node",
            "process_id=92217\tprocess_name=/Applications/Co\tcommand=/Applications/Codex.app/Contents/Frameworks/Codex Framework.framework/Versions/149.0.7827.197/Helpers/Codex (Service).app/Contents/MacOS/Codex (Service) --type=utility",
        ]

        self.assertEqual(list(_classify_process_rows(rows)), [])

    def test_ignores_invalid_json_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            Path(temp_dir, "bad.json").write_text("{bad")

            self.assertEqual(JsonSessionSource(Path(temp_dir)).poll(), [])

    def test_cleans_old_idle_files_before_polling(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            write_json_session(directory / "old.json", "idle", datetime.now(timezone.utc) - timedelta(days=8))
            write_json_session(directory / "action.json", "needs_action", datetime.now(timezone.utc) - timedelta(days=8))

            updates = JsonSessionSource(directory, cleanup_after_seconds=7 * 24 * 60 * 60).poll()

            self.assertFalse((directory / "old.json").exists())
            self.assertTrue((directory / "action.json").exists())
            self.assertEqual([update.session_id for update in updates], ["action"])


if __name__ == "__main__":
    unittest.main()
