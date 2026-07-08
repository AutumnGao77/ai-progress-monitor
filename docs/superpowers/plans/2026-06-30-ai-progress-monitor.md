# AI Progress Monitor Implementation Plan

> 历史计划：本文件记录 2026-06-30 阶段的早期实现路线，包含旧的低风险 Yes/No 宠物内处理设想。当前执行目标以 `docs/prd/2026-07-01-ai-sloth-pet-monitor-ai-coding-prd.md` 为准：主体验为原创树懒 Pet、气泡列表、点击回原窗口、右键隐藏/退出、通用 AI 工具配置和桌面端已查看会话 15 分钟收口。不要按本历史计划恢复旧工具面板或宠物内 Yes/No 主路径。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a usable cross-platform local desktop companion that monitors Claude Code and Codex sessions, shows low-intrusion progress, and supports low-risk Yes/No style actions.

**Architecture:** Use a Python standard-library local service and Web Companion so the first version runs without dependency downloads. Keep core state classification, session storage, window scanning, action execution, and UI delivery in separate modules. OS-specific monitoring and action execution are adapter layers so they can be replaced later with stronger native integrations or a packaged macOS / Windows desktop shell.

**Tech Stack:** Python 3, standard-library HTTP server, unittest, macOS AppleScript adapter, Windows PowerShell adapter, JSON session feed.

---

## File Structure

- `src/ai_progress_monitor/models.py`: shared dataclasses and enums.
- `src/ai_progress_monitor/classifier.py`: text/title to status and action classification.
- `src/ai_progress_monitor/store.py`: session merge, stuck detection, and action audit log.
- `src/ai_progress_monitor/sources.py`: JSON feed source and OS window source.
- `src/ai_progress_monitor/actions.py`: low-risk action validation and execution adapters.
- `src/ai_progress_monitor/web.py`: low-intrusion local Web Companion and HTTP API.
- `src/ai_progress_monitor/service.py`: UI-independent monitor service.
- `src/ai_progress_monitor/demo.py`: demo sessions for manual validation.
- `src/ai_progress_monitor/app.py`: experimental Tkinter companion, not the default entry point.
- `src/ai_progress_monitor/__main__.py`: default Web Companion entry point.
- `scripts/emit_event.py`: helper for integrations to publish reliable session events.
- `scripts/monitor_command.py`: wraps Claude Code / Codex terminal commands and streams status events.
- `scripts/monitor_claude.sh`, `scripts/monitor_codex.sh`: macOS/Linux convenience wrappers.
- `scripts/monitor_claude.bat`, `scripts/monitor_codex.bat`: Windows convenience wrappers.
- `tests/test_classifier.py`: status and action classification tests.
- `tests/test_store.py`: merge, ordering, and stuck detection tests.
- `tests/test_actions.py`: low-risk action boundary tests.
- `tests/test_sources.py`: JSON feed parsing tests.
- `tests/test_terminal_bridge.py`: terminal bridge status and response-file tests.
- `README.md`: setup, run, test, and packaging notes.

## Task 1: Core Status Model and Classifier

**Files:**
- Create: `src/ai_progress_monitor/models.py`
- Create: `src/ai_progress_monitor/classifier.py`
- Test: `tests/test_classifier.py`

- [ ] Write tests for running, needs-action, completed, unknown, and safe Yes/No detection.
- [ ] Run `python3 -m unittest tests.test_classifier` and confirm it fails because modules are missing.
- [ ] Implement enums, dataclasses, and classifier rules.
- [ ] Re-run `python3 -m unittest tests.test_classifier` and confirm it passes.

## Task 2: Session Store and Stuck Detection

**Files:**
- Create: `src/ai_progress_monitor/store.py`
- Test: `tests/test_store.py`

- [ ] Write tests for merging sessions from multiple sources, keeping latest updates, sorting needs-action first, and marking stale running sessions as stuck.
- [ ] Run `python3 -m unittest tests.test_store` and confirm it fails because store is missing.
- [ ] Implement session store and local audit writing.
- [ ] Re-run `python3 -m unittest tests.test_store` and confirm it passes.

## Task 3: Monitoring Sources

**Files:**
- Create: `src/ai_progress_monitor/sources.py`
- Create: `scripts/emit_event.py`
- Test: `tests/test_sources.py`

- [ ] Write tests for reading JSON session files and ignoring invalid files.
- [ ] Run `python3 -m unittest tests.test_sources` and confirm it fails because sources are missing.
- [ ] Implement JSON directory source, macOS window scanner command builder, and Windows window scanner command builder.
- [ ] Add `scripts/emit_event.py` to let Claude/Codex wrappers publish reliable events.
- [ ] Re-run `python3 -m unittest tests.test_sources` and confirm it passes.

## Task 4: Low-Risk Action Execution

**Files:**
- Create: `src/ai_progress_monitor/actions.py`
- Test: `tests/test_actions.py`

- [ ] Write tests proving Yes/No, Allow/Deny, and Continue/Stop are allowed only when classified as safe.
- [ ] Write tests proving free text, multi-option, and high-risk prompts are blocked.
- [ ] Run `python3 -m unittest tests.test_actions` and confirm it fails because actions are missing.
- [ ] Implement response-file execution for integrated sessions and guarded OS action command generation.
- [ ] Re-run `python3 -m unittest tests.test_actions` and confirm it passes.

## Task 5: Low-Intrusion Web Companion UI

**Files:**
- Create: `src/ai_progress_monitor/web.py`
- Create: `src/ai_progress_monitor/service.py`
- Create: `src/ai_progress_monitor/demo.py`
- Create: `src/ai_progress_monitor/app.py`
- Create: `src/ai_progress_monitor/__main__.py`

- [ ] Implement a low-intrusion bottom-right Web Companion.
- [ ] Add click-to-expand session list with current status, source, last update, and safe action buttons.
- [ ] Add pause, collapse, and refresh behavior.
- [ ] Keep Tkinter as experimental because system Tk availability varies across macOS machines.
- [ ] Run `PYTHONPATH=src python3 -m ai_progress_monitor --demo --no-windows` and manually verify the demo states render at `http://127.0.0.1:8765`.

## Task 6: Documentation and Release Readiness

**Files:**
- Create: `README.md`
- Modify: `AGENTS.md`

- [ ] Document setup, run, test, demo mode, JSON feed format, platform limitations, and packaging commands.
- [ ] Document that first version is local-only and privacy-preserving.
- [ ] Run `PYTHONPATH=src python3 -m unittest discover -s tests`.
- [ ] Run `PYTHONPATH=src python3 -m ai_progress_monitor --demo --no-windows` long enough to verify the Web Companion launches.
- [ ] Confirm no sensitive local real name appears in docs or code.
