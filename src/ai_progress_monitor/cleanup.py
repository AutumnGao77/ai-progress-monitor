from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


DELETABLE_STATUSES = {"idle", "unknown", "stuck"}
PROTECTED_STATUSES = {"running", "needs_action"}


def cleanup_session_files(directory: Path, max_age_seconds: int, now: Optional[datetime] = None) -> int:
    if max_age_seconds <= 0 or not directory.exists():
        return 0
    current = now or datetime.now(timezone.utc)
    removed = 0
    for path in directory.glob("*.json"):
        if _should_remove(path, max_age_seconds, current):
            try:
                path.unlink()
                removed += 1
            except OSError:
                continue
    return removed


def _should_remove(path: Path, max_age_seconds: int, now: datetime) -> bool:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        status = str(payload.get("status", "unknown"))
        updated_at = _parse_datetime(payload.get("updated_at"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return False
    if status in PROTECTED_STATUSES:
        return False
    if status not in DELETABLE_STATUSES:
        return False
    return (now - updated_at).total_seconds() >= max_age_seconds


def _parse_datetime(value) -> datetime:
    if not isinstance(value, str) or not value:
        return datetime.now(timezone.utc)
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed
