from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .classifier import classify_session_text
from .models import SessionStatus


class TerminalBridge:
    def __init__(
        self,
        session_id: str,
        title: str,
        tool: str,
        session_dir: Path,
        response_dir: Path,
        surface: str = "terminal",
    ):
        self.session_id = session_id
        self.title = title
        self.tool = tool
        self.surface = surface
        self.session_dir = session_dir
        self.response_dir = response_dir
        self.process_id: Optional[int] = None
        self.process_name: Optional[str] = None
        self.focus_process_id: Optional[int] = None
        self.focus_app_name: Optional[str] = None
        self._recent_output = ""
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.response_dir.mkdir(parents=True, exist_ok=True)

    def set_process_metadata(
        self,
        process_id: Optional[int],
        process_name: Optional[str] = None,
        focus_process_id: Optional[int] = None,
        focus_app_name: Optional[str] = None,
    ) -> None:
        self.process_id = process_id
        self.process_name = process_name
        self.focus_process_id = focus_process_id
        self.focus_app_name = focus_app_name

    def mark_running(self, summary: str) -> None:
        self._write_event(SessionStatus.RUNNING.value, clean_terminal_text(summary))

    def process_output(self, text: str) -> None:
        text = clean_terminal_text(text)
        if not text:
            return
        self._recent_output = _trim_recent_output(f"{self._recent_output}\n{text}")
        update = classify_session_text(self.title, self._recent_output, self.session_id)
        payload = {
            "session_id": self.session_id,
            "title": self.title,
            "tool": self.tool,
            "surface": self.surface,
            "status": update.status.value,
            "summary": update.summary,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if update.safe_action is not None:
            payload["safe_action"] = {
                "kind": update.safe_action.kind.value,
                "options": list(update.safe_action.options),
                "prompt": update.safe_action.prompt,
            }
        self._write_payload(payload)

    def consume_response(self) -> Optional[str]:
        path = self.response_dir / f"{self._safe_session_id()}.response"
        if not path.exists():
            return None
        value = path.read_text(encoding="utf-8").strip()
        path.unlink()
        return value or None

    def mark_finished(self, exit_code: int) -> None:
        status = SessionStatus.IDLE if exit_code == 0 else SessionStatus.STUCK
        self._write_event(status.value, f"Process exited with code {exit_code}")

    def _write_event(self, status: str, summary: str) -> None:
        self._write_payload(
            {
                "session_id": self.session_id,
                "title": self.title,
                "tool": self.tool,
                "surface": self.surface,
                "status": status,
                "summary": clean_terminal_text(summary),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )

    def _write_payload(self, payload: dict) -> None:
        if self.process_id is not None:
            payload["process_id"] = self.process_id
        if self.process_name:
            payload["process_name"] = self.process_name
        if self.focus_process_id is not None:
            payload["focus_process_id"] = self.focus_process_id
        if self.focus_app_name:
            payload["focus_app_name"] = self.focus_app_name
        path = self.session_dir / f"{self._safe_session_id()}.json"
        temp_path = path.with_suffix(".json.tmp")
        temp_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
        temp_path.replace(path)

    def _safe_session_id(self) -> str:
        return "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in self.session_id)


ANSI_CONTROL_RE = re.compile(
    r"\x1b\][^\x07]*(?:\x07|\x1b\\)|"
    r"\x1b[@-Z\\-_]|"
    r"\x1b\[[0-?]*[ -/]*[@-~]"
)
VISIBLE_ANSI_FRAGMENT_RE = re.compile(r"(?:\ufffd|\?)\[[0-?;]*[ -/]*[@-~]")
STALE_ANSI_FRAGMENT_RE = re.compile(r"\[(?:[0-?;]+[ -/]*[@-~]|[ABCDHJKm])")
NON_PRINTABLE_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
MAX_RECENT_OUTPUT_CHARS = 4000


def clean_terminal_text(text: str) -> str:
    cleaned = ANSI_CONTROL_RE.sub("", text)
    cleaned = VISIBLE_ANSI_FRAGMENT_RE.sub("", cleaned)
    cleaned = STALE_ANSI_FRAGMENT_RE.sub("", cleaned)
    cleaned = cleaned.replace("\ufffd", "")
    cleaned = NON_PRINTABLE_RE.sub("", cleaned)
    return " ".join(part for part in cleaned.strip().split())


def _trim_recent_output(text: str) -> str:
    text = text.strip()
    if len(text) <= MAX_RECENT_OUTPUT_CHARS:
        return text
    return text[-MAX_RECENT_OUTPUT_CHARS:]
