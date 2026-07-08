from __future__ import annotations

import argparse
import errno
from datetime import datetime, timezone
from importlib import resources
import json
import os
import secrets
import socket
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import List, Mapping, Optional
from urllib.parse import parse_qs, urlparse

from .actions import ActionExecutor
from .demo import DemoSource
from .doctor import run_diagnostics
from .notifier import NotificationManager
from .service import MonitorService
from .sources import CodexSessionSource, JsonSessionSource, OsWindowSource, ProcessSource
from .store import SessionStore


DEFAULT_MONITOR_HOME = Path.home() / ".ai-progress-monitor"
PET_ASSET_KEYS = {"idle", "running", "needs_action", "app_avatar"}
DEFAULT_PET_ASSETS = {
    "idle": "assets/sloth-pet-idle.png",
    "running": "assets/sloth-pet-running.png",
    "needs_action": "assets/sloth-pet-needs-action.png",
    "app_avatar": "assets/app-avatar.png",
}
PET_ASSET_ROUTES = {
    "/assets/pet/idle.png": "idle",
    "/assets/pet/running.png": "running",
    "/assets/pet/needs-action.png": "needs_action",
    "/assets/app-avatar.png": "app_avatar",
}
PET_IMAGE_CONTENT_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}
MAX_CONFIGURED_PET_ASSET_BYTES = 8 * 1024 * 1024


class MonitorRequestHandler(BaseHTTPRequestHandler):
    service: MonitorService
    token: str

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/":
            self._send(200, render_html(self.token, pet_asset_urls()), "text/html; charset=utf-8")
        elif path in PET_ASSET_ROUTES:
            self._send_pet_asset(PET_ASSET_ROUTES[path])
        elif path == "/assets/sloth-pet.png":
            self._send_package_asset("assets/sloth-pet.png", "image/png")
        elif path == "/api/sessions":
            if not self._authorized(parsed.query):
                self._send_json(403, {"error": "forbidden"})
                return
            sessions = self.service.sessions_payload()
            print(session_snapshot_line(sessions), flush=True)
            self._send_json(200, {"sessions": sessions, "paused": self.service.paused})
        elif path == "/api/doctor":
            if not self._authorized(parsed.query):
                self._send_json(403, {"error": "forbidden"})
                return
            self._send_json(200, doctor_payload())
        elif path == "/api/hidden-sessions":
            if not self._authorized(parsed.query):
                self._send_json(403, {"error": "forbidden"})
                return
            self._send_json(200, {"sessions": self.service.hidden_sessions_payload(), "paused": self.service.paused})
        else:
            self._send_json(404, {"error": "not_found"})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if not self._authorized(parsed.query):
            self._send_json(403, {"error": "forbidden"})
            return
        payload = self._read_json()
        if path == "/api/action":
            result = self.service.execute_action(str(payload.get("session_id", "")), str(payload.get("option", "")))
            self._send_json(200 if result.ok else 400, {"ok": result.ok, "detail": result.detail})
        elif path == "/api/focus":
            result = self.service.focus_session(str(payload.get("session_id", "")))
            print(focus_snapshot_line(result.ok, result.detail), flush=True)
            self._send_json(200 if result.ok else 400, {"ok": result.ok, "detail": result.detail})
        elif path == "/api/session-viewed":
            result = self.service.mark_session_viewed(str(payload.get("session_id", "")))
            self._send_json(200 if result.ok else 400, {"ok": result.ok, "detail": result.detail})
        elif path == "/api/pause":
            self.service.set_paused(bool(payload.get("paused")))
            self._send_json(200, {"ok": True, "paused": self.service.paused})
        elif path == "/api/hide-session":
            result = self.service.hide_session(str(payload.get("session_id", "")))
            self._send_json(200 if result.ok else 400, {"ok": result.ok, "detail": result.detail})
        elif path == "/api/unhide-session":
            result = self.service.unhide_session(str(payload.get("session_id", "")))
            self._send_json(200 if result.ok else 400, {"ok": result.ok, "detail": result.detail})
        elif path == "/api/rename-session":
            result = self.service.rename_session(str(payload.get("session_id", "")), str(payload.get("title", "")))
            self._send_json(200 if result.ok else 400, {"ok": result.ok, "detail": result.detail})
        elif path == "/api/reset-session-title":
            result = self.service.reset_session_title(str(payload.get("session_id", "")))
            self._send_json(200 if result.ok else 400, {"ok": result.ok, "detail": result.detail})
        else:
            self._send_json(404, {"error": "not_found"})

    def log_message(self, format: str, *args) -> None:
        return

    def _authorized(self, query: str) -> bool:
        headers = {key.lower(): value for key, value in self.headers.items()}
        return is_authorized(self.token, headers, query)

    def _read_json(self) -> dict:
        length = int(self.headers.get("content-length", "0"))
        if length <= 0:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except json.JSONDecodeError:
            return {}

    def _send_json(self, status: int, payload: dict) -> None:
        self._send(status, json.dumps(payload).encode("utf-8"), "application/json; charset=utf-8")

    def _send_package_asset(self, name: str, content_type: str) -> None:
        try:
            body = resources.files("ai_progress_monitor").joinpath(name).read_bytes()
        except (FileNotFoundError, ModuleNotFoundError, OSError):
            self._send_json(404, {"error": "not_found"})
            return
        self._send(200, body, content_type)

    def _send_pet_asset(self, key: str) -> None:
        custom_path = self.service.preferences.pet_asset_path(key)
        if custom_path is not None:
            custom = read_configured_pet_asset(custom_path)
            if custom is not None:
                body, content_type = custom
                self._send(200, body, content_type)
                return
        self._send_package_asset(DEFAULT_PET_ASSETS[key], pet_asset_content_type(Path(DEFAULT_PET_ASSETS[key])))

    def _send(self, status: int, body, content_type: str) -> None:
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", content_type)
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def build_sources(args) -> List:
    sources: List = []
    source_started_at = datetime.now(timezone.utc)
    if args.demo:
        sources.append(DemoSource())
    sources.append(
        JsonSessionSource(
            resolve_session_dir(args),
            cleanup_after_seconds=args.cleanup_after_seconds,
            source_started_at=source_started_at,
        )
    )
    sources.append(CodexSessionSource(source_started_at=source_started_at))
    sources.append(ProcessSource(source_started_at=source_started_at))
    if not args.no_windows:
        sources.append(OsWindowSource())
    return sources


def resolve_monitor_home() -> Path:
    return Path(os.environ.get("AI_PROGRESS_MONITOR_HOME") or DEFAULT_MONITOR_HOME)


def resolve_session_dir(args) -> Path:
    if args.session_dir:
        return Path(args.session_dir)
    return resolve_monitor_home() / "sessions"


def resolve_response_dir(args) -> Path:
    if args.response_dir:
        return Path(args.response_dir)
    if args.session_dir:
        return Path(args.session_dir).parent / "responses"
    return resolve_monitor_home() / "responses"


def generate_token() -> str:
    return secrets.token_urlsafe(32)


def is_authorized(expected_token: str, headers: dict, query: str) -> bool:
    header_token = headers.get("x-monitor-token", "")
    query_values = parse_qs(query).get("token", [])
    query_token = query_values[0] if query_values else ""
    return secrets.compare_digest(expected_token, header_token) or secrets.compare_digest(expected_token, query_token)


def pet_asset_urls() -> dict:
    return {
        "idle": "/assets/pet/idle.png",
        "running": "/assets/pet/running.png",
        "needs_action": "/assets/pet/needs-action.png",
        "app_avatar": "/assets/app-avatar.png",
    }


def render_html(token: str, pet_assets: Optional[Mapping[str, str]] = None) -> str:
    assets = pet_asset_urls()
    if pet_assets:
        for key, value in pet_assets.items():
            if key in PET_ASSET_KEYS and isinstance(value, str) and value:
                assets[key] = value
    return (
        HTML_TEMPLATE.replace("__MONITOR_TOKEN__", token)
        .replace("__PET_ASSETS__", json.dumps(assets, ensure_ascii=True))
    )


def pet_asset_content_type(path: Path) -> str:
    return PET_IMAGE_CONTENT_TYPES.get(path.suffix.lower(), "application/octet-stream")


def read_configured_pet_asset(path: Path) -> Optional[tuple[bytes, str]]:
    if path.suffix.lower() not in PET_IMAGE_CONTENT_TYPES:
        return None
    try:
        if not path.is_file() or path.stat().st_size > MAX_CONFIGURED_PET_ASSET_BYTES:
            return None
        return path.read_bytes(), pet_asset_content_type(path)
    except OSError:
        return None


def create_server(host: str, port: int, service: MonitorService, token: str) -> ThreadingHTTPServer:
    handler = type("BoundMonitorRequestHandler", (MonitorRequestHandler,), {"service": service, "token": token})
    return ThreadingHTTPServer((host, port), handler)


def create_server_with_port_fallback(
    host: str,
    port: int,
    service: MonitorService,
    token: str,
    attempts: int = 20,
) -> tuple[ThreadingHTTPServer, int]:
    last_error: Optional[OSError] = None
    for selected_port in range(port, port + attempts):
        try:
            return create_server(host, selected_port, service, token), selected_port
        except OSError as exc:
            if not _is_address_in_use(exc):
                raise
            last_error = exc
    if last_error is not None:
        raise last_error
    raise OSError("No port attempts were made")


def _is_address_in_use(error: OSError) -> bool:
    return error.errno in {errno.EADDRINUSE, getattr(socket, "EADDRINUSE", errno.EADDRINUSE)}


def build_launch_url(host: str, port: int, token: str) -> str:
    return f"http://{host}:{port}/?token={token}"


def maybe_open_browser(url: str, enabled: bool) -> None:
    if enabled:
        webbrowser.open(url)


def doctor_payload() -> dict:
    return run_diagnostics().to_dict()


def session_snapshot_line(sessions: List[dict]) -> str:
    counts = {"needs_action": 0, "running": 0, "idle": 0}
    monitoring = {"process_only": 0, "full": 0}
    for session in sessions:
        status = str(session.get("status") or "idle")
        if status == "needs_action":
            counts["needs_action"] += 1
        elif status in {"running", "stuck"}:
            counts["running"] += 1
        else:
            counts["idle"] += 1
        level = "process_only" if session.get("monitoring_level") == "process_only" else "full"
        monitoring[level] += 1
    return (
        "AI Progress Monitor sessions: "
        f"total={len(sessions)} "
        f"needs_action={counts['needs_action']} "
        f"running={counts['running']} "
        f"idle={counts['idle']} "
        f"process_only={monitoring['process_only']} "
        f"full={monitoring['full']}"
    )


def focus_snapshot_line(ok: bool, detail: str = "") -> str:
    line = f"AI Progress Monitor focus: ok={str(bool(ok)).lower()}"
    safe_methods = {
        "activated-app",
        "focused-process",
        "focused-project-window",
        "focused-title-window",
        "focused-window",
        "focused-window-id",
    }
    if ok:
        for method in safe_methods:
            if detail == method or detail.startswith(method + " "):
                line += f" method={method}"
                break
    return line


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Web companion for Claude Code and Codex progress")
    parser.add_argument("--demo", action="store_true", help="Show sample Claude Code and Codex sessions")
    parser.add_argument("--session-dir", help="Directory containing JSON session files")
    parser.add_argument("--response-dir", help="Directory where pet actions write response files")
    parser.add_argument("--no-windows", action="store_true", help="Disable OS window scanning")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--open", action="store_true", help="Open the monitor page in the default browser")
    parser.add_argument("--no-notifications", action="store_true", help="Disable native needs-action notifications")
    parser.add_argument(
        "--cleanup-after-seconds",
        type=int,
        default=7 * 24 * 60 * 60,
        help="Remove old idle/unknown/stuck session files after this many seconds; 0 disables cleanup",
    )
    args = parser.parse_args(argv)

    notifier = NotificationManager(enabled=not args.no_notifications)
    service = MonitorService(build_sources(args), SessionStore(), ActionExecutor(response_dir=resolve_response_dir(args)), notifier=notifier)
    token = generate_token()
    server, selected_port = create_server_with_port_fallback(args.host, args.port, service, token)
    url = build_launch_url(args.host, selected_port, token)
    if selected_port != args.port:
        print(f"Port {args.port} is busy; using {selected_port} instead.", flush=True)
    print(f"AI Progress Monitor running at {url}", flush=True)
    maybe_open_browser(url, args.open)
    server.serve_forever()
    return 0


HTML_TEMPLATE = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>AI Progress Monitor</title>
<link rel="icon" href="/assets/app-avatar.png">
<style>
:root { color-scheme: light; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
html, body { margin: 0; width: 100%; height: 100%; overflow: hidden; background: transparent; color: #172033; }
.bubble-list { position: fixed; right: 10px; bottom: 150px; display: none; flex-direction: column; gap: 8px; max-width: min(300px, calc(100vw - 20px)); max-height: min(320px, calc(100vh - 190px)); overflow: auto; z-index: 19; }
.bubble-list.open { display: flex; }
.session-bubble { border: 0; border-radius: 16px 16px 16px 6px; background: rgba(255,255,255,.96); color: #172033; box-shadow: 0 12px 30px rgba(21,32,51,.2); padding: 9px 12px; text-align: left; font: inherit; cursor: pointer; min-width: 178px; max-width: 280px; }
.session-bubble:hover { transform: translateY(-1px); }
.session-bubble.needs_action { border-left: 4px solid #df3b30; }
.session-bubble.running { border-left: 4px solid #2f9e44; }
.session-bubble.idle { border-left: 4px solid #2f6fbb; }
.bubble-title { display: block; font-size: 13px; font-weight: 750; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.bubble-meta { display: block; margin-top: 2px; font-size: 11px; color: #667085; }
.pet { position: fixed; right: 10px; bottom: 10px; width: 150px; height: 136px; border: 0; background: transparent; padding: 0; cursor: grab; user-select: none; touch-action: none; z-index: 20; filter: none; animation: pet-float 4.2s ease-in-out infinite; }
.pet.dragging { cursor: grabbing; }
.pet:focus { outline: none; }
.pet:focus-visible .pet-focus-ring { opacity: 1; }
.pet-focus-ring { position: absolute; inset: 12px 15px 4px 15px; border: 4px solid rgba(47,111,187,.34); border-radius: 999px; opacity: 0; transition: opacity .16s ease; }
.pet-art-wrap { position: absolute; inset: 0 3px 0 3px; transform-origin: 50% 78%; animation: pet-idle-breathe 4.6s ease-in-out infinite; }
.pet-art { width: 100%; height: 100%; object-fit: contain; display: block; pointer-events: none; -webkit-user-drag: none; }
.pet-alert-card { position: absolute; left: 26px; top: 18px; width: 18px; height: 18px; border-radius: 999px; display: flex; align-items: center; justify-content: center; background: #fff7d6; border: 1.5px solid #7a5b46; color: #df3b30; font-size: 12px; line-height: 1; font-weight: 900; opacity: 0; transform-origin: 50% 100%; transition: opacity .18s ease; }
.pet-typing-dots { position: absolute; left: 44px; bottom: 4px; min-width: 46px; height: 17px; border-radius: 999px; display: flex; align-items: center; justify-content: center; background: rgba(23,32,51,.82); color: white; font-size: 15px; font-weight: 900; letter-spacing: 1px; opacity: 0; transition: opacity .18s ease; }
.pet-nap-mark { position: absolute; right: 22px; top: 13px; color: #2f6fbb; font-size: 17px; font-weight: 900; opacity: 0; transform-origin: 20% 100%; transition: opacity .18s ease; }
.pet.needs-action .pet-art-wrap { animation: pet-alert-bob 1.15s ease-in-out infinite; }
.pet.needs-action .pet-alert-card { opacity: 1; animation: pet-card-pop 1.15s ease-in-out infinite; }
.pet.running .pet-art-wrap { animation: pet-working-nod 1.45s ease-in-out infinite; }
.pet.running .pet-typing-dots { opacity: 1; animation: pet-dots-type 1.05s ease-in-out infinite; }
.pet.idle .pet-art-wrap { animation: pet-idle-breathe 4.6s ease-in-out infinite; }
.pet.idle .pet-nap-mark { opacity: 1; animation: pet-zzz 3.8s ease-in-out infinite; }
.pet-badge { position: absolute; top: 2px; right: 12px; min-width: 24px; height: 24px; border-radius: 999px; display: none; align-items: center; justify-content: center; color: white; font-size: 12px; font-weight: 800; box-shadow: 0 4px 10px rgba(0,0,0,.25); z-index: 6; }
.pet-badge.show { display: flex; }
.pet-badge.badge-needs-action { background: #df3b30; }
.pet-badge.badge-running { background: #2f9e44; }
.pet-badge.badge-idle { background: #2f6fbb; }
.pet-context-menu { position: fixed; display: none; min-width: 108px; padding: 4px; border-radius: 8px; background: rgba(255,255,255,.98); border: 1px solid rgba(17,24,39,.08); box-shadow: 0 10px 24px rgba(17,24,39,.18); z-index: 30; }
.pet-context-menu.open { display: block; }
.pet-context-menu button { display: block; width: 100%; border: 0; background: transparent; border-radius: 6px; padding: 5px 7px; text-align: left; font: inherit; font-size: 13px; line-height: 1.2; color: #172033; cursor: pointer; }
.pet-context-menu button:hover { background: #eef2f7; }
.status-note { position: fixed; right: 12px; bottom: 112px; max-width: 260px; display: none; padding: 7px 10px; border-radius: 10px; background: rgba(23,32,51,.9); color: white; font-size: 12px; z-index: 22; }
.status-note.show { display: block; }
@keyframes pet-float { 0%,100% { transform: translateY(0); } 50% { transform: translateY(-2px); } }
@keyframes pet-idle-breathe { 0%,100% { transform: translateY(0) rotate(0) scale(1); } 50% { transform: translateY(2px) rotate(-1.2deg) scale(.992); } }
@keyframes pet-working-nod { 0%,100% { transform: translateX(0) rotate(-1deg); } 50% { transform: translateX(1px) translateY(2px) rotate(2.2deg); } }
@keyframes pet-alert-bob { 0%,100% { transform: translateY(0) rotate(-2deg) scale(1); } 50% { transform: translateY(-4px) rotate(3deg) scale(1.015); } }
@keyframes pet-card-pop { 0%,100% { transform: scale(.96) rotate(-2deg); } 50% { transform: scale(1.06) rotate(2deg); } }
@keyframes pet-dots-type { 0%,100% { transform: translateY(0); opacity: .76; } 50% { transform: translateY(2px); opacity: 1; } }
@keyframes pet-zzz { 0%,100% { transform: translateY(0) scale(.96); opacity: .7; } 50% { transform: translateY(-5px) scale(1.05); opacity: 1; } }
@media (max-width: 420px) {
  .bubble-list { left: 10px !important; right: auto; bottom: auto; max-width: min(300px, calc(100vw - 20px)); }
  .status-note { left: 12px; right: auto; top: 112px; bottom: auto; }
}
</style>
</head>
<body>
<script>
window.MONITOR_TOKEN = "__MONITOR_TOKEN__";
window.PET_ASSETS = __PET_ASSETS__;
</script>
<div class="bubble-list" id="bubbleList"></div>
<button class="pet idle" id="pet" aria-label="AI 监控 Pet">
  <span class="pet-focus-ring" aria-hidden="true"></span>
  <span class="pet-art-wrap" aria-hidden="true">
    <img class="pet-art" id="petArt" src="/assets/pet/idle.png" alt="" draggable="false" />
  </span>
  <span class="pet-alert-card" aria-hidden="true">!</span>
  <span class="pet-typing-dots" aria-hidden="true">...</span>
  <span class="pet-nap-mark" aria-hidden="true">Zz</span>
  <span class="pet-badge" id="petBadge"></span>
</button>
<div class="pet-context-menu" id="petContextMenu">
  <button type="button" id="hidePetMenuItem">隐藏 Pet</button>
  <button type="button" id="quitPetMenuItem">退出程序</button>
</div>
<div class="status-note" id="statusNote"></div>
<script>
const statusLabel = {needs_action:"待处理", running:"进行中", idle:"空闲"};
const statusRank = {needs_action:1, running:2, idle:3};
const badgeClass = {needs_action:"badge-needs-action", running:"badge-running", idle:"badge-idle"};
const toolLabel = {claude_code:"Claude", codex:"Codex", unknown:"AI"};
const pet = document.getElementById("pet");
const petArt = document.getElementById("petArt");
const petBadge = document.getElementById("petBadge");
const bubbleList = document.getElementById("bubbleList");
const petContextMenu = document.getElementById("petContextMenu");
const statusNote = document.getElementById("statusNote");
const petImages = {
  idle:"/assets/pet/idle.png",
  running:"/assets/pet/running.png",
  needs_action:"/assets/pet/needs-action.png",
};
Object.assign(petImages, window.PET_ASSETS || {});
const sessionSequenceByGroup = new Map();
const BUBBLE_GAP = 10;
const VISUAL_MOTION_BUFFER = 24;
const EDGE_INSET = 10;
const MAX_BUBBLE_HEIGHT = 320;
let dragging = false;
let dragMoved = false;
let draggingHostWindow = false;
let dragOffsetX = 0;
let dragOffsetY = 0;
let lastDragScreenX = 0;
let lastDragScreenY = 0;
let loadTimer = null;
const POLL_INTERVAL_MS = 3000;
const PET_POSITION_KEY = "monitor.pet.position";

applyPetPosition();
resizeHostWindow("compact");
window.restorePetFromHost = restorePetFromHost;
pet.addEventListener("pointerdown", startPetDrag);
pet.addEventListener("contextmenu", showPetContextMenu);
window.addEventListener("pointermove", movePet);
window.addEventListener("pointerup", stopPetDrag);
window.addEventListener("click", event => {
  if (!petContextMenu.contains(event.target)) closePetContextMenu();
});
pet.onclick = () => {
  if (dragMoved) {
    dragMoved = false;
    return;
  }
  toggleBubbleList();
};
document.getElementById("hidePetMenuItem").onclick = hidePet;
document.getElementById("quitPetMenuItem").onclick = quitApp;

async function load() {
  try {
    const data = await fetch(`/api/sessions?token=${encodeURIComponent(window.MONITOR_TOKEN)}`).then(r => r.json());
    render(data.sessions || []);
  } catch (_error) {
    render([]);
    showStatusNote("连接中断，正在重试");
  } finally {
    window.clearTimeout(loadTimer);
    loadTimer = setTimeout(load, POLL_INTERVAL_MS);
  }
}

function render(sessions) {
  const visibleSessions = sessions.slice();
  renderBadge(visibleSessions);
  renderBubbles(visibleSessions);
}

function displayStatus(session) {
  if (session.status === "needs_action") return "needs_action";
  if (session.status === "running" || session.status === "stuck") return "running";
  return "idle";
}

function badgeState(sessions) {
  const counts = {needs_action:0, running:0, idle:0};
  sessions.forEach(session => {
    counts[displayStatus(session)] += 1;
  });
  for (const status of ["needs_action", "running", "idle"]) {
    if (counts[status] > 0) {
      return {count: sessions.length, status, colorClass: badgeClass[status]};
    }
  }
  return {count: 0, status: "idle", colorClass: ""};
}

function renderBadge(sessions) {
  const state = badgeState(sessions);
  petBadge.className = "pet-badge";
  pet.classList.remove("needs-action", "running", "idle");
  if (!state.count) {
    petBadge.textContent = "";
    pet.classList.add("idle");
    petArt.src = petImages.idle;
    return;
  }
  petBadge.textContent = String(state.count);
  petBadge.classList.add("show", state.colorClass);
  pet.classList.add(state.status === "needs_action" ? "needs-action" : state.status);
  petArt.src = petImages[state.status] || petImages.idle;
}

function renderBubbles(sessions) {
  prepareBubbleSequences(sessions);
  const sorted = sessions.slice().sort((a, b) => statusRank[displayStatus(a)] - statusRank[displayStatus(b)]);
  if (!sorted.length) {
    bubbleList.innerHTML = '<button class="session-bubble idle" type="button"><span class="bubble-title">暂无 Claude/Codex 会话</span><span class="bubble-meta">空闲</span></button>';
    return;
  }
  bubbleList.innerHTML = sorted.map(session => sessionBubbleHtml(session, sessions)).join("");
  bubbleList.querySelectorAll(".session-bubble[data-session-id]").forEach(button => {
    button.addEventListener("click", () => focusSessionFromButton(button));
  });
  if (bubbleList.classList.contains("open")) scheduleBubbleLayout();
}

function prepareBubbleSequences(sessions) {
  const liveGroups = new Map();
  sessions.forEach(session => {
    const folder = sessionFolderName(session);
    const group = `${folder}::${session.tool || "unknown"}`;
    if (!liveGroups.has(group)) liveGroups.set(group, new Set());
    liveGroups.get(group).add(session.session_id);
  });
  sessionSequenceByGroup.forEach((groupMap, group) => {
    const liveIds = liveGroups.get(group);
    if (!liveIds) {
      sessionSequenceByGroup.delete(group);
      return;
    }
    groupMap.forEach((_sequence, sessionId) => {
      if (!liveIds.has(sessionId)) groupMap.delete(sessionId);
    });
    if (!groupMap.size) sessionSequenceByGroup.delete(group);
  });
  sessions.slice().sort((a, b) => sequenceSortKey(a).localeCompare(sequenceSortKey(b))).forEach(session => {
    const group = sequenceGroup(session);
    stableSequence(group, session.session_id);
  });
}

function sequenceSortKey(session) {
  return `${sequenceGroup(session)}::${session.session_id || ""}`;
}

function sessionBubbleHtml(session, allSessions) {
  const status = displayStatus(session);
  const label = bubbleLabel(session, allSessions);
  return `<button class="session-bubble ${status}" type="button" data-session-id="${escapeAttr(session.session_id)}" data-title="${escapeAttr(session.title || "")}" data-window-id="${escapeAttr(session.window_id || "")}" data-process-id="${escapeAttr(session.focus_process_id || session.process_id || "")}" data-app-name="${escapeAttr(session.focus_app_name || "")}" data-cwd="${escapeAttr(session.cwd || "")}">
    <span class="bubble-title">${escapeHtml(label)}</span>
  </button>`;
}

function bubbleLabel(session, allSessions) {
  if (isDesktopConversationWithoutFolder(session)) {
    return desktopConversationBubbleLabel(session, allSessions);
  }
  const folder = sessionFolderName(session);
  const group = sequenceGroup(session);
  const sameFolder = allSessions.filter(item => sessionFolderName(item) === folder);
  const status = statusLabel[displayStatus(session)];
  if (sameFolder.length <= 1) return `${folder} · ${status}`;
  const sequence = stableSequence(group, session.session_id);
  return `${folder} · ${sessionToolName(session)} #${sequence} · ${status}`;
}

function desktopConversationBubbleLabel(session, allSessions) {
  const base = desktopConversationBase(session);
  const sameBase = allSessions.filter(item => isDesktopConversationWithoutFolder(item) && desktopConversationBase(item) === base);
  const status = statusLabel[displayStatus(session)];
  if (sameBase.length <= 1) return `${base} · ${status}`;
  return `${base} #${stableSequence(sequenceGroup(session), session.session_id)} · ${status}`;
}

function sequenceGroup(session) {
  const base = isDesktopConversationWithoutFolder(session) ? desktopConversationBase(session) : sessionFolderName(session);
  return `${base}::${session.tool || "unknown"}`;
}

function stableSequence(group, sessionId) {
  if (!sessionSequenceByGroup.has(group)) sessionSequenceByGroup.set(group, new Map());
  const groupMap = sessionSequenceByGroup.get(group);
  if (!groupMap.has(sessionId)) groupMap.set(sessionId, groupMap.size + 1);
  return groupMap.get(sessionId);
}

function sessionFolderName(session) {
  if (session.monitoring_level === "process_only" && session.surface === "desktop") {
    return truncateLabel(session.title || `${sessionToolName(session)} Desktop`, 28);
  }
  return folderName(session.title);
}

function isDesktopConversationWithoutFolder(session) {
  if (session.surface !== "desktop" || session.monitoring_level === "process_only") return false;
  const cwd = String(session.cwd || "").trim();
  return !cwd || session.generated_conversation_path === true;
}

function desktopConversationBase(session) {
  const readableTitle = readableDesktopConversationTitle(session);
  if (readableTitle) return `${sessionToolName(session)} · ${readableTitle}`;
  return `${sessionToolName(session)} 对话`;
}

function readableDesktopConversationTitle(session) {
  const candidate = folderName(session.title);
  if (!candidate || candidate === "AI 会话") return "";
  if (looksLikeGeneratedSessionName(candidate)) return "";
  return truncateLabel(candidate, 18);
}

function looksLikeGeneratedSessionName(value) {
  const text = String(value || "").trim();
  if (!text) return true;
  if (/^[a-f0-9-]{6,}$/i.test(text)) return true;
  if (/^[a-z0-9]{1,4}-[a-z0-9-]{1,8}$/i.test(text)) return true;
  return false;
}

function sessionToolName(session) {
  return truncateLabel(session.tool_display_name || toolLabel[session.tool] || "AI", 18);
}

function folderName(title) {
  const normalized = String(title || "")
    .replace(/claude code/ig, "")
    .replace(/codex desktop/ig, "")
    .replace(/codex/ig, "")
    .replace(/terminal/ig, "")
    .replace(/[–—]/g, "-")
    .replace(/^[-·:|\\s]+/, "")
    .trim();
  const cleaned = normalized
    .split(/\\s+-\\s+/)
    .map(part => part.trim())
    .filter(Boolean)
    .pop() || "";
  const lastPath = cleaned.split(/[\\\\/]/).filter(Boolean).pop() || cleaned;
  return truncateLabel(lastPath || "AI 会话", 28);
}

function truncateLabel(value, maxLength) {
  const text = String(value || "AI 会话").trim();
  return text.length > maxLength ? `${text.slice(0, maxLength - 1)}…` : text;
}

function toggleBubbleList() {
  const willOpen = !bubbleList.classList.contains("open");
  bubbleList.classList.toggle("open", willOpen);
  if (!willOpen && hasHostWindow()) resetPetDomPosition();
  resizeHostWindow(willOpen ? "bubbles" : "compact");
  scheduleBubbleLayout();
}

function restorePetFromHost() {
  dragging = false;
  dragMoved = false;
  draggingHostWindow = false;
  pet.style.display = "";
  bubbleList.classList.remove("open");
  closePetContextMenu();
  resetPetDomPosition();
  resizeHostWindow("compact");
}

function startPetDrag(event) {
  if (event.button !== undefined && event.button !== 0) return;
  dragging = true;
  dragMoved = false;
  closePetContextMenu();
  pet.classList.add("dragging");
  draggingHostWindow = hasHostWindow();
  lastDragScreenX = event.screenX;
  lastDragScreenY = event.screenY;
  if (draggingHostWindow) postHostMessage("start-window-drag");
  const rect = pet.getBoundingClientRect();
  dragOffsetX = event.clientX - rect.left;
  dragOffsetY = event.clientY - rect.top;
  pet.setPointerCapture(event.pointerId);
}

function movePet(event) {
  if (!dragging) return;
  dragMoved = true;
  if (draggingHostWindow) {
    lastDragScreenX = event.screenX;
    lastDragScreenY = event.screenY;
    return;
  }
  const width = pet.offsetWidth;
  const height = pet.offsetHeight;
  const x = clamp(event.clientX - dragOffsetX, 8, window.innerWidth - width - 8);
  const y = clamp(event.clientY - dragOffsetY, 8, window.innerHeight - height - 8);
  setPetPosition(x, y);
  localStorage.setItem(PET_POSITION_KEY, JSON.stringify({x, y}));
}

function stopPetDrag() {
  if (!dragging) return;
  dragging = false;
  if (draggingHostWindow) postHostMessage("stop-window-drag");
  draggingHostWindow = false;
  pet.classList.remove("dragging");
  updateBubblePosition();
}

function applyPetPosition() {
  if (hasHostWindow()) {
    localStorage.removeItem(PET_POSITION_KEY);
    resetPetDomPosition();
    return;
  }
  const saved = safeJson(localStorage.getItem(PET_POSITION_KEY));
  if (!saved || typeof saved.x !== "number" || typeof saved.y !== "number") return;
  const x = clamp(saved.x, 8, window.innerWidth - 80);
  const y = clamp(saved.y, 8, window.innerHeight - 80);
  setPetPosition(x, y);
}

function setPetPosition(x, y) {
  setPetPositionWithoutLayout(x, y);
  updateBubblePosition();
}

function setPetPositionWithoutLayout(x, y) {
  pet.style.left = `${x}px`;
  pet.style.top = `${y}px`;
  pet.style.right = "auto";
  pet.style.bottom = "auto";
}

function resetPetDomPosition() {
  pet.style.left = "";
  pet.style.top = "";
  pet.style.right = "";
  pet.style.bottom = "";
}

function updateBubblePosition() {
  dockPetBelowBubbles();
  const rect = pet.getBoundingClientRect();
  const visualRect = getPetVisualRect();
  const width = Math.min(300, window.innerWidth - 20);
  const left = clamp(rect.right - width, 10, window.innerWidth - width - 10);
  const bubbleHeight = fitBubbleAbovePet(visualRect);
  const top = Math.max(EDGE_INSET, visualRect.top - bubbleHeight - BUBBLE_GAP - VISUAL_MOTION_BUFFER);
  bubbleList.style.maxHeight = `${bubbleHeight}px`;
  bubbleList.style.left = `${left}px`;
  bubbleList.style.top = `${top}px`;
  bubbleList.style.right = "auto";
  bubbleList.style.bottom = "auto";
}

function fitBubbleAbovePet(petRect) {
  const availableHeight = Math.max(0, petRect.top - EDGE_INSET - BUBBLE_GAP - VISUAL_MOTION_BUFFER);
  const desiredHeight = bubbleList.scrollHeight || bubbleList.offsetHeight || 72;
  return Math.min(MAX_BUBBLE_HEIGHT, desiredHeight, availableHeight);
}

function dockPetBelowBubbles() {
  if (!bubbleList.classList.contains("open")) return;
  if (hasHostWindow()) return;
  const rect = pet.getBoundingClientRect();
  const visualRect = getPetVisualRect();
  const visualTopOverflow = Math.max(0, rect.top - visualRect.top);
  const desiredBubbleHeight = Math.min(MAX_BUBBLE_HEIGHT, bubbleList.scrollHeight || bubbleList.offsetHeight || 72);
  const minPetTop = desiredBubbleHeight + BUBBLE_GAP + EDGE_INSET + visualTopOverflow + VISUAL_MOTION_BUFFER;
  const maxPetTop = Math.max(EDGE_INSET, window.innerHeight - pet.offsetHeight - EDGE_INSET);
  const x = clamp(rect.left, EDGE_INSET, Math.max(EDGE_INSET, window.innerWidth - pet.offsetWidth - EDGE_INSET));
  const y = rect.top < minPetTop ? maxPetTop : clamp(rect.top, EDGE_INSET, maxPetTop);
  if (Math.abs(rect.left - x) > 1 || Math.abs(rect.top - y) > 1) {
    setPetPositionWithoutLayout(x, y);
  }
}

function getPetVisualRect() {
  const rects = [pet.getBoundingClientRect()];
  pet.querySelectorAll(".pet-art, .pet-alert-card, .pet-typing-dots, .pet-nap-mark, .pet-badge").forEach(element => {
    const rect = element.getBoundingClientRect();
    if (rect.width > 0 && rect.height > 0) rects.push(rect);
  });
  const left = Math.min(...rects.map(rect => rect.left));
  const top = Math.min(...rects.map(rect => rect.top));
  const right = Math.max(...rects.map(rect => rect.right));
  const bottom = Math.max(...rects.map(rect => rect.bottom));
  return {left, top, right, bottom, width: right - left, height: bottom - top};
}

function scheduleBubbleLayout() {
  window.requestAnimationFrame(updateBubblePosition);
  window.setTimeout(updateBubblePosition, 120);
  window.setTimeout(updateBubblePosition, 320);
}

function showPetContextMenu(event) {
  event.preventDefault();
  petContextMenu.style.left = `${clamp(event.clientX, 8, window.innerWidth - 116)}px`;
  petContextMenu.style.top = `${clamp(event.clientY, 8, window.innerHeight - 72)}px`;
  petContextMenu.classList.add("open");
}

function closePetContextMenu() {
  petContextMenu.classList.remove("open");
}

function hidePet() {
  closePetContextMenu();
  postHostMessage("hide");
  showStatusNote("Pet 已收起，可从菜单栏图标恢复");
}

function quitApp() {
  closePetContextMenu();
  postHostMessage("quit");
  showStatusNote("正在退出");
}

function postHostMessage(type, payload={}) {
  try {
    window.webkit.messageHandlers.monitorWindow.postMessage(Object.assign({type}, payload));
  } catch (_error) {
    if (type === "hide") pet.style.display = "none";
  }
}

function hasHostWindow() {
  return Boolean(window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.monitorWindow);
}

function resizeHostWindow(mode) {
  const size = mode === "bubbles" ? {width: 340, height: 500} : {width: 170, height: 150};
  try { window.resizeTo(size.width, size.height); } catch (_error) {}
  postHostMessage("resize", {mode, width: size.width, height: size.height});
}

async function focusSession(sessionId) {
  try {
    const response = await fetch("/api/focus", {method:"POST", body: JSON.stringify({session_id:sessionId}), headers: {"content-type":"application/json", "x-monitor-token": window.MONITOR_TOKEN}});
    if (response.ok) load();
    else showStatusNote("无法定位窗口");
  } catch (_error) {
    showStatusNote("无法定位窗口");
  }
}

async function markSessionViewed(sessionId) {
  if (!sessionId) return;
  try {
    const response = await fetch("/api/session-viewed", {method:"POST", body: JSON.stringify({session_id:sessionId}), headers: {"content-type":"application/json", "x-monitor-token": window.MONITOR_TOKEN}});
    if (response.ok) load();
  } catch (_error) {}
}

function focusSessionFromButton(button) {
  if (hasHostWindow()) {
    postHostMessage("focus", {
      session_id: button.dataset.sessionId || "",
      title: button.dataset.title || "",
      window_id: button.dataset.windowId || "",
      process_id: button.dataset.processId || "",
      app_name: button.dataset.appName || "",
      cwd: button.dataset.cwd || "",
    });
    return;
  }
  focusSession(button.dataset.sessionId);
}

window.onHostFocusResult = function(result) {
  if (!result) return;
  if (result.ok === true) {
    markSessionViewed(result.session_id);
    return;
  }
  if (result.detail === "accessibility-permission-required") {
    showStatusNote("请允许辅助功能权限");
    return;
  }
  showStatusNote("无法定位窗口");
};

function showStatusNote(message) {
  statusNote.textContent = message;
  statusNote.classList.add("show");
  window.setTimeout(() => statusNote.classList.remove("show"), 2200);
}

function safeJson(value) {
  try { return value ? JSON.parse(value) : null; } catch (_error) { return null; }
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function escapeHtml(value) {
  const entities = {"&":"&amp;","<":"&lt;",">":"&gt;"};
  entities[String.fromCharCode(34)] = "&quot;";
  entities[String.fromCharCode(39)] = "&#39;";
  return String(value).replace(/[&<>"']/g, char => entities[char]);
}
function escapeAttr(value) { return escapeHtml(value).replace(/`/g, "&#96;"); }
load();
</script>
</body>
</html>
"""

HTML = render_html("__MONITOR_TOKEN__", pet_asset_urls())
