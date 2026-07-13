#!/usr/bin/env python3
from __future__ import annotations

import importlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List


ROOT = Path(__file__).resolve().parents[1]
COMPANY_TOKEN = "s" + "to"
LEGACY_SENSITIVE_PARTS = [
    "strong" + "gao",
    "gao" + "jian",
    "outlook" + ".com",
    "s" + "todeMacBook",
    "/Users/" + COMPANY_TOKEN,
    "Autumn " + "<",
]

TEXT_SUFFIXES = {
    ".bat",
    ".css",
    ".html",
    ".js",
    ".json",
    ".md",
    ".ps1",
    ".py",
    ".sh",
    ".swift",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}
TEXT_FILENAMES = {
    ".claudeignore",
    ".gitignore",
    "LICENSE",
}


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
    html = rendered_monitor_html()
    scripts = re.findall(r"<script>([\s\S]*?)</script>", html)
    if not scripts:
        raise SystemExit("[FAIL] js syntax: script block not found")
    script = "\n".join(f"new Function({json.dumps(item)});" for item in scripts)
    run_check("js syntax", [node, "-e", script], env)


def rendered_monitor_html() -> str:
    src_path = str(ROOT / "src")
    original_path = list(sys.path)
    previous_modules = {
        name: module
        for name, module in list(sys.modules.items())
        if name == "ai_progress_monitor" or name.startswith("ai_progress_monitor.")
    }
    try:
        for name in previous_modules:
            sys.modules.pop(name, None)
        sys.path.insert(0, src_path)
        module = importlib.import_module("ai_progress_monitor.web")
        html = getattr(module, "HTML", "")
    finally:
        for name in list(sys.modules):
            if name == "ai_progress_monitor" or name.startswith("ai_progress_monitor."):
                sys.modules.pop(name, None)
        sys.modules.update(previous_modules)
        sys.path[:] = original_path
    if not isinstance(html, str) or not html:
        raise SystemExit("[FAIL] js syntax: rendered HTML not found")
    return html


def check_sensitive_text() -> None:
    company_token_pattern = re.compile(
        rf"(^|[^A-Za-z0-9_]){COMPANY_TOKEN}([^A-Za-z0-9_]|$)|@{COMPANY_TOKEN}|{COMPANY_TOKEN}\.cn",
        re.IGNORECASE,
    )
    legacy_sensitive_pattern = re.compile(
        "|".join(re.escape(part) for part in LEGACY_SENSITIVE_PARTS),
        re.IGNORECASE,
    )
    for path in iter_public_text_paths():
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if company_token_pattern.search(text):
            raise SystemExit(f"[FAIL] sensitive company token: {path}")
        if legacy_sensitive_pattern.search(text):
            raise SystemExit(f"[FAIL] sensitive legacy identity: {path}")
    print("[OK] sensitive text")


def iter_public_text_paths() -> List[Path]:
    completed = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if completed.returncode == 0 and completed.stdout:
        paths = [
            ROOT / name
            for name in completed.stdout.split("\0")
            if name and should_scan_text_path(Path(name))
        ]
        return paths

    paths: List[Path] = []
    for pattern in (
        "*.md",
        ".*ignore",
        ".github/**/*.yml",
        ".github/**/*.yaml",
        "docs/**/*.md",
        "docs/**/*.html",
        "native/**/*",
        "scripts/*",
        "src/**/*.py",
        "tests/**/*.py",
        "pyproject.toml",
        "LICENSE",
    ):
        paths.extend(path for path in ROOT.glob(pattern) if should_scan_text_path(path.relative_to(ROOT)))
    return paths


def should_scan_text_path(path: Path) -> bool:
    return path.name in TEXT_FILENAMES or path.suffix.lower() in TEXT_SUFFIXES


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
