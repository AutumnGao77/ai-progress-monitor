#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Optional
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
API_TIMEOUT_SECONDS = 6


def main() -> int:
    parser = argparse.ArgumentParser(description="Run an end-to-end monitor smoke test")
    parser.add_argument("--artifact", default=str(ROOT / "dist" / "ai-progress-monitor.pyz"))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args()

    artifact = Path(args.artifact)
    if not artifact.exists():
        raise SystemExit(f"artifact not found: {artifact}")

    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        monitor_home = root / "monitor-home"
        port = args.port or find_free_port(args.host)
        env = os.environ.copy()
        env["AI_PROGRESS_MONITOR_HOME"] = str(monitor_home)
        service = subprocess.Popen(
            [sys.executable, str(artifact), "--host", args.host, "--port", str(port), "--no-windows"],
            cwd=ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        service_output: list[str] = []
        try:
            token = read_startup_token(service)
            start_output_drain(service, sink=service_output.append)
            api_base = f"http://{args.host}:{port}"
            try:
                run_prompt_case(
                    api_base=api_base,
                    token=token,
                    env=env,
                    temp_root=root,
                    session_id="smoke-inline",
                    title="Claude Code - smoke inline",
                    tool="claude_code",
                    prompt_lines=["Do you want to continue? (yes/no)"],
                )
                run_prompt_case(
                    api_base=api_base,
                    token=token,
                    env=env,
                    temp_root=root,
                    session_id="smoke-split",
                    title="Claude Code - smoke split",
                    tool="claude_code",
                    prompt_lines=["Do you want to continue?", "1. Yes", "2. No"],
                )
                run_prompt_case(
                    api_base=api_base,
                    token=token,
                    env=env,
                    temp_root=root,
                    session_id="smoke-codex",
                    title="Codex - smoke split",
                    tool="codex",
                    prompt_lines=["Do you want to continue?", "1. Yes", "2. No"],
                )
            except Exception as exc:
                recent = "".join(service_output[-20:])
                raise RuntimeError(f"e2e smoke failed: {exc}\nrecent monitor output:\n{recent}") from exc
        finally:
            stop_process(service)

    print("e2e-smoke-ok")
    return 0


def find_free_port(host: str) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


def read_startup_token(service: subprocess.Popen[str]) -> str:
    deadline = time.time() + 8
    output = []
    while time.time() < deadline:
        if service.poll() is not None:
            raise RuntimeError("monitor service exited early:\n" + "".join(output))
        line = service.stdout.readline() if service.stdout else ""
        if line:
            output.append(line)
            marker = "?token="
            if marker in line:
                return line.strip().split(marker, 1)[1]
        else:
            time.sleep(0.05)
    raise RuntimeError("monitor startup token not found:\n" + "".join(output))


def start_output_drain(process: subprocess.Popen[str], sink=lambda _line: None) -> threading.Thread:
    def drain() -> None:
        if process.stdout is None:
            return
        for line in process.stdout:
            sink(line)

    thread = threading.Thread(target=drain, daemon=True)
    thread.start()
    return thread


def run_prompt_case(
    api_base: str,
    token: str,
    env: dict[str, str],
    temp_root: Path,
    session_id: str,
    title: str,
    tool: str,
    prompt_lines: list[str],
) -> None:
    result_file = temp_root / f"{session_id}.txt"
    child_script = temp_root / f"{session_id}.py"
    child_script.write_text(
        "\n".join(
            [
                "import sys",
                *[f"print({line!r})" for line in prompt_lines],
                "sys.stdout.flush()",
                "answer = sys.stdin.readline().strip()",
                f"open({str(result_file)!r}, 'w', encoding='utf-8').write(answer)",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    child_env = env.copy()
    child_env["AI_MONITOR_SESSION_ID"] = session_id
    child_env["AI_MONITOR_TITLE"] = title
    wrapped = subprocess.Popen(
        wrapper_command(tool, [sys.executable, str(child_script)]),
        cwd=ROOT,
        env=child_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        text=True,
    )
    try:
        session = wait_for_action_session(api_base, token, session_id)
        if session.get("monitoring_level") != "full":
            raise RuntimeError(f"{session_id}: expected full monitoring, got {session.get('monitoring_level')}")
        options = session.get("safe_action", {}).get("options") or []
        if "Yes" not in options:
            raise RuntimeError(f"{session_id}: Yes option missing: {options}")
        send_action(api_base, token, session_id, "Yes")
        deadline = time.time() + 8
        while time.time() < deadline and not result_file.exists():
            time.sleep(0.1)
        if not result_file.exists():
            raise RuntimeError(f"{session_id}: child did not receive response")
        result = result_file.read_text(encoding="utf-8").strip()
        if result != "Yes":
            raise RuntimeError(f"{session_id}: expected child reply Yes, got {result!r}")
        wrapped.wait(timeout=5)
        if wrapped.returncode != 0:
            raise RuntimeError(f"{session_id}: wrapped command exited {wrapped.returncode}")
    finally:
        stop_process(wrapped)


def wrapper_command(tool: str, command: list[str], os_name: str = os.name) -> list[str]:
    if tool == "codex":
        script = "monitor_codex"
    else:
        script = "monitor_claude"
    if os_name == "nt":
        return ["cmd", "/c", f"scripts\\{script}.bat", *command]
    return ["sh", f"scripts/{script}.sh", *command]


def wait_for_action_session(api_base: str, token: str, session_id: str) -> dict:
    deadline = time.time() + 8
    last_seen: Optional[dict] = None
    while time.time() < deadline:
        with urlopen(f"{api_base}/api/sessions?token={token}", timeout=API_TIMEOUT_SECONDS) as response:
            data = json.loads(response.read().decode("utf-8"))
        for session in data.get("sessions", []):
            if session.get("session_id") == session_id:
                last_seen = session
                if session.get("status") == "needs_action" and session.get("safe_action"):
                    return session
        time.sleep(0.1)
    raise RuntimeError(f"{session_id}: needs_action session not found; last_seen={last_seen!r}")


def send_action(api_base: str, token: str, session_id: str, option: str) -> None:
    request = Request(
        f"{api_base}/api/action",
        data=json.dumps({"session_id": session_id, "option": option}).encode("utf-8"),
        headers={"content-type": "application/json", "x-monitor-token": token},
        method="POST",
    )
    with urlopen(request, timeout=API_TIMEOUT_SECONDS) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not payload.get("ok"):
        raise RuntimeError(f"{session_id}: action failed: {payload}")


def stop_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=3)


if __name__ == "__main__":
    raise SystemExit(main())
