"""Parse desktop question identities, without retaining question or answer text."""
from __future__ import annotations

import json
from typing import Optional, Set


def canonical_question_id(value) -> Optional[str]:
    if not isinstance(value, str):
        return None
    try:
        parts = json.loads(value)
    except ValueError:
        return None
    if (not isinstance(parts, list) or len(parts) != 3
            or parts[0] != "request_user_input_async"
            or not isinstance(parts[1], str) or not parts[1]
            or type(parts[2]) is not int or parts[2] < 0):
        return None
    return json.dumps(parts, separators=(",", ":"))


def async_question_ids(payload: dict) -> Set[str]:
    name = str(payload.get("name") or payload.get("tool_name") or "")
    name = name.replace("-", "_").rsplit(".", 1)[-1].rsplit("/", 1)[-1].lower()
    if payload.get("type") in {"function_call", "custom_tool_call"} and name == "request_user_input_async":
        call_id = payload.get("call_id") or payload.get("id")
        arguments = payload.get("arguments", payload.get("input"))
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except ValueError:
                return set()
        questions = arguments.get("questions") if isinstance(arguments, dict) else None
    elif payload.get("type") == "AgentMessage" and payload.get("delivery") == "async":
        call_id, questions = payload.get("id"), payload.get("questions")
    else:
        return set()
    if not isinstance(call_id, str) or not call_id or not isinstance(questions, list):
        return set()
    return {json.dumps(["request_user_input_async", call_id, index], separators=(",", ":"))
            for index, question in enumerate(questions) if isinstance(question, dict)}


def answered_question_ids(record_type: str, payload: dict) -> Set[str]:
    text = None
    if record_type == "event_msg" and payload.get("type") == "user_message":
        text = payload.get("message")
    elif record_type == "response_item" and payload.get("type") == "message" and payload.get("role") == "user":
        content = payload.get("content")
        if isinstance(content, list) and len(content) == 1 and isinstance(content[0], dict):
            if content[0].get("type") in {"input_text", "text"}:
                text = content[0].get("text")
    if not isinstance(text, str):
        return set()
    text = text.strip()
    opening, closing = "<send_user_message_question_reply>", "</send_user_message_question_reply>"
    if not text.startswith(opening) or not text.endswith(closing):
        return set()
    try:
        answers = json.loads(text[len(opening):-len(closing)])
    except ValueError:
        return set()
    if isinstance(answers, dict):
        answers = [answers]
    if not isinstance(answers, list):
        return set()
    result = set()
    for answer in answers:
        if (not isinstance(answer, dict) or not isinstance(answer.get("question"), str)
                or not isinstance(answer.get("answer"), str)):
            continue
        identity = canonical_question_id(answer.get("questionItemId"))
        if identity is not None:
            result.add(identity)
    return result


def rejected_async_call(payload: dict) -> bool:
    output = payload.get("output")
    if isinstance(output, str):
        try:
            output = json.loads(output)
        except ValueError:
            return False
    return isinstance(output, dict) and (output.get("accepted") is False or bool(output.get("error")))


def question_lifecycle_record(record: dict) -> Optional[dict]:
    """Keep only lifecycle fields needed when a record leaves the rollout tail."""
    payload = record.get("payload")
    if not isinstance(payload, dict):
        return None
    kind = payload.get("type")
    clean = None
    if kind in {"task_started", "task_complete", "turn_aborted"}:
        clean = {"type": kind}
        if isinstance(payload.get("turn_id"), str):
            clean["turn_id"] = payload["turn_id"]
    elif kind in {"function_call_output", "custom_tool_call_output"} and rejected_async_call(payload):
        clean = {"type": kind, "call_id": payload.get("call_id") or payload.get("id"),
                 "output": {"accepted": False}}
    questions = async_question_ids(payload)
    item = payload.get("item")
    if record.get("type") == "event_msg" and kind == "item_completed" and isinstance(item, dict):
        questions.update(async_question_ids(item))
    if questions:
        identities = [json.loads(identity) for identity in questions]
        indices = {identity[2] for identity in identities}
        clean = {"type": "function_call", "name": "request_user_input_async", "call_id": identities[0][1],
                 "arguments": {"questions": [{} if index in indices else None for index in range(max(indices) + 1)]}}
        if kind == "item_completed":
            clean = {"type": "item_completed", "item": {"type": "AgentMessage", "id": identities[0][1],
                     "delivery": "async", "questions": clean["arguments"]["questions"]}}
    answers = answered_question_ids(str(record.get("type")), payload)
    if answers:
        body = [{"questionItemId": identity, "question": "", "answer": ""} for identity in sorted(answers)]
        clean = {"type": "user_message", "message": "<send_user_message_question_reply>\n"
                 + json.dumps(body) + "\n</send_user_message_question_reply>"}
        return {"timestamp": record.get("timestamp"), "type": "event_msg", "payload": clean}
    if clean is None:
        return None
    return {"timestamp": record.get("timestamp"), "type": record.get("type"), "payload": clean}
