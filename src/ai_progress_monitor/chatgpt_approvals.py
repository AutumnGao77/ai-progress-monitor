"""Recover desktop approval lifecycles without persisting conversation content."""
from __future__ import annotations

import json
import os
import platform
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, Optional, Tuple

from .models import SessionStatus
from .chatgpt_questions import canonical_question_id


DEFAULT_APPROVAL_LOG_DIRECTORY = Path.home() / "Library" / "Logs" / "com.openai.codex"
_LOG_NAME = re.compile(
    r"codex-desktop-([a-f0-9-]{36})-(\d+)-t0-i\d+-(\d+)-(\d+)\.log$"
)
_READ_CHUNK_BYTES = 1024 * 1024
_POLL_BYTE_BUDGET = 8 * _READ_CHUNK_BYTES
_MAX_LINE_BYTES = 64 * 1024


def _process_alive(pid: int) -> Optional[bool]:
    # os.kill(pid, 0) is not a harmless probe on Windows. This log format is macOS-only.
    if platform.system() != "Darwin":
        return False
    try:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "comm="],
            capture_output=True, text=True, timeout=0.5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode == 1 and not result.stderr.strip():
        return False
    if result.returncode != 0:
        return None
    # A recycled PID or the retired Codex.app must not resurrect desktop sessions.
    return result.stdout.strip().casefold().endswith("/chatgpt.app/contents/macos/chatgpt")


@dataclass(frozen=True)
class DesktopSessionSignal:
    status: SessionStatus
    updated_at: datetime
    view_ack_required: bool = False
    turn_id: Optional[str] = None


@dataclass
class _LogCursor:
    inode: int
    offset: int = 0
    fragment: bytes = b""
    skipping_line: bool = False


@dataclass(frozen=True)
class _Event:
    timestamp: datetime
    process: str
    kind: str
    thread: Optional[str] = None
    request: Optional[str] = None
    turn_id: Optional[str] = None


class DesktopApprovalLog:
    def __init__(
        self, directory: Path = DEFAULT_APPROVAL_LOG_DIRECTORY,
        process_alive: Callable[[int], Optional[bool]] = _process_alive,
    ):
        self.directory = directory
        self.process_alive = process_alive
        self._cursors: Dict[Path, _LogCursor] = {}
        self._pending: Dict[Tuple[str, str], Tuple[str, datetime]] = {}
        self._questions: Dict[Tuple[str, str, str], datetime] = {}
        self._states: Dict[Tuple[str, str], DesktopSessionSignal] = {}
        self._tracked = set()
        self.session_signals: Dict[str, DesktopSessionSignal] = {}
        self.live_processes = frozenset()

    def poll(self) -> Optional[Dict[str, datetime]]:
        """Return pending requests, or None while catching up/unable to read.

        Read every retained byte of live-app logs, with bounded work per poll.
        Publish only complete snapshots so historical requests are not flashed
        while their matching responses are still in the unread backlog.
        """
        files = []
        alive: Dict[int, Optional[bool]] = {}
        newest_process = {}
        try:
            for path in self.directory.glob("**/codex-desktop-*-t0-*.log"):
                match = _LOG_NAME.fullmatch(path.name)
                if match is None:
                    continue
                pid = int(match[2])
                if pid not in alive:
                    alive[pid] = self.process_alive(pid)
                if alive[pid] is None:
                    return None
                if not alive[pid]:
                    continue
                stat = path.stat()
                process = match[1] + "-" + match[2]
                order = (str(path.parent), match[3], int(match[4]))
                files.append((order, path, process, stat, pid))
                previous = newest_process.get(pid)
                if previous is None or stat.st_mtime_ns > previous[0]:
                    newest_process[pid] = (stat.st_mtime_ns, process)
        except OSError:
            return None
        # A PID can be reused by a later ChatGPT process. Keep its newest log identity.
        files = [entry for entry in files if entry[2] == newest_process[entry[4]][1]]
        live = {entry[2] for entry in files}
        self._pending = {key: value for key, value in self._pending.items() if key[0] in live}
        self._questions = {key: value for key, value in self._questions.items() if key[0] in live}
        self._states = {key: value for key, value in self._states.items() if key[0] in live}
        self._tracked = {key for key in self._tracked if key[0] in live}
        paths = {entry[1] for entry in files}
        self._cursors = {path: cursor for path, cursor in self._cursors.items() if path in paths}
        reset = {
            process for _, path, process, stat, _ in files
            if path in self._cursors and (
                self._cursors[path].inode != stat.st_ino or self._cursors[path].offset > stat.st_size
            )
        }
        if reset:
            self._pending = {key: value for key, value in self._pending.items() if key[0] not in reset}
            self._questions = {key: value for key, value in self._questions.items() if key[0] not in reset}
            self._states = {key: value for key, value in self._states.items() if key[0] not in reset}
            self._tracked = {key for key in self._tracked if key[0] not in reset}
            for _, path, process, _, _ in files:
                if process in reset:
                    self._cursors.pop(path, None)
        budget = _POLL_BYTE_BUDGET
        events = []
        complete = True
        ordered = sorted(files, key=lambda entry: entry[0])
        last_paths = {process: path for _, path, process, _, _ in ordered}
        for _, path, process, stat, _ in ordered:
            cursor = self._cursors.setdefault(path, _LogCursor(stat.st_ino))
            try:
                with path.open("rb") as handle:
                    if os.fstat(handle.fileno()).st_ino != cursor.inode:
                        complete = False
                        continue
                    handle.seek(cursor.offset)
                    while cursor.offset < stat.st_size and budget > 0:
                        data = handle.read(min(_READ_CHUNK_BYTES, budget, stat.st_size - cursor.offset))
                        if not data:
                            break
                        cursor.offset += len(data)
                        budget -= len(data)
                        events.extend(self._read_lines(data, cursor, process))
                    if cursor.offset == stat.st_size and path != last_paths[process]:
                        # A rotated file may end with a torn line that will never
                        # be completed. Its successor is the active append target.
                        cursor.fragment = b""
                        cursor.skipping_line = False
                    if cursor.offset < stat.st_size or cursor.fragment or cursor.skipping_line:
                        complete = False
            except OSError:
                complete = False
        # Append order is authoritative within each app's ordered log files.
        # Wall-clock corrections must never move a response before its request.
        for event in events:
            self._apply(event)
        if not complete:
            return None
        self.live_processes = frozenset(live)
        return self._publish()

    def _publish(self) -> Dict[str, datetime]:
        signals = {}
        for (_, thread), state in self._states.items():
            if thread not in signals or state.updated_at >= signals[thread].updated_at:
                signals[thread] = state
        pending: Dict[str, datetime] = {}
        for thread, timestamp in self._pending.values():
            if thread not in pending or timestamp > pending[thread]:
                pending[thread] = timestamp
        for (_, thread, _), timestamp in self._questions.items():
            if thread not in pending or timestamp > pending[thread]:
                pending[thread] = timestamp
        for thread, timestamp in pending.items():
            signals[thread] = DesktopSessionSignal(SessionStatus.NEEDS_ACTION, timestamp)
        self.session_signals = signals
        return pending

    def _read_lines(self, data: bytes, cursor: _LogCursor, process: str):
        parts = data.split(b"\n")
        for index, part in enumerate(parts):
            terminated = index < len(parts) - 1
            if not cursor.skipping_line:
                if len(cursor.fragment) + len(part) > _MAX_LINE_BYTES:
                    cursor.fragment = b""
                    cursor.skipping_line = True
                else:
                    cursor.fragment += part
            if terminated:
                if not cursor.skipping_line:
                    event = self._event(cursor.fragment.decode("utf-8", errors="replace"), process)
                    if event is not None:
                        yield event
                cursor.fragment = b""
                cursor.skipping_line = False

    def _apply(self, event: _Event) -> None:
        if event.kind == "question":
            self._questions.setdefault((event.process, event.thread, event.request),
                                       self._signal_time(event.process, event.thread, event.timestamp))
            self._tracked.add((event.process, event.thread))
        elif event.kind == "request":
            key = (event.process, event.request)
            self._pending[key] = (event.thread, self._signal_time(event.process, event.thread, event.timestamp))
            self._tracked.add((event.process, event.thread))
        elif event.kind in {"response", "abort"}:
            pending = self._pending.pop((event.process, event.request), None)
            if pending is not None:
                thread, requested_at = pending
                self._states[(event.process, thread)] = DesktopSessionSignal(
                    SessionStatus.IDLE if event.kind == "abort" else SessionStatus.RUNNING,
                    self._signal_time(event.process, thread, max(event.timestamp, requested_at)),
                )
        elif event.kind == "complete":
            key = (event.process, event.thread)
            # Only supplement conversations observed through explicit approvals.
            # Other desktop/internal notifications must not create new bubbles.
            if key in self._tracked:
                timestamp = self._signal_time(event.process, event.thread, event.timestamp)
                self._pending = {
                    pending_key: value for pending_key, value in self._pending.items()
                    if pending_key[0] != event.process or value[0] != event.thread
                }
                self._questions = {question: value for question, value in self._questions.items()
                                   if question[:2] != key}
                self._states[key] = DesktopSessionSignal(
                    SessionStatus.NEEDS_ACTION, timestamp, view_ack_required=True,
                    turn_id=event.turn_id,
                )

    def _signal_time(self, process: str, thread: str, timestamp: datetime) -> datetime:
        state = self._states.get((process, thread))
        times = [timestamp] + ([state.updated_at] if state is not None else [])
        times.extend(value[1] for key, value in self._pending.items()
                     if key[0] == process and value[0] == thread)
        times.extend(value for key, value in self._questions.items() if key[:2] == (process, thread))
        return max(times)

    def resolve_questions(self, thread: str, answers: Dict[str, datetime]) -> None:
        for key, requested_at in list(self._questions.items()):
            process, question_thread, question = key
            if question_thread == thread and question in answers:
                timestamp = self._signal_time(process, thread, max(requested_at, answers[question]))
                del self._questions[key]
                self._states[(process, thread)] = DesktopSessionSignal(SessionStatus.RUNNING, timestamp)
        self._publish()

    def has_questions(self, thread: str) -> bool:
        return any(key[1] == thread for key in self._questions)

    def dismiss_through(self, thread: str, timestamp: datetime) -> None:
        self._questions = {key: value for key, value in self._questions.items()
                           if key[1] != thread or value > timestamp}
        self._pending = {
            key: value for key, value in self._pending.items()
            if value[0] != thread or value[1] > timestamp
        }
        self._states = {
            key: value for key, value in self._states.items()
            if key[1] != thread or value.updated_at > timestamp
        }

    @staticmethod
    def _event(line: str, process: str) -> Optional[_Event]:
        header = re.match(r"^\S+ \w+ \[(electron-message-handler|notifications-service)\] (.*)$", line)
        if header is None:
            return None
        message = header[2]
        thread = None
        request = None
        turn_id = None
        if header[1] == "notifications-service":
            prefix = "[desktop-notifications] forward show kind=question notificationId=async-question-"
            if not message.startswith(prefix):
                return None
            try:
                identity = json.loads(message[len(prefix):])
            except ValueError:
                return None
            if (not isinstance(identity, list) or len(identity) != 6 or identity[2] != "local"
                    or not isinstance(identity[3], str) or not re.fullmatch(r"[\w-]+", identity[3])):
                return None
            thread, request = identity[3], canonical_question_id(identity[5])
            if request is None:
                return None
            kind = "question"
        elif message.startswith("[desktop-notifications] received approval "):
            conversation = re.search(r"\bconversationId=([\w-]+)\b", message)
            request_match = re.search(r"\brequestId=([\w-]+)\b", message)
            if conversation is None or request_match is None:
                return None
            thread, request = conversation[1], request_match[1]
            kind = "request"
        elif message.startswith("Sending server response ") and re.search(
            r"\bmethod=item/[^ ]+/(?:requestApproval|requestUserInput)\b", message
        ):
            request_match = re.search(r"\bid=([\w-]+)\b", message)
            if request_match is None:
                return None
            request = request_match[1]
            kind = "response"
            try:
                response = json.loads(message.split(" response=", 1)[1])
                if isinstance(response, dict) and response.get("decision") == "abort":
                    kind = "abort"
            except (IndexError, ValueError):
                return None
        elif message.startswith("[desktop-notifications] received turn-complete "):
            conversation = re.search(r"\bconversationId=([\w-]+)\b", message)
            if conversation is None:
                return None
            thread, kind = conversation[1], "complete"
            turn_match = re.search(r"\bturnId=([\w-]+)\b", message)
            turn_id = turn_match[1] if turn_match is not None else None
        else:
            return None
        try:
            timestamp = datetime.fromisoformat(line.split(" ", 1)[0].replace("Z", "+00:00"))
            if timestamp.tzinfo is None:
                return None
        except ValueError:
            return None
        return _Event(timestamp, process, kind, thread, request, turn_id)
