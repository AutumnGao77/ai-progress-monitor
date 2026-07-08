#!/usr/bin/env python3
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    env = os.environ.copy()
    env["PYTHONPATH"] = "src"
    env["PYTHONPYCACHEPREFIX"] = "/private/tmp/ai-progress-pycache"

    checks = [
        ("unit tests", [sys.executable, "-m", "unittest", "discover", "-s", "tests"]),
        ("compile", [sys.executable, "-m", "compileall", "-q", "src", "scripts"]),
        ("app help", [sys.executable, "-m", "ai_progress_monitor", "--help"]),
        ("event help", [sys.executable, "scripts/emit_event.py", "--help"]),
        ("e2e smoke help", [sys.executable, "scripts/e2e_smoke.py", "--help"]),
        ("terminal bridge help", [sys.executable, "scripts/monitor_command.py", "--help"]),
        ("doctor help", [sys.executable, "scripts/doctor.py", "--help"]),
    ]
    for name, command in checks:
        run_check(name, command, env)

    check_js_syntax(env)
    check_help_contains_notifications(env)
    check_sensitive_text()
    print("release-validation-ok")
    return 0


def run_check(name: str, command: List[str], env: Dict[str, str]) -> None:
    completed = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True)
    if completed.returncode != 0:
        print(f"[FAIL] {name}", file=sys.stderr)
        print(completed.stdout, file=sys.stderr)
        print(completed.stderr, file=sys.stderr)
        raise SystemExit(completed.returncode)
    print(f"[OK] {name}")


def check_js_syntax(env: Dict[str, str]) -> None:
    node = shutil.which("node")
    if node is None:
        print("[SKIP] js syntax: node not found")
        return
    script = '''
const fs = require("fs");
const source = fs.readFileSync("src/ai_progress_monitor/web.py", "utf8");
const patterns = [
  new RegExp('HTML_TEMPLATE = """([\\\\s\\\\S]*?)"""\\\\s*\\\\n\\\\nHTML = render_html'),
  new RegExp('HTML = """([\\\\s\\\\S]*)"""\\\\s*$'),
];
const match = patterns.map(pattern => source.match(pattern)).find(Boolean);
if (!match) throw new Error("HTML template block not found");
const assetConfig = JSON.stringify({
  idle: "/assets/pet/idle.png",
  running: "/assets/pet/running.png",
  needs_action: "/assets/pet/needs-action.png",
  app_avatar: "/assets/app-avatar.png",
});
const html = match[1]
  .replaceAll("__MONITOR_TOKEN__", "token")
  .replaceAll("__PET_ASSETS__", assetConfig);
for (const item of html.matchAll(new RegExp('<script>([\\\\s\\\\S]*?)<\\\\/script>', 'g'))) {
  new Function(item[1]);
}
'''
    run_check("js syntax", [node, "-e", script], env)


def check_sensitive_text() -> None:
    banned_exact = re.compile(r"\bsto\b", re.IGNORECASE)
    paths = []
    for pattern in ("*.md", "docs/**/*.md", "src/**/*.py", "tests/**/*.py", "scripts/*", "pyproject.toml"):
        paths.extend(ROOT.glob(pattern))
    for path in paths:
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if banned_exact.search(text):
            raise SystemExit(f"[FAIL] sensitive text: {path}")
    print("[OK] sensitive text")


def check_help_contains_notifications(env: Dict[str, str]) -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "ai_progress_monitor", "--help"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    if "--no-notifications" not in completed.stdout:
        raise SystemExit("[FAIL] help missing --no-notifications")
    if "--cleanup-after-seconds" not in completed.stdout:
        raise SystemExit("[FAIL] help missing --cleanup-after-seconds")
    print("[OK] notification help")


if __name__ == "__main__":
    raise SystemExit(main())
