# AI 工作进度监控桌面助手

[English](README.en.md) | 中文

[![Validate](https://github.com/AutumnGao77/ai-progress-monitor/actions/workflows/validate.yml/badge.svg)](https://github.com/AutumnGao77/ai-progress-monitor/actions/workflows/validate.yml)

结论：这是一个本地优先、低侵入的 AI 工作进度监控助手，用来聚合主流 AI 工具在终端/桌面端中的状态，并在需要用户处理时提醒。当前稳定交付重点是本地 Web Companion 和已验收的 macOS 原生悬浮窗口；Windows 保留轻量预览入口，尚未作为稳定交付版本验收。

产品规则：打开这个 App 之后，才开始监控所有 AI 对话的进度并按状态反馈；打开前已经沉淀在历史文件里的桌面/JSON 会话不纳入本轮气泡列表。当前仍存活的 CLI 和桌面 App 属于现场，可显示为空闲入口或当前状态，后续活动继续更新；有具体会话时，具体会话优先于通用存活入口。桌面端具体对话被用户点击查看并转为空闲后，在气泡列表保留 15 分钟；15 分钟后自动移出，如果该桌面 App 仍存活，则保留 App 空闲入口。

## 当前能力

| 能力 | 状态 |
|---|---|
| 低侵入 Web Companion | 已支持 |
| macOS 原生悬浮 Companion | 已支持，发布包内提供置顶窗口与状态栏恢复入口 |
| Windows 轻量悬浮 Companion | 预览入口，发布包内保留 WinForms/PowerShell 启动脚本，尚未作为稳定交付版本验收 |
| 左键展开/收起气泡列表 | 已支持 |
| 拖动宠物位置并记忆 | 已支持 |
| 右键隐藏 Pet | 已支持，程序继续运行，可从菜单栏/托盘恢复 |
| 右键退出程序 | 已支持，关闭桌面 Pet 和本地服务 |
| 同文件夹/无文件夹多对话区分 | 已支持；有文件夹时用文件夹名 + 工具名和稳定序号区分；桌面版无真实文件夹时用 `工具名 对话` / `工具名 对话 #1`，不展示不可读 session_id 碎片；自动聊天目录由工具定义表配置识别 |
| Claude Code / Codex 状态模型 | 已支持 |
| JSON 事件源 | 已支持，推荐作为可靠接入方式 |
| 通用 AI 工具识别配置 | 已支持，桌面 App 和 CLI 通过工具定义表接入；配置项包含 `key`、`display_name`、内部工具类型、CLI 可执行名、桌面主程序路径、忽略进程 token、自动聊天目录 pattern。当前覆盖 Claude、Codex、ChatGPT、Gemini、Perplexity、Poe、Cursor Agent、Qwen Code、Aider、OpenCode、Goose、Continue、Kiro 等主流工具的存活入口 |
| Codex 桌面端会话识别 | 已支持，读取 `~/.codex/sessions` 中的会话事件，未完成任务显示为进行中；已查看后转空闲的具体桌面对话保留 15 分钟后移出；如果只有桌面 App 存活且没有具体会话事件，则显示空闲入口 |
| Claude/Codex CLI 进程检测 | 已支持，直接启动 `claude` / `codex` 时显示 process-only 气泡；Claude CLI 优先读取 Claude 会话状态，明确 idle 时不因短暂 CPU/MCP 活跃翻成进行中，读不到时回退到进程活跃度；Codex CLI 暂按进程活跃度保守判断 |
| macOS / Windows 窗口扫描 | 已支持基础窗口标题扫描 |
| 桌面窗口 ID / 进程信息跟踪 | 已支持，用于更可靠地回到原窗口 |
| 点击气泡回到原窗口 | 已支持，优先用窗口 ID / 进程信息聚焦 |
| 主界面信息脱敏 | 已支持，不展示 summary、命令输出或直接回复按钮 |
| 完成/空闲轻提示 | 已支持，仅从执行中转为完成时提醒一次 |
| 疑似卡住轻提示 | 已支持，仅从执行中转为疑似卡住时提醒一次 |

## 运行环境

- Python 3.9+
- 无第三方运行依赖
- macOS 是当前已验收的原生悬浮入口平台
- Windows 可运行 Web Companion 和轻量预览脚本，但不是当前稳定交付重点

## 快速启动

```bash
PYTHONPATH=src python3 -m ai_progress_monitor --demo --no-windows
```

启动后终端会打印带令牌的本地访问地址。页面本身会自动携带令牌访问 API；如果手动调接口，需要带上启动时生成的 `token`。如果默认端口 `8765` 已被占用，程序会自动尝试后续端口，并以终端打印的地址为准。

```text
http://127.0.0.1:8765
```

也可以使用脚本：

```bash
sh scripts/run_web_demo.sh
```

Windows:

```bat
scripts\run_web_demo.bat
```

发布包内推荐使用一键启动脚本，会自动打开浏览器：

```bash
sh scripts/start_monitor.sh --demo --no-windows
```

Windows:

```bat
scripts\start_monitor.bat --demo --no-windows
```

macOS 用户也可以双击发布包内的 `AI Progress Monitor.app` 启动。

如果需要更接近桌面宠物的体验，优先使用发布包中的原生悬浮入口：

| 系统 | 启动方式 | 行为 |
|---|---|---|
| macOS | 双击 `AI Progress Monitor Floating.app` | 当前已验收的桌面 Pet 入口；原生置顶窗口；点击关闭只隐藏，可从菜单栏头像图标恢复或退出 |
| Windows | 双击 `scripts\start_floating_monitor.bat` | 轻量预览入口；WinForms/PowerShell 置顶窗口；点击关闭只隐藏，可从托盘图标恢复或退出；后续需单独验收 |

开发阶段不需要先打发布包，可以在 macOS 上生成临时试用版：

```bash
scripts/run_macos_floating_dev.sh
```

该脚本只在 `build/macos-dev/` 生成本地开发态 `AI Progress Monitor Floating Dev.app`，用于本机真实鼠标测试，不生成 release zip，也不写入 `dist/` 发布目录。

手工测试后可查看开发态检查结果：

```bash
scripts/check_macos_floating_dev.sh
```

它只读取进程和 `~/Library/Logs/AI Progress Monitor/native-monitor.log`，用于确认 dev Pet 是否启动、服务 URL 是否出现、本轮是否收到隐藏/恢复/退出等 host 消息。输出中的本地访问令牌会脱敏；如果服务已被 Pet 轮询，还会显示类似 `total=4 running=1 idle=3 process_only=4` 的脱敏会话计数，用来确认终端和桌面 Claude/Codex 是否已被识别。

完成真实鼠标验收时使用严格模式：

```bash
scripts/check_macos_floating_dev.sh --strict
```

如果仍有未完成路径，输出会包含 `Manual acceptance incomplete` 和对应 `[TODO]`；所有真实路径都有证据后才会输出 `Manual acceptance complete`。严格模式只统计本次开发态启动后的日志，避免旧操作记录造成误判。

## 外观资源与配置

当前 Pet 使用三张本地图片表达三种用户状态，并使用独立 APP 头像资源。角标、气泡、拖动和右键菜单逻辑不依赖具体图片内容。

| 用途 | 运行时路由 | 内置资源 |
|---|---|---|
| 空闲 | `/assets/pet/idle.png` | `src/ai_progress_monitor/assets/sloth-pet-idle.png` |
| 进行中 | `/assets/pet/running.png` | `src/ai_progress_monitor/assets/sloth-pet-running.png` |
| 待处理 | `/assets/pet/needs-action.png` | `src/ai_progress_monitor/assets/sloth-pet-needs-action.png` |
| APP 头像 / favicon / macOS 图标 | `/assets/app-avatar.png` | `src/ai_progress_monitor/assets/app-avatar.png` |

三态 Pet 图片当前为 768 x 768 PNG，APP 头像为 1024 x 1024 PNG。图片角落必须保持透明；APP 头像源图和运行图必须保持透明圆形，水印和圆外方框背景应清除，透明像素应保持 `(0,0,0,0)`，避免系统图标缓存或缩放时出现脏边。Web 容器本身保持 `background: transparent` 且 `.pet` 不额外添加 `drop-shadow`，避免原生悬浮窗出现灰底或阴影边。macOS 发布包会把 APP 头像复制到 `.app` 资源目录，生成 `AppIcon.icns`，并让菜单栏状态项显示头像图标而不是 `AI` 文字。

如果只想替换外观，不需要改代码，可以在偏好文件中配置本地图片路径：

```json
{
  "pet_assets": {
    "idle": "/path/to/idle.png",
    "running": "/path/to/running.png",
    "needs_action": "/path/to/needs-action.png",
    "app_avatar": "/path/to/app-avatar.png"
  }
}
```

偏好文件默认位置是 `~/.ai-progress-monitor/preferences.json`。自定义图片支持 PNG、JPG、JPEG、WebP，单个文件最大 8 MB；路径无效、格式不支持或文件过大时会自动回退到内置资源。兼容旧入口的 `sloth-pet.png` 保留为空闲态图片。

页面右下角会显示原创树懒 Pet。左键点击 Pet 只负责展开或收起上方气泡列表；右键点击 Pet 会打开菜单，菜单只提供“隐藏 Pet”和“退出程序”。每条气泡只展示文件夹/对话标识和状态；桌面版 AI 对话没有真实项目文件夹时显示为 `工具名 对话` 或安全短标题，工具定义表中声明的自动聊天目录也按无真实项目文件夹处理，例如 Codex 的 `Documents/Codex/YYYY-MM-DD/<对话名>`。后续接入其他 AI 桌面端时，只需补充对应工具配置和自动聊天目录 pattern，不需要改前端命名逻辑；页面不会展示不可读 session_id 碎片。点击气泡会尝试回到对应 Claude/Codex 窗口。

启动失败时，一键启动脚本会写入本地日志。macOS 日志默认在 `~/Library/Logs/AI Progress Monitor/monitor.log`，Windows 日志默认在 `%LOCALAPPDATA%\AI Progress Monitor\monitor.log`。

说明：

| 参数 | 作用 |
|---|---|
| `--demo` | 展示模拟 Claude Code / Codex 会话 |
| `--no-windows` | 关闭系统窗口扫描，便于先看界面 |
| `--session-dir` | 指定 JSON 会话目录 |
| `--response-dir` | 指定兼容响应目录；新版 Pet 主界面不提供直接回复按钮 |
| `--host` | 指定监听地址，默认 `127.0.0.1` |
| `--port` | 指定端口，默认 `8765` |
| `--open` | 启动后自动打开默认浏览器 |
| `--no-notifications` | 关闭系统级“需要处理”提醒 |
| `--cleanup-after-seconds` | 清理旧的完成/未知/疑似卡住会话文件，默认 7 天，设为 `0` 关闭；待处理会话不自动清理 |

终端桥接脚本和 Web 服务都支持 `AI_PROGRESS_MONITOR_HOME`。设置后，sessions 和 responses 会写到同一个根目录下，便于本地试用、便携发布或隔离测试：

```bash
AI_PROGRESS_MONITOR_HOME=/tmp/ai-monitor \
AI_MONITOR_SESSION_ID=checkout-flow \
AI_MONITOR_TITLE="Claude Code - checkout-flow" \
sh scripts/monitor_claude.sh claude
```

## 运行测试

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
```

上线前完整检查：

```bash
python3 scripts/validate_release.py
```

发布包端到端冒烟测试：

```bash
python3 scripts/e2e_smoke.py --artifact dist/ai-progress-monitor.pyz
```

该测试会临时启动本地服务和 wrapper，验证事件接入、状态更新与本地服务链路。新版 Pet 主界面只提供状态气泡和回到原窗口入口。

环境自检：

```bash
python3 scripts/doctor.py
```

当前测试覆盖：

| 测试文件 | 覆盖内容 |
|---|---|
| `tests/test_classifier.py` | 状态识别、工具识别、低风险动作识别 |
| `tests/test_store.py` | 会话合并、排序、疑似卡住、操作审计 |
| `tests/test_sources.py` | JSON 会话读取、进程级 CLI 检测、窗口元数据解析 |
| `tests/test_actions.py` | 兼容动作边界、响应文件写入 |
| `tests/test_service.py` | Web Companion 服务层数据和操作 |
| `tests/test_web_security.py` | 本地 API 访问令牌 |
| `tests/test_doctor.py` | 运行环境诊断 |
| `tests/test_macos_native_companion.py` | macOS 原生悬浮窗尺寸、置顶、收起/恢复 |
| `tests/test_windows_native_companion.py` | Windows 原生悬浮窗置顶、托盘恢复、展开/收起 |
| `scripts/e2e_smoke.py` | 发布包级端到端验证：服务、wrapper、事件接入链路 |

## 接入真实会话

推荐方式有两种：直接写 JSON 事件，或用终端桥接脚本包装 Claude Code / Codex 命令。

如果用户直接在终端运行已配置的 AI CLI，监控器会通过进程扫描显示 process-only 气泡；气泡本身仍只展示文件夹/对话标识和状态。当前仍处于前台交互终端状态的直接 CLI 会话会显示；即使 CLI 在 App 启动前已经打开，只要进程仍存在，也会显示为空闲或当前状态；退出 CLI 后，即使 IDE、终端或项目窗口还开着，也不应继续保留气泡。Claude CLI 会优先读取 `~/.claude/sessions/<pid>.json` 中 Claude 自己记录的会话状态：运行中显示进行中；明确空闲时保持空闲，不因短暂 CPU/MCP 活跃翻成进行中；回复完成后，或同一会话出现新的空闲完成时间后，先显示待处理，点击气泡成功回到对应系统终端或 IDE 内置终端后标记为已查看并转为空闲；读不到、状态不匹配或过期 running 时再按 CPU、进程运行态和过滤后的活跃子进程做保守判断。Codex CLI 暂按进程活跃度判断。Codex 桌面端会优先读取 `~/.codex/sessions` 的会话事件：App 启动后有未完成任务时显示进行中，有可见回复并完成后显示待处理，点击气泡成功回到窗口后转为空闲；已查看后转为空闲的桌面端具体对话保留 15 分钟后从气泡列表移出；如果只是已配置的 AI 桌面 App 主程序存活，或具体桌面对话都已移出，先显示空闲入口，有具体桌面会话后自动隐藏该入口，避免重复计数。普通系统权限不会读取或展示终端内部文本。

### 方式一：终端桥接脚本

macOS / Linux 示例：

```bash
AI_MONITOR_SESSION_ID=checkout-flow \
AI_MONITOR_TITLE="Claude Code - checkout-flow" \
sh scripts/monitor_claude.sh claude
```

Codex 示例：

```bash
AI_MONITOR_SESSION_ID=prd-polish \
AI_MONITOR_TITLE="Codex - PRD polish" \
sh scripts/monitor_codex.sh codex
```

Windows 示例：

```bat
set AI_MONITOR_SESSION_ID=prd-polish
set AI_MONITOR_TITLE=Codex - PRD polish
scripts\monitor_codex.bat codex
```

桥接脚本会：

| 行为 | 说明 |
|---|---|
| 读取终端输出 | 自动识别执行中、需要处理、完成等状态 |
| 写入 session JSON | Web Companion 会自动展示状态 |
| 支持窗口定位 | 复杂交互时可尝试激活对应窗口 |
| 保留原输出 | 终端仍会正常显示 Claude Code / Codex 输出 |

### 方式二：直接写 JSON 事件

默认目录：

```text
~/.ai-progress-monitor/sessions
```

示例：

```bash
python3 scripts/emit_event.py \
  --session-id claude-demo-1 \
  --title "Claude Code - checkout-flow" \
  --tool claude_code \
  --surface terminal \
  --status needs_action \
  --summary "需要回到原窗口处理"
```

新版 Pet 气泡不会展示 `summary` 或直接回复按钮；用户点击气泡后回到原 Claude/Codex 窗口处理。兼容响应文件目录仍保留给旧集成或外部适配器使用：

```text
~/.ai-progress-monitor/responses/<session-id>.response
```

集成方可读取该文件并把确认动作转发给对应 Claude Code 或 Codex 会话。

## 隐私与安全

| 原则 | 说明 |
|---|---|
| 本地优先 | 不上传会话内容 |
| 最小展示 | 默认只展示文件夹/对话标识和三态状态 |
| 回原窗口处理 | 主 Pet 不提供直接回复按钮 |
| 复杂交互回原窗口 | 大段阅读、自由输入、多选项、高风险命令不在宠物内处理 |
| 本地 API 令牌 | 页面和接口使用启动时生成的随机令牌 |
| 系统通知 | 仅在需要处理时提醒，并带冷却去重；同一轮多个待处理会话合并成一条通知 |
| 保守清理 | 仅自动清理旧的 idle/unknown/stuck，会保留 running/needs_action；待处理不会因为用户长时间未点击而自动消失 |
| 桌面对话收口 | 已查看后转为空闲的桌面端具体对话在气泡列表保留 15 分钟后移出；如果桌面 App 仍存活，则保留 App 空闲入口 |

API 示例：

```text
GET /api/sessions?token=<启动时生成的令牌>
POST /api/focus
Header: x-monitor-token: <启动时生成的令牌>
```

## 当前限制

| 限制 | 原因 | 后续方向 |
|---|---|---|
| 窗口扫描主要基于标题做状态识别 | 跨平台读取窗口内容需要系统权限 | 增强原生适配器 |
| 直接启动 `claude` / `codex` 仍不能读取具体对话内容 | Claude CLI 可用本地会话状态识别回复完成后或同一会话新的空闲完成时间后的待处理；Codex 桌面端可用会话事件识别回复完成后的待处理；Codex CLI 仍按进程活跃度保守判断 | 需要展示提示正文或更细粒度状态时使用桥接脚本 |
| 窗口激活仍依赖系统权限 | 当前优先用窗口 ID / 进程 ID，失败时按标题兜底 | 后续加入更完整的原生桌面壳 |
| Pet 不直接回复终端问题 | 避免误操作和焦点抢占 | 点击气泡回到原窗口处理 |
| Windows 通知依赖系统能力 | 当前优先使用 BurntToast 命令能力，缺失时静默降级 | 后续加入原生通知壳 |
| Windows 轻量悬浮入口尚未作为稳定交付验收 | 当前是 WinForms/PowerShell 预览版本，便于无依赖运行，视觉、动效和真实用户路径仍需单独验证 | 后续单独开 Windows 迭代，可升级为 WinUI/.NET 桌面壳 |
| Linux 不是首发重点 | PRD 优先 macOS / Windows | 架构已预留 |

## 打包建议

第一阶段可直接以源码方式运行，也可以构建无第三方依赖的发布包：

```bash
python3 scripts/build_release.py
python3 dist/ai-progress-monitor.pyz --demo --no-windows
python3 scripts/e2e_smoke.py --artifact dist/ai-progress-monitor.pyz
```

构建后会生成：

| 产物 | 用途 |
|---|---|
| `dist/ai-progress-monitor.pyz` | 单文件 Web Companion 运行包 |
| `dist/ai-progress-monitor-release.zip` | 推荐分发包，包含运行包、macOS `.app`、桥接脚本、一键启动脚本、Windows 预览脚本和说明 |

公开发布到 GitHub 时，建议把 `dist/ai-progress-monitor-release.zip` 作为 Release 附件上传，不提交到源码仓库。当前 macOS `.app` 是本地构建产物，未做 Apple notarization；下载用户可能需要在系统设置中允许打开。

如果用户反馈“打不开、没有提醒、无法回到窗口”，优先让用户运行：

```bash
python3 scripts/doctor.py
```

当前 Pet 主界面不提供诊断入口；需要排障时使用上面的命令行自检。

如果是双击或一键启动后没有反应，先查看启动日志：

| 系统 | 日志位置 |
|---|---|
| macOS | `~/Library/Logs/AI Progress Monitor/monitor.log` |
| Windows | `%LOCALAPPDATA%\AI Progress Monitor\monitor.log` |

当前默认界面是本地 Web Companion，适合先验证核心体验和接入链路。发布包已包含已验收的 macOS 原生悬浮 `.app`，并保留 Windows WinForms 轻量预览入口；后续上线可继续升级为更完整的 Electron、Tauri、WinUI 或平台原生壳。

当前系统自带 Tkinter 在部分 macOS 环境可能无法启动真实窗口，因此 Tkinter 悬浮窗只作为实验入口保留，不作为默认交付入口。

## 开源协议与视觉素材

| 内容 | 说明 |
|---|---|
| 代码协议 | MIT License，见 `LICENSE` |
| 视觉素材 | Pet 图片、APP 头像、宣传页图片和候选素材按 `ASSET_LICENSE.md` 说明授权 |
| 图片来源 | 基于原创提示词使用豆包 AI 辅助生成，并经人工筛选和透明背景、尺寸、图标适配处理 |
| 公开仓库 | 提交并推送到公开仓库的源码、文档和素材可被互联网用户访问、下载和 fork；`build/`、`dist/`、`backups/`、`chats/` 等本地目录不提交 |
