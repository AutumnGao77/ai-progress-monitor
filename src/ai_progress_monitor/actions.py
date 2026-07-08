from __future__ import annotations

from pathlib import Path
from typing import Optional

from .models import ActionKind, ActionResult, SafeAction


LOW_RISK_KINDS = {ActionKind.YES_NO, ActionKind.ALLOW_DENY, ActionKind.CONTINUE_STOP}


def is_low_risk_action(action: SafeAction) -> bool:
    return action.kind in LOW_RISK_KINDS and 1 < len(action.options) <= 2


class ActionExecutor:
    def __init__(self, response_dir: Optional[Path] = None, direct_os_actions: bool = False):
        self.response_dir = response_dir or Path.home() / ".ai-progress-monitor" / "responses"
        self.direct_os_actions = direct_os_actions

    def execute_response_file(self, session_id: str, option: str) -> ActionResult:
        safe_name = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in session_id)
        self.response_dir.mkdir(parents=True, exist_ok=True)
        path = self.response_dir / f"{safe_name}.response"
        path.write_text(option, encoding="utf-8")
        return ActionResult(True, str(path))

    def execute(self, session_id: str, action: SafeAction, option: str) -> ActionResult:
        if not is_low_risk_action(action) or option not in action.options:
            return ActionResult(False, "Action blocked by low-risk policy")
        return self.execute_response_file(session_id, option)
