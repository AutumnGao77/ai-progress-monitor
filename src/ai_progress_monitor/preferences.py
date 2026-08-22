from __future__ import annotations

import json
from pathlib import Path
from threading import RLock
from typing import Optional, Set


PET_ASSET_KEYS = {"idle", "running", "needs_action", "app_avatar"}
DEFAULT_PET_APPEARANCE = "default"
PET_APPEARANCE_THEMES = {DEFAULT_PET_APPEARANCE, "shirt"}


class MonitorPreferences:
    def __init__(self, path: Path | None = None):
        self.path = path or Path.home() / ".ai-progress-monitor" / "preferences.json"
        self._mutation_lock = RLock()

    def hidden_sessions(self) -> Set[str]:
        payload = self._read()
        values = payload.get("hidden_sessions", [])
        if not isinstance(values, list):
            return set()
        return {str(value) for value in values if str(value)}

    def is_hidden(self, session_id: str) -> bool:
        return session_id in self.hidden_sessions()

    def hide_session(self, session_id: str) -> None:
        if not session_id:
            return
        with self._mutation_lock:
            hidden = self.hidden_sessions()
            hidden.add(session_id)
            self._write_hidden(hidden)

    def unhide_session(self, session_id: str) -> None:
        with self._mutation_lock:
            hidden = self.hidden_sessions()
            hidden.discard(session_id)
            self._write_hidden(hidden)

    def session_alias(self, session_id: str) -> Optional[str]:
        aliases = self._aliases()
        alias = aliases.get(session_id)
        return alias if alias else None

    def rename_session(self, session_id: str, title: str) -> None:
        session_id = str(session_id).strip()
        title = str(title).strip()
        if not session_id:
            return
        with self._mutation_lock:
            if not title:
                self.reset_session_alias(session_id)
                return
            aliases = self._aliases()
            aliases[session_id] = title[:80]
            self._write_aliases(aliases)

    def reset_session_alias(self, session_id: str) -> None:
        with self._mutation_lock:
            aliases = self._aliases()
            aliases.pop(str(session_id), None)
            self._write_aliases(aliases)

    def migrate_session_identity(self, previous_id: str, current_id: str) -> None:
        previous_id = str(previous_id).strip()
        current_id = str(current_id).strip()
        if not previous_id or not current_id or previous_id == current_id:
            return
        with self._mutation_lock:
            payload = self._read()
            changed = False
            hidden = payload.get("hidden_sessions")
            if isinstance(hidden, list):
                hidden_ids = {str(value) for value in hidden if str(value)}
                if previous_id in hidden_ids:
                    hidden_ids.discard(previous_id)
                    hidden_ids.add(current_id)
                    payload["hidden_sessions"] = sorted(hidden_ids)
                    changed = True
            aliases = payload.get("session_aliases")
            if isinstance(aliases, dict) and previous_id in aliases:
                migrated_aliases = dict(aliases)
                previous_alias = migrated_aliases.pop(previous_id)
                migrated_aliases.setdefault(current_id, previous_alias)
                payload["session_aliases"] = dict(sorted(migrated_aliases.items()))
                changed = True
            if changed:
                self._write_payload(payload)

    def pet_asset_path(self, key: str) -> Optional[Path]:
        assets = self._pet_assets()
        value = assets.get(str(key))
        return Path(value).expanduser() if value else None

    def pet_appearance(self) -> str:
        return normalize_pet_appearance(self._read().get("pet_appearance"))

    def set_pet_appearance(self, theme: str) -> bool:
        normalized = normalize_pet_appearance(theme)
        if normalized != theme:
            return False
        with self._mutation_lock:
            payload = self._read()
            payload["pet_appearance"] = normalized
            self._write_payload(payload)
        return True

    def notifications_enabled(self) -> bool:
        value = self._read().get("notifications_enabled")
        return value if isinstance(value, bool) else True

    def set_notifications_enabled(self, enabled: bool) -> bool:
        if not isinstance(enabled, bool):
            return False
        with self._mutation_lock:
            payload = self._read()
            current = payload.get("notifications_enabled")
            current_enabled = current if isinstance(current, bool) else True
            if current_enabled == enabled:
                return True
            payload["notifications_enabled"] = enabled
            self._write_payload(payload)
        return True

    def _read(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def _write_hidden(self, hidden: Set[str]) -> None:
        payload = self._read()
        payload["hidden_sessions"] = sorted(hidden)
        self._write_payload(payload)

    def _aliases(self) -> dict:
        payload = self._read()
        values = payload.get("session_aliases", {})
        if not isinstance(values, dict):
            return {}
        return {str(key): str(value) for key, value in values.items() if str(key) and str(value)}

    def _pet_assets(self) -> dict:
        payload = self._read()
        values = payload.get("pet_assets", {})
        if not isinstance(values, dict):
            return {}
        assets = {}
        for key, value in values.items():
            key = str(key)
            if key not in PET_ASSET_KEYS or not isinstance(value, str):
                continue
            value = value.strip()
            if value:
                assets[key] = value
        return assets

    def _write_aliases(self, aliases: dict) -> None:
        payload = self._read()
        payload["session_aliases"] = dict(sorted(aliases.items()))
        self._write_payload(payload)

    def _write_payload(self, payload: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_suffix(".json.tmp")
        temp_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
        temp_path.replace(self.path)


def normalize_pet_appearance(theme) -> str:
    value = str(theme).strip() if theme is not None else ""
    return value if value in PET_APPEARANCE_THEMES else DEFAULT_PET_APPEARANCE
