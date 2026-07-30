#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def runtime_import_path(root: Path) -> Path:
    source_root = root / "src"
    if source_root.is_dir():
        return source_root
    return root / "ai-progress-monitor.pyz"


RUNTIME_IMPORT_PATH = runtime_import_path(ROOT)
if str(RUNTIME_IMPORT_PATH) not in sys.path:
    sys.path.insert(0, str(RUNTIME_IMPORT_PATH))

from ai_progress_monitor.doctor import run_diagnostics


def main() -> int:
    parser = argparse.ArgumentParser(description="Check AI Progress Monitor runtime environment")
    parser.add_argument("--session-dir", type=Path)
    parser.add_argument("--response-dir", type=Path)
    args = parser.parse_args()

    result = run_diagnostics(session_dir=args.session_dir, response_dir=args.response_dir)
    print(result.to_text())
    return result.exit_code()


if __name__ == "__main__":
    raise SystemExit(main())
