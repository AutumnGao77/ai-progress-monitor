"""Bounded, incremental rollout lifecycle replay; no conversation text is cached."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Optional

from .chatgpt_questions import question_lifecycle_record


def has_visible_content(payload: dict) -> bool:
    """Recognize displayed content; replay stores only this boolean, never text."""
    if type(payload.get("_has_visible_content")) is bool:
        return payload["_has_visible_content"]
    if any(isinstance(payload.get(key), str) and payload[key].strip()
           for key in ("message", "text")):
        return True
    content = payload.get("content")
    if isinstance(content, str):
        return bool(content.strip())
    if not isinstance(content, list):
        return False
    for part in content:
        if not isinstance(part, dict):
            continue
        kind = str(part.get("type", "")).lower()
        if kind in {"text", "output_text", "refusal"}:
            value = part.get("text") if kind != "refusal" else part.get("refusal")
            if isinstance(value, str) and value.strip():
                return True
        elif kind in {"image", "image_url", "output_image", "audio", "output_audio", "file"}:
            if any(part.get(key) for key in ("image_url", "url", "data", "file_id", "audio")):
                return True
    return False


def lifecycle_record(record: dict) -> Optional[dict]:
    question = question_lifecycle_record(record)
    if question is not None:
        item = question["payload"].get("item")
        if isinstance(item, dict) and item.get("type") == "AgentMessage":
            item["_has_visible_content"] = has_visible_content(record["payload"]["item"])
        return question
    payload = record.get("payload")
    if not isinstance(payload, dict):
        return None
    kind = payload.get("type")
    clean = None
    if kind in {"approval_requested", "apply_patch_approval_requested", "exec_approval_requested",
                "user_input_requested", "agent_message", "reasoning", "token_count"}:
        clean = {"type": kind}
        if kind == "agent_message":
            clean["_has_visible_content"] = has_visible_content(payload)
    elif kind == "item_completed" and record.get("type") == "event_msg":
        item = payload.get("item")
        if isinstance(item, dict) and item.get("type") == "AgentMessage":
            clean = {"type": "agent_message", "_has_visible_content": has_visible_content(item)}
    elif kind == "message" and record.get("type") == "response_item" and payload.get("role") == "assistant":
        clean = {"type": "message", "role": "assistant", "_has_visible_content": has_visible_content(payload)}
    elif kind in {"function_call", "custom_tool_call"}:
        clean = {"type": kind, "name": payload.get("name") or payload.get("tool_name"),
                 "call_id": payload.get("call_id") or payload.get("id")}
    elif kind in {"function_call_output", "custom_tool_call_output"}:
        clean = {"type": kind, "call_id": payload.get("call_id") or payload.get("id")}
    if clean is None:
        return None
    return {"timestamp": record.get("timestamp"), "type": record.get("type"), "payload": clean}


class LifecycleHistory:
    """Incrementally cover the gap between rollout head and tail, in memory only."""
    def __init__(self):
        self.inode = None
        self.offset = 0
        self.size = 0
        self.fragment = b""
        self.skipping = False
        self.records = []
        self.bytes_read = 0

    def read_middle(self, path: Path, head_bytes: int, tail_bytes: int, budget: int, deadline=None):
        self.bytes_read = 0
        try:
            with path.open("rb") as handle:
                stat = os.fstat(handle.fileno())
                if self.inode != stat.st_ino or stat.st_size < self.size:
                    self.__init__()
                    self.inode = stat.st_ino
                self.size = stat.st_size
                if stat.st_size <= head_bytes + tail_bytes:
                    return []
                if not self.offset:
                    head = handle.read(head_bytes)
                    self.offset = head.rfind(b"\n") + 1
                # Include the line crossing the tail boundary: the tail reader
                # cannot parse its truncated first line on its own.
                handle.seek(stat.st_size - tail_bytes)
                handle.readline(1024 * 1024)
                end = handle.tell()
                handle.seek(self.offset)
                while self.offset < end and self.bytes_read < budget:
                    if deadline is not None and time.monotonic() >= deadline:
                        return None
                    data = handle.read(min(1024 * 1024, end - self.offset, budget - self.bytes_read))
                    if not data:
                        return None
                    self.offset += len(data)
                    self.bytes_read += len(data)
                    parts = data.split(b"\n")
                    for index, part in enumerate(parts):
                        if not self.skipping:
                            if len(self.fragment) + len(part) > 1024 * 1024:
                                self.fragment = b""
                                self.skipping = True
                            else:
                                self.fragment += part
                        if index < len(parts) - 1:
                            if not self.skipping:
                                try:
                                    record = json.loads(self.fragment)
                                except (ValueError, UnicodeDecodeError):
                                    record = None
                                if isinstance(record, dict):
                                    clean = lifecycle_record(record)
                                    if clean is not None:
                                        self._remember(clean)
                            self.fragment = b""
                            self.skipping = False
                return self.records if self.offset >= end else None
        except OSError:
            return None

    def _remember(self, record: dict) -> None:
        kind = record["payload"].get("type")
        if kind == "task_started":
            # Older turns cannot affect the current turn. Keeping their text-
            # free records forever would still grow memory over long runtimes.
            self.records.clear()
        elif kind in {"task_complete", "turn_aborted"}:
            started = None
            visible = None
            for item in self.records:
                payload = item["payload"]
                if payload.get("type") == "task_started":
                    started = item
                if (payload.get("type") in {"agent_message", "message", "item_completed"}
                        and has_visible_content(payload.get("item", payload))):
                    visible = item
            self.records = [item for item in (started, visible) if item is not None]
        self.records.append(record)
