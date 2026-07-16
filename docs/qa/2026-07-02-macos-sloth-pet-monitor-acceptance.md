# macOS 原创树懒 Pet 监控助手验收报告

## 结论

macOS 版本已完成 PRD 主路径验收并已构建发布包：默认 Pet、三色角标、气泡列表、同文件夹多对话区分、隐私保护、点击气泡聚焦、拖动不误展开、右键隐藏/退出、Show 恢复链路、再次打开 app 恢复、桌面端具体对话已查看后 15 分钟收口。

菜单栏头像图标中的 `Show Monitor`、外接屏跨屏拖动、气泡点击聚焦、状态稳定性已完成自动化覆盖和本地手动测试。用户本地测试通过后，已执行 `python3 scripts/build_release.py` 生成发布包。

| 项目 | 结论 |
|---|---|
| 当前本地源码状态 | 已验证，用户本地测试通过 |
| 自动化测试 | 通过，`298 tests OK` |
| Swift 编译 | 通过 |
| 发布包构建 | 通过，已生成 `dist/ai-progress-monitor.pyz` 和 `dist/ai-progress-monitor-release.zip` |
| 本地校验 | 通过，包含 release 校验、JS 语法、敏感信息扫描、e2e smoke |
| 真实运行 | macOS 开发态 app 已多轮真实测试；发布包已构建 |
| 完整目标状态 | 主路径已验收，`v0.1.0` 已作为 GitHub Release 发布 |
| 外观状态 | 三态 Pet 图片、APP 头像、透明背景和发布包已完成；后续换图优先走 `pet_assets` 配置 |

## 验收范围

| 范围 | 本轮状态 |
|---|---|
| macOS 桌面 Pet | 已验收 |
| Web UI 主体验 | 已验收 |
| 服务层 `/api/sessions` / `/api/focus` | 已回归 |
| Windows 托盘版 | 代码和发布包保留入口；本轮重点验收 macOS，Windows 体验后续单独迭代 |

## 2026-07-08 外观形象补充验收

| 项目 | 证据 | 结果 |
|---|---|---|
| 三态换图 | `renderBadge()` 根据待处理、进行中、空闲状态切换 `/assets/pet/needs-action.png`、`/assets/pet/running.png`、`/assets/pet/idle.png`；行为级 JS 测试覆盖三态 `petArt.src` | 通过 |
| APP 头像 | 源图和运行图均为透明圆形，水印和圆外方框背景已清除；页面 favicon 使用 `/assets/app-avatar.png`；macOS `.app` 内包含 `app-avatar.png` 和 `AppIcon.icns`，`Info.plist` 声明 `CFBundleIconFile=AppIcon` | 通过 |
| 菜单栏图标 | 原生 macOS 状态栏使用 `app-avatar.png` 图片，正常路径不再显示文字 `AI` | 通过 |
| 透明背景 | 三态 Pet PNG 为 768 x 768，APP 头像为 1024 x 1024，四角 alpha 均为 0；`.pet` 明确 `filter: none` 且不含 `drop-shadow` | 通过 |
| 可配置替换 | `~/.ai-progress-monitor/preferences.json` 支持 `pet_assets.idle`、`pet_assets.running`、`pet_assets.needs_action`、`pet_assets.app_avatar`；无效路径自动回退内置资源 | 通过 |
| 发布包资源 | `dist/ai-progress-monitor.pyz` 内包含 `sloth-pet-idle.png`、`sloth-pet-running.png`、`sloth-pet-needs-action.png`、`app-avatar.png`，不包含候选素材目录或 `.DS_Store` | 通过 |

## 2026-07-09 公开发布与 CI 收口

| 项目 | 证据 | 结果 |
|---|---|---|
| GitHub Release | 已发布 `v0.1.0`，附件为 `ai-progress-monitor-release.zip` | 通过 |
| tag 策略 | `v0.1.0` 保持指向已发布源码快照；发布后的 CI/测试边界修复留在 `main`，不移动已发布 tag | 通过 |
| GitHub Actions | 最新 `main` 校验通过；Web Python tests 已移除对本地候选素材目录的依赖，只校验公开运行时资产 | 通过 |
| 敏感信息收口 | 本地发布校验、GitHub Actions 敏感扫描、发布 zip 扫描、Release 页面文字扫描均通过；扫描范围覆盖本机真实姓名、公司相关账号标识、本机路径、旧邮箱片段和机器名 | 通过 |
| 公开仓库边界 | `build/`、`dist/`、本地候选源素材、日志和本地 agent 文件不提交；发布包只包含最终运行时视觉资产 | 通过 |

## 2026-07-11 Pet 外观主题切换补充验收

| 项目 | 证据 | 结果 |
|---|---|---|
| 执行 PRD | `docs/prd/2026-07-11-pet-appearance-theme-switching-prd.md` 记录菜单、资源、偏好、API、App 验收和文档同步关系 | 通过 |
| 菜单结构 | 右键 Pet 主菜单为“外观 / 隐藏 Pet / 退出程序”；外观子菜单为“背带裤树懒 / 衬衫树懒”，当前项显示对勾 | 通过 |
| 衬衫树懒资源 | `/assets/pet/shirt.png` 对应 `src/ai_progress_monitor/assets/sloth-pet-shirt.png`，来源为 `docs/promo/assets/sloth-mascot-transparent.png`；开发态检查脚本请求运行中 App 的该资源路由并校验 no-store | 通过 |
| 主题偏好 | `pet_appearance` 支持 `default` / `shirt`，缺失或非法值回退 `default`；写入时保留 `hidden_sessions`、`session_aliases`、`pet_assets` | 通过 |
| 本地 API | `GET /api/preferences` 和 `POST /api/preferences/pet-appearance` 均受 token 保护；非法 theme 返回 400，写入失败返回明确错误 | 通过 |
| 外观切换边界 | 外观只切换 Pet 本体；APP 头像、菜单栏图标、favicon、角标、气泡、拖动、隐藏、退出、通知、会话识别和聚焦逻辑不随主题改变 | 通过 |
| App 形态验收 | `scripts/check_macos_floating_dev.sh --strict` 已输出 `Manual acceptance complete`；用户已手动确认点击气泡聚焦窗口正常 | 通过 |
| 发布边界 | 已发布的 `v0.1.0` tag 不移动；本增量进入后续源码与发版流程，公开发版前按 `docs/release-checklist.md` 重新验证发布包资源 | 通过 |

## PRD P0 验收矩阵

| 编号 | 标准 | 证据 | 结果 |
|---|---|---|---|
| AC-1 | 主界面从工具面板变为原创树懒 Pet | `tests/test_web_ui.py` 检查 `pet-art`、`petBadge`、`bubbleList`；运行日志 `Pet visibility check` | 通过 |
| AC-2 | Pet 右上角数字角标显示气泡列表总数，并按状态变色 | 行为级 JS 测试执行真实 `renderBadge()`，覆盖混合 3 条会话显示 `3`、混合 6 条会话显示 `6`，并覆盖 `badge-needs-action`、`badge-running`、`badge-idle` | 通过 |
| AC-3 | 待处理红色、进行中绿色、空闲蓝色 | 行为级 JS 测试 + 静态颜色 class 测试 | 通过 |
| AC-4 | 多状态优先级：数字显示总数，颜色按待处理 > 进行中 > 空闲 | 行为级 JS 测试：1 待处理 + 2 进行中 + 3 空闲，角标红色 `6`；2 进行中角标绿色 `2`；3 空闲角标蓝色 `3` | 通过 |
| AC-5 | 点击 Pet 展开/收起气泡列表 | 行为级 JS 测试确认左键只发送 `resize:bubbles` / `resize:compact`；拖动后点击不展开；收起时重置 Pet 网页位置，不触发隐藏 | 通过 |
| AC-6 | 点击气泡调用 `/api/focus`，不调用 `/api/action` | 行为级 JS 测试真实点击待处理气泡，确认请求 `/api/focus` 且 body 为对应 `session_id`，无 `/api/action`；服务层优先使用终端父 GUI 进程聚焦 | 通过 |
| AC-7 | 主界面不展示 `summary`、命令输出、用户输入 | 注入 `SECRET_` 和 Yes/No 数据，页面未泄露 | 通过 |
| AC-8 | 主界面不展示旧入口 | 静态测试排除诊断、已隐藏、暂停、暂隐、隐藏会话、重命名 | 通过 |
| AC-9 | 同文件夹多个对话可区分 | 行为级 JS 测试验证同文件夹两个 Codex 的 `Codex #1/#2`、同文件夹 Claude + Codex 的 `Claude #1` / `Codex #1`，并验证排序变化后编号不跳动 | 通过 |
| AC-9b | 桌面版无文件夹对话不展示不可读 session_id | 行为级 JS 测试验证 `Codex Desktop - he-l` 这类无 cwd 对话显示为 `Codex 对话 · 空闲`；多个无文件夹桌面对话显示为 `Codex 对话 #1/#2`；安全可读标题可显示为 `Codex · hello`；工具定义表中声明的自动聊天目录按无真实项目文件夹处理，后续桌面端工具只补配置 | 通过 |
| AC-10 | 轮询和刷新链路支持 5 秒内可见 | `POLL_INTERVAL_MS = 3000`；source 并发轮询避免进程/窗口扫描超时串行累加；真实 `sessions_payload()` 约 1.37 秒返回 4 个会话 | 通过 |
| AC-11 | 右键 Pet 展示隐藏 Pet、退出程序 | 静态结构测试 + 行为级 JS 测试验证右键菜单打开本身不发送消息，点击“隐藏 Pet”才发送 `hide`，点击“退出程序”才发送 `quit`；右键按下不会触发拖动或展开 | 通过 |
| AC-12 | 隐藏 Pet 不停止监控，可恢复 | 右键隐藏入口独立；macOS `hideMonitor()` 只 `orderOut`，不 terminate；Show/reopen 会恢复紧凑尺寸、网页 Pet 可见态和收起态 | 通过 |
| AC-13 | 退出程序关闭 Pet 和本地服务 | macOS `quit()` 调用 `NSApp.terminate(nil)`，`applicationWillTerminate` 负责 `monitorProcess?.terminate()`；Quit 入口直接 target | 通过 |

## PRD P1 验收矩阵

| 编号 | 标准 | 证据 | 结果 |
|---|---|---|---|
| AC-14 | Pet 拖动和位置记忆保留 | 行为级 JS 测试执行真实 `pointerdown` / `pointermove` / `pointerup` 链路，确认只发送 `start-window-drag` / `stop-window-drag`，拖动后的点击不会展开气泡；Web 测试保留 `monitor.pet.position` | 通过 |
| AC-15 | 聚焦失败轻量提示，不展开诊断 | `test_focus_failure_shows_lightweight_note_without_diagnostics` 确认点击气泡失败显示“无法定位窗口”，无诊断入口 | 通过 |
| AC-16 | `process_only` 不读取终端内容，但必须显示直接 CLI 会话并区分活跃/静默/待查看 | 直接已配置 AI CLI 进程生成 process-only 气泡；Claude CLI 优先使用 `~/.claude/sessions/<pid>.json` 的会话状态，回复完成后或同一会话出现新的空闲完成时间后转待处理，点击气泡成功回到系统终端或 IDE 内置终端后转空闲；读不到时回退进程活跃度；气泡只展示文件夹/对话标识和状态；真实扫描能找到父 GUI 应用用于聚焦 | 通过 |
| AC-16b | 窗口权限不可用时，Codex 桌面端运行中对话仍可见 | 基于 `~/.codex/sessions` 的会话事件显示 Codex 运行中气泡；通用 Codex 桌面存活入口只显示空闲，且在具体会话存在时让位；内部 helper/app-server/sandbox 不展示 | 通过 |
| AC-16c | 已查看桌面端具体对话空闲 15 分钟后移出 | 服务层测试验证：桌面端具体对话点击气泡查看后转为空闲，15 分钟内仍显示；15 分钟后从气泡列表移出；如果桌面 App 进程仍存活，则显示 App 空闲入口 | 通过 |
| AC-17 | 小窗口不重叠 | 气泡避让 Pet，使用 `getPetVisualRect` 和 `VISUAL_MOTION_BUFFER`；行为级 JS 测试确认 host 模式不移动 Pet | 通过 |
| AC-18 | 待处理动作更明显 | `.pet.needs-action`、`.pet.running`、`.pet.idle` 动画层存在 | 通过 |

## 手工场景逐项映射

| 编号 | 场景 | 当前证据 | 判定 |
|---|---|---|---|
| M-1 | 无会话 | 行为级 JS 测试 `api.renderBadge([])`：无角标，Pet 保持 idle，气泡为空闲占位 | 已自动化 |
| M-2 | 单个进行中 | 行为级 JS 测试：1 running 角标绿色 `1`，气泡 `pricing-page · 进行中` | 已自动化 |
| M-3 | 单个待处理 | 行为级 JS 测试：needs_action 角标红色 `1`，Pet class 为 `needs-action`；CSS 待处理动作层存在 | 已自动化 |
| M-4 | 单个空闲 | 行为级 JS 测试：1 idle 角标蓝色 `1`，Pet class 为 `idle` | 已自动化 |
| M-5 | 混合状态 | 行为级 JS 测试：1 待处理 + 2 进行中 + 3 空闲时角标红色 `6`；进行中和空闲场景也分别覆盖 | 已自动化 |
| M-6 | 点击 Pet 展开 | 行为级 JS 测试：左键打开气泡，发送 `resize:bubbles` | 已自动化 |
| M-7 | 再次点击 Pet 收起 | 行为级 JS 测试：再次左键收起气泡，发送 `resize:compact`，不隐藏 | 已自动化 |
| M-8 | 点击气泡 | 行为级 JS 测试：点击气泡 POST `/api/focus`，body 为对应 `session_id`，不调用 `/api/action` | 已自动化 |
| M-9 | 同文件夹多对话 | 行为级 JS 测试：同文件夹两个 Codex、同文件夹 Claude + Codex、排序变化后稳定编号 | 已自动化 |
| M-9b | 无文件夹桌面对话 | 行为级 JS 测试：无 cwd 的 Codex 桌面对话不显示 `he-l` 等 session_id 碎片；工具定义表识别到自动聊天目录时显示 `Codex · hello`，真实项目目录仍显示项目文件夹；同一机制可复用于其他桌面 AI 工具 | 已自动化 |
| M-10 | 隐私检查 | 行为级 JS 测试注入 `SECRET`、`safe_action` 后气泡不展示 summary 或 Yes/No | 已自动化 |
| M-11 | 旧入口检查 | 静态测试和文档对齐测试排除诊断、已隐藏、暂停、暂隐、隐藏会话、重命名等旧主路径 | 已自动化 |
| M-12 | 拖动 Pet | 行为级 JS 测试执行真实拖动事件链，拖动后点击不展开；macOS 几何测试覆盖边界 | 已自动化 |
| M-13 | 右键 Pet | 行为级 JS 测试：右键菜单打开，出现隐藏 Pet、退出程序，打开菜单本身不发送消息 | 已自动化 |
| M-14 | 隐藏 Pet | 行为级 JS 测试：点击隐藏菜单项才发送 `hide`；macOS 原生测试确认隐藏只 `orderOut`，不停止 monitor 进程 | 已自动化 |
| M-15 | 状态栏/托盘恢复 | macOS 原生测试覆盖菜单栏 `Show Monitor` 绑定、恢复窗口、恢复 Web Pet 状态；真实点击菜单栏头像图标菜单中的 `Show Monitor` 后日志出现 `Show monitor requested from menu` 和 `Restored pet web state` | 已自动化 + 真实点击 |
| M-16 | 退出程序 | 行为级 JS 测试：点击退出菜单项发送 `quit`；macOS 原生测试确认退出触发 app terminate，终止 monitor 子进程 | 已自动化 |
| M-17 | 直接终端 CLI 进程级检测 | source/service 测试 + 真实源码扫描：直接已配置 AI CLI 生成 `process_only` 气泡；Claude 终端从运行变空闲时转 `needs_action`，点击气泡成功跳回后转 `idle`；Codex、Qoder、WorkBuddy、`codebuddy` 等其他直接 CLI 仍按活跃/静默保守判断；不读终端内容 | 已自动化 + 真实扫描 |
| M-18 | 点击直接终端 CLI 气泡 | 真实点击 `网点抛扔 · 空闲` 气泡，`/api/focus` 返回 `ok=true`；服务层确认使用对应 cwd 和父 GUI 应用 | 已自动化 + 真实点击 |
| M-19 | Codex 桌面会话事件检测 | source/service 测试 + 真实会话扫描：`~/.codex/sessions` 中未完成任务显示为 Codex 进行中气泡，helper/app-server/sandbox 不生成假会话；桌面主程序只作为空闲入口且被具体会话去重 | 已自动化 + 真实扫描 |
| M-19c | 已查看桌面会话收口 | 服务层测试：已查看后转为空闲的桌面端具体对话保留 15 分钟；超过 15 分钟移出；App 仍存活时显示空闲入口 | 已自动化 |

## 用户反馈问题回归

| 问题 | 修复 | 证据 |
|---|---|---|
| 点击展开后遮挡 Pet | 气泡按 Pet 视觉外框避让，必要时下移 Pet | 浏览器展开后气泡与 Pet 分离 |
| 再点 Pet 消失 | 左键收起时重置 Pet DOM 位置，避免大窗口坐标遗留到 170×150 紧凑窗口外 | `test_native_compact_toggle_restores_pet_position_instead_of_hiding` |
| Show Monitor 无法唤醒 | Show 强制停止拖拽残留、恢复紧凑尺寸、restore + unhide + order front，并调用 `restorePetFromHost()` | 原生测试 + 日志 `Restored pet web state` |
| Pet 跑到看不到的位置 | Show 和 resize 都会夹取到当前屏幕可见区域 | `Restored monitor frame` 日志 |
| 拖动乱跑 | 原生拖动用屏幕坐标并 clamp 到可见区域 | 原生拖动测试和日志 `Moved window frame` |
| 发布包烟测/API 响应预算 | 外部进程/窗口扫描超时预算为 4 秒，避免 macOS 多个 AI/IDE 进程导致一次正常扫描被误杀；source 并发轮询避免多个外部源串行吃掉主路径预算。该配置不提高轮询频率 | `test_external_source_timeout_allows_macos_cwd_lookup_within_poll_budget`、`test_refresh_polls_independent_sources_concurrently_for_visibility_budget`、真实服务层 payload 可同时识别 Codex 桌面会话和 Claude Code CLI |
| 外接显示器无法跨屏拖动 | 拖拽边界改为根据鼠标所在屏幕选择屏幕 frame，不再锁死在 window 原屏幕；展开态按右下角 Pet 的紧凑可见区域计算可拖范围 | `test_native_drag_can_cross_external_displays`、`test_native_drag_bounds_use_pet_size_not_large_bubble_window`、`tests/test_macos_geometry.py` 真实 Swift 几何执行测试，Swift 编译通过 |
| 点击 Pet 展开/收起时跳动 | host 模式不再改 Pet DOM 坐标；原生 resize 取消动画，并保持窗口右下角锚定，让 Pet 不被 170→340 的窗口扩展推走 | `test_native_host_bubble_layout_does_not_reposition_pet`、`test_native_resize_keeps_pet_anchored_to_bottom_right`、`tests/test_macos_geometry.py` 真实 Swift 几何执行测试，行为级 JS 测试 |
| 终端 Claude/Codex 对话监控不到 | 根因是 macOS 进程扫描可能超过旧预算，但旧代码超时后整批丢弃；同时直接 CLI 会话曾把“进程存在”误当作“正在工作”。已把扫描超时预算调整为 4 秒，修复 `basename -zsh` 兼容问题；Claude CLI 优先读取 Claude 自己的会话状态，读不到时再回退 CPU 和进程运行态 | `test_classifies_direct_claude_process_as_idle_when_process_is_quiet`、`test_classifies_direct_claude_process_as_running_when_cpu_or_child_is_active`、`test_classifies_direct_claude_process_status_from_claude_session_file_before_cpu`、`test_classifies_direct_claude_process_running_from_claude_session_file`、`test_classifies_direct_codex_process_as_running_basic_detection_session`、`test_external_source_timeout_allows_macos_cwd_lookup_within_poll_budget`、真实源码扫描识别到 Claude Code CLI 且均为空闲 |
| 网点清场空闲状态闪成进行中 | 根因是 Claude CLI 下常驻 MCP 辅助进程或 Claude 自身短暂 CPU 活跃，叠加旧逻辑把超过 30 秒的 idle 状态视为过期并回退到进程活跃度，导致空闲会话短暂误判为进行中。已过滤常驻 MCP 辅助进程，并让 Claude CLI 明确 idle 状态持续优先于瞬时进程活跃；只有读不到、状态不匹配或过期 running 才回退到进程活跃度 | `test_posix_process_command_ignores_background_mcp_helpers_for_activity`、`test_classifies_direct_claude_process_status_from_claude_session_file_before_cpu`、`test_stale_claude_idle_session_file_stays_idle_despite_transient_process_activity` |
| 退出网点清场 Claude Code 后气泡仍残留 | 根因是 Claude 子进程仍挂在 IDE 父进程下，但已不处于前台交互终端状态。修复后直接 CLI 只有仍处于前台交互终端状态才进入气泡列表；IDE/终端/项目窗口打开只用于聚焦，不证明 Claude/Codex 会话存在 | `test_ignores_detached_direct_claude_process_after_terminal_closes`；真实 `ProcessSource` 扫描已不返回 `网点清场`，开发版日志从 `total=3` 变为 `total=2` |
| 会话计数偶发从 4 闪成 0 | 根因是 `ProcessSource` 一次空扫描会被当作进程全部消失，`replace_source_updates("process", [])` 立即清空 process-only 会话。已增加 process 源一次空扫描防抖：首次空结果保留，连续两次空才清除 | `test_refresh_debounces_one_empty_process_poll_before_removing_sessions`；重启开发态后需以最新 session snapshots 为准 |
| Codex 桌面端运行中对话监控不到 | 旧实现只看 Codex.app 主进程，既会漏掉真实运行中对话，也会把 App 打开误当成进行中。已改为读取 `~/.codex/sessions` 的会话事件：未完成 `task_started` 显示进行中，`task_complete` 后按刷新规则移除；桌面主程序存活只显示空闲入口，具体会话存在时该入口被去重 | `test_codex_session_source_marks_unfinished_task_as_running`、`test_codex_session_source_drops_old_completed_sessions`、`test_configured_desktop_ai_app_process_creates_idle_fallback_entry`、`test_visible_sessions_hide_generic_desktop_fallback_when_full_desktop_session_exists`、真实服务层 payload 识别到 Codex 桌面会话和桌面空闲入口去重 |
| 点击终端 process-only 气泡可能无法回到原窗口 | 直接 CLI 子进程不是 GUI 应用，旧实现只拿子进程 ID 或生成标题，无法可靠聚焦真实终端/编辑器窗口。已新增 `focus_process_id` / `focus_app_name`，从父进程链识别 IDE、Terminal、iTerm、Codex 等 GUI 应用；带 cwd 的 process-only 先按 cwd 文件夹名匹配 IDE/终端窗口，再 `AXRaise` 目标窗口。真实点击曾因 fallback 5 秒超时出现 `ok=false`，已把 fallback 超时放宽到 15 秒，并修复验收脚本只接受 `ok=true` | `test_focus_session_uses_window_metadata_when_available`、`test_macos_focus_command_does_not_raise_parent_app_first_when_cwd_is_available`、`test_macos_focus_command_matches_project_folder_window_when_cwd_is_available`、`test_focus_fallback_timeout_allows_slow_project_activation`、`test_macos_dev_acceptance_helper_rejects_failed_focus_as_manual_evidence`、真实点击 `网点清场 · 空闲` 后日志 `AI Progress Monitor focus: ok=true` |
| 多屏下点击一个 IDE 项目气泡时另一个项目窗口也被带出 | 根因是 macOS 激活整个 IDE App 会把同一 App 的多个项目窗口一起前置。修复为通用 IDE 策略：如果已匹配到具体窗口 ID、cwd 文件夹名或窗口标题，只对目标窗口执行 `AXRaise`，不先 `set frontmost of proc` 激活整个 App；只有无法匹配具体窗口时才 fallback 打开目录 | `test_macos_focus_command_can_target_window_id`、`test_macos_focus_command_matches_project_folder_window_when_cwd_is_available`；真实点击 `网点清场 · 空闲` 后 `/api/focus` 为 `ok=true`；用户手动确认点击各气泡只带出对应窗口 |
| 右键 Pet 后可能污染拖动状态 | 根因是 `pointerdown` 没有限制鼠标按钮，右键按下也会发送 `start-window-drag`，可能导致后续点击/恢复状态异常。已限制只有左键进入拖动流程 | 先让行为测试失败：`messagesAfterRightPointerDown` 得到 `start-window-drag`；修复后 `tests.test_web_ui_behavior` 通过 |
| 当前说明文档仍描述旧体验 | README 和 release checklist 仍出现旧的主路径描述，例如暂隐、会话管理、宠物内直接回复和面板诊断，会误导真实试用和后续验收 | 新增 `tests/test_docs_prd_alignment.py`，先失败后修正文档；现在 README 和发布清单已改为左键展开/收起、右键隐藏/退出、点击气泡回原窗口 |

## macOS 找回路径

| 路径 | 结果 |
|---|---|
| 菜单栏头像图标中的 `Show Monitor` | 代码测试通过；真实点击后窗口恢复，日志出现 `Show monitor requested from menu`、`Restored pet web state` |
| 外接屏跨屏拖动 | 代码测试通过；真实系统拖动事件已把窗口从外接屏区域拖到主屏可见区域 |
| 再次打开 app | 已真实验证，日志出现 `Reopen requested` |
| Show 内部恢复 | 已真实验证，日志出现 `Show monitor completed frame`、`Restored pet web state` |

## Completion Audit

| 要求 | 当前证据 | 判定 |
|---|---|---|
| 左键点击 Pet 只能展开/收起气泡列表 | `tests/test_web_ui.py` 静态检查 click handler 不含 `hide`；`tests/test_web_ui_behavior.py` 执行真实 JS，左键只发送 `resize:bubbles` / `resize:compact`，拖动后的点击不展开 | 已证明 |
| 隐藏功能只能右键菜单触发 | 右键菜单结构测试；行为级 JS 测试确认打开右键菜单不发送消息，调用 `hidePet()` 后才发送 `hide`，右键按下本身不发送拖动或隐藏消息 | 已证明 |
| 退出功能只能右键菜单触发 | 行为级 JS 测试确认点击“退出程序”才发送 `quit`；macOS 原生测试覆盖 `monitorProcess?.terminate()` | 已证明 |
| 点击展开后不遮挡 Pet | 气泡布局测试覆盖 `getPetVisualRect`、`VISUAL_MOTION_BUFFER`、`dockPetBelowBubbles`；host 模式不会再移动 Pet DOM | 已证明 |
| 收起后 Pet 不消失 | `test_native_compact_toggle_restores_pet_position_instead_of_hiding`；行为级 JS 测试确认收起后 Pet 位置 reset 且未隐藏 | 已证明 |
| 点击展开/收起不跳动 | 原生 resize 保持右下角锚定，且 `setFrame(... animate: false)`；行为级 JS 测试确认左键只发送 `resize:bubbles` / `resize:compact` | 已证明 |
| 外接屏跨屏拖动边界 | 拖拽按鼠标所在屏幕选择屏幕 frame，展开态按右下角 Pet 可见区域约束，不按整块透明窗口约束；真实系统拖动事件后窗口从 `x=-194` 到 `x=45` | 已证明 |
| 右键隐藏后可恢复 | 原生测试覆盖 `showMonitorFromMenu()` 恢复紧凑尺寸和 `restorePetWebState()`；真实日志出现 `Restored pet web state` | 恢复链路已证明 |
| 菜单栏头像图标中的 `Show Monitor` 真实点击 | `showItem.target = self` 和 selector 测试已证明菜单项绑定；真实点击菜单项后窗口数恢复为 1，日志出现 `Show monitor requested from menu` 和 `Restored pet web state` | 已证明 |
| 点击气泡回对应窗口/页面 | `/api/focus` 服务测试和窗口聚焦命令测试；行为级 JS 测试真实点击 `codex-2` 气泡，请求 `/api/focus` 且不请求 `/api/action`；点击气泡会尝试回到对应 AI 工具窗口；真实点击 `网点清场/网点抛扔` 气泡后日志 `AI Progress Monitor focus: ok=true`；用户手动确认多屏下只带出对应窗口 | 已证明 |
| 同文件夹多对话可区分 | 行为级 JS 测试验证 `checkout-flow · Codex #1/#2` | 已证明 |
| 无文件夹桌面对话可读 | 行为级 JS 测试验证无 cwd 或工具定义表识别出的自动聊天目录使用 `Codex 对话` / `Codex · hello` / `Codex 对话 #1/#2`，不展示不可读 session_id 碎片；真实项目目录仍显示项目文件夹；Qoder 日志优先显示本地缓存或 project session 的真实标题，只有生成目录名时前端兜底为 `Qoder 对话 #1/#2`，不展示 `chat-1/chat-2` 或长内部 ID | 已证明 |
| 同一文件夹多个 wrapper 对话不互相覆盖 | macOS/Linux wrapper 在未设置 `AI_MONITOR_SESSION_ID` 时按文件夹名、时间戳和进程号生成默认唯一会话 ID；真实执行同一目录连续两次生成 2 个 session JSON | 已证明 |
| 直接终端已配置 AI CLI 会话至少可见 | 直接运行 `claude`、`codex`、`qoder`、`workbuddy`、`codebuddy` 等已配置 AI CLI 时，即使没有 wrapper，也必须生成 process-only 气泡；退出 CLI 后，即使 IDE/终端/项目窗口仍打开，也不能继续保留气泡；Claude CLI 优先使用 Claude 会话状态，回复完成后或同一会话出现新的空闲完成时间后待处理，点击气泡成功回到系统终端或 IDE 内置终端后空闲；其他直接 CLI 按进程活跃度保守判断 | 已证明；当前源码真实服务层 payload 识别到直接 CLI，并带父 GUI 聚焦信息 |
| Qoder 新增工具 full 监控 | Qoder 支持 CLI、Qoder Desktop、Qoder CN Desktop 存活入口；普通 Qoder 和 Qoder CN 的 macOS `Electron` 主进程都可识别，空闲入口和 full 会话分别显示为 `Qoder` / `Qoder CN`；Qoder/Qoder CN 日志按 `taskId` / `sessionId` 拆成具体对话，能从 `filePath` 读到 `chat-*` 时显示可读短标题，日志只有内部 ID 时前端兜底显示 `Qoder 对话 #1/#2`，避免气泡只剩 `Qoder Desktop` 或泄漏长内部 ID；Completed/ActionRequired/suspended/requiresApproval 转待处理，Running/streaming/prompting 转进行中，且同时间戳下待处理信号不能被 streaming 渲染快照覆盖；启动前历史完成不误弹，启动前已经处于 suspended / requiresApproval 的用户介入态仍显示待处理，启动后新完成必须待处理；Qoder 气泡点击支持 `Qoder` 与 `Qoder CN` 名称别名并回到对应 AI 工具窗口 | `test_qoder_completed_task_log_creates_needs_action_conversation`、`test_qoder_completion_after_monitor_start_is_not_filtered_as_history`、`test_qoder_completion_before_monitor_start_falls_back_to_idle_desktop_entry`、`test_qoder_user_attention_state_before_monitor_start_still_needs_action`、`test_qoder_multiple_task_logs_create_separate_conversation_updates`、`test_qoder_suspended_transition_is_not_overridden_by_same_timestamp_streaming_snapshot`、`test_qoder_suspended_payload_state_counts_as_needs_action`、`test_qoder_payload_requiring_user_input_counts_as_needs_action`、`test_qoder_log_desktop_session_payload_is_full_and_view_acknowledged_after_focus`、`test_pet_frontend_behaviors_match_prd`、`test_qoder_cn_desktop_ignores_regular_qoder_logs`、`test_regular_qoder_desktop_ignores_qoder_cn_logs`、`test_native_focus_matches_qoder_cn_when_payload_uses_qoder_display_name` |
| WorkBuddy 新增工具 full 接入 | WorkBuddy 已进入通用 AI 工具定义表，支持 `workbuddy` / `codebuddy` CLI、真实 macOS `Electron` 桌面主进程存活入口和桌面点击聚焦，并忽略 daemon / sidecar / `codebuddy --serve` 等 Electron 服务进程，避免重复气泡；直接运行 WorkBuddy CLI 仍按进程活跃度保守判断；WorkBuddy Desktop 会读取本地 sessions 数据库中明确的 `Running` / `Completed` / `Failed` 等状态并生成 full 级具体会话，默认 `Pending` 且无活动时间的空白会话不误报；WorkBuddy full 会话气泡必须显示软件名，例如 `WorkBuddy · Start new chat session · 待处理`；使用 `monitor_workbuddy.sh` / `monitor_workbuddy.bat` 或 `emit_event.py --tool unknown --tool-display-name WorkBuddy` 时，也可写出 full 级会话、待处理、聚焦字段和已查看收口语义；JSON 事件默认跟随 `AI_PROGRESS_MONITOR_HOME` 并原子写入 | `test_new_configured_ai_tools_create_generic_process_entries`、`test_workbuddy_desktop_scan_ignores_electron_service_processes`、`test_workbuddy_db_sessions_create_full_desktop_conversation_entries`、`test_workbuddy_db_ignores_history_and_ambiguous_pending_sessions`、`test_workbuddy_db_desktop_session_payload_is_full_and_view_acknowledged_after_focus`、`test_terminal_bridge_writes_generic_tool_display_name_for_full_monitoring`、`test_emit_event_default_session_dir_follows_monitor_home_and_writes_atomically`、`test_emit_event_can_publish_generic_ai_tool_full_session`、`test_generic_full_session_is_view_acknowledged_after_focus`、`test_generic_shell_wrapper_writes_tool_display_name`、`test_native_focus_only_activates_ai_desktop_apps_as_last_resort` |
| Codex 桌面运行中对话可见 | macOS 窗口扫描权限不可用时，运行中的 Codex 桌面会话仍要基于 `~/.codex/sessions` 生成气泡；Codex.app 主程序存活只生成空闲入口，具体会话优先 | 已证明；当前源码真实服务层 payload 识别到 Codex 桌面会话并对通用入口去重 |
| 已查看桌面会话自动收口 | 已查看后转为空闲的桌面端具体对话保留 15 分钟后移出；桌面 App 仍存活时，App 空闲入口重新显示 | 已证明 |
| 进程级检测聚焦字段贯通 | source 识别出的 `focus_process_id` / `focus_app_name` 必须进入 `/api/sessions` payload，并被 `/api/focus` 使用 | `test_process_only_payload_includes_focus_metadata_for_bubble_navigation`、`test_focus_session_uses_window_metadata_when_available` |
| 完整窗口项优先于桌面进程级检测 | 若窗口扫描成功拿到同一 `process_id` 的完整桌面会话，不再重复显示 process-only 项 | `test_visible_sessions_hide_desktop_process_only_duplicate_when_window_scan_has_same_process_id` |
| source 轮询不串行拖慢主路径 | 进程源和窗口源相互独立，刷新时应并发 poll，避免外部命令超时相加 | `test_refresh_polls_independent_sources_concurrently_for_visibility_budget` |
| 角标数字显示气泡总数，颜色符合状态优先级 | 行为级 JS 测试执行 `renderBadge()`；静态测试覆盖红/绿/蓝 class | 已证明 |
| 不展示 summary、命令输出、用户输入、Yes/No | 行为级 JS 测试注入 `SECRET` 和 safe_action 后气泡不泄露；静态测试排除 `session.summary` 和 safe action 渲染 | 已证明 |
| 不展示诊断、已隐藏、暂停、暂隐等旧入口 | 静态测试排除旧入口文本和函数 | 已证明 |
| 当前文档不再宣传旧主路径 | README 和 release checklist 不再描述暂隐、会话管理、宠物内直接回复或主界面诊断 | `tests/test_docs_prd_alignment.py` |
| 不打 release 包也能试最新源码 | `scripts/run_macos_floating_dev.sh --build-only` 成功在 `build/macos-dev/AI Progress Monitor Floating Dev.app` 生成本地开发态 app；脚本不调用 `build_release.py`，不生成 release zip，不写发布目录 | `test_macos_dev_floating_runner_builds_stable_signed_app_without_release_packaging` |
| 手工验收后可读日志核对 | `scripts/check_macos_floating_dev.sh` 读取 dev app 进程和 `~/Library/Logs/AI Progress Monitor/native-monitor.log`，显示最近外观切换记录，并请求当前 dev app 本机资源路由核对衬衫树懒图和防缓存响应头；不控制 GUI；session snapshot 显示总数、进行中、空闲、process-only 和 full 计数，可避免误测旧包 | `test_macos_dev_acceptance_helper_reads_logs_without_gui_control`、`test_macos_dev_acceptance_helper_checks_running_app_shirt_asset_route`、`test_macos_dev_acceptance_helper_reports_recent_pet_appearance_changes`、`test_session_snapshot_line_logs_counts_without_sensitive_content` |
| 发布包可用 | 用户本地测试通过后，已运行 `python3 scripts/build_release.py`；发布包包含 macOS 普通 `.app`、macOS Floating `.app`、Windows 悬浮脚本和主 `.pyz` | 已证明 |

## 最终验证命令

| 命令 | 结果 |
|---|---|
| `PYTHONPATH=src python3 -m unittest discover -s tests` | `298 tests OK` |
| `PYTHONPATH=src python3 -m unittest tests.test_service tests.test_store tests.test_docs_prd_alignment tests.test_web_ui_behavior` | 52 tests OK，覆盖桌面端 15 分钟收口、Store 状态、文档对齐和前端行为 |
| `PYTHONPATH=src python3 -m unittest tests.test_window_focus tests.test_start_scripts` | 25 tests OK，覆盖聚焦 fallback 超时、带 cwd 不抢抬父窗口、开发态检查脚本只接受 `ok=true` |
| `scripts/run_macos_floating_dev.sh` | 成功构建并启动本地开发态 app：`build/macos-dev/AI Progress Monitor Floating Dev.app` |
| `scripts/check_macos_floating_dev.sh` | 成功读取开发态状态；服务有 session snapshots，计数会随真实已配置 AI 工具进程实时变化；衬衫树懒资源路由返回已确认图片并禁用缓存 |
| 修复后真实源码扫描 | `CodexSessionSource` 可识别 Codex Desktop 运行中会话；`ProcessSource` 可把已配置桌面主程序识别为空闲入口，具体桌面会话存在时由服务层去重；保留的直接 CLI 带父 GUI 聚焦信息 |
| `swiftc -parse native/macos/FloatingMonitor.swift native/macos/FloatingMonitorGeometry.swift ...` | 通过 |
| `python3 scripts/validate_release.py` | 通过，由 `scripts/build_release.py` 内部执行 |
| `python3 scripts/build_release.py` | 通过；生成 `dist/ai-progress-monitor.pyz`（2.74 MiB）和 `dist/ai-progress-monitor-release.zip`（12.26 MiB） |
| release zip 完整性检查 | 通过；包含主 `.pyz`、macOS 普通 `.app`、macOS Floating `.app`、Windows 悬浮脚本、启动脚本和 README |
| pyz 视觉资源检查 | 通过；包含三态 Pet PNG、APP 头像 PNG，资源头有效；不包含候选素材目录或 `.DS_Store` |
| macOS app 签名检查 | 通过；两个 `.app` 均为本地 ad-hoc 签名，未 Apple notarized |

## 当前运行日志关键证据

| 日志 | 含义 |
|---|---|
| `AI Progress Monitor sessions` | 开发态 Pet 服务已被 WebView 轮询；最新逻辑应显示 Codex 桌面运行中会话为 `full`，直接已配置 AI CLI 为 `process_only`，数量会随真实会话实时变化 |
| `Manual acceptance evidence: [OK] sessions visible` | 开发态 Pet 已识别监控对象 |
| `Manual acceptance evidence: [OK] left-click open/close evidence` | 前一轮真实 CGEvent 左键展开/收起日志已通过，且没有 hide；本轮按要求未重复测试 |
| `Manual acceptance evidence: [OK] drag evidence` | 前一轮真实拖动日志已通过，窗口从外接屏区域拖到主屏可见区域；本轮按要求未重复测试 |
| `Manual acceptance evidence: [OK] hide evidence` | 前一轮真实右键菜单隐藏日志已通过，窗口数变 0 且进程仍在；本轮按要求未重复测试 |
| `Manual acceptance evidence: [OK] menu restore evidence` | 前一轮真实点击菜单栏头像图标菜单中的 `Show Monitor` 已恢复窗口；本轮按要求未重复测试 |
| `Manual acceptance evidence: [OK] bubble focus evidence` | 本轮重启后真实点击 `网点抛扔 · 空闲` 气泡，日志为 `AI Progress Monitor focus: ok=true` |
| `scripts/check_macos_floating_dev.sh --strict` | 重启后只复测聚焦项，因此 strict 因未重复左键/拖动/隐藏/恢复而失败；不作为本轮焦点修复失败证据 |
| `Pet visibility check ... "petDisplay":"block"` | Pet 已渲染且可见 |
| `Selected screen visible frame: (0.0, 0.0, 1440.0, 870.0)` | 当前运行识别到当前屏幕坐标 |
| `Show monitor completed frame: (1246.0, 24.0, 170.0, 150.0)` | Show 后窗口在可见区域 |
| `Reopen requested` | 再次打开 app 恢复路径已触发 |
| `Restored monitor frame` | 窗口恢复到当前屏幕 |
| `Restored pet web state` | 网页内 Pet 状态已恢复为可见、收起、紧凑 |

## 剩余风险

| 风险 | 说明 | 处理建议 |
|---|---|---|
| 菜单栏恢复仍需用户体验确认 | 自动化已真实点击菜单栏头像图标菜单中的 `Show Monitor` 并恢复窗口，但最终体感仍建议用户试一次 | 用户本地确认恢复位置和体验是否满意 |
| 外接屏拖动仍需用户体验确认 | CGEvent 已真实拖动窗口从外接屏区域到主屏可见区域，代码层覆盖跨屏和边缘边界；最终手感仍建议用户试一次 | 用户本地确认跨屏拖动手感是否满意 |
| 直接读取终端内容有隐私风险 | macOS 自动化读取 Terminal 内容被拒绝；即使可读也可能暴露命令输出或凭据 | 默认不读取终端内容；准确监控请用 wrapper 脚本接入 |
| 直接运行 `claude` / `codex` 仍不能读取具体对话内容 | Claude CLI 可优先使用本地会话状态，回复完成后或同一会话出现新的空闲完成时间后转待处理，点击气泡成功回到系统终端或 IDE 内置终端后转空闲；Codex CLI 仍按进程活跃度保守判断；现在会尽量聚焦父 GUI 应用 | 需要展示提示正文或更细粒度状态时使用桥接脚本 |
| Windows 版本仍是旧壳 | 用户已明确 macOS 先可用，Windows 后续再说 | 后续单独开 Windows 迭代 |

## 本机开发态试用入口

| 操作 | 命令/路径 | 说明 |
|---|---|---|
| 构建但不启动 | `scripts/run_macos_floating_dev.sh --build-only` | 验证最新源码能生成本地开发态 macOS Pet |
| 启动最新源码 Pet | `scripts/run_macos_floating_dev.sh` | 会启动 `build/macos-dev/AI Progress Monitor Floating Dev.app` |
| 查看手工验收日志 | `scripts/check_macos_floating_dev.sh` | 查看 dev app 是否运行、脱敏服务 URL、session snapshot、外观切换记录、host 消息、Show/Hide/Quit 日志，以及衬衫树懒资源路由是否正确 |
| 严格验收门 | `scripts/check_macos_floating_dev.sh --strict` | 有任何 `[TODO]` 时返回失败；全部真实路径有证据后才通过 |
| 手工测试重点 | 左键 Pet、右键隐藏/退出、菜单栏头像图标中的 `Show Monitor`、外接屏跨屏拖动、点击气泡聚焦 | 这些是真实鼠标路径，必须用开发态 app 试 |
