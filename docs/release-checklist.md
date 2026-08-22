# Release Checklist

结论：每次交付前必须先证明核心逻辑、事件接入、原生悬浮入口、进程探测边界、Pet 左键/右键边界和隐私减负主路径都可用。

Pet 外观主题切换的执行 PRD 是 `docs/prd/2026-07-11-pet-appearance-theme-switching-prd.md`；系统通知开关的执行 PRD 是 `docs/prd/2026-07-14-notification-preference-toggle-prd.md`；新增 AI 工具监控的执行 PRD 是 `docs/prd/2026-07-14-ai-tool-monitoring-expansion-prd.md`；ChatGPT 迁移与多工具回归记录是 `docs/qa/2026-07-17-chatgpt-and-multi-tool-regression-test-cases.md`；v0.2.1 历史双包记录是 `docs/qa/2026-07-17-v0.2.1-release-packaging-validation.md`；v0.3.0 撤回候选、校验和、回下载、工具驱动实机证据和撤回原因记录在 `docs/qa/2026-07-30-v0.3.0-release-packaging-validation.md`。发布前需确认 PRD、README、QA 报告和本清单中的菜单、资源、偏好、API、App 验收描述一致。

## v0.3.0 撤回候选状态

| 项目 | 历史要求 | 当前状态 |
|---|---|---|
| Release | 标题使用与历史版本一致的 `v0.3.0`；发布前不得把候选状态写成已通过 | GitHub 技术状态为 Draft、非 Prerelease、不是 Latest；产品状态为已撤回，公开稳定版仍为 v0.2.1 |
| 源码基线 | PR #5 合并提交 `770d447` 与测试稳定性 PR #6 合并提交 `ed468b8`，再叠加版本、发布文档和 portable 解压态入口修复 | PR #7 已合并；最终 `main` 为 `ff667a3813d90cd701a016d6ae5a0f08612587a8` |
| 附件 | `AI-Progress-Monitor-v0.3.0-macOS-arm64.zip`、`ai-progress-monitor-v0.3.0-portable.zip` | 保留在 Draft Release 作为历史证据；远端字节数与 SHA-256 正确，但附件不包含后续运行时修复且不得发布 |
| 自动化门 | 本地完整测试、`scripts/validate_release.py`、PR CI 和合并后 `main` CI | 本地 517 项和发布校验通过；后续审计确认当时远端 workflow 漏掉 6 个模块、100 项测试，旧 CI 不能作为完整门禁 |
| 候选包验证门 | 双包结构、版本、架构、最低系统、签名、资源、SHA-256 和工具驱动核心交互 | 历史结构与工具驱动检查通过，但最终人工验收发现状态抖动和并发刷新阻塞，候选失去发布资格 |
| 用户验收门 | 用户亲自测试最终候选包，并明确确认“验收通过，可以发布” | 未通过；v0.3.0 放行路径已关闭，不能通过补测旧附件恢复 |
| GitHub 发布门 | annotated tag、附件、回下载哈希、用户验收和明确授权全部满足后才能发布 | 不得发布 v0.3.0，不得移动 tag、替换附件或复用旧 SHA-256 |
| 权威证据 | `docs/qa/2026-07-30-v0.3.0-release-packaging-validation.md` | 已按撤回状态回填；后续发布证据必须属于 v0.3.1 |

## v0.3.1 Draft PR 状态（截至 2026-08-22，未发布）

| 项目 | 当前证据 | 状态 |
|---|---|---|
| 源码候选 | 分支 `codex/fix-runtime-state-and-notification-dedup` 已推送并创建 Draft PR #9；版本为 `0.3.1`，运行态、并发刷新、通知去重和 3 个 P2 修复均已进入该分支 | 尚未合并、打 Tag 或发布 |
| 完整 CI 门 | 旧 PR run 在手工枚举测试模块的 workflow 下通过，但漏掉 6 个模块、100 项测试；本分支已改为直接执行 `scripts/validate_release.py`，与本地完整门禁共用同一入口；本地 630 项和统一发布校验已通过 | 必须在包含本次改动的新 PR CI 上复核，旧 run 不能放行 |
| 构建防错门 | `build_release.py` 要求仓库根目录、完整 `--source-commit`、干净工作区、版本一致和 Tag 冲突检查；从指定 Git commit 导出仅含已跟踪文件且保留权限的隔离 TAR 快照完成校验和打包，二次校验后才安全替换 `dist/`；正式附件再用 `--require-tag` 校验 annotated tag 精确指向源码提交 | 17 条定向回归与本地完整门禁通过；仍须通过新 PR CI |
| 早期 macOS 候选包 | `AI-Progress-Monitor-v0.3.1-macOS-arm64.zip` 曾独立解包并通过版本、arm64、macOS 13+、资源与 ad-hoc 验签 | 只对应 `9d280a0`；不包含后续 P2 和门禁修复，不得发布 |
| 早期 portable 候选包 | `ai-progress-monitor-v0.3.1-portable.zip` 曾通过入口帮助、doctor、monitor command 与包内 E2E | 只对应 `9d280a0`；不包含后续 P2 和门禁修复，不得发布 |
| 人工验收 | 用户已验证早期包和后续 Dev App 的 Zed / VS Code 状态、精准聚焦、通知关闭/恢复、去重、重启、隐藏与恢复 | 不能替代最终 Tag 对应附件的回下载验收；最终包尚未生成 |
| 命令行锁定门 | 隔离偏好为开启时使用 `--no-notifications` 启动，实际状态为关闭且锁定；开启请求返回 `409 notifications_forced_disabled`，原偏好与未知字段未改写，文件权限为 `600` | 功能证据通过；最终 portable 包仍需复核 |
| GitHub Release | 当前不存在 v0.3.1 Release 或 Tag；v0.3.0 Draft 不得复用 | 待合并、完整 CI、annotated tag、双包构建、Draft 回下载和最终人工验收后再申请发布授权 |

早期候选包 SHA-256（历史证据，不得用于最终发布）：

| 文件 | SHA-256 |
|---|---|
| `AI-Progress-Monitor-v0.3.1-macOS-arm64.zip` | `5f5c5aea5a15e09f6f9a6514ab8a8cb72453448f17dbae3c8d88a16f60646f9a` |
| `ai-progress-monitor-v0.3.1-portable.zip` | `f2efe5c69755137c5038e2cb2bf152efc8eb9614625259a1f1484ecb233c19c2` |
| `ai-progress-monitor.pyz` | `7212855f579a893d5d38fa62b2bd486893008dd51f576fb5c4dbcfb292bf4ebd` |

以上哈希只对应候选包源码提交 `9d280a02f5e4d644c87c6724f54ed35adc275ffa`。其后的 P2、完整 CI 和构建防错修复已改变最终源码与发布流程，因此旧包与本表哈希不得作为最终发布依据。进入公开发布前，必须从最终 annotated tag 对应提交重新构建双包、重新计算哈希、上传到新的 v0.3.1 Draft Release，并回下载后完成最终人工验收。

## v0.2.1 历史发布基线

| 项目 | 结果 |
|---|---|
| Release | [v0.2.1](https://github.com/AutumnGao77/ai-progress-monitor/releases/tag/v0.2.1)，2026-07-20 发布，非 Draft / Prerelease |
| Tag 固定点 | annotated tag `v0.2.1` → `0deab62144d4c16e780b8aaa7cafe6fbbe9c5175` |
| 附件 | `AI-Progress-Monitor-v0.2.1-macOS-arm64.zip`、`ai-progress-monitor-v0.2.1-portable.zip` |
| 自动化门 | 445 项全量测试、发布校验和双包结构检查通过 |
| 下载后人工门 | GitHub 回下载、解压、首次打开、Pet、菜单、气泡和窗口跳转于 2026-07-20 通过 |
| 权威证据 | 最终 SHA-256 与逐项结果见 `docs/qa/2026-07-17-v0.2.1-release-packaging-validation.md`；后续版本必须重新构建、重新计算校验和，不能沿用 v0.2.1 数值 |

## 必跑检查

> 候选构建必须在干净工作区显式绑定当前完整提交。正式附件必须在 annotated `v<版本>` tag 创建并确认不可移动后增加 `--require-tag`；构建成功不等于允许发布。

推荐直接运行：

```bash
python3 scripts/validate_release.py
```

| 检查项 | 命令 | 通过标准 |
|---|---|---|
| 单元测试 | `PYTHONPATH=src python3 -m unittest discover -s tests` | 全部通过 |
| 语法编译 | `PYTHONPYCACHEPREFIX=/private/tmp/ai-progress-pycache PYTHONPATH=src python3 -m compileall -q src scripts` | 无报错 |
| 入口帮助 | `PYTHONPATH=src python3 -m ai_progress_monitor --help` | 正常显示参数 |
| 事件脚本 | `python3 scripts/emit_event.py --help` | 正常显示参数 |
| 前端脚本语法 | `python3 scripts/validate_release.py` 内置检查 | 无 JS 语法错误 |
| 敏感信息扫描 | `python3 scripts/validate_release.py` 内置检查 | 无本机真实姓名、公司相关账号标识、本机路径、旧邮箱片段或机器名命中 |
| Web API 冒烟 | 启动服务后用页面令牌请求 `/api/sessions` | 返回会话 JSON |
| API 安全冒烟 | 不带令牌请求 `/api/sessions` | 返回 403 |
| 三态 Pet 资源与外观切换 | `PYTHONPATH=src python3 -m unittest tests.test_web_ui tests.test_web_launch tests.test_web_ui_behavior tests.test_preferences` | 三态图片路由、衬衫树懒外观路由、APP 头像、可配置资源、透明角、状态切图和右键外观子菜单均通过；运行时 APP 头像为透明圆形，无水印和圆外方框背景 |
| 原生透明背景 | `PYTHONPATH=src python3 -m unittest tests.test_web_ui` | `.pet` 不添加 `drop-shadow`；WebView 背景保持透明 |
| 候选包构建 | `python3 scripts/build_release.py --source-commit "$(git rev-parse HEAD)"` | 仅在仓库根目录、工作区干净、完整 SHA 等于当前 `HEAD`、版本一致且不存在冲突 Tag 时，从该 commit 的隔离已跟踪文件快照生成三项产物；失败不得覆盖原 `dist/` |
| 正式 Tag 附件构建 | `python3 scripts/build_release.py --source-commit "$(git rev-parse HEAD)" --require-tag` | 除候选门禁外，annotated `v<版本>` tag 必须精确指向同一提交；生成 `dist/ai-progress-monitor.pyz`、macOS ZIP 和 portable ZIP |
| 版本一致性 | `PYTHONPATH=src python3 -m unittest tests.test_macos_app_bundle` | `ai_progress_monitor.__version__`、`pyproject.toml`、macOS App 的 `CFBundleVersion` / `CFBundleShortVersionString` 一致；正式 Tag 使用对应的 `v<版本号>`，已发布 Tag 不移动 |
| macOS 用户包 | 解压 macOS ZIP | 根目录只包含一个 `AI Progress Monitor.app`、`README.txt` 和 `LICENSE`；App 为 arm64、最低 macOS 13，不出现 `Floating` 后缀、根目录 `.pyz`、`scripts/` 或 `native/` |
| portable 包 | 解压 portable ZIP | 包含 `.pyz`、`scripts/`、`native/windows/`、`README.txt` 和 `LICENSE`；不包含任何 macOS `.app` |
| macOS App 编译门禁 | `PYTHONPATH=src python3 -m unittest tests.test_macos_app_bundle` | 缺少 `swiftc`、Swift 编译失败或未生成可执行文件时发布构建必须失败；不得生成占位 App，不嵌入 Swift 构建源码 |
| macOS App 图标 | 检查 `.app/Contents/Resources/` 和 `Info.plist` | 包含 `app-avatar.png`、`AppIcon.icns`，且 `CFBundleIconFile` 为 `AppIcon` |
| 发布包视觉资源 | 检查 `dist/ai-progress-monitor.pyz` 内容 | 包含 `sloth-pet-idle.png`、`sloth-pet-running.png`、`sloth-pet-needs-action.png`、`sloth-pet-shirt.png`、`app-avatar.png` |
| 发布包资源收口 | 检查 `dist/ai-progress-monitor.pyz` 内容 | 不包含 `assets/sloth-candidates/` 或 `.DS_Store` |
| 终端桥接 | `python3 scripts/monitor_command.py --help` | 正常显示参数 |
| 一键启动 | `python3 dist/ai-progress-monitor.pyz --help` | 参数包含 `--open` |
| 命令行通知关闭 | `python3 dist/ai-progress-monitor.pyz --help` | 参数包含 `--no-notifications` |
| Pet 系统通知开关 | `PYTHONPATH=src python3 -m unittest tests.test_preferences tests.test_notifier tests.test_service tests.test_web_launch tests.test_web_ui tests.test_web_ui_behavior` | “系统通知 >”展开“开启 / 关闭”，当前项互斥勾选；默认开启、持久化、同值不重复写入、即时生效、失败回滚、快速连点、旧通知不补发、持续待处理不周期重复、跨重启去重和命令行锁定态均通过 |
| 会话清理 | `python3 dist/ai-progress-monitor.pyz --help` | 参数包含 `--cleanup-after-seconds` |
| 响应目录 | `python3 dist/ai-progress-monitor.pyz --help` | 参数包含 `--response-dir` |
| 环境诊断 | `python3 scripts/doctor.py` | 输出 Python、平台、目录、通知、窗口适配检查 |
| 进程探测边界 | `PYTHONPATH=src python3 -m unittest tests.test_sources tests.test_service tests.test_web_ui` | 直接 CLI 标记为 `process_only`；POSIX 扫描在 `lsof`、子进程和父进程查询前丢弃 `Z/E` 退出态进程，避免单个残留进程耗尽全局扫描预算；Claude 每轮扫描先重置进程级 `cwd`，只使用当前进程或同 PID 且目录一致的状态记录，不虚构其他项目会话；Claude 终端回复完成后显示待处理，点击气泡成功回到系统终端或 IDE 内置终端后转空闲；Codex、Qoder、WorkBuddy CLI 按进程活跃度保守判断；桌面端具体对话已查看后转空闲并保留 15 分钟后移出；不展示终端内容 |
| Qoder / WorkBuddy 监控 | `PYTHONPATH=src python3 -m unittest tests.test_sources tests.test_service tests.test_store tests.test_web_ui_behavior tests.test_window_focus` | Qoder、Qoder CN、WorkBuddy 均支持桌面空闲入口、具体会话气泡、统一三态、真实标题、点击聚焦、15 分钟收口和退出后清理；用户注意状态不能因点击气泡变空闲 |
| 原生浮窗 | `PYTHONPATH=src python3 -m unittest tests.test_macos_native_companion tests.test_windows_native_companion` | macOS 已验收路径和 Windows 轻量预览入口的代码级边界被覆盖；Windows 稳定交付仍需单独人工验收 |
| 端到端冒烟 | `python3 scripts/e2e_smoke.py --artifact dist/ai-progress-monitor.pyz` | 临时启动 Web 服务和 Claude/Codex wrapper，验证服务、事件接入和状态更新链路；新版 Pet 主界面不展示直接回复按钮 |

## 人工验收

| 场景 | 期望结果 |
|---|---|
| Demo 模式启动 | 浏览器访问 `http://127.0.0.1:8765` 能看到 3 个会话 |
| macOS 用户入口 | 解压 macOS arm64 ZIP 后双击唯一的 `AI Progress Monitor.app`；原生 Pet 小窗置顶；关闭只隐藏；菜单栏头像图标可恢复/退出；无需在两个 App 之间选择 |
| Windows 轻量预览入口 | 解压 portable ZIP 后双击 `scripts\start_floating_monitor.bat`；小窗置顶；关闭只隐藏；托盘可恢复/退出；作为预览路径记录，稳定交付需单独验收 |
| API 令牌 | 页面能读取启动令牌并请求会话 API |
| 系统通知 | 右键 Pet → 系统通知，展开“开启 / 关闭”；默认显示“✓ 开启”；关闭后显示“✓ 关闭”，不弹窗但 Pet 状态继续更新；重新开启不补发旧状态；每次进入待处理只提醒一次，持续待处理超过 5 分钟不重复，保持待处理重启也不补发，离开后重新进入且冷却满足时恢复提醒 |
| 需要处理状态 | 页面右下角宠物显示“待处理” |
| 三态换图 | 空闲、进行中、待处理分别显示对应 Pet 图片；右上角数字角标仍显示总气泡数 |
| 外观子菜单 | 右键 Pet → 外观，展开“背带裤树懒 / 衬衫树懒”；当前项显示对勾；切换衬衫树懒后三态共用衬衫图，切回背带裤树懒后三态恢复 |
| 悬浮窗透明 | 原生悬浮入口只显示 Pet、角标和气泡，不出现灰底、白底或额外阴影边 |
| 菜单栏图标 | macOS 菜单栏状态项显示 APP 头像图标，不显示文字 `AI` |
| 终端桥接 | 用 `scripts/monitor_codex.*` 或 `scripts/monitor_claude.*` 包装命令后，输出能进入 Web Companion |
| 直接 CLI 探测 | 直接运行 `claude` / `codex`；显示 process-only 气泡；Claude 终端回复完成后进入“待处理”，点击气泡跳回对应终端后转“空闲”；Codex CLI 活跃为“进行中”、静默为“空闲”；气泡不展示终端内容或技术说明 |
| ChatGPT 桌面端监控与已查看收口 | 让 ChatGPT 具体对话进入运行中、待处理后点击气泡查看；仅接收明确桌面 `originator`，显示真实状态；无辅助功能权限也能激活 ChatGPT；完成待查看转为空闲并保留 15 分钟；超过 15 分钟具体对话移出，ChatGPT 仍存活时显示 App 空闲入口 |
| App 长期运行恢复 | 精确终止 Dev.app 的内嵌 Python 子服务；原生 App 应按指数退避自动拉起新服务、加载新令牌 URL 并恢复会话轮询，退出 App 时不重启 |
| Qoder / Qoder CN | 打开 Qoder 或 Qoder CN，发起任务或触发 Action Required；App 存活但无具体会话时显示桌面空闲入口，具体任务显示产品名和真实标题，完成待查看可点击后转空闲，Action Required / suspended / requiresApproval 保持待处理 |
| WorkBuddy | 打开 WorkBuddy，分别验证空闲、运行中、完成、等待用户操作、项目/文件夹下对话；空闲入口显示 `WorkBuddy Desktop · 空闲`，具体会话显示软件名和项目/文件夹上下文，完成待查看可点击后转空闲，用户注意状态点击后仍待处理 |
| process-only 去重 | 同一个进程已被桥接脚本监控时，只显示完整监控项，不再显示重复的 process-only 项 |
| 复杂交互 | 不展示直接回复按钮，引导回原窗口 |
| 窗口定位 | 点击气泡后尝试激活对应窗口；直接 CLI 优先聚焦父 GUI 应用。精确命中 macOS 窗口后，必须先连续确认目标为 AX focused/main，再监听真实 App 激活，激活完成后重新抬升并复核同一目标；快速连续点击时旧任务必须失效。macOS 14+ 使用来源感知的协调激活，不能回退到无来源 App 激活；macOS 13 兼容请求也必须等待并验证激活结果。多屏 Zed 至少用两个项目窗口做正反向真实鼠标验收，分别确认只出现目标窗口且可直接输入 |
| 左键 Pet | 只展开/收起气泡列表，不隐藏 Pet |
| 右键 Pet | 只出现外观、系统通知、隐藏 Pet、退出程序；“系统通知 >”二级菜单显示互斥的“开启 / 关闭”，锁定时显示“✓ 关闭”且两项均置灰；隐藏后程序继续运行 |
| 低侵入体验 | 默认只显示 Pet、角标和气泡列表，不出现工具面板 |

## 当前发布说明

| 项 | 说明 |
|---|---|
| 默认界面 | 本地 Web Companion；桌面宠物体验当前推荐已验收的 macOS 原生悬浮入口，Windows 轻量入口保留为预览路径 |
| 实验界面 | Tkinter 悬浮窗，受系统 Tk 版本影响，暂不作为默认交付入口 |
| 数据接入 | 推荐终端桥接脚本或 JSON 事件源；直接 Claude CLI 可用本地会话状态识别回复后待处理，Codex / Qoder / WorkBuddy CLI 仍保守判断活跃/空闲；ChatGPT Desktop 兼容读取 `~/.codex/sessions`，Qoder / Qoder CN / WorkBuddy 桌面端读取本地日志、缓存或会话库生成具体对话 |
| GitHub 公开发布 | `dist/` 产物不提交源码仓库；macOS arm64 ZIP 与 portable ZIP 同时作为 GitHub Release 附件上传；当前 macOS `.app` 未 notarized |
| 版本 tag 策略 | 已发布 tag 不移动；发布后 CI、测试边界或文档修复留在 `main`，下一次用户可见改动再发新的补丁版本 |
| 隐私策略 | 本地运行，不上传会话内容 |
| 当前发布包 | macOS 13+ Apple Silicon 用户包只含一个正式 App、README 和 LICENSE；portable 包承载 Python 3.9+ Web Companion、CLI 集成、诊断和 Windows 轻量预览脚本 |
| 诊断工具 | `scripts/doctor.py` 可用于定位权限、目录和平台适配问题 |
| Pet 偏好配置 | `~/.ai-progress-monitor/preferences.json` 支持 `pet_appearance`、布尔值 `notifications_enabled` 和 `pet_assets.*` 本地路径；通知值缺失或非法时默认开启，资源无效时回退内置资源 |
| 通知运行基线 | `~/.ai-progress-monitor/notification-state.json` 只包含哈希会话键、状态和通知时间，权限为 `600`；不得出现原始会话 ID、标题、项目名或摘要；历史/非活跃条目最多 512 条，当前活跃会话优先保留；损坏和写入失败安全降级 |
