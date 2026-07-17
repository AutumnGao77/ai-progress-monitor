import json
import sqlite3
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import time
from unittest import mock

from ai_progress_monitor.models import SessionStatus, SurfaceKind, ToolKind
from ai_progress_monitor.sources import (
    AiToolDefinition,
    ChatGPTSessionSource,
    SOURCE_COMMAND_TIMEOUT_SECONDS,
    JsonSessionSource,
    _classify_process_rows,
    _classify_window_rows,
    _is_generated_conversation_path,
    _posix_process_command,
    _run_command,
)
from ai_progress_monitor.store import SessionStore


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
    normalized_events = []
    for event in events:
        normalized = dict(event)
        payload = normalized.get("payload")
        if normalized.get("type") == "session_meta" and isinstance(payload, dict):
            normalized["payload"] = dict(payload)
            normalized["payload"].setdefault("originator", "Codex Desktop")
        normalized_events.append(normalized)
    path.write_text("\n".join(json.dumps(event) for event in normalized_events) + "\n", encoding="utf-8")


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
        class TimeoutProcess:
            pid = 12345
            returncode = None

            def communicate(self, timeout=None):
                if timeout is not None:
                    raise subprocess.TimeoutExpired(["ps"], timeout)
                return ("", "")

            def kill(self):
                return None

        timeout_process = TimeoutProcess()
        with mock.patch("ai_progress_monitor.sources.subprocess.Popen", return_value=timeout_process), mock.patch(
            "ai_progress_monitor.sources.os.killpg"
        ) as killpg:
            self.assertIsNone(_run_command(["ps"]))
            killpg.assert_called_once()

        class EmptySuccessProcess:
            returncode = 0

            def communicate(self, timeout=None):
                return ("", "")

        with mock.patch("ai_progress_monitor.sources.subprocess.Popen", return_value=EmptySuccessProcess()):
            self.assertEqual(_run_command(["ps"]), [])

    def test_posix_process_command_uses_portable_ps_columns(self):
        command = _posix_process_command()

        self.assertEqual(command[:2], ["sh", "-c"])
        self.assertNotIn("etimes=", command[-1])
        self.assertIn("ps -axo pid=,ppid=,pgid=,stat=,%cpu=,comm=,args=", command[-1])
        self.assertIn("Qoder.app/Contents/Resources/app/resources/bin", command[-1])
        self.assertIn("continue", command[-1])

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
                        "status_source": "codex-session",
                    }
                )
            )

            updates = JsonSessionSource(Path(temp_dir), cleanup_after_seconds=0).poll()

            self.assertEqual(updates[0].window_id, "win-42")
            self.assertEqual(updates[0].process_id, 1234)
            self.assertEqual(updates[0].process_name, "Codex")
            self.assertEqual(updates[0].focus_process_id, 75407)
            self.assertEqual(updates[0].focus_app_name, "Zed")
            self.assertEqual(updates[0].status_source, "codex-session")

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

    def test_ignores_exiting_or_zombie_cli_processes_even_with_attached_terminal(self):
        rows = [
            "process_id=27876\tprocess_name=codex\tcommand=codex\tcwd=/Users/Gao/Documents/checkout-flow\tcpu_percent=0.0\tstat=UEs+\tactive_child_count=0",
            "process_id=27877\tprocess_name=claude\tcommand=claude\tcwd=/Users/Gao/Documents/docs\tcpu_percent=0.0\tstat=Z+\tactive_child_count=0",
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

    def test_claude_process_without_scanned_cwd_uses_its_own_pid_session_cwd(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            Path(temp_dir, "27876.json").write_text(
                json.dumps(
                    {
                        "pid": 27876,
                        "cwd": "/Users/Gao/Documents/StudyCC",
                        "status": "idle",
                        "updatedAt": int(time() * 1000),
                    }
                )
            )
            rows = [
                "process_id=27876\tprocess_name=claude\tcommand=claude\tcwd=\tcpu_percent=0.0\tstat=S+\tactive_child_count=0"
            ]

            updates = list(_classify_process_rows(rows, claude_sessions_dir=Path(temp_dir)))

            self.assertEqual(len(updates), 1)
            self.assertEqual(updates[0].title, "Claude Code CLI - StudyCC")
            self.assertEqual(updates[0].cwd, "/Users/Gao/Documents/StudyCC")
            self.assertEqual(updates[0].status_source, "claude-session")

    def test_claude_session_from_different_cwd_cannot_override_live_process(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            Path(temp_dir, "27876.json").write_text(
                json.dumps(
                    {
                        "pid": 27876,
                        "cwd": "/Users/Gao/Documents/wrong-project",
                        "status": "waiting",
                        "updatedAt": int(time() * 1000),
                    }
                )
            )
            rows = [
                "process_id=27876\tprocess_name=claude\tcommand=claude\tcwd=/Users/Gao/Documents/StudyCC\tcpu_percent=0.0\tstat=S+\tactive_child_count=0"
            ]

            updates = list(_classify_process_rows(rows, claude_sessions_dir=Path(temp_dir)))

            self.assertEqual(len(updates), 1)
            self.assertEqual(updates[0].title, "Claude Code CLI - StudyCC")
            self.assertEqual(updates[0].cwd, "/Users/Gao/Documents/StudyCC")
            self.assertEqual(updates[0].status, SessionStatus.IDLE)
            self.assertEqual(updates[0].status_source, "process")

    def test_claude_prompt_session_file_is_idle_for_quiet_process(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            Path(temp_dir, "27876.json").write_text(
                json.dumps(
                    {
                        "pid": 27876,
                        "cwd": "/Users/Gao/Documents/projects/网点清场",
                        "status": "prompt",
                        "updatedAt": int(time() * 1000),
                    }
                )
            )
            rows = [
                "process_id=27876\tprocess_name=claude\tcommand=claude\tcwd=/Users/Gao/Documents/projects/网点清场\tcpu_percent=0.0\tstat=S+\tactive_child_count=0"
            ]

            updates = list(_classify_process_rows(rows, claude_sessions_dir=Path(temp_dir)))

            self.assertEqual(len(updates), 1)
            self.assertEqual(updates[0].status, SessionStatus.IDLE)
            self.assertEqual(updates[0].status_source, "claude-session-prompt")

    def test_claude_initial_idle_session_file_is_marked_as_initial_idle(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            started_at = int(time() * 1000)
            Path(temp_dir, "27876.json").write_text(
                json.dumps(
                    {
                        "pid": 27876,
                        "cwd": "/Users/Gao/Documents/projects/网点清场",
                        "status": "idle",
                        "startedAt": started_at,
                        "updatedAt": started_at + 57,
                        "statusUpdatedAt": started_at + 57,
                    }
                )
            )
            rows = [
                "process_id=27876\tprocess_name=claude\tcommand=claude\tcwd=/Users/Gao/Documents/projects/网点清场\tcpu_percent=0.0\tstat=S+\tactive_child_count=0"
            ]

            updates = list(_classify_process_rows(rows, claude_sessions_dir=Path(temp_dir)))

            self.assertEqual(len(updates), 1)
            self.assertEqual(updates[0].status, SessionStatus.IDLE)
            self.assertEqual(updates[0].status_source, "claude-session-initial-idle")

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

            updates = ChatGPTSessionSource(
                Path(temp_dir),
                now=lambda: datetime(2026, 7, 2, 14, 1, 5, tzinfo=timezone.utc),
            ).poll()

            self.assertEqual(len(updates), 1)
            self.assertEqual(updates[0].session_id, "chatgpt-session-codex-active")
            self.assertEqual(updates[0].title, "ChatGPT Desktop - 20260703AIcoding")
            self.assertEqual(updates[0].tool, ToolKind.CHATGPT)
            self.assertEqual(updates[0].status, SessionStatus.RUNNING)
            self.assertEqual(updates[0].surface.value, "desktop")
            self.assertEqual(updates[0].source, "chatgpt-session")
            self.assertEqual(updates[0].focus_app_name, "ChatGPT")
            self.assertEqual(updates[0].tool_display_name, "ChatGPT")
            self.assertEqual(updates[0].cwd, "/Users/Gao/Documents/20260703AIcoding")
            self.assertFalse(updates[0].generated_conversation_path)

    def test_chatgpt_session_source_accepts_future_chatgpt_desktop_originator(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            session_file = Path(temp_dir) / "rollout-chatgpt-desktop.jsonl"
            write_codex_jsonl(
                session_file,
                [
                    {
                        "type": "session_meta",
                        "timestamp": "2026-07-02T14:00:00+00:00",
                        "payload": {
                            "id": "chatgpt-desktop",
                            "cwd": "/Users/Gao/Documents/20260703AIcoding",
                            "originator": "ChatGPT Desktop",
                        },
                    },
                    {
                        "type": "event_msg",
                        "timestamp": "2026-07-02T14:01:00+00:00",
                        "payload": {"type": "task_started", "turn_id": "turn-1"},
                    },
                ],
            )

            updates = ChatGPTSessionSource(
                Path(temp_dir),
                now=lambda: datetime(2026, 7, 2, 14, 1, 5, tzinfo=timezone.utc),
            ).poll()

            self.assertEqual(len(updates), 1)
            self.assertEqual(updates[0].tool, ToolKind.CHATGPT)

    def test_chatgpt_session_source_keeps_multiple_sessions_in_same_folder(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            for session_id, minute in (("chatgpt-first", 1), ("chatgpt-second", 2)):
                write_codex_jsonl(
                    Path(temp_dir) / f"rollout-{session_id}.jsonl",
                    [
                        {
                            "type": "session_meta",
                            "timestamp": "2026-07-02T14:00:00+00:00",
                            "payload": {
                                "id": session_id,
                                "cwd": "/Users/Gao/Documents/20260703AIcoding",
                                "originator": "ChatGPT Desktop",
                            },
                        },
                        {
                            "type": "event_msg",
                            "timestamp": f"2026-07-02T14:0{minute}:00+00:00",
                            "payload": {"type": "task_started", "turn_id": "turn-1"},
                        },
                    ],
                )

            updates = ChatGPTSessionSource(
                Path(temp_dir),
                now=lambda: datetime(2026, 7, 2, 14, 2, 5, tzinfo=timezone.utc),
            ).poll()

            self.assertCountEqual(
                [update.session_id for update in updates],
                ["chatgpt-session-chatgpt-first", "chatgpt-session-chatgpt-second"],
            )
            self.assertTrue(all(update.tool == ToolKind.CHATGPT for update in updates))
            self.assertTrue(all(update.cwd == "/Users/Gao/Documents/20260703AIcoding" for update in updates))

    def test_chatgpt_session_source_ignores_codex_cli_originator(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            session_file = Path(temp_dir) / "rollout-codex-cli.jsonl"
            write_codex_jsonl(
                session_file,
                [
                    {
                        "type": "session_meta",
                        "timestamp": "2026-07-02T14:00:00+00:00",
                        "payload": {
                            "id": "codex-cli",
                            "cwd": "/Users/Gao/Documents/20260703AIcoding",
                            "originator": "codex_cli_rs",
                        },
                    },
                    {
                        "type": "event_msg",
                        "timestamp": "2026-07-02T14:01:00+00:00",
                        "payload": {"type": "task_started", "turn_id": "turn-1"},
                    },
                ],
            )

            updates = ChatGPTSessionSource(
                Path(temp_dir),
                now=lambda: datetime(2026, 7, 2, 14, 1, 5, tzinfo=timezone.utc),
            ).poll()

            self.assertEqual(updates, [])

    def test_chatgpt_session_source_ignores_unidentified_session_originator(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            session_file = Path(temp_dir) / "rollout-unknown-originator.jsonl"
            write_codex_jsonl(
                session_file,
                [
                    {
                        "type": "session_meta",
                        "timestamp": "2026-07-02T14:00:00+00:00",
                        "payload": {
                            "id": "unknown-originator",
                            "cwd": "/Users/Gao/Documents/20260703AIcoding",
                            "originator": None,
                        },
                    },
                    {
                        "type": "event_msg",
                        "timestamp": "2026-07-02T14:01:00+00:00",
                        "payload": {"type": "task_started", "turn_id": "turn-1"},
                    },
                ],
            )

            updates = ChatGPTSessionSource(
                Path(temp_dir),
                now=lambda: datetime(2026, 7, 2, 14, 1, 5, tzinfo=timezone.utc),
            ).poll()

            self.assertEqual(updates, [])

    def test_chatgpt_session_source_skips_file_removed_during_directory_scan(self):
        class RemovedSessionPath:
            def stat(self):
                raise FileNotFoundError("session rotated")

        class SessionDirectory:
            def exists(self):
                return True

            def glob(self, _pattern):
                return [RemovedSessionPath()]

        updates = ChatGPTSessionSource(SessionDirectory()).poll()

        self.assertEqual(updates, [])

    def test_codex_session_source_marks_plan_user_input_function_call_as_needs_action(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            session_file = Path(temp_dir) / "rollout-2026-07-02T22-16-56-codex-plan-input.jsonl"
            write_codex_jsonl(
                session_file,
                [
                    {
                        "type": "session_meta",
                        "timestamp": "2026-07-02T14:00:00+00:00",
                        "payload": {"id": "codex-plan-input", "cwd": "/Users/Gao/Documents/20260703AIcoding"},
                    },
                    {
                        "type": "event_msg",
                        "timestamp": "2026-07-02T14:01:00+00:00",
                        "payload": {"type": "task_started", "turn_id": "turn-1"},
                    },
                    {
                        "type": "response_item",
                        "timestamp": "2026-07-02T14:01:30+00:00",
                        "payload": {
                            "type": "function_call",
                            "call_id": "call-user-input",
                            "name": "request_user_input",
                        },
                    },
                ],
            )

            updates = ChatGPTSessionSource(
                Path(temp_dir),
                now=lambda: datetime(2026, 7, 2, 14, 1, 35, tzinfo=timezone.utc),
            ).poll()

            self.assertEqual(len(updates), 1)
            self.assertEqual(updates[0].status, SessionStatus.NEEDS_ACTION)
            self.assertFalse(updates[0].view_ack_required)

    def test_codex_session_source_clears_plan_user_input_after_function_call_output(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            session_file = Path(temp_dir) / "rollout-2026-07-02T22-16-56-codex-plan-answered.jsonl"
            write_codex_jsonl(
                session_file,
                [
                    {
                        "type": "session_meta",
                        "timestamp": "2026-07-02T14:00:00+00:00",
                        "payload": {"id": "codex-plan-answered", "cwd": "/Users/Gao/Documents/20260703AIcoding"},
                    },
                    {
                        "type": "event_msg",
                        "timestamp": "2026-07-02T14:01:00+00:00",
                        "payload": {"type": "task_started", "turn_id": "turn-1"},
                    },
                    {
                        "type": "response_item",
                        "timestamp": "2026-07-02T14:01:30+00:00",
                        "payload": {
                            "type": "function_call",
                            "call_id": "call-user-input",
                            "name": "request_user_input",
                        },
                    },
                    {
                        "type": "response_item",
                        "timestamp": "2026-07-02T14:01:45+00:00",
                        "payload": {"type": "function_call_output", "call_id": "call-user-input"},
                    },
                ],
            )

            updates = ChatGPTSessionSource(
                Path(temp_dir),
                now=lambda: datetime(2026, 7, 2, 14, 1, 50, tzinfo=timezone.utc),
            ).poll()

            self.assertEqual(len(updates), 1)
            self.assertEqual(updates[0].status, SessionStatus.RUNNING)

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

            updates = ChatGPTSessionSource(
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

            updates = ChatGPTSessionSource(
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

            updates = ChatGPTSessionSource(
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

            updates = ChatGPTSessionSource(
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

            updates = ChatGPTSessionSource(
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

            updates = ChatGPTSessionSource(
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

            updates = ChatGPTSessionSource(
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

    def test_retired_codex_desktop_app_is_not_treated_as_active_product(self):
        rows = [
            "process_id=38434\tprocess_name=/Applications/Codex.app/Contents/MacOS/Codex\tcommand=/Applications/Codex.app/Contents/MacOS/Codex"
        ]

        updates = list(_classify_process_rows(rows))

        self.assertEqual(updates, [])

    def test_configured_desktop_ai_app_uses_generic_tool_display_name(self):
        rows = [
            "process_id=40001\tprocess_name=/Applications/ChatGPT.app/Contents/MacOS/ChatGPT\tcommand=/Applications/ChatGPT.app/Contents/MacOS/ChatGPT"
        ]

        updates = list(_classify_process_rows(rows))

        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0].session_id, "process-40001")
        self.assertEqual(updates[0].title, "ChatGPT Desktop")
        self.assertEqual(updates[0].tool, ToolKind.CHATGPT)
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

    def test_new_configured_ai_tools_create_generic_process_entries(self):
        cases = (
            (
                "process_id=51001\tprocess_name=workbuddy\tcommand=workbuddy\tcwd=/Users/Gao/Documents/product-ops\tcpu_percent=0.0\tstat=S+",
                "process-51001",
                "WorkBuddy CLI - product-ops",
                "WorkBuddy",
                SurfaceKind.TERMINAL,
                None,
                None,
            ),
            (
                "process_id=51006\tprocess_name=codebuddy\tcommand=codebuddy\tcwd=/Users/Gao/Documents/product-ops\tcpu_percent=0.0\tstat=S+",
                "process-51006",
                "WorkBuddy CLI - product-ops",
                "WorkBuddy",
                SurfaceKind.TERMINAL,
                None,
                None,
            ),
            (
                "process_id=51002\tprocess_name=qoder\tcommand=qoder\tcwd=/Users/Gao/Documents/coding\tcpu_percent=0.0\tstat=S+",
                "process-51002",
                "Qoder CLI - coding",
                "Qoder",
                SurfaceKind.TERMINAL,
                None,
                None,
            ),
            (
                "process_id=51003\tprocess_name=/Applications/WorkBuddy.app/Contents/MacOS/WorkBuddy\tcommand=/Applications/WorkBuddy.app/Contents/MacOS/WorkBuddy",
                "process-51003",
                "WorkBuddy Desktop",
                "WorkBuddy",
                SurfaceKind.DESKTOP,
                51003,
                "WorkBuddy",
            ),
            (
                "process_id=51007\tprocess_name=/Applications/WorkBuddy.app/Contents/MacOS/Electron\tcommand=/Applications/WorkBuddy.app/Contents/MacOS/Electron --app-path=/Applications/WorkBuddy.app/Contents/Resources/app.asar",
                "process-51007",
                "WorkBuddy Desktop",
                "WorkBuddy",
                SurfaceKind.DESKTOP,
                51007,
                "WorkBuddy",
            ),
            (
                "process_id=51009\tprocess_name=/Applications/Wo\tcommand=/Applications/WorkBuddy.app/Contents/MacOS/Electron",
                "process-51009",
                "WorkBuddy Desktop",
                "WorkBuddy",
                SurfaceKind.DESKTOP,
                51009,
                "WorkBuddy",
            ),
            (
                "process_id=51004\tprocess_name=/Applications/Qoder.app/Contents/MacOS/Qoder\tcommand=/Applications/Qoder.app/Contents/MacOS/Qoder",
                "process-51004",
                "Qoder Desktop",
                "Qoder",
                SurfaceKind.DESKTOP,
                51004,
                "Qoder",
            ),
            (
                "process_id=51008\tprocess_name=/Applications/Qoder.app/Contents/MacOS/Electron\tcommand=/Applications/Qoder.app/Contents/MacOS/Electron --app-path=/Applications/Qoder.app/Contents/Resources/app.asar",
                "process-51008",
                "Qoder Desktop",
                "Qoder",
                SurfaceKind.DESKTOP,
                51008,
                "Qoder",
            ),
            (
                "process_id=51005\tprocess_name=/Applications/Qo\tcommand=/Applications/Qoder CN.app/Contents/MacOS/Electron --aicoding-open-agents-window",
                "process-51005",
                "Qoder CN Desktop",
                "Qoder CN",
                SurfaceKind.DESKTOP,
                51005,
                "Qoder CN",
            ),
        )

        for row, expected_session_id, expected_title, expected_display_name, expected_surface, expected_focus_pid, expected_focus_app in cases:
            with self.subTest(expected_display_name=expected_display_name, expected_title=expected_title):
                updates = list(_classify_process_rows([row], workbuddy_db_paths=()))

                self.assertEqual(len(updates), 1)
                self.assertEqual(updates[0].session_id, expected_session_id)
                self.assertEqual(updates[0].title, expected_title)
                self.assertEqual(updates[0].tool, ToolKind.UNKNOWN)
                self.assertEqual(updates[0].surface, expected_surface)
                self.assertEqual(updates[0].status, SessionStatus.IDLE)
                self.assertEqual(updates[0].tool_display_name, expected_display_name)
                self.assertEqual(updates[0].focus_process_id, expected_focus_pid)
                self.assertEqual(updates[0].focus_app_name, expected_focus_app)

    def test_qoder_desktop_idle_fallback_ignores_bundled_helper_process(self):
        rows = [
            "process_id=61028\tprocess_name=/Applications/Qo\tcommand=/Applications/Qoder.app/Contents/Resources/app/resources/bin/aarch64_darwin/Qoder start --workDir /Users/Gao/Library/Application Support/Qoder/SharedClientCache\tcpu_percent=0.0\tstat=S",
            "process_id=60489\tprocess_name=/Applications/Qo\tcommand=/Applications/Qoder.app/Contents/MacOS/Electron\tcpu_percent=0.0\tstat=S",
        ]

        updates = list(_classify_process_rows(rows, qoder_logs_dirs=(), workbuddy_db_paths=()))

        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0].session_id, "process-60489")
        self.assertEqual(updates[0].title, "Qoder Desktop")
        self.assertEqual(updates[0].status, SessionStatus.IDLE)
        self.assertEqual(updates[0].tool_display_name, "Qoder")
        self.assertEqual(updates[0].focus_process_id, 60489)
        self.assertEqual(updates[0].focus_app_name, "Qoder")

    def test_shell_process_mentioning_configured_desktop_app_is_not_classified_as_app(self):
        rows = [
            "process_id=51006\tprocess_name=sh\tcommand=sh -c echo /Applications/Qoder CN.app/Contents/MacOS/Electron\tcpu_percent=0.0\tstat=S+"
        ]

        updates = list(_classify_process_rows(rows))

        self.assertEqual(updates, [])

    def test_workbuddy_desktop_scan_ignores_electron_service_processes(self):
        rows = [
            "process_id=52001\tprocess_name=/Applications/WorkBuddy.app/Contents/MacOS/Electron\tcommand=/Applications/WorkBuddy.app/Contents/MacOS/Electron /Applications/WorkBuddy.app/Contents/Resources/app.asar/main/daemon-app-server-entry.js --stdio\tcpu_percent=0.0\tstat=S",
            "process_id=52002\tprocess_name=/Applications/WorkBuddy.app/Contents/MacOS/Electron\tcommand=/Applications/WorkBuddy.app/Contents/MacOS/Electron /Applications/WorkBuddy.app/Contents/Resources/app.asar/main/sidecar-entry.js --token abc\tcpu_percent=0.0\tstat=S",
            "process_id=52003\tprocess_name=/Applications/WorkBuddy.app/Contents/MacOS/Electron\tcommand=/Applications/WorkBuddy.app/Contents/MacOS/Electron /Applications/WorkBuddy.app/Contents/Resources/app.asar/cli/bin/codebuddy --serve --port 52788\tcpu_percent=0.0\tstat=S",
        ]

        updates = list(_classify_process_rows(rows, workbuddy_db_paths=()))

        self.assertEqual(updates, [])

    def test_workbuddy_db_sessions_create_full_desktop_conversation_entries(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "workbuddy.db"
            self._write_workbuddy_session_db(
                db_path,
                [
                    {
                        "id": "wb-done",
                        "cwd": "/Users/Gao/Documents/product-ops",
                        "title": "需求复盘",
                        "status": "Completed",
                        "updated_at": 1783919968000,
                        "last_activity_at": 1783919968000,
                    },
                    {
                        "id": "wb-running",
                        "cwd": "/Users/Gao/Documents/research",
                        "title": "竞品扫描",
                        "status": "Running",
                        "updated_at": 1783919970000,
                        "last_activity_at": 1783919970000,
                    },
                ],
            )
            rows = [
                "process_id=51007\tprocess_name=/Applications/WorkBuddy.app/Contents/MacOS/Electron\tcommand=/Applications/WorkBuddy.app/Contents/MacOS/Electron --app-path=/Applications/WorkBuddy.app/Contents/Resources/app.asar"
            ]

            updates = list(
                _classify_process_rows(
                    rows,
                    workbuddy_db_paths=(db_path,),
                    now=datetime(2026, 7, 13, 5, 19, 35, tzinfo=timezone.utc),
                    source_started_at=datetime(2026, 7, 13, 5, 19, 20, tzinfo=timezone.utc),
                )
            )

            self.assertEqual([update.session_id for update in updates], ["workbuddy-wb-done", "workbuddy-wb-running"])
            self.assertEqual([update.status for update in updates], [SessionStatus.NEEDS_ACTION, SessionStatus.RUNNING])
            self.assertEqual(updates[0].title, "WorkBuddy Desktop - product-ops - 需求复盘")
            self.assertTrue(updates[0].view_ack_required)
            self.assertEqual(updates[0].status_source, "workbuddy-db")
            self.assertEqual(updates[0].source, "process")
            self.assertEqual(updates[0].focus_process_id, 51007)
            self.assertEqual(updates[0].focus_app_name, "WorkBuddy")
            self.assertEqual(updates[0].tool_display_name, "WorkBuddy")
            self.assertEqual(updates[1].title, "WorkBuddy Desktop - research - 竞品扫描")
            self.assertEqual(updates[1].cwd, "/Users/Gao/Documents/research")

    def test_workbuddy_db_ignores_history_and_ambiguous_pending_sessions(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "workbuddy.db"
            self._write_workbuddy_session_db(
                db_path,
                [
                    {
                        "id": "wb-old-done",
                        "cwd": "/Users/Gao/Documents/history",
                        "title": "历史完成",
                        "status": "Completed",
                        "updated_at": 1783919900000,
                        "last_activity_at": 1783919900000,
                    },
                    {
                        "id": "wb-blank",
                        "cwd": "/Users/Gao/Documents/blank",
                        "title": "新会话",
                        "status": "Pending",
                        "updated_at": 1783919970000,
                        "last_activity_at": None,
                    },
                ],
            )
            rows = [
                "process_id=51007\tprocess_name=/Applications/WorkBuddy.app/Contents/MacOS/Electron\tcommand=/Applications/WorkBuddy.app/Contents/MacOS/Electron --app-path=/Applications/WorkBuddy.app/Contents/Resources/app.asar"
            ]

            updates = list(
                _classify_process_rows(
                    rows,
                    workbuddy_db_paths=(db_path,),
                    now=datetime(2026, 7, 13, 5, 19, 35, tzinfo=timezone.utc),
                    source_started_at=datetime(2026, 7, 13, 5, 19, 20, tzinfo=timezone.utc),
                )
            )

            self.assertEqual(len(updates), 1)
            self.assertEqual(updates[0].session_id, "process-51007")
            self.assertEqual(updates[0].title, "WorkBuddy Desktop")
            self.assertEqual(updates[0].status, SessionStatus.IDLE)
            self.assertEqual(updates[0].status_source, "desktop-process")

    def test_workbuddy_db_ignores_completed_session_touched_without_new_activity(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "workbuddy.db"
            self._write_workbuddy_session_db(
                db_path,
                [
                    {
                        "id": "wb-touched-history",
                        "cwd": "/Users/Gao/Documents/history",
                        "title": "点开的历史会话",
                        "status": "Completed",
                        "updated_at": 1783920030000,
                        "last_activity_at": 1783919900000,
                    },
                ],
            )
            rows = [
                "process_id=51007\tprocess_name=/Applications/WorkBuddy.app/Contents/MacOS/Electron\tcommand=/Applications/WorkBuddy.app/Contents/MacOS/Electron --app-path=/Applications/WorkBuddy.app/Contents/Resources/app.asar"
            ]

            updates = list(
                _classify_process_rows(
                    rows,
                    workbuddy_db_paths=(db_path,),
                    now=datetime(2026, 7, 13, 5, 20, 40, tzinfo=timezone.utc),
                    source_started_at=datetime(2026, 7, 13, 5, 19, 20, tzinfo=timezone.utc),
                )
            )

            self.assertEqual(len(updates), 1)
            self.assertEqual(updates[0].session_id, "process-51007")
            self.assertEqual(updates[0].title, "WorkBuddy Desktop")
            self.assertEqual(updates[0].status, SessionStatus.IDLE)
            self.assertEqual(updates[0].status_source, "desktop-process")

    def test_workbuddy_db_marks_active_pending_session_as_needs_action(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "workbuddy.db"
            self._write_workbuddy_session_db(
                db_path,
                [
                    {
                        "id": "wb-pending",
                        "cwd": "/Users/Gao/Documents/product",
                        "title": "Start new chat session",
                        "status": "pending",
                        "updated_at": 1783920000000,
                        "last_activity_at": 1783920000000,
                    },
                ],
            )
            rows = [
                "process_id=51007\tprocess_name=/Applications/WorkBuddy.app/Contents/MacOS/Electron\tcommand=/Applications/WorkBuddy.app/Contents/MacOS/Electron --app-path=/Applications/WorkBuddy.app/Contents/Resources/app.asar"
            ]

            updates = list(
                _classify_process_rows(
                    rows,
                    workbuddy_db_paths=(db_path,),
                    now=datetime(2026, 7, 13, 5, 20, 5, tzinfo=timezone.utc),
                    source_started_at=datetime(2026, 7, 13, 5, 19, 55, tzinfo=timezone.utc),
                )
            )

            self.assertEqual(len(updates), 1)
            self.assertEqual(updates[0].session_id, "workbuddy-wb-pending")
            self.assertEqual(updates[0].title, "WorkBuddy Desktop - product - Start new chat session")
            self.assertEqual(updates[0].status, SessionStatus.NEEDS_ACTION)
            self.assertFalse(updates[0].view_ack_required)
            self.assertEqual(updates[0].status_source, "workbuddy-db")

    def test_workbuddy_db_pending_user_attention_before_monitor_start_still_needs_action(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "workbuddy.db"
            self._write_workbuddy_session_db(
                db_path,
                [
                    {
                        "id": "wb-pending-before-start",
                        "cwd": "/Users/Gao/Documents/product",
                        "title": "Start new chat session",
                        "status": "pending",
                        "updated_at": 1783920000000,
                        "last_activity_at": 1783920000000,
                    },
                ],
            )
            rows = [
                "process_id=51007\tprocess_name=/Applications/WorkBuddy.app/Contents/MacOS/Electron\tcommand=/Applications/WorkBuddy.app/Contents/MacOS/Electron --app-path=/Applications/WorkBuddy.app/Contents/Resources/app.asar"
            ]

            updates = list(
                _classify_process_rows(
                    rows,
                    workbuddy_db_paths=(db_path,),
                    now=datetime(2026, 7, 13, 5, 22, 0, tzinfo=timezone.utc),
                    source_started_at=datetime(2026, 7, 13, 5, 21, 0, tzinfo=timezone.utc),
                )
            )

            self.assertEqual(len(updates), 1)
            self.assertEqual(updates[0].session_id, "workbuddy-wb-pending-before-start")
            self.assertEqual(updates[0].status, SessionStatus.NEEDS_ACTION)
            self.assertFalse(updates[0].view_ack_required)
            self.assertEqual(updates[0].status_source, "workbuddy-db")

    def test_workbuddy_db_user_attention_status_variants_are_needs_action(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "workbuddy.db"
            statuses = [
                "WaitingForInput",
                "RequiresApproval",
                "ApprovalRequired",
                "InputRequired",
                "Suspended",
            ]
            self._write_workbuddy_session_db(
                db_path,
                [
                    {
                        "id": f"wb-attention-{index}",
                        "cwd": f"/Users/Gao/Documents/product-{index}",
                        "title": f"待处理会话 {index}",
                        "status": status,
                        "updated_at": 1783920000000 + index,
                        "last_activity_at": 1783920000000 + index,
                    }
                    for index, status in enumerate(statuses, start=1)
                ],
            )
            rows = [
                "process_id=51007\tprocess_name=/Applications/WorkBuddy.app/Contents/MacOS/Electron\tcommand=/Applications/WorkBuddy.app/Contents/MacOS/Electron --app-path=/Applications/WorkBuddy.app/Contents/Resources/app.asar"
            ]

            updates = list(
                _classify_process_rows(
                    rows,
                    workbuddy_db_paths=(db_path,),
                    now=datetime(2026, 7, 13, 5, 20, 5, tzinfo=timezone.utc),
                    source_started_at=datetime(2026, 7, 13, 5, 19, 55, tzinfo=timezone.utc),
                )
            )

            self.assertEqual(len(updates), len(statuses))
            self.assertEqual({update.status for update in updates}, {SessionStatus.NEEDS_ACTION})
            self.assertTrue(all(not update.view_ack_required for update in updates))
            self.assertEqual({update.status_source for update in updates}, {"workbuddy-db"})

    def test_workbuddy_db_paused_session_is_idle_fallback(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "workbuddy.db"
            self._write_workbuddy_session_db(
                db_path,
                [
                    {
                        "id": "wb-paused",
                        "cwd": "/Users/Gao/Documents/product",
                        "title": "用户暂停的会话",
                        "status": "Paused",
                        "updated_at": 1783920000000,
                        "last_activity_at": 1783920000000,
                    },
                ],
            )
            rows = [
                "process_id=51007\tprocess_name=/Applications/WorkBuddy.app/Contents/MacOS/Electron\tcommand=/Applications/WorkBuddy.app/Contents/MacOS/Electron --app-path=/Applications/WorkBuddy.app/Contents/Resources/app.asar"
            ]

            updates = list(
                _classify_process_rows(
                    rows,
                    workbuddy_db_paths=(db_path,),
                    now=datetime(2026, 7, 13, 5, 20, 5, tzinfo=timezone.utc),
                    source_started_at=datetime(2026, 7, 13, 5, 19, 55, tzinfo=timezone.utc),
                )
            )

            self.assertEqual(len(updates), 1)
            self.assertEqual(updates[0].session_id, "process-51007")
            self.assertEqual(updates[0].title, "WorkBuddy Desktop")
            self.assertEqual(updates[0].status, SessionStatus.IDLE)
            self.assertEqual(updates[0].status_source, "desktop-process")

    def test_workbuddy_db_prompt_status_is_idle_fallback(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "workbuddy.db"
            self._write_workbuddy_session_db(
                db_path,
                [
                    {
                        "id": "wb-prompt",
                        "cwd": "/Users/Gao/Documents/product",
                        "title": "等待输入提示符",
                        "status": "Prompt",
                        "updated_at": 1783920000000,
                        "last_activity_at": 1783920000000,
                    },
                ],
            )
            rows = [
                "process_id=51007\tprocess_name=/Applications/WorkBuddy.app/Contents/MacOS/Electron\tcommand=/Applications/WorkBuddy.app/Contents/MacOS/Electron --app-path=/Applications/WorkBuddy.app/Contents/Resources/app.asar"
            ]

            updates = list(
                _classify_process_rows(
                    rows,
                    workbuddy_db_paths=(db_path,),
                    now=datetime(2026, 7, 13, 5, 20, 5, tzinfo=timezone.utc),
                    source_started_at=datetime(2026, 7, 13, 5, 19, 55, tzinfo=timezone.utc),
                )
            )

            self.assertEqual(len(updates), 1)
            self.assertEqual(updates[0].session_id, "process-51007")
            self.assertEqual(updates[0].title, "WorkBuddy Desktop")
            self.assertEqual(updates[0].status, SessionStatus.IDLE)
            self.assertEqual(updates[0].status_source, "desktop-process")

    def test_workbuddy_db_completed_with_incomplete_final_assistant_is_idle_fallback(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "workbuddy.db"
            session_id = "wb-stopped"
            cwd = "/Users/Gao/WorkBuddy/stop-generation"
            self._write_workbuddy_session_db(
                db_path,
                [
                    {
                        "id": session_id,
                        "cwd": cwd,
                        "title": "用户停止生成的会话",
                        "status": "Completed",
                        "updated_at": 1783920000000,
                        "last_activity_at": 1783920000000,
                    },
                ],
            )
            project_dir = Path(temp_dir) / "projects" / "Users-Gao-WorkBuddy-stop-generation"
            project_dir.mkdir(parents=True)
            (project_dir / f"{session_id}.jsonl").write_text(
                "\n".join(
                    [
                        json.dumps({"timestamp": 1783919999000, "type": "message", "role": "assistant", "status": "completed"}),
                        json.dumps({"timestamp": 1783920000000, "type": "message", "role": "assistant", "status": "incomplete"}),
                    ]
                ),
                encoding="utf-8",
            )
            rows = [
                "process_id=51007\tprocess_name=/Applications/WorkBuddy.app/Contents/MacOS/Electron\tcommand=/Applications/WorkBuddy.app/Contents/MacOS/Electron --app-path=/Applications/WorkBuddy.app/Contents/Resources/app.asar"
            ]

            updates = list(
                _classify_process_rows(
                    rows,
                    workbuddy_db_paths=(db_path,),
                    now=datetime(2026, 7, 13, 5, 20, 5, tzinfo=timezone.utc),
                    source_started_at=datetime(2026, 7, 13, 5, 19, 55, tzinfo=timezone.utc),
                )
            )

            self.assertEqual(len(updates), 1)
            self.assertEqual(updates[0].session_id, "process-51007")
            self.assertEqual(updates[0].title, "WorkBuddy Desktop")
            self.assertEqual(updates[0].status, SessionStatus.IDLE)
            self.assertEqual(updates[0].status_source, "desktop-process")

    def test_workbuddy_db_running_status_uses_newer_updated_at_when_activity_is_stale(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "workbuddy.db"
            self._write_workbuddy_session_db(
                db_path,
                [
                    {
                        "id": "wb-working",
                        "cwd": "/Users/Gao/Documents/product",
                        "title": "开发一个五子棋游戏",
                        "status": "working",
                        "updated_at": 1783920120000,
                        "last_activity_at": 1783918800000,
                    },
                ],
            )
            rows = [
                "process_id=51007\tprocess_name=/Applications/WorkBuddy.app/Contents/MacOS/Electron\tcommand=/Applications/WorkBuddy.app/Contents/MacOS/Electron --app-path=/Applications/WorkBuddy.app/Contents/Resources/app.asar"
            ]

            updates = list(
                _classify_process_rows(
                    rows,
                    workbuddy_db_paths=(db_path,),
                    now=datetime(2026, 7, 13, 5, 22, 5, tzinfo=timezone.utc),
                    source_started_at=datetime(2026, 7, 13, 5, 21, 0, tzinfo=timezone.utc),
                )
            )

            self.assertEqual(len(updates), 1)
            self.assertEqual(updates[0].session_id, "workbuddy-wb-working")
            self.assertEqual(updates[0].status, SessionStatus.RUNNING)
            self.assertEqual(updates[0].status_source, "workbuddy-db")
            self.assertEqual(updates[0].updated_at, datetime(2026, 7, 13, 5, 22, tzinfo=timezone.utc))

    def test_workbuddy_db_planning_status_is_running_not_idle_fallback(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "workbuddy.db"
            self._write_workbuddy_session_db(
                db_path,
                [
                    {
                        "id": "wb-planning",
                        "cwd": "/Users/Gao/Documents/product",
                        "title": "规划任务",
                        "status": "planning",
                        "updated_at": 1783920120000,
                        "last_activity_at": 1783918800000,
                    },
                ],
            )
            rows = [
                "process_id=51007\tprocess_name=/Applications/WorkBuddy.app/Contents/MacOS/Electron\tcommand=/Applications/WorkBuddy.app/Contents/MacOS/Electron --app-path=/Applications/WorkBuddy.app/Contents/Resources/app.asar"
            ]

            updates = list(
                _classify_process_rows(
                    rows,
                    workbuddy_db_paths=(db_path,),
                    now=datetime(2026, 7, 13, 5, 22, 5, tzinfo=timezone.utc),
                    source_started_at=datetime(2026, 7, 13, 5, 21, 0, tzinfo=timezone.utc),
                )
            )

            self.assertEqual(len(updates), 1)
            self.assertEqual(updates[0].session_id, "workbuddy-wb-planning")
            self.assertEqual(updates[0].status, SessionStatus.RUNNING)
            self.assertEqual(updates[0].status_source, "workbuddy-db")

    def test_workbuddy_runtime_log_running_overrides_completed_db_status_with_clock_skew(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "workbuddy.db"
            db_updated_at = datetime(2026, 7, 15, 13, 48, 24, 388000).astimezone(timezone.utc)
            self._write_workbuddy_session_db(
                db_path,
                [
                    {
                        "id": "wb-live",
                        "cwd": "/Users/Gao/WorkBuddy/2026-07-15-13-12-11",
                        "title": "问候并询问今日状况",
                        "status": "Completed",
                        "updated_at": int(db_updated_at.timestamp() * 1000),
                        "last_activity_at": int(db_updated_at.timestamp() * 1000),
                    },
                ],
            )
            log_path = Path(temp_dir) / "logs" / "2026-07-15" / "workspace.log"
            log_path.parent.mkdir(parents=True)
            log_path.write_text(
                "[7/15/2026, 1:48:24 PM.368] [Info] [SessionRunStateMachine] transition | "
                "sessionId=wb-live | event=MODEL_RESPONSE_DONE | from=model_streaming | "
                "to=model_done | lifecycle=running | busy=true | queueBusy=true\n",
                encoding="utf-8",
            )
            rows = [
                "process_id=51007\tprocess_name=/Applications/WorkBuddy.app/Contents/MacOS/Electron\tcommand=/Applications/WorkBuddy.app/Contents/MacOS/Electron --app-path=/Applications/WorkBuddy.app/Contents/Resources/app.asar"
            ]

            updates = list(
                _classify_process_rows(
                    rows,
                    workbuddy_db_paths=(db_path,),
                    now=db_updated_at + timedelta(seconds=1),
                    source_started_at=db_updated_at - timedelta(seconds=5),
                )
            )

            self.assertEqual(len(updates), 1)
            self.assertEqual(updates[0].session_id, "workbuddy-wb-live")
            self.assertEqual(updates[0].title, "WorkBuddy Desktop - 2026-07-15-13-12-11 - 问候并询问今日状况")
            self.assertEqual(updates[0].status, SessionStatus.RUNNING)
            self.assertEqual(updates[0].status_source, "workbuddy-log")

    def test_workbuddy_runtime_log_latest_idle_keeps_completed_result_needs_action(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "workbuddy.db"
            db_updated_at = datetime(2026, 7, 15, 13, 48, 24, 388000).astimezone(timezone.utc)
            self._write_workbuddy_session_db(
                db_path,
                [
                    {
                        "id": "wb-finished",
                        "cwd": "/Users/Gao/WorkBuddy/2026-07-15-13-12-11",
                        "title": "问候并询问今日状况",
                        "status": "Completed",
                        "updated_at": int(db_updated_at.timestamp() * 1000),
                        "last_activity_at": int(db_updated_at.timestamp() * 1000),
                    },
                ],
            )
            log_path = Path(temp_dir) / "logs" / "2026-07-15" / "workspace.log"
            log_path.parent.mkdir(parents=True)
            log_path.write_text(
                "[7/15/2026, 1:48:24 PM.368] [Info] [SessionRunStateMachine] transition | "
                "sessionId=wb-finished | event=MODEL_RESPONSE_DONE | from=model_streaming | "
                "to=model_done | lifecycle=running | busy=true | queueBusy=true\n"
                "[7/15/2026, 1:48:24 PM.370] [Info] [SessionRunStateMachine] transition | "
                "sessionId=wb-finished | event=AGENT_ENDED | from=model_done | "
                "to=idle | lifecycle=idle | busy=false | queueBusy=false\n",
                encoding="utf-8",
            )
            rows = [
                "process_id=51007\tprocess_name=/Applications/WorkBuddy.app/Contents/MacOS/Electron\tcommand=/Applications/WorkBuddy.app/Contents/MacOS/Electron --app-path=/Applications/WorkBuddy.app/Contents/Resources/app.asar"
            ]

            updates = list(
                _classify_process_rows(
                    rows,
                    workbuddy_db_paths=(db_path,),
                    now=db_updated_at + timedelta(seconds=1),
                    source_started_at=db_updated_at - timedelta(seconds=5),
                )
            )

            self.assertEqual(len(updates), 1)
            self.assertEqual(updates[0].session_id, "workbuddy-wb-finished")
            self.assertEqual(updates[0].title, "WorkBuddy Desktop - 2026-07-15-13-12-11 - 问候并询问今日状况")
            self.assertEqual(updates[0].status, SessionStatus.NEEDS_ACTION)
            self.assertTrue(updates[0].view_ack_required)
            self.assertEqual(updates[0].status_source, "workbuddy-db")

    def test_workbuddy_runtime_log_latest_idle_clears_running_db_status(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "workbuddy.db"
            db_updated_at = datetime(2026, 7, 15, 13, 48, 24, 388000).astimezone(timezone.utc)
            self._write_workbuddy_session_db(
                db_path,
                [
                    {
                        "id": "wb-working",
                        "cwd": "/Users/Gao/WorkBuddy/2026-07-15-13-12-11",
                        "title": "问候并询问今日状况",
                        "status": "Running",
                        "updated_at": int(db_updated_at.timestamp() * 1000),
                        "last_activity_at": int(db_updated_at.timestamp() * 1000),
                    },
                ],
            )
            log_path = Path(temp_dir) / "logs" / "2026-07-15" / "workspace.log"
            log_path.parent.mkdir(parents=True)
            log_path.write_text(
                "[7/15/2026, 1:48:24 PM.368] [Info] [SessionRunStateMachine] transition | "
                "sessionId=wb-working | event=MODEL_RESPONSE_DONE | from=model_streaming | "
                "to=model_done | lifecycle=running | busy=true | queueBusy=true\n"
                "[7/15/2026, 1:48:24 PM.370] [Info] [SessionRunStateMachine] transition | "
                "sessionId=wb-working | event=AGENT_ENDED | from=model_done | "
                "to=idle | lifecycle=idle | busy=false | queueBusy=false\n",
                encoding="utf-8",
            )
            rows = [
                "process_id=51007\tprocess_name=/Applications/WorkBuddy.app/Contents/MacOS/Electron\tcommand=/Applications/WorkBuddy.app/Contents/MacOS/Electron --app-path=/Applications/WorkBuddy.app/Contents/Resources/app.asar"
            ]

            updates = list(
                _classify_process_rows(
                    rows,
                    workbuddy_db_paths=(db_path,),
                    now=db_updated_at + timedelta(seconds=1),
                    source_started_at=db_updated_at - timedelta(seconds=5),
                )
            )

            self.assertEqual(len(updates), 1)
            self.assertEqual(updates[0].session_id, "process-51007")
            self.assertEqual(updates[0].title, "WorkBuddy Desktop")
            self.assertEqual(updates[0].status, SessionStatus.IDLE)
            self.assertEqual(updates[0].status_source, "desktop-process")

    def test_workbuddy_runtime_log_running_creates_session_when_db_has_not_caught_up(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "workbuddy.db"
            runtime_at = datetime(2026, 7, 15, 8, 24, 30, 349000).astimezone(timezone.utc)
            self._write_workbuddy_session_db(db_path, [])
            log_path = Path(temp_dir) / "logs" / "2026-07-15" / "workspace.log"
            log_path.parent.mkdir(parents=True)
            log_path.write_text(
                "[7/15/2026, 8:24:30 AM.349] [Info] [SessionRunStateMachine] transition | "
                "sessionId=wb-runtime-only | event=AGENT_STARTED | from=pending | "
                "to=agent_running | lifecycle=running | busy=true | queueBusy=true\n",
                encoding="utf-8",
            )
            rows = [
                "process_id=51007\tprocess_name=/Applications/WorkBuddy.app/Contents/MacOS/Electron\tcommand=/Applications/WorkBuddy.app/Contents/MacOS/Electron --app-path=/Applications/WorkBuddy.app/Contents/Resources/app.asar"
            ]

            updates = list(
                _classify_process_rows(
                    rows,
                    workbuddy_db_paths=(db_path,),
                    now=runtime_at + timedelta(seconds=1),
                    source_started_at=runtime_at - timedelta(seconds=5),
                )
            )

            self.assertEqual(len(updates), 1)
            self.assertEqual(updates[0].session_id, "workbuddy-wb-runtime-only")
            self.assertEqual(updates[0].title, "WorkBuddy Desktop - wb-runtime-only")
            self.assertEqual(updates[0].status, SessionStatus.RUNNING)
            self.assertFalse(updates[0].view_ack_required)
            self.assertEqual(updates[0].status_source, "workbuddy-log")

    def test_workbuddy_runtime_log_keeps_state_machine_when_noisy_tail_exceeds_legacy_window(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "workbuddy.db"
            db_updated_at = datetime(2026, 7, 15, 13, 48, 24, 388000).astimezone(timezone.utc)
            self._write_workbuddy_session_db(
                db_path,
                [
                    {
                        "id": "wb-noisy",
                        "cwd": "/Users/Gao/WorkBuddy/2026-07-15-13-12-11",
                        "title": "写入文档",
                        "status": "Completed",
                        "updated_at": int(db_updated_at.timestamp() * 1000),
                        "last_activity_at": int(db_updated_at.timestamp() * 1000),
                    },
                ],
            )
            log_path = Path(temp_dir) / "logs" / "2026-07-15" / "workspace.log"
            log_path.parent.mkdir(parents=True)
            noisy_tail = "x" * (96 * 1024)
            log_path.write_text(
                "[7/15/2026, 1:48:24 PM.368] [Info] [SessionRunStateMachine] transition | "
                "sessionId=wb-noisy | event=MODEL_RESPONSE_DONE | from=model_streaming | "
                "to=model_done | lifecycle=running | busy=true | queueBusy=true\n"
                f"[7/15/2026, 1:48:25 PM.000] [Info] [WorkflowMemProbe] {noisy_tail}\n",
                encoding="utf-8",
            )
            rows = [
                "process_id=51007\tprocess_name=/Applications/WorkBuddy.app/Contents/MacOS/Electron\tcommand=/Applications/WorkBuddy.app/Contents/MacOS/Electron --app-path=/Applications/WorkBuddy.app/Contents/Resources/app.asar"
            ]

            updates = list(
                _classify_process_rows(
                    rows,
                    workbuddy_db_paths=(db_path,),
                    now=db_updated_at + timedelta(seconds=1),
                    source_started_at=db_updated_at - timedelta(seconds=5),
                )
            )

            self.assertEqual(len(updates), 1)
            self.assertEqual(updates[0].session_id, "workbuddy-wb-noisy")
            self.assertEqual(updates[0].status, SessionStatus.RUNNING)
            self.assertEqual(updates[0].status_source, "workbuddy-log")

    def test_workbuddy_old_runtime_log_does_not_override_newer_db_attention_status(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "workbuddy.db"
            db_updated_at = datetime(2026, 7, 15, 13, 50, 0).astimezone(timezone.utc)
            self._write_workbuddy_session_db(
                db_path,
                [
                    {
                        "id": "wb-attention",
                        "cwd": "/Users/Gao/WorkBuddy/current",
                        "title": "等待用户确认",
                        "status": "Completed",
                        "updated_at": int(db_updated_at.timestamp() * 1000),
                        "last_activity_at": int(db_updated_at.timestamp() * 1000),
                    },
                ],
            )
            log_path = Path(temp_dir) / "logs" / "2026-07-15" / "workspace.log"
            log_path.parent.mkdir(parents=True)
            log_path.write_text(
                "[7/15/2026, 1:48:24 PM.368] [Info] [SessionRunStateMachine] transition | "
                "sessionId=wb-attention | event=MODEL_RESPONSE_DONE | from=model_streaming | "
                "to=model_done | lifecycle=running | busy=true | queueBusy=true\n",
                encoding="utf-8",
            )
            rows = [
                "process_id=51007\tprocess_name=/Applications/WorkBuddy.app/Contents/MacOS/Electron\tcommand=/Applications/WorkBuddy.app/Contents/MacOS/Electron --app-path=/Applications/WorkBuddy.app/Contents/Resources/app.asar"
            ]

            updates = list(
                _classify_process_rows(
                    rows,
                    workbuddy_db_paths=(db_path,),
                    now=db_updated_at + timedelta(seconds=1),
                    source_started_at=db_updated_at - timedelta(seconds=5),
                )
            )

            self.assertEqual(len(updates), 1)
            self.assertEqual(updates[0].session_id, "workbuddy-wb-attention")
            self.assertEqual(updates[0].status, SessionStatus.NEEDS_ACTION)
            self.assertEqual(updates[0].status_source, "workbuddy-db")

    def _write_workbuddy_session_db(self, path: Path, rows: list[dict]) -> None:
        connection = sqlite3.connect(path)
        try:
            connection.execute(
                """
                CREATE TABLE sessions (
                    id TEXT PRIMARY KEY,
                    cwd TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    title TEXT,
                    custom_title TEXT,
                    status TEXT NOT NULL DEFAULT 'Pending',
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL,
                    deleted_at INTEGER,
                    is_playground INTEGER NOT NULL DEFAULT 0,
                    source_mode TEXT,
                    is_background_automation INTEGER,
                    mode TEXT,
                    model TEXT,
                    expert_id TEXT,
                    expert_locale TEXT,
                    expert_runtime_identity TEXT,
                    expert_marketplace TEXT,
                    permission_mode TEXT,
                    last_activity_at INTEGER,
                    use_sandbox_cli INTEGER,
                    project_id TEXT
                )
                """
            )
            for row in rows:
                connection.execute(
                    """
                    INSERT INTO sessions (
                        id, cwd, user_id, title, custom_title, status,
                        created_at, updated_at, deleted_at, last_activity_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row["id"],
                        row["cwd"],
                        "user-1",
                        row.get("title"),
                        row.get("custom_title"),
                        row["status"],
                        row.get("created_at", row["updated_at"]),
                        row["updated_at"],
                        row.get("deleted_at"),
                        row.get("last_activity_at"),
                    ),
                )
            connection.commit()
        finally:
            connection.close()

    def test_qoder_desktop_process_uses_recent_task_status_log_as_running(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "20260710T102318" / "window1" / "quest.log"
            log_path.parent.mkdir(parents=True)
            log_path.write_text(
                '2026-07-10 10:25:58.542 [info] task.status.update {"taskId":"task-1.session.execution","status":"Running"}\n'
                '2026-07-10 10:25:58.547 [info] task.status.update.afterRefresh {"taskId":"task-1.session.execution","finalStatus":"Running"}\n',
                encoding="utf-8",
            )
            rows = [
                "process_id=51005\tprocess_name=/Applications/Qo\tcommand=/Applications/Qoder CN.app/Contents/MacOS/Electron --aicoding-open-agents-window\tcpu_percent=0.0\tstat=S"
            ]

            updates = list(
                _classify_process_rows(
                    rows,
                    qoder_logs_dir=Path(temp_dir),
                    now=datetime(2026, 7, 10, 10, 26, 0).astimezone(timezone.utc),
                )
            )

            self.assertEqual(len(updates), 1)
            self.assertEqual(updates[0].title, "Qoder CN Desktop - 对话")
            self.assertEqual(updates[0].status, SessionStatus.RUNNING)
            self.assertEqual(updates[0].status_source, "qoder-log")
            self.assertEqual(updates[0].tool_display_name, "Qoder CN")
            self.assertEqual(updates[0].updated_at, datetime(2026, 7, 10, 10, 25, 58, 547000).astimezone(timezone.utc))

    def test_qoder_resumed_prompt_to_status_counts_as_running(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "20260715T162247" / "questWindow" / "quest.log"
            log_path.parent.mkdir(parents=True)
            log_path.write_text(
                '2026-07-15 16:24:54.558 [info] quest.task.resumedByUserPrompt '
                '{"taskId":"task-edfa4f9da2a447d5b106","sessionId":"task-edfa4f9da2a447d5b106.session.execution",'
                '"fromStatus":"Completed","toStatus":"Running","acpState":"prompting"}\n',
                encoding="utf-8",
            )
            rows = [
                "process_id=51005\tprocess_name=/Applications/Qo\tcommand=/Applications/Qoder CN.app/Contents/MacOS/Electron --aicoding-open-agents-window\tcpu_percent=0.0\tstat=S"
            ]

            updates = list(
                _classify_process_rows(
                    rows,
                    qoder_logs_dir=Path(temp_dir),
                    now=datetime(2026, 7, 15, 16, 25, 0).astimezone(timezone.utc),
                )
            )

            self.assertEqual(len(updates), 1)
            self.assertEqual(updates[0].session_id, "qoder-task-edfa4f9da2a447d5b106")
            self.assertEqual(updates[0].title, "Qoder CN Desktop - 对话")
            self.assertEqual(updates[0].status, SessionStatus.RUNNING)
            self.assertFalse(updates[0].view_ack_required)
            self.assertEqual(updates[0].status_source, "qoder-log")

    def test_qoder_completed_task_log_creates_needs_action_conversation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "20260713T110839" / "questWindow" / "quest.log"
            agent_log_path = log_path.with_name("agent.log")
            log_path.parent.mkdir(parents=True)
            agent_log_path.write_text(
                '2026-07-13 11:09:59.009 [info] [ChatSessionService] rebindSessionAuthorityFromTask.resolve {"sessionId":"task-alpha.session.execution","taskId":"task-alpha","filePath":"/Users/Gao/Documents/QoderCN/2026-07-13/chat-1"}\n',
                encoding="utf-8",
            )
            log_path.write_text(
                '2026-07-13 11:09:58.931 [info] task.status.update {"taskId":"task-alpha.session.execution","status":"Running"}\n'
                '2026-07-13 11:10:08.022 [info] task.status.update {"taskId":"task-alpha.session.execution","status":"Completed"}\n',
                encoding="utf-8",
            )
            rows = [
                "process_id=51005\tprocess_name=/Applications/Qo\tcommand=/Applications/Qoder CN.app/Contents/MacOS/Electron --aicoding-open-agents-window\tcpu_percent=0.0\tstat=S"
            ]

            updates = list(
                _classify_process_rows(
                    rows,
                    qoder_logs_dir=Path(temp_dir),
                    now=datetime(2026, 7, 13, 11, 10, 10).astimezone(timezone.utc),
                )
            )

            self.assertEqual(len(updates), 1)
            self.assertEqual(updates[0].session_id, "qoder-task-alpha")
            self.assertEqual(updates[0].title, "Qoder CN Desktop - 对话")
            self.assertEqual(updates[0].status, SessionStatus.NEEDS_ACTION)
            self.assertTrue(updates[0].view_ack_required)
            self.assertEqual(updates[0].cwd, "/Users/Gao/Documents/QoderCN/2026-07-13/chat-1")
            self.assertTrue(updates[0].generated_conversation_path)
            self.assertEqual(updates[0].updated_at, datetime(2026, 7, 13, 11, 10, 8, 22000).astimezone(timezone.utc))

    def test_qoder_uses_project_session_title_instead_of_generated_chat_folder(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            app_root = Path(temp_dir) / "QoderCN"
            log_path = app_root / "logs" / "20260713T110839" / "questWindow" / "quest.log"
            agent_log_path = log_path.with_name("agent.log")
            project_session = (
                app_root
                / "SharedClientCache"
                / "cli"
                / "projects"
                / "task-alpha.session.execution-session.json"
            )
            log_path.parent.mkdir(parents=True)
            project_session.parent.mkdir(parents=True)
            agent_log_path.write_text(
                '2026-07-13 11:09:59.009 [info] [ChatSessionService] rebindSessionAuthorityFromTask.resolve {"sessionId":"task-alpha.session.execution","taskId":"task-alpha","filePath":"/Users/Gao/Documents/QoderCN/2026-07-13/chat-1"}\n',
                encoding="utf-8",
            )
            log_path.write_text(
                '2026-07-13 11:09:58.931 [info] task.status.update {"taskId":"task-alpha.session.execution","status":"Running"}\n',
                encoding="utf-8",
            )
            project_session.write_text(
                json.dumps({"title": "深度分析AI代码助手动向"}, ensure_ascii=False),
                encoding="utf-8",
            )
            rows = [
                "process_id=51005\tprocess_name=/Applications/Qo\tcommand=/Applications/Qoder CN.app/Contents/MacOS/Electron --aicoding-open-agents-window\tcpu_percent=0.0\tstat=S"
            ]

            updates = list(
                _classify_process_rows(
                    rows,
                    qoder_logs_dir=app_root / "logs",
                    now=datetime(2026, 7, 13, 11, 10, 10).astimezone(timezone.utc),
                )
            )

            self.assertEqual(len(updates), 1)
            self.assertEqual(updates[0].session_id, "qoder-task-alpha")
            self.assertEqual(updates[0].title, "Qoder CN Desktop - 深度分析AI代码助手动向")
            self.assertEqual(updates[0].cwd, "/Users/Gao/Documents/QoderCN/2026-07-13/chat-1")
            self.assertTrue(updates[0].generated_conversation_path)

    def test_qoder_uses_local_cache_session_title_instead_of_generated_chat_folder(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            app_root = Path(temp_dir) / "QoderCN"
            log_path = app_root / "logs" / "20260714T091333" / "questWindow" / "quest.log"
            agent_log_path = log_path.with_name("agent.log")
            db_path = app_root / "SharedClientCache" / "cache" / "db" / "local.db"
            log_path.parent.mkdir(parents=True)
            db_path.parent.mkdir(parents=True)
            agent_log_path.write_text(
                '2026-07-14 09:13:33.213 [info] [ChatSessionService] rebindSessionAuthorityFromTask.resolve {"sessionId":"task-alpha.session.execution","taskId":"task-alpha","filePath":"/Users/Gao/Documents/QoderCN/2026-07-14/chat-1"}\n',
                encoding="utf-8",
            )
            log_path.write_text(
                '2026-07-14 09:13:35.741 [info] task.status.update {"taskId":"task-alpha.session.execution","status":"Running"}\n',
                encoding="utf-8",
            )
            connection = sqlite3.connect(db_path)
            try:
                connection.execute(
                    """
                    CREATE TABLE chat_session (
                        session_id TEXT,
                        session_title TEXT,
                        project_uri TEXT,
                        project_name TEXT,
                        status TEXT,
                        extra TEXT,
                        gmt_create INTEGER,
                        gmt_modified INTEGER
                    )
                    """
                )
                connection.execute(
                    """
                    INSERT INTO chat_session (
                        session_id, session_title, project_uri, project_name, status, extra, gmt_create, gmt_modified
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "task-alpha.session.execution",
                        "围棋游戏开发",
                        "/Users/Gao/Documents/QoderCN/2026-07-14/chat-1",
                        "chat-1",
                        "Running",
                        "{}",
                        1783991613213,
                        1783991615741,
                    ),
                )
                connection.commit()
            finally:
                connection.close()
            rows = [
                "process_id=51005\tprocess_name=/Applications/Qo\tcommand=/Applications/Qoder CN.app/Contents/MacOS/Electron --aicoding-open-agents-window\tcpu_percent=0.0\tstat=S"
            ]

            updates = list(
                _classify_process_rows(
                    rows,
                    qoder_logs_dir=app_root / "logs",
                    now=datetime(2026, 7, 14, 9, 13, 40).astimezone(timezone.utc),
                )
            )

            self.assertEqual(len(updates), 1)
            self.assertEqual(updates[0].session_id, "qoder-task-alpha")
            self.assertEqual(updates[0].title, "Qoder CN Desktop - 围棋游戏开发")
            self.assertEqual(updates[0].cwd, "/Users/Gao/Documents/QoderCN/2026-07-14/chat-1")
            self.assertTrue(updates[0].generated_conversation_path)

    def test_qoder_shared_cache_db_status_creates_full_session_without_status_log(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            app_root = Path(temp_dir) / "Qoder"
            db_path = app_root / "SharedClientCache" / "cache" / "db" / "local.db"
            db_path.parent.mkdir(parents=True)
            connection = sqlite3.connect(db_path)
            try:
                connection.execute(
                    """
                    CREATE TABLE chat_session (
                        session_id TEXT,
                        session_title TEXT,
                        project_uri TEXT,
                        project_name TEXT,
                        status TEXT,
                        stop_reason TEXT,
                        extra TEXT,
                        last_user_query_at INTEGER,
                        gmt_create INTEGER,
                        gmt_modified INTEGER
                    )
                    """
                )
                connection.execute(
                    """
                    INSERT INTO chat_session (
                        session_id, session_title, project_uri, project_name, status, stop_reason, extra,
                        last_user_query_at, gmt_create, gmt_modified
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "task-48708e3212644a42b72d.session.execution",
                        "Hello",
                        "/Users/Gao/Documents/StudyCC",
                        "StudyCC",
                        "Stopped",
                        "Stopped",
                        '{"acp_session_chat_finish_reason":"action_required"}',
                        1783929398082,
                        1783929398081,
                        1784081769413,
                    ),
                )
                connection.commit()
            finally:
                connection.close()
            rows = [
                "process_id=60489\tprocess_name=/Applications/Qo\tcommand=/Applications/Qoder.app/Contents/MacOS/Qoder\tcpu_percent=0.0\tstat=S"
            ]

            updates = list(
                _classify_process_rows(
                    rows,
                    qoder_logs_dir=app_root / "SharedClientCache" / "logs",
                    now=datetime(2026, 7, 15, 10, 20, 0).astimezone(timezone.utc),
                )
            )
            updates_after_monitor_start = list(
                _classify_process_rows(
                    rows,
                    qoder_logs_dir=app_root / "SharedClientCache" / "logs",
                    now=datetime(2026, 7, 15, 10, 20, 0).astimezone(timezone.utc),
                    source_started_at=datetime(2026, 7, 15, 10, 30, 0).astimezone(timezone.utc),
                )
            )

            self.assertEqual(len(updates), 1)
            self.assertEqual(updates[0].session_id, "qoder-task-48708e3212644a42b72d")
            self.assertEqual(updates[0].title, "Qoder Desktop - Hello")
            self.assertEqual(updates[0].status, SessionStatus.NEEDS_ACTION)
            self.assertTrue(updates[0].view_ack_required)
            self.assertEqual(updates[0].status_source, "qoder-log")
            self.assertEqual(updates[0].cwd, "/Users/Gao/Documents/StudyCC")
            self.assertEqual(len(updates_after_monitor_start), 1)
            self.assertEqual(updates_after_monitor_start[0].session_id, "process-60489")
            self.assertEqual(updates_after_monitor_start[0].title, "Qoder Desktop")
            self.assertEqual(updates_after_monitor_start[0].status, SessionStatus.IDLE)
            self.assertEqual(updates_after_monitor_start[0].status_source, "desktop-process")

    def test_qoder_shared_cache_db_error_overrides_running_status(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            app_root = Path(temp_dir) / "Qoder"
            db_path = app_root / "SharedClientCache" / "cache" / "db" / "local.db"
            db_path.parent.mkdir(parents=True)
            connection = sqlite3.connect(db_path)
            try:
                connection.execute(
                    """
                    CREATE TABLE chat_session (
                        session_id TEXT,
                        session_title TEXT,
                        project_uri TEXT,
                        project_name TEXT,
                        status TEXT,
                        stop_reason TEXT,
                        extra TEXT,
                        last_user_query_at INTEGER,
                        gmt_create INTEGER,
                        gmt_modified INTEGER
                    )
                    """
                )
                connection.execute(
                    """
                    INSERT INTO chat_session (
                        session_id, session_title, project_uri, project_name, status, stop_reason, extra,
                        last_user_query_at, gmt_create, gmt_modified
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "task-b251.session.execution",
                        "hello",
                        "/Users/Gao/Documents/Qoder/2026-07-15/chat-2",
                        "chat-2",
                        "Running",
                        "Stopped",
                        json.dumps(
                            {
                                "acp_session_chat_finish_reason": "net/http: request canceled (Client.Timeout or context cancellation while reading body)",
                                "acp_session_status_code": 500,
                            }
                        ),
                        1784099454157,
                        1784099454157,
                        1784099464238,
                    ),
                )
                connection.commit()
            finally:
                connection.close()
            rows = [
                "process_id=60489\tprocess_name=/Applications/Qo\tcommand=/Applications/Qoder.app/Contents/MacOS/Qoder\tcpu_percent=0.0\tstat=S"
            ]

            updates = list(
                _classify_process_rows(
                    rows,
                    qoder_logs_dir=app_root / "SharedClientCache" / "logs",
                    now=datetime(2026, 7, 15, 15, 11, 10).astimezone(timezone.utc),
                )
            )

            self.assertEqual(len(updates), 1)
            self.assertEqual(updates[0].session_id, "qoder-task-b251")
            self.assertEqual(updates[0].title, "Qoder Desktop - hello")
            self.assertEqual(updates[0].status, SessionStatus.NEEDS_ACTION)
            self.assertTrue(updates[0].view_ack_required)
            self.assertEqual(updates[0].status_source, "qoder-log")

    def test_qoder_cn_cache_history_before_source_start_falls_back_to_single_idle_entry(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            app_root = Path(temp_dir) / "QoderCN"
            db_path = app_root / "SharedClientCache" / "cache" / "db" / "local.db"
            db_path.parent.mkdir(parents=True)
            connection = sqlite3.connect(db_path)
            try:
                connection.execute(
                    """
                    CREATE TABLE chat_session (
                        session_id TEXT,
                        session_title TEXT,
                        project_uri TEXT,
                        project_name TEXT,
                        status TEXT,
                        stop_reason TEXT,
                        extra TEXT,
                        last_user_query_at INTEGER,
                        gmt_create INTEGER,
                        gmt_modified INTEGER
                    )
                    """
                )
                rows_to_insert = [
                    (
                        "task-alpha.session.execution",
                        "介绍一下你自己",
                        "/Users/Gao/Documents/QoderCN/2026-07-14/chat-1",
                        "chat-1",
                        "Stopped",
                        "Stopped",
                        '{"acp_session_chat_finish_reason":"action_required"}',
                        1783991600000,
                        1783991600000,
                        1783991601000,
                    ),
                    (
                        "task-beta.session.execution",
                        "Qoder国际版免费额度",
                        "/Users/Gao/Documents/QoderCN/2026-07-14/chat-2",
                        "chat-2",
                        "Stopped",
                        "Stopped",
                        '{"acp_session_chat_finish_reason":"action_required"}',
                        1783991700000,
                        1783991700000,
                        1783991701000,
                    ),
                ]
                connection.executemany(
                    """
                    INSERT INTO chat_session (
                        session_id, session_title, project_uri, project_name, status, stop_reason, extra,
                        last_user_query_at, gmt_create, gmt_modified
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    rows_to_insert,
                )
                connection.commit()
            finally:
                connection.close()
            rows = [
                "process_id=51005\tprocess_name=/Applications/Qo\tcommand=/Applications/Qoder CN.app/Contents/MacOS/Electron --aicoding-open-agents-window\tcpu_percent=0.0\tstat=S"
            ]

            updates = list(
                _classify_process_rows(
                    rows,
                    qoder_logs_dir=app_root / "SharedClientCache" / "logs",
                    now=datetime(2026, 7, 15, 10, 20, 0).astimezone(timezone.utc),
                    source_started_at=datetime(2026, 7, 15, 10, 0, 0).astimezone(timezone.utc),
                )
            )

            self.assertEqual(len(updates), 1)
            self.assertEqual(updates[0].session_id, "process-51005")
            self.assertEqual(updates[0].title, "Qoder CN Desktop")
            self.assertEqual(updates[0].status, SessionStatus.IDLE)
            self.assertEqual(updates[0].status_source, "desktop-process")

    def test_qoder_status_update_planning_counts_as_running(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "20260710T102318" / "window1" / "quest.log"
            log_path.parent.mkdir(parents=True)
            log_path.write_text(
                '2026-07-10 10:25:58.542 [info] task.status.update {"taskId":"task-1.session.execution","status":"Planning"}\n',
                encoding="utf-8",
            )
            rows = [
                "process_id=51005\tprocess_name=/Applications/Qo\tcommand=/Applications/Qoder CN.app/Contents/MacOS/Electron --aicoding-open-agents-window\tcpu_percent=0.0\tstat=S"
            ]

            updates = list(
                _classify_process_rows(
                    rows,
                    qoder_logs_dir=Path(temp_dir),
                    now=datetime(2026, 7, 10, 10, 26, 0).astimezone(timezone.utc),
                )
            )

            self.assertEqual(len(updates), 1)
            self.assertEqual(updates[0].session_id, "qoder-task-1")
            self.assertEqual(updates[0].status, SessionStatus.RUNNING)
            self.assertEqual(updates[0].status_source, "qoder-log")

    def test_qoder_completion_after_monitor_start_is_not_filtered_as_history(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "20260713T110839" / "questWindow" / "quest.log"
            agent_log_path = log_path.with_name("agent.log")
            log_path.parent.mkdir(parents=True)
            agent_log_path.write_text(
                '2026-07-13 11:09:59.009 [info] [ChatSessionService] rebindSessionAuthorityFromTask.resolve {"sessionId":"task-alpha.session.execution","taskId":"task-alpha","filePath":"/Users/Gao/Documents/QoderCN/2026-07-13/chat-1"}\n',
                encoding="utf-8",
            )
            log_path.write_text(
                '2026-07-13 11:09:58.931 [info] task.status.update {"taskId":"task-alpha.session.execution","status":"Running"}\n'
                '2026-07-13 11:10:08.022 [info] task.status.update {"taskId":"task-alpha.session.execution","status":"Completed"}\n',
                encoding="utf-8",
            )
            rows = [
                "process_id=51005\tprocess_name=/Applications/Qo\tcommand=/Applications/Qoder CN.app/Contents/MacOS/Electron --aicoding-open-agents-window\tcpu_percent=0.0\tstat=S"
            ]

            updates = list(
                _classify_process_rows(
                    rows,
                    qoder_logs_dir=Path(temp_dir),
                    source_started_at=datetime(2026, 7, 13, 11, 10, 0).astimezone(timezone.utc),
                    now=datetime(2026, 7, 13, 11, 10, 10).astimezone(timezone.utc),
                )
            )

            self.assertEqual(len(updates), 1)
            self.assertEqual(updates[0].session_id, "qoder-task-alpha")
            self.assertEqual(updates[0].title, "Qoder CN Desktop - 对话")
            self.assertEqual(updates[0].status, SessionStatus.NEEDS_ACTION)
            self.assertTrue(updates[0].view_ack_required)

    def test_qoder_completion_before_monitor_start_falls_back_to_idle_desktop_entry(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "20260713T110839" / "questWindow" / "quest.log"
            log_path.parent.mkdir(parents=True)
            log_path.write_text(
                '2026-07-13 11:09:58.931 [info] task.status.update {"taskId":"task-alpha.session.execution","status":"Running"}\n'
                '2026-07-13 11:10:08.022 [info] task.status.update {"taskId":"task-alpha.session.execution","status":"Completed"}\n',
                encoding="utf-8",
            )
            rows = [
                "process_id=51005\tprocess_name=/Applications/Qo\tcommand=/Applications/Qoder CN.app/Contents/MacOS/Electron --aicoding-open-agents-window\tcpu_percent=0.0\tstat=S"
            ]

            updates = list(
                _classify_process_rows(
                    rows,
                    qoder_logs_dir=Path(temp_dir),
                    source_started_at=datetime(2026, 7, 13, 11, 11, 0).astimezone(timezone.utc),
                    now=datetime(2026, 7, 13, 11, 11, 10).astimezone(timezone.utc),
                )
            )

            self.assertEqual(len(updates), 1)
            self.assertEqual(updates[0].session_id, "process-51005")
            self.assertEqual(updates[0].title, "Qoder CN Desktop")
            self.assertEqual(updates[0].status, SessionStatus.IDLE)
            self.assertEqual(updates[0].status_source, "desktop-process")

    def test_qoder_after_refresh_completed_snapshot_without_running_evidence_is_idle_desktop_entry(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "20260713T110839" / "questWindow" / "quest.log"
            log_path.parent.mkdir(parents=True)
            log_path.write_text(
                '2026-07-13 11:10:08.022 [info] task.status.update.afterRefresh {"taskId":"task-alpha.session.execution","finalStatus":"Completed"}\n',
                encoding="utf-8",
            )
            rows = [
                "process_id=51005\tprocess_name=/Applications/Qo\tcommand=/Applications/Qoder.app/Contents/MacOS/Qoder\tcpu_percent=0.0\tstat=S"
            ]

            updates = list(
                _classify_process_rows(
                    rows,
                    qoder_logs_dir=Path(temp_dir),
                    source_started_at=datetime(2026, 7, 13, 11, 0, 0).astimezone(timezone.utc),
                    now=datetime(2026, 7, 13, 11, 10, 10).astimezone(timezone.utc),
                )
            )

            self.assertEqual(len(updates), 1)
            self.assertEqual(updates[0].session_id, "process-51005")
            self.assertEqual(updates[0].title, "Qoder Desktop")
            self.assertEqual(updates[0].status, SessionStatus.IDLE)
            self.assertEqual(updates[0].status_source, "desktop-process")

    def test_qoder_history_loaded_chat_finish_from_load_is_idle_desktop_entry(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "20260715T095144" / "questWindow" / "agent.log"
            log_path.parent.mkdir(parents=True)
            log_path.write_text(
                '2026-07-15 09:51:48.417 [info] [ChatSessionService] loadHistory.authorityContext {"sessionId":"task-alpha.session.execution","sessionType":"quest","taskId":"task-alpha","filePath":"/Users/Gao/Documents/StudyCC"}\n'
                "2026-07-15 09:51:48.549 [info] [ChatSessionService] ACP progress: task-alpha.session.execution, rid=req-1, type=notification, notification type=chat_finish, from=load\n",
                encoding="utf-8",
            )
            rows = [
                "process_id=51005\tprocess_name=/Applications/Qoder.app/Contents/MacOS/Electron\tcommand=/Applications/Qoder.app/Contents/MacOS/Electron\tcpu_percent=0.0\tstat=S"
            ]

            updates = list(
                _classify_process_rows(
                    rows,
                    qoder_logs_dir=Path(temp_dir),
                    now=datetime(2026, 7, 15, 9, 52, 0).astimezone(timezone.utc),
                )
            )

            self.assertEqual(len(updates), 1)
            self.assertEqual(updates[0].session_id, "process-51005")
            self.assertEqual(updates[0].title, "Qoder Desktop")
            self.assertEqual(updates[0].status, SessionStatus.IDLE)
            self.assertEqual(updates[0].status_source, "desktop-process")

    def test_qoder_current_cancelled_history_state_overrides_older_suspended_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            old_log_path = Path(temp_dir) / "20260714T092500" / "questWindow" / "agent.log"
            current_log_path = Path(temp_dir) / "20260715T095144" / "questWindow" / "agent.log"
            old_log_path.parent.mkdir(parents=True)
            current_log_path.parent.mkdir(parents=True)
            old_log_path.write_text(
                '2026-07-14 09:25:37.860 [info] [ChatPanel.acpBlocks] {"taskId":"task-alpha","sessionId":"task-alpha.session.execution","state":"suspended"}\n',
                encoding="utf-8",
            )
            current_log_path.write_text(
                '2026-07-15 09:51:48.417 [info] [ChatSessionService] loadHistory.authorityContext {"sessionId":"task-alpha.session.execution","sessionType":"quest","taskId":"task-alpha","filePath":"/Users/Gao/Documents/StudyCC"}\n'
                '2026-07-15 09:51:48.563 [info] [ChatPanel.acpBlocks] {"taskId":"task-alpha","sessionId":"task-alpha.session.execution","state":"cancelled"}\n',
                encoding="utf-8",
            )
            rows = [
                "process_id=51005\tprocess_name=/Applications/Qoder.app/Contents/MacOS/Electron\tcommand=/Applications/Qoder.app/Contents/MacOS/Electron\tcpu_percent=0.0\tstat=S"
            ]

            updates = list(
                _classify_process_rows(
                    rows,
                    qoder_logs_dir=Path(temp_dir),
                    now=datetime(2026, 7, 15, 9, 52, 0).astimezone(timezone.utc),
                )
            )

            self.assertEqual(len(updates), 1)
            self.assertEqual(updates[0].session_id, "process-51005")
            self.assertEqual(updates[0].title, "Qoder Desktop")
            self.assertEqual(updates[0].status, SessionStatus.IDLE)
            self.assertEqual(updates[0].status_source, "desktop-process")

    def test_qoder_multiple_task_logs_create_separate_conversation_updates(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "20260713T110839" / "questWindow" / "quest.log"
            agent_log_path = log_path.with_name("agent.log")
            log_path.parent.mkdir(parents=True)
            agent_log_path.write_text(
                '2026-07-13 11:09:59.009 [info] [ChatSessionService] rebindSessionAuthorityFromTask.resolve {"sessionId":"task-alpha.session.execution","taskId":"task-alpha","filePath":"/Users/Gao/Documents/QoderCN/2026-07-13/chat-1"}\n'
                '2026-07-13 11:12:30.916 [info] [ChatSessionService] rebindSessionAuthorityFromTask.resolve {"sessionId":"task-beta.session.execution","taskId":"task-beta","filePath":"/Users/Gao/Documents/QoderCN/2026-07-10/chat-2"}\n',
                encoding="utf-8",
            )
            log_path.write_text(
                '2026-07-13 11:10:08.022 [info] task.status.update {"taskId":"task-alpha.session.execution","status":"Completed"}\n'
                '2026-07-13 11:12:26.675 [info] task.status.update {"taskId":"task-beta.session.execution","status":"Running"}\n',
                encoding="utf-8",
            )
            rows = [
                "process_id=51005\tprocess_name=/Applications/Qo\tcommand=/Applications/Qoder CN.app/Contents/MacOS/Electron --aicoding-open-agents-window\tcpu_percent=0.0\tstat=S"
            ]

            updates = list(
                _classify_process_rows(
                    rows,
                    qoder_logs_dir=Path(temp_dir),
                    now=datetime(2026, 7, 13, 11, 12, 30).astimezone(timezone.utc),
                )
            )

            by_id = {update.session_id: update for update in updates}
            self.assertEqual(set(by_id), {"qoder-task-alpha", "qoder-task-beta"})
            self.assertEqual(by_id["qoder-task-alpha"].title, "Qoder CN Desktop - 对话")
            self.assertEqual(by_id["qoder-task-alpha"].status, SessionStatus.NEEDS_ACTION)
            self.assertEqual(by_id["qoder-task-beta"].title, "Qoder CN Desktop - 对话")
            self.assertEqual(by_id["qoder-task-beta"].status, SessionStatus.RUNNING)

    def test_qoder_after_refresh_final_status_overrides_pushed_running_status(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "20260710T102318" / "window1" / "quest.log"
            log_path.parent.mkdir(parents=True)
            log_path.write_text(
                '2026-07-10 10:34:45.994 [info] task.status.update {"taskId":"task-1.session.execution","status":"Running"}\n'
                '2026-07-10 10:34:45.999 [info] task.status.update.afterRefresh {"taskId":"task-1.session.execution","pushedStatus":"Running","finalStatus":"Completed"}\n',
                encoding="utf-8",
            )
            rows = [
                "process_id=51005\tprocess_name=/Applications/Qo\tcommand=/Applications/Qoder CN.app/Contents/MacOS/Electron --aicoding-open-agents-window\tcpu_percent=0.0\tstat=S"
            ]

            updates = list(
                _classify_process_rows(
                    rows,
                    qoder_logs_dir=Path(temp_dir),
                    now=datetime(2026, 7, 10, 10, 34, 50).astimezone(timezone.utc),
                )
            )

            self.assertEqual(len(updates), 1)
            self.assertEqual(updates[0].status, SessionStatus.NEEDS_ACTION)
            self.assertTrue(updates[0].view_ack_required)
            self.assertEqual(updates[0].status_source, "qoder-log")
            self.assertEqual(updates[0].updated_at, datetime(2026, 7, 10, 10, 34, 45, 999000).astimezone(timezone.utc))

    def test_qoder_after_refresh_ignores_stale_completed_snapshot_when_pushed_status_is_running(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "20260710T102318" / "window1" / "quest.log"
            log_path.parent.mkdir(parents=True)
            log_path.write_text(
                '2026-07-10 10:34:45.994 [info] task.status.update {"taskId":"task-1.session.execution","status":"Running"}\n'
                '2026-07-10 10:34:45.999 [info] task.status.update.afterRefresh {"taskId":"task-1.session.execution","pushedStatus":"Running","refreshedStatus":"Completed","finalStatus":"Completed","updatedAtTimestamp":1783650359937}\n',
                encoding="utf-8",
            )
            rows = [
                "process_id=51005\tprocess_name=/Applications/Qo\tcommand=/Applications/Qoder CN.app/Contents/MacOS/Electron --aicoding-open-agents-window\tcpu_percent=0.0\tstat=S"
            ]

            updates = list(
                _classify_process_rows(
                    rows,
                    qoder_logs_dir=Path(temp_dir),
                    now=datetime(2026, 7, 10, 10, 34, 50).astimezone(timezone.utc),
                )
            )

            self.assertEqual(len(updates), 1)
            self.assertEqual(updates[0].status, SessionStatus.RUNNING)
            self.assertEqual(updates[0].status_source, "qoder-log")

    def test_qoder_desktop_process_uses_recent_agent_streaming_log_as_running(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "20260710T102318" / "questWindow" / "agent.log"
            log_path.parent.mkdir(parents=True)
            log_path.write_text(
                '2026-07-10 10:59:57.244 [info] [ChatPanel.acpBlocks] {"taskId":"task-2","sessionId":"task-2.session.execution","progressLen":456,"blocksLen":14,"state":"streaming"}\n',
                encoding="utf-8",
            )
            rows = [
                "process_id=51005\tprocess_name=/Applications/Qo\tcommand=/Applications/Qoder CN.app/Contents/MacOS/Electron --aicoding-open-agents-window\tcpu_percent=0.0\tstat=S"
            ]

            updates = list(
                _classify_process_rows(
                    rows,
                    qoder_logs_dir=Path(temp_dir),
                    now=datetime(2026, 7, 10, 11, 0, 0).astimezone(timezone.utc),
                )
            )

            self.assertEqual(len(updates), 1)
            self.assertEqual(updates[0].status, SessionStatus.RUNNING)
            self.assertEqual(updates[0].status_source, "qoder-log")

    def test_qoder_agent_state_machine_prompting_log_counts_as_running(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "20260710T102318" / "questWindow" / "agent.log"
            log_path.parent.mkdir(parents=True)
            log_path.write_text(
                "2026-07-10 10:25:58.534 [info] [ACPProgressStateMachine] State transition: initial -> prompting, trigger: user_message_chunk, sessionId: task-2.session.execution\n",
                encoding="utf-8",
            )
            rows = [
                "process_id=51005\tprocess_name=/Applications/Qo\tcommand=/Applications/Qoder CN.app/Contents/MacOS/Electron --aicoding-open-agents-window\tcpu_percent=0.0\tstat=S"
            ]

            updates = list(
                _classify_process_rows(
                    rows,
                    qoder_logs_dir=Path(temp_dir),
                    now=datetime(2026, 7, 10, 10, 26, 0).astimezone(timezone.utc),
                )
            )

            self.assertEqual(len(updates), 1)
            self.assertEqual(updates[0].status, SessionStatus.RUNNING)
            self.assertEqual(updates[0].status_source, "qoder-log")

    def test_qoder_agent_state_machine_suspended_log_counts_as_needs_action(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "20260710T102318" / "questWindow" / "agent.log"
            log_path.parent.mkdir(parents=True)
            log_path.write_text(
                "2026-07-10 10:21:21.448 [info] [ACPProgressStateMachine] State transition: streaming -> suspended, trigger: resume_tool_call, sessionId: task-2.session.execution\n",
                encoding="utf-8",
            )
            rows = [
                "process_id=51005\tprocess_name=/Applications/Qo\tcommand=/Applications/Qoder CN.app/Contents/MacOS/Electron --aicoding-open-agents-window\tcpu_percent=0.0\tstat=S"
            ]

            updates = list(
                _classify_process_rows(
                    rows,
                    qoder_logs_dir=Path(temp_dir),
                    now=datetime(2026, 7, 10, 10, 21, 25).astimezone(timezone.utc),
                )
            )

            self.assertEqual(len(updates), 1)
            self.assertEqual(updates[0].status, SessionStatus.NEEDS_ACTION)
            self.assertFalse(updates[0].view_ack_required)
            self.assertEqual(updates[0].status_source, "qoder-log")

    def test_qoder_suspended_transition_is_not_overridden_by_same_timestamp_streaming_snapshot(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "20260710T102318" / "questWindow" / "agent.log"
            log_path.parent.mkdir(parents=True)
            log_path.write_text(
                "2026-07-10 10:21:21.448 [info] [ACPProgressStateMachine] State transition: streaming -> suspended, trigger: resume_tool_call, sessionId: task-2.session.execution\n"
                '2026-07-10 10:21:21.448 [info] [ChatPanel.acpBlocks] {"taskId":"task-2","sessionId":"task-2.session.execution","state":"streaming"}\n',
                encoding="utf-8",
            )
            rows = [
                "process_id=51005\tprocess_name=/Applications/Qo\tcommand=/Applications/Qoder CN.app/Contents/MacOS/Electron --aicoding-open-agents-window\tcpu_percent=0.0\tstat=S"
            ]

            updates = list(
                _classify_process_rows(
                    rows,
                    qoder_logs_dir=Path(temp_dir),
                    now=datetime(2026, 7, 10, 10, 21, 25).astimezone(timezone.utc),
                )
            )

            self.assertEqual(len(updates), 1)
            self.assertEqual(updates[0].status, SessionStatus.NEEDS_ACTION)
            self.assertFalse(updates[0].view_ack_required)
            self.assertEqual(updates[0].status_source, "qoder-log")

    def test_qoder_agent_error_state_survives_cancelled_cleanup(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "20260715T151026" / "questWindow" / "agent.log"
            log_path.parent.mkdir(parents=True)
            log_path.write_text(
                "2026-07-15 15:11:04.237 [info] [ACPProgressStateMachine] State transition: prompting -> error, trigger: chat_finish:net/http: request canceled (Client.Timeout or context cancellation while reading body):500, sessionId: task-b251.session.execution\n"
                '2026-07-15 15:11:04.238 [info] [ChatSessionService] ACP stream completed: {"sessionId":"task-b251.session.execution","state":"error","totalUpdates":4}\n'
                "2026-07-15 15:11:04.253 [info] [ACPProgressStateMachine] State transition: error -> cancelled, trigger: session/prompt:cancelled, sessionId: task-b251.session.execution\n"
                '2026-07-15 15:11:04.265 [info] [ChatPanel.acpBlocks] {"taskId":"task-b251","sessionId":"task-b251.session.execution","progressLen":5,"blocksLen":3,"state":"cancelled"}\n',
                encoding="utf-8",
            )
            rows = [
                "process_id=60489\tprocess_name=/Applications/Qoder.app/Contents/MacOS/Electron\tcommand=/Applications/Qoder.app/Contents/MacOS/Electron\tcpu_percent=0.0\tstat=S"
            ]

            updates = list(
                _classify_process_rows(
                    rows,
                    qoder_logs_dir=Path(temp_dir),
                    now=datetime(2026, 7, 15, 15, 11, 10).astimezone(timezone.utc),
                )
            )

            self.assertEqual(len(updates), 1)
            self.assertEqual(updates[0].session_id, "qoder-task-b251")
            self.assertEqual(updates[0].status, SessionStatus.NEEDS_ACTION)
            self.assertTrue(updates[0].view_ack_required)
            self.assertEqual(updates[0].status_source, "qoder-log")

    def test_qoder_suspended_payload_state_counts_as_needs_action(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "20260710T102318" / "questWindow" / "agent.log"
            log_path.parent.mkdir(parents=True)
            log_path.write_text(
                '2026-07-10 10:21:21.448 [info] [ChatPanel.acpBlocks] {"taskId":"task-2","sessionId":"task-2.session.execution","state":"suspended"}\n',
                encoding="utf-8",
            )
            rows = [
                "process_id=51005\tprocess_name=/Applications/Qo\tcommand=/Applications/Qoder CN.app/Contents/MacOS/Electron --aicoding-open-agents-window\tcpu_percent=0.0\tstat=S"
            ]

            updates = list(
                _classify_process_rows(
                    rows,
                    qoder_logs_dir=Path(temp_dir),
                    now=datetime(2026, 7, 10, 10, 21, 25).astimezone(timezone.utc),
                )
            )

            self.assertEqual(len(updates), 1)
            self.assertEqual(updates[0].status, SessionStatus.NEEDS_ACTION)
            self.assertFalse(updates[0].view_ack_required)
            self.assertEqual(updates[0].status_source, "qoder-log")

    def test_qoder_action_required_with_suspended_acp_state_needs_user_attention(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "20260710T102318" / "questWindow" / "agent.log"
            log_path.parent.mkdir(parents=True)
            log_path.write_text(
                '2026-07-10 10:21:21.448 [info] task.status.update.afterRefresh {"taskId":"task-2","pushedStatus":"ActionRequired","finalStatus":"ActionRequired","acpState":"suspended"}\n',
                encoding="utf-8",
            )
            rows = [
                "process_id=51005\tprocess_name=/Applications/Qo\tcommand=/Applications/Qoder CN.app/Contents/MacOS/Electron --aicoding-open-agents-window\tcpu_percent=0.0\tstat=S"
            ]

            updates = list(
                _classify_process_rows(
                    rows,
                    qoder_logs_dir=Path(temp_dir),
                    now=datetime(2026, 7, 10, 10, 21, 25).astimezone(timezone.utc),
                )
            )

            self.assertEqual(len(updates), 1)
            self.assertEqual(updates[0].status, SessionStatus.NEEDS_ACTION)
            self.assertFalse(updates[0].view_ack_required)
            self.assertEqual(updates[0].status_source, "qoder-log")

    def test_qoder_prompt_payload_state_falls_back_to_idle_desktop_entry(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "20260710T102318" / "questWindow" / "agent.log"
            log_path.parent.mkdir(parents=True)
            log_path.write_text(
                '2026-07-10 10:21:21.448 [info] [ChatPanel.acpBlocks] {"taskId":"task-2","sessionId":"task-2.session.execution","state":"prompt"}\n',
                encoding="utf-8",
            )
            rows = [
                "process_id=51005\tprocess_name=/Applications/Qo\tcommand=/Applications/Qoder CN.app/Contents/MacOS/Electron --aicoding-open-agents-window\tcpu_percent=0.0\tstat=S"
            ]

            updates = list(
                _classify_process_rows(
                    rows,
                    qoder_logs_dir=Path(temp_dir),
                    now=datetime(2026, 7, 10, 10, 21, 25).astimezone(timezone.utc),
                )
            )

            self.assertEqual(len(updates), 1)
            self.assertEqual(updates[0].session_id, "process-51005")
            self.assertEqual(updates[0].title, "Qoder CN Desktop")
            self.assertEqual(updates[0].status, SessionStatus.IDLE)
            self.assertEqual(updates[0].status_source, "desktop-process")

    def test_qoder_user_attention_state_is_not_cleared_by_view_ack(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "20260710T102318" / "questWindow" / "agent.log"
            log_path.parent.mkdir(parents=True)
            log_path.write_text(
                '2026-07-10 10:21:21.448 [info] [ChatPanel.acpBlocks] {"taskId":"task-2","sessionId":"task-2.session.execution","state":"suspended"}\n',
                encoding="utf-8",
            )
            rows = [
                "process_id=51005\tprocess_name=/Applications/Qo\tcommand=/Applications/Qoder CN.app/Contents/MacOS/Electron --aicoding-open-agents-window\tcpu_percent=0.0\tstat=S"
            ]

            updates = list(
                _classify_process_rows(
                    rows,
                    qoder_logs_dir=Path(temp_dir),
                    now=datetime(2026, 7, 10, 10, 21, 25).astimezone(timezone.utc),
                )
            )

            self.assertEqual(len(updates), 1)
            self.assertEqual(updates[0].status, SessionStatus.NEEDS_ACTION)
            self.assertFalse(updates[0].view_ack_required)
            self.assertEqual(updates[0].status_source, "qoder-log")

    def test_qoder_user_attention_state_before_monitor_start_still_needs_action(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "20260710T102318" / "questWindow" / "agent.log"
            log_path.parent.mkdir(parents=True)
            log_path.write_text(
                '2026-07-10 10:21:21.448 [info] [ChatPanel.acpBlocks] {"taskId":"task-2","sessionId":"task-2.session.execution","state":"suspended"}\n',
                encoding="utf-8",
            )
            rows = [
                "process_id=51005\tprocess_name=/Applications/Qo\tcommand=/Applications/Qoder CN.app/Contents/MacOS/Electron --aicoding-open-agents-window\tcpu_percent=0.0\tstat=S"
            ]

            updates = list(
                _classify_process_rows(
                    rows,
                    qoder_logs_dir=Path(temp_dir),
                    source_started_at=datetime(2026, 7, 10, 10, 22, 0).astimezone(timezone.utc),
                    now=datetime(2026, 7, 10, 10, 22, 10).astimezone(timezone.utc),
                )
            )

            self.assertEqual(len(updates), 1)
            self.assertEqual(updates[0].status, SessionStatus.NEEDS_ACTION)
            self.assertFalse(updates[0].view_ack_required)
            self.assertEqual(updates[0].status_source, "qoder-log")

    def test_qoder_payload_requiring_user_input_counts_as_needs_action(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "20260710T102318" / "questWindow" / "agent.log"
            log_path.parent.mkdir(parents=True)
            log_path.write_text(
                '2026-07-10 10:21:21.448 [info] [ChatPanel.acpBlocks] {"taskId":"task-2","sessionId":"task-2.session.execution","state":"streaming","requiresApproval":true}\n',
                encoding="utf-8",
            )
            rows = [
                "process_id=51005\tprocess_name=/Applications/Qo\tcommand=/Applications/Qoder CN.app/Contents/MacOS/Electron --aicoding-open-agents-window\tcpu_percent=0.0\tstat=S"
            ]

            updates = list(
                _classify_process_rows(
                    rows,
                    qoder_logs_dir=Path(temp_dir),
                    now=datetime(2026, 7, 10, 10, 21, 25).astimezone(timezone.utc),
                )
            )

            self.assertEqual(len(updates), 1)
            self.assertEqual(updates[0].status, SessionStatus.NEEDS_ACTION)
            self.assertFalse(updates[0].view_ack_required)
            self.assertEqual(updates[0].status_source, "qoder-log")

    def test_qoder_agent_state_machine_groups_uuid_session_transitions(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "20260710T102318" / "window1" / "agent.log"
            log_path.parent.mkdir(parents=True)
            log_path.write_text(
                "2026-07-10 10:21:19.037 [info] [ACPProgressStateMachine] State transition: completed -> prompting, trigger: user_message_chunk, sessionId: 9ab90918-7c7f-4622-b477-94979f445fbd\n"
                "2026-07-10 10:21:21.448 [info] [ACPProgressStateMachine] State transition: prompting -> streaming, trigger: tool_call, sessionId: 9ab90918-7c7f-4622-b477-94979f445fbd\n"
                "2026-07-10 10:21:29.448 [info] [ACPProgressStateMachine] State transition: streaming -> completed, trigger: chat_finish:success:200, sessionId: 9ab90918-7c7f-4622-b477-94979f445fbd\n",
                encoding="utf-8",
            )
            rows = [
                "process_id=51005\tprocess_name=/Applications/Qo\tcommand=/Applications/Qoder.app/Contents/MacOS/Electron --app-path=/Applications/Qoder.app/Contents/Resources/app.asar\tcpu_percent=0.0\tstat=S"
            ]

            updates = list(
                _classify_process_rows(
                    rows,
                    qoder_logs_dir=Path(temp_dir),
                    now=datetime(2026, 7, 10, 10, 21, 35).astimezone(timezone.utc),
                )
            )

            self.assertEqual(len(updates), 1)
            self.assertEqual(updates[0].status, SessionStatus.NEEDS_ACTION)
            self.assertEqual(updates[0].status_source, "qoder-log")

    def test_qoder_same_task_completed_log_overrides_older_agent_streaming_log(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            agent_log_path = Path(temp_dir) / "20260710T102318" / "questWindow" / "agent.log"
            quest_log_path = Path(temp_dir) / "20260710T102318" / "questWindow" / "quest.log"
            agent_log_path.parent.mkdir(parents=True)
            agent_log_path.write_text(
                '2026-07-10 10:59:57.244 [info] [ChatPanel.acpBlocks] {"taskId":"task-2","sessionId":"task-2.session.execution","progressLen":456,"blocksLen":14,"state":"streaming"}\n',
                encoding="utf-8",
            )
            quest_log_path.write_text(
                '2026-07-10 11:00:03.995 [info] task.status.update.afterRefresh {"taskId":"task-2.session.execution","pushedStatus":"Completed","refreshedStatus":"Completed","finalStatus":"Completed"}\n',
                encoding="utf-8",
            )
            rows = [
                "process_id=51005\tprocess_name=/Applications/Qo\tcommand=/Applications/Qoder CN.app/Contents/MacOS/Electron --aicoding-open-agents-window\tcpu_percent=0.0\tstat=S"
            ]

            updates = list(
                _classify_process_rows(
                    rows,
                    qoder_logs_dir=Path(temp_dir),
                    now=datetime(2026, 7, 10, 11, 0, 10).astimezone(timezone.utc),
                )
            )

            self.assertEqual(len(updates), 1)
            self.assertEqual(updates[0].status, SessionStatus.NEEDS_ACTION)
            self.assertEqual(updates[0].status_source, "qoder-log")

    def test_qoder_running_signal_survives_verbose_log_tail(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "20260710T102318" / "questWindow" / "agent.log"
            log_path.parent.mkdir(parents=True)
            noisy_lines = "".join(
                f"2026-07-10 10:59:{index % 60:02d}.000 [info] [InlineChatInput] verbose noise {index:04d} {'x' * 80}\n"
                for index in range(1600)
            )
            log_path.write_text(
                '2026-07-10 10:59:57.244 [info] [ChatPanel.acpBlocks] {"taskId":"task-2","sessionId":"task-2.session.execution","progressLen":456,"blocksLen":14,"state":"streaming"}\n'
                + noisy_lines,
                encoding="utf-8",
            )
            rows = [
                "process_id=51005\tprocess_name=/Applications/Qo\tcommand=/Applications/Qoder CN.app/Contents/MacOS/Electron --aicoding-open-agents-window\tcpu_percent=0.0\tstat=S"
            ]

            updates = list(
                _classify_process_rows(
                    rows,
                    qoder_logs_dir=Path(temp_dir),
                    now=datetime(2026, 7, 10, 11, 0, 0).astimezone(timezone.utc),
                )
            )

            self.assertEqual(len(updates), 1)
            self.assertEqual(updates[0].session_id, "qoder-task-2")
            self.assertEqual(updates[0].status, SessionStatus.RUNNING)
            self.assertEqual(updates[0].status_source, "qoder-log")

    def test_qoder_short_run_completion_keeps_running_visible_for_one_poll(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "20260710T102318" / "questWindow" / "quest.log"
            log_path.parent.mkdir(parents=True)
            log_path.write_text(
                '2026-07-10 10:59:55.950 [info] task.status.update {"taskId":"task-2.session.execution","status":"Running"}\n'
                '2026-07-10 11:00:01.632 [info] task.status.update.afterRefresh {"taskId":"task-2.session.execution","pushedStatus":"Completed","refreshedStatus":"Completed","finalStatus":"Completed","acpState":"completed"}\n',
                encoding="utf-8",
            )
            rows = [
                "process_id=51005\tprocess_name=/Applications/Qo\tcommand=/Applications/Qoder CN.app/Contents/MacOS/Electron --aicoding-open-agents-window\tcpu_percent=0.0\tstat=S"
            ]

            updates = list(
                _classify_process_rows(
                    rows,
                    qoder_logs_dir=Path(temp_dir),
                    now=datetime(2026, 7, 10, 11, 0, 3).astimezone(timezone.utc),
                )
            )

            self.assertEqual(len(updates), 1)
            self.assertEqual(updates[0].session_id, "qoder-task-2")
            self.assertEqual(updates[0].status, SessionStatus.RUNNING)
            self.assertFalse(updates[0].view_ack_required)

            updates_after_visibility_window = list(
                _classify_process_rows(
                    rows,
                    qoder_logs_dir=Path(temp_dir),
                    now=datetime(2026, 7, 10, 11, 0, 11).astimezone(timezone.utc),
                )
            )

            self.assertEqual(len(updates_after_visibility_window), 1)
            self.assertEqual(updates_after_visibility_window[0].status, SessionStatus.NEEDS_ACTION)
            self.assertTrue(updates_after_visibility_window[0].view_ack_required)

    def test_qoder_anonymous_prompt_log_does_not_override_newer_completed_task_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            agent_log_path = Path(temp_dir) / "20260710T102318" / "questWindow" / "agent.log"
            quest_log_path = Path(temp_dir) / "20260710T102318" / "questWindow" / "quest.log"
            agent_log_path.parent.mkdir(parents=True)
            agent_log_path.write_text(
                "2026-07-10 10:59:57.244 [info] [ACPIntegration] ACP prompt sent successfully\n",
                encoding="utf-8",
            )
            quest_log_path.write_text(
                '2026-07-10 11:00:03.995 [info] task.status.update.afterRefresh {"taskId":"task-2.session.execution","pushedStatus":"Completed","refreshedStatus":"Completed","finalStatus":"Completed"}\n',
                encoding="utf-8",
            )
            rows = [
                "process_id=51005\tprocess_name=/Applications/Qo\tcommand=/Applications/Qoder CN.app/Contents/MacOS/Electron --aicoding-open-agents-window\tcpu_percent=0.0\tstat=S"
            ]

            updates = list(
                _classify_process_rows(
                    rows,
                    qoder_logs_dir=Path(temp_dir),
                    now=datetime(2026, 7, 10, 11, 0, 10).astimezone(timezone.utc),
                )
            )

            self.assertEqual(len(updates), 1)
            self.assertEqual(updates[0].status, SessionStatus.NEEDS_ACTION)
            self.assertEqual(updates[0].status_source, "qoder-log")

    def test_qoder_keeps_other_running_task_when_same_agent_log_later_records_completed_task(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "20260710T102318" / "questWindow" / "agent.log"
            log_path.parent.mkdir(parents=True)
            log_path.write_text(
                '2026-07-10 10:59:57.244 [info] [ChatPanel.acpBlocks] {"taskId":"task-2","sessionId":"task-2.session.execution","progressLen":456,"blocksLen":14,"state":"streaming"}\n'
                '2026-07-10 11:00:03.917 [info] [ACPProgressStateMachine] State transition: streaming -> completed, trigger: chat_finish:success:200, sessionId: task-1.session.execution\n',
                encoding="utf-8",
            )
            rows = [
                "process_id=51005\tprocess_name=/Applications/Qo\tcommand=/Applications/Qoder CN.app/Contents/MacOS/Electron --aicoding-open-agents-window\tcpu_percent=0.0\tstat=S"
            ]

            updates = list(
                _classify_process_rows(
                    rows,
                    qoder_logs_dir=Path(temp_dir),
                    now=datetime(2026, 7, 10, 11, 0, 10).astimezone(timezone.utc),
                )
            )

            by_id = {update.session_id: update for update in updates}
            self.assertEqual(set(by_id), {"qoder-task-1", "qoder-task-2"})
            self.assertEqual(by_id["qoder-task-1"].status, SessionStatus.NEEDS_ACTION)
            self.assertEqual(by_id["qoder-task-2"].status, SessionStatus.RUNNING)
            self.assertEqual(by_id["qoder-task-1"].status_source, "qoder-log")
            self.assertEqual(by_id["qoder-task-2"].status_source, "qoder-log")

    def test_qoder_completed_log_replaces_previous_running_poll_in_store(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "20260710T102318" / "window1" / "quest.log"
            log_path.parent.mkdir(parents=True)
            rows = [
                "process_id=51005\tprocess_name=/Applications/Qo\tcommand=/Applications/Qoder CN.app/Contents/MacOS/Electron --aicoding-open-agents-window\tcpu_percent=0.0\tstat=S"
            ]
            store = SessionStore()
            first_poll_at = datetime(2026, 7, 10, 10, 35, 0).astimezone(timezone.utc)
            second_poll_at = datetime(2026, 7, 10, 10, 35, 2).astimezone(timezone.utc)
            log_path.write_text(
                '2026-07-10 10:34:45.999 [info] task.status.update.afterRefresh {"taskId":"task-1.session.execution","finalStatus":"Running"}\n',
                encoding="utf-8",
            )
            store.replace_source_updates(
                "process",
                list(_classify_process_rows(rows, qoder_logs_dir=Path(temp_dir), now=first_poll_at)),
            )
            log_path.write_text(
                '2026-07-10 10:34:45.999 [info] task.status.update.afterRefresh {"taskId":"task-1.session.execution","finalStatus":"Running"}\n'
                '2026-07-10 10:34:59.500 [info] task.status.update.afterRefresh {"taskId":"task-1.session.execution","pushedStatus":"Running","finalStatus":"Completed"}\n',
                encoding="utf-8",
            )

            store.replace_source_updates(
                "process",
                list(_classify_process_rows(rows, qoder_logs_dir=Path(temp_dir), now=second_poll_at)),
            )

            sessions = store.sessions(now=second_poll_at)
            self.assertEqual(len(sessions), 1)
            self.assertEqual(sessions[0].status, SessionStatus.NEEDS_ACTION)
            self.assertTrue(sessions[0].view_ack_required)
            self.assertEqual(sessions[0].status_source, "qoder-log")

    def test_qoder_desktop_process_uses_latest_task_status_across_windows(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            older_log_path = Path(temp_dir) / "20260710T102318" / "window1" / "quest.log"
            newer_log_path = Path(temp_dir) / "20260710T102318" / "window2" / "quest.log"
            older_log_path.parent.mkdir(parents=True)
            newer_log_path.parent.mkdir(parents=True)
            older_log_path.write_text(
                '2026-07-10 10:25:58.542 [info] task.status.update.afterRefresh {"taskId":"task-1.session.execution","pushedStatus":"Running","finalStatus":"Completed"}\n',
                encoding="utf-8",
            )
            newer_log_path.write_text(
                '2026-07-10 10:26:10.100 [info] task.status.update.afterRefresh {"taskId":"task-2.session.execution","finalStatus":"Running"}\n',
                encoding="utf-8",
            )
            rows = [
                "process_id=51005\tprocess_name=/Applications/Qo\tcommand=/Applications/Qoder CN.app/Contents/MacOS/Electron --aicoding-open-agents-window\tcpu_percent=0.0\tstat=S"
            ]

            updates = list(
                _classify_process_rows(
                    rows,
                    qoder_logs_dir=Path(temp_dir),
                    now=datetime(2026, 7, 10, 10, 26, 20).astimezone(timezone.utc),
                )
            )

            by_id = {update.session_id: update for update in updates}
            self.assertEqual(set(by_id), {"qoder-task-1", "qoder-task-2"})
            self.assertEqual(by_id["qoder-task-1"].status, SessionStatus.NEEDS_ACTION)
            self.assertEqual(by_id["qoder-task-2"].status, SessionStatus.RUNNING)
            self.assertEqual(by_id["qoder-task-1"].status_source, "qoder-log")
            self.assertEqual(by_id["qoder-task-2"].status_source, "qoder-log")

    def test_qoder_recent_running_window_is_not_overridden_by_other_completed_window(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            running_log_path = Path(temp_dir) / "20260710T102318" / "window1" / "quest.log"
            completed_log_path = Path(temp_dir) / "20260710T102318" / "window2" / "quest.log"
            running_log_path.parent.mkdir(parents=True)
            completed_log_path.parent.mkdir(parents=True)
            running_log_path.write_text(
                '2026-07-10 10:26:10.100 [info] task.status.update.afterRefresh {"taskId":"task-1.session.execution","finalStatus":"Running"}\n',
                encoding="utf-8",
            )
            completed_log_path.write_text(
                '2026-07-10 10:27:20.100 [info] task.status.update.afterRefresh {"taskId":"task-2.session.execution","pushedStatus":"Running","finalStatus":"Completed"}\n',
                encoding="utf-8",
            )
            rows = [
                "process_id=51005\tprocess_name=/Applications/Qo\tcommand=/Applications/Qoder CN.app/Contents/MacOS/Electron --aicoding-open-agents-window\tcpu_percent=0.0\tstat=S"
            ]

            updates = list(
                _classify_process_rows(
                    rows,
                    qoder_logs_dir=Path(temp_dir),
                    now=datetime(2026, 7, 10, 10, 27, 30).astimezone(timezone.utc),
                )
            )

            by_id = {update.session_id: update for update in updates}
            self.assertEqual(set(by_id), {"qoder-task-1", "qoder-task-2"})
            self.assertEqual(by_id["qoder-task-1"].status, SessionStatus.RUNNING)
            self.assertEqual(by_id["qoder-task-2"].status, SessionStatus.NEEDS_ACTION)
            self.assertEqual(by_id["qoder-task-1"].status_source, "qoder-log")
            self.assertEqual(by_id["qoder-task-2"].status_source, "qoder-log")

    def test_qoder_after_refresh_falls_back_to_pushed_status_when_final_status_is_missing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "20260710T102318" / "window1" / "quest.log"
            log_path.parent.mkdir(parents=True)
            log_path.write_text(
                '2026-07-10 10:28:10.100 [info] task.status.update.afterRefresh {"taskId":"task-1.session.execution","pushedStatus":"Running"}\n',
                encoding="utf-8",
            )
            rows = [
                "process_id=51005\tprocess_name=/Applications/Qo\tcommand=/Applications/Qoder CN.app/Contents/MacOS/Electron --aicoding-open-agents-window\tcpu_percent=0.0\tstat=S"
            ]

            updates = list(
                _classify_process_rows(
                    rows,
                    qoder_logs_dir=Path(temp_dir),
                    now=datetime(2026, 7, 10, 10, 28, 20).astimezone(timezone.utc),
                )
            )

            self.assertEqual(len(updates), 1)
            self.assertEqual(updates[0].status, SessionStatus.RUNNING)
            self.assertEqual(updates[0].status_source, "qoder-log")

    def test_qoder_status_parser_accepts_in_progress_variants(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "20260710T102318" / "window1" / "quest.log"
            log_path.parent.mkdir(parents=True)
            log_path.write_text(
                '2026-07-10 10:29:10.100 [info] task.status.update.afterRefresh {"taskId":"task-1.session.execution","finalStatus":"InProgress"}\n',
                encoding="utf-8",
            )
            rows = [
                "process_id=51005\tprocess_name=/Applications/Qo\tcommand=/Applications/Qoder CN.app/Contents/MacOS/Electron --aicoding-open-agents-window\tcpu_percent=0.0\tstat=S"
            ]

            updates = list(
                _classify_process_rows(
                    rows,
                    qoder_logs_dir=Path(temp_dir),
                    now=datetime(2026, 7, 10, 10, 29, 20).astimezone(timezone.utc),
                )
            )

            self.assertEqual(len(updates), 1)
            self.assertEqual(updates[0].status, SessionStatus.RUNNING)
            self.assertEqual(updates[0].status_source, "qoder-log")

    def test_qoder_status_parser_treats_action_required_as_needs_action(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "20260710T102318" / "window1" / "quest.log"
            log_path.parent.mkdir(parents=True)
            log_path.write_text(
                '2026-07-10 10:21:19.052 [info] task.status.update {"taskId":"9ab90918-7c7f-4622-b477-94979f445fbd","status":"Running"}\n'
                '2026-07-10 10:21:21.459 [info] task.status.update {"taskId":"9ab90918-7c7f-4622-b477-94979f445fbd","status":"ActionRequired"}\n',
                encoding="utf-8",
            )
            rows = [
                "process_id=51005\tprocess_name=/Applications/Qo\tcommand=/Applications/Qoder.app/Contents/MacOS/Qoder\tcpu_percent=0.0\tstat=S"
            ]

            updates = list(
                _classify_process_rows(
                    rows,
                    qoder_logs_dir=Path(temp_dir),
                    now=datetime(2026, 7, 10, 10, 21, 25).astimezone(timezone.utc),
                )
            )

            self.assertEqual(len(updates), 1)
            self.assertEqual(updates[0].status, SessionStatus.NEEDS_ACTION)
            self.assertTrue(updates[0].view_ack_required)
            self.assertEqual(updates[0].status_source, "qoder-log")

    def test_qoder_needs_action_task_takes_priority_over_other_running_task(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "20260710T102318" / "window1" / "quest.log"
            log_path.parent.mkdir(parents=True)
            log_path.write_text(
                '2026-07-10 10:21:19.052 [info] task.status.update {"taskId":"task-running.session.execution","status":"Running"}\n'
                '2026-07-10 10:21:21.459 [info] task.status.update {"taskId":"task-waiting.session.execution","status":"ActionRequired"}\n',
                encoding="utf-8",
            )
            rows = [
                "process_id=51005\tprocess_name=/Applications/Qo\tcommand=/Applications/Qoder.app/Contents/MacOS/Qoder\tcpu_percent=0.0\tstat=S"
            ]

            updates = list(
                _classify_process_rows(
                    rows,
                    qoder_logs_dir=Path(temp_dir),
                    now=datetime(2026, 7, 10, 10, 21, 25).astimezone(timezone.utc),
                )
            )

            by_id = {update.session_id: update for update in updates}
            self.assertEqual(set(by_id), {"qoder-task-running", "qoder-task-waiting"})
            self.assertEqual(by_id["qoder-task-running"].status, SessionStatus.RUNNING)
            self.assertEqual(by_id["qoder-task-waiting"].status, SessionStatus.NEEDS_ACTION)
            self.assertEqual(by_id["qoder-task-running"].status_source, "qoder-log")
            self.assertEqual(by_id["qoder-task-waiting"].status_source, "qoder-log")

    def test_qoder_cn_desktop_ignores_regular_qoder_logs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cn_log_path = Path(temp_dir) / "QoderCN" / "logs" / "20260710T102318" / "window1" / "quest.log"
            regular_log_path = Path(temp_dir) / "Qoder" / "logs" / "20260710T102109" / "window1" / "quest.log"
            cn_log_path.parent.mkdir(parents=True)
            regular_log_path.parent.mkdir(parents=True)
            cn_log_path.write_text(
                '2026-07-10 11:00:03.940 [info] task.status.update.afterRefresh {"taskId":"task-cn.session.execution","pushedStatus":"Running","finalStatus":"Completed"}\n',
                encoding="utf-8",
            )
            regular_log_path.write_text(
                '2026-07-10 10:21:21.459 [info] task.status.update {"taskId":"regular-session","status":"ActionRequired"}\n',
                encoding="utf-8",
            )
            rows = [
                "process_id=51005\tprocess_name=/Applications/Qo\tcommand=/Applications/Qoder CN.app/Contents/MacOS/Electron --aicoding-open-agents-window\tcpu_percent=0.0\tstat=S"
            ]

            updates = list(
                _classify_process_rows(
                    rows,
                    qoder_logs_dirs=(cn_log_path.parents[2], regular_log_path.parents[2]),
                    now=datetime(2026, 7, 10, 11, 0, 10).astimezone(timezone.utc),
                )
            )

            self.assertEqual(len(updates), 1)
            self.assertEqual(updates[0].status, SessionStatus.NEEDS_ACTION)
            self.assertEqual(updates[0].status_source, "qoder-log")

    def test_regular_qoder_desktop_ignores_qoder_cn_logs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cn_log_path = Path(temp_dir) / "QoderCN" / "logs" / "20260710T102318" / "window1" / "quest.log"
            regular_log_path = Path(temp_dir) / "Qoder" / "logs" / "20260710T102109" / "window1" / "quest.log"
            cn_log_path.parent.mkdir(parents=True)
            regular_log_path.parent.mkdir(parents=True)
            cn_log_path.write_text(
                '2026-07-10 10:59:18.224 [info] task.status.update.afterRefresh {"taskId":"task-cn.session.execution","finalStatus":"Running"}\n',
                encoding="utf-8",
            )
            regular_log_path.write_text(
                '2026-07-10 10:21:29.448 [info] task.status.update.afterRefresh {"taskId":"regular-session","pushedStatus":"Running","finalStatus":"Completed"}\n',
                encoding="utf-8",
            )
            rows = [
                "process_id=51005\tprocess_name=/Applications/Qo\tcommand=/Applications/Qoder.app/Contents/MacOS/Qoder\tcpu_percent=0.0\tstat=S"
            ]

            updates = list(
                _classify_process_rows(
                    rows,
                    qoder_logs_dirs=(cn_log_path.parents[2], regular_log_path.parents[2]),
                    now=datetime(2026, 7, 10, 10, 21, 35).astimezone(timezone.utc),
                )
            )

            self.assertEqual(len(updates), 1)
            self.assertEqual(updates[0].status, SessionStatus.NEEDS_ACTION)
            self.assertEqual(updates[0].status_source, "qoder-log")

    def test_qoder_log_scan_prefers_recently_modified_session_dirs_over_names(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            rows = [
                "process_id=51005\tprocess_name=/Applications/Qo\tcommand=/Applications/Qoder CN.app/Contents/MacOS/Electron --aicoding-open-agents-window\tcpu_percent=0.0\tstat=S"
            ]
            for index in range(8):
                stale_log = Path(temp_dir) / f"zz-stale-{index}" / "window1" / "quest.log"
                stale_log.parent.mkdir(parents=True)
                stale_log.write_text(
                    '2026-07-10 10:29:00.000 [info] task.status.update.afterRefresh {"taskId":"stale.session.execution","finalStatus":"Completed"}\n',
                    encoding="utf-8",
                )
            active_log = Path(temp_dir) / "aa-active" / "window1" / "quest.log"
            active_log.parent.mkdir(parents=True)
            active_log.write_text(
                '2026-07-10 10:30:10.100 [info] task.status.update.afterRefresh {"taskId":"active.session.execution","finalStatus":"Running"}\n',
                encoding="utf-8",
            )

            updates = list(
                _classify_process_rows(
                    rows,
                    qoder_logs_dir=Path(temp_dir),
                    source_started_at=datetime(2026, 7, 10, 10, 30, 0).astimezone(timezone.utc),
                    now=datetime(2026, 7, 10, 10, 30, 20).astimezone(timezone.utc),
                )
            )

            self.assertEqual(len(updates), 1)
            self.assertEqual(updates[0].status, SessionStatus.RUNNING)
            self.assertEqual(updates[0].status_source, "qoder-log")

    def test_qoder_stale_running_status_log_falls_back_to_idle_desktop_process(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "20260710T102318" / "window1" / "quest.log"
            log_path.parent.mkdir(parents=True)
            log_path.write_text(
                '2026-07-10 10:00:00.000 [info] task.status.update.afterRefresh {"taskId":"task-1.session.execution","finalStatus":"Running"}\n',
                encoding="utf-8",
            )
            rows = [
                "process_id=51005\tprocess_name=/Applications/Qo\tcommand=/Applications/Qoder CN.app/Contents/MacOS/Electron --aicoding-open-agents-window\tcpu_percent=0.0\tstat=S"
            ]

            updates = list(
                _classify_process_rows(
                    rows,
                    qoder_logs_dir=Path(temp_dir),
                    now=datetime(2026, 7, 10, 10, 20, 1).astimezone(timezone.utc),
                )
            )

            self.assertEqual(len(updates), 1)
            self.assertEqual(updates[0].status, SessionStatus.IDLE)
            self.assertEqual(updates[0].status_source, "desktop-process")

    def test_process_without_cwd_falls_back_to_cli_title(self):
        rows = ["process_id=27876\tprocess_name=claude\tcommand=claude"]

        updates = list(_classify_process_rows(rows))

        self.assertEqual(updates[0].title, "Claude Code CLI")

    def test_posix_process_command_filters_before_cwd_lookup(self):
        script = _posix_process_command()[-1]

        self.assertLess(script.index('case "$exe" in'), script.index("lsof -a -p"))
        self.assertLess(script.index("active_child_count=0\\tfocus_process_id"), script.index("lsof -a -p"))
        self.assertIn('exe_raw=${comm##*/}', script)
        self.assertIn("claude|claude.exe", script)
        self.assertIn("codex|codex.exe", script)
        self.assertIn("focus_process_id=%s", script)
        self.assertIn("focus_app_name=%s", script)
        self.assertNotIn("/codex.app/contents/macos/codex", script)
        self.assertIn("/claude.app/contents/macos/claude", script)
        self.assertIn("/Zed.app/", script)
        self.assertIn("/Cursor.app/", script)
        self.assertIn("Visual\\ Studio\\ Code*.app", script)
        self.assertIn("IntelliJ\\ IDEA*.app", script)
        self.assertIn("/PyCharm*.app/", script)
        self.assertIn("/Windsurf.app/", script)

    def test_posix_process_command_includes_configured_ai_tools(self):
        script = _posix_process_command()[-1]

        self.assertIn("gemini|gemini.exe", script)
        self.assertIn("cursor-agent|cursor-agent.exe", script)
        self.assertIn("qwen|qwen-code|qwen.exe", script)
        self.assertIn("opencode|opencode.exe", script)
        self.assertIn("workbuddy|workbuddy.exe|codebuddy|codebuddy.exe", script)
        self.assertIn("qoder|qoder.exe|qodercn|qodercn.exe", script)
        self.assertIn("/chatgpt.app/contents/macos/chatgpt", script)
        self.assertIn("/perplexity.app/contents/macos/perplexity", script)
        self.assertIn("/workbuddy.app/contents/macos/workbuddy", script)
        self.assertIn("/workbuddy.app/contents/macos/electron", script)
        self.assertIn("/qoder.app/contents/macos/qoder", script)
        self.assertIn("/qoder.app/contents/macos/electron", script)
        self.assertIn("qodercn|qodercn.exe", script)
        self.assertIn("/qoder\\ cn.app/contents/macos/electron", script)

    def test_posix_process_command_skips_ignored_desktop_helpers_before_emit(self):
        script = _posix_process_command()[-1]

        self.assertIn("ignored_desktop_process=0", script)
        self.assertIn('if [ "$shell_process" = "0" ] && [ "$ignored_desktop_process" = "0" ]; then', script)
        self.assertIn("/main/daemon-app-server-entry.js", script)
        self.assertIn("/main/sidecar-entry.js", script)
        self.assertIn("/cli/bin/codebuddy\\ --serve", script)
        self.assertIn("mcp-app-bootstrap.cjs", script)

    def test_posix_process_command_matches_desktop_app_paths_with_spaces(self):
        script = _posix_process_command()[-1]

        self.assertIn("args_lc=$(printf '%s' \"$args\"", script)
        self.assertIn('case "$args" in *.app/Contents/MacOS/*|*.app/contents/macos/*)', script)
        self.assertIn('case "$exe:$args_lc" in', script)
        self.assertIn("/qoder\\ cn.app/contents/macos/electron*", script)
        self.assertIn('case "$exe_raw" in sh|bash|zsh|fish) shell_process=1 ;;', script)

    def test_posix_process_command_skips_lsof_for_claude_cli(self):
        script = _posix_process_command()[-1]

        self.assertIn('case "$exe" in claude|claude.exe) ;; *) cwd=$(lsof -a -p', script)

    def test_posix_process_command_skips_terminating_rows_before_expensive_lookup(self):
        script = _posix_process_command()[-1]

        terminating_filter = 'case "$stat" in Z*|?*E*) continue ;; esac;'
        self.assertIn(terminating_filter, script)
        self.assertLess(script.index(terminating_filter), script.index("lsof -a -p"))

    def test_posix_process_command_resets_cwd_before_each_cli_lookup(self):
        script = _posix_process_command()[-1]

        reset_index = script.index('cwd=; case "$exe" in claude|claude.exe)')
        emit_index = script.index("printf 'process_id=%s\\tprocess_name=%s\\tcommand=%s\\tcwd=%s")
        self.assertLess(reset_index, emit_index)

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

        self.assertIn('case "$exe" in claude|claude.exe) active_children=0 ;; *) active_children=$(printf', script)

    def test_posix_process_command_ignores_background_mcp_helpers_for_activity(self):
        script = _posix_process_command()[-1]

        self.assertIn("background_ai_helper", script)
        self.assertIn("mcp", script)
        self.assertIn("tavily", script)
        self.assertIn("searxng", script)
        self.assertIn("next", script)

    def test_external_source_timeout_allows_macos_cwd_lookup_within_poll_budget(self):
        self.assertGreaterEqual(SOURCE_COMMAND_TIMEOUT_SECONDS, 4.0)
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
