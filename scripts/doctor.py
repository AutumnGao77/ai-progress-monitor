#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

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
