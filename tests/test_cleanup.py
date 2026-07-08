import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ai_progress_monitor.cleanup import cleanup_session_files


class CleanupTests(unittest.TestCase):
    def test_removes_old_idle_session_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            write_session(directory / "old.json", "idle", datetime.now(timezone.utc) - timedelta(days=3))

            removed = cleanup_session_files(directory, max_age_seconds=24 * 60 * 60)

            self.assertEqual(removed, 1)
            self.assertFalse((directory / "old.json").exists())

    def test_keeps_old_needs_action_session_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            write_session(directory / "action.json", "needs_action", datetime.now(timezone.utc) - timedelta(days=3))

            removed = cleanup_session_files(directory, max_age_seconds=24 * 60 * 60)

            self.assertEqual(removed, 0)
            self.assertTrue((directory / "action.json").exists())

    def test_keeps_old_running_session_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            write_session(directory / "running.json", "running", datetime.now(timezone.utc) - timedelta(days=3))

            removed = cleanup_session_files(directory, max_age_seconds=24 * 60 * 60)

            self.assertEqual(removed, 0)
            self.assertTrue((directory / "running.json").exists())

    def test_ignores_invalid_json(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            (directory / "bad.json").write_text("{bad")

            removed = cleanup_session_files(directory, max_age_seconds=1)

            self.assertEqual(removed, 0)
            self.assertTrue((directory / "bad.json").exists())


def write_session(path: Path, status: str, updated_at: datetime) -> None:
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


if __name__ == "__main__":
    unittest.main()
