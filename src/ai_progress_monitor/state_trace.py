"""Small, content-free traces for changes in visible session state."""
from __future__ import annotations

import hashlib
import json
import logging
import sys

from .models import session_instance_key


LOGGER = logging.getLogger("ai_progress_monitor.state")


def configure_state_logging() -> None:
    if not LOGGER.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter("%(message)s"))
        LOGGER.addHandler(handler)
    LOGGER.setLevel(logging.INFO)
    LOGGER.propagate = False


class SessionStateTrace:
    def __init__(self):
        self.states = {}

    def observe(self, sessions) -> None:
        current = {}
        for session in sessions:
            key = hashlib.sha256(session_instance_key(session).encode("utf-8")).hexdigest()[:16]
            result_at = session.updated_at.isoformat() if session.view_ack_required else None
            state = (session.status.value, session.view_ack_required, result_at)
            current[key] = state
            previous = self.states.get(key)
            if previous != state:
                LOGGER.info("AI Progress Monitor state: %s", json.dumps({
                    "key": key, "tool": session.tool.value,
                    "from": previous[0] if previous is not None else "not_visible",
                    "to": state[0], "view_ack": state[1], "result_at": state[2],
                }, separators=(",", ":")))
        for key in self.states.keys() - current.keys():
            LOGGER.info("AI Progress Monitor state: %s", json.dumps({
                "key": key, "from": self.states[key][0], "to": "not_visible",
            }, separators=(",", ":")))
        self.states = current
