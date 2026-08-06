# macOS 原创树懒 Pet 监控助手验收报告

## 结论

macOS 版本已完成 PRD 主路径验收并已正式发布：默认 Pet、三色角标、气泡列表、同文件夹多对话区分、隐私保护、点击气泡聚焦、拖动不误展开、右键隐藏/退出、Show 恢复链路、再次打开 App 恢复、桌面端具体对话已查看后 15 分钟收口。2026-07-14 增量已完成 Pet 外观主题切换，以及 WorkBuddy、Qoder、Qoder CN 监控扩展。2026-07-17 已完成桌面产品从 Codex 到 ChatGPT 的身份迁移，并修复 Claude Code CLI 工作目录串扰。v0.2.1 已于 2026-07-20 发布，用户已完成 GitHub 回下载与首次打开、Pet、菜单、气泡、窗口跳转验收。

2026-07-21 至 2026-07-29，系统通知开关增量完成开发态自动化、浏览器和 macOS Dev App 实机验收；通知开关、多窗口聚焦、残留会话清理和多工具状态回归修复随 PR #5 合并到 `main`（`770d447`），并已随 v0.3.0 于 2026-07-30 正式发布和完成 GitHub 回下载验收。

2026-07-23，针对 macOS 原生 Pet 在 Zed 多窗口、多显示器环境中点击一个项目气泡却同时带出另一个 Zed 窗口的问题，完成事件驱动修复、自动化、Swift 编译和发布门禁。用户已用真实鼠标完成正反向视觉验收：点击 SellerBooks 只出现 SellerBooks，点击“日报推送”只出现“日报推送”。随后发现最小化 SellerBooks 时 Zed 会显示“日报推送”；不经过 Pet 的对照实验得到完全相同结果，且 AX 状态证明 SellerBooks 为单窗口最小化、Zed App 未隐藏、“日报推送”由 Zed 接替为主窗口，因此该现象不属于 Pet 聚焦回归。事件驱动聚焦与 Zed 残留会话修复均已进入 PR #5。

2026-07-24，修复 WorkBuddy 真实运行时 Pet 仍显示空闲、完成后才直接变为待处理的回归。根因是服务层只把 `workbuddy-db` 认作完整桌面会话，漏掉了同样能精确绑定会话的 `workbuddy-log`；当同一 WorkBuddy 进程还有旧数据库会话时，运行中的 runtime-log 会话会被误当成低层级重复项过滤。修复只补齐完整会话来源契约，不改 WorkBuddy 状态解析、通知、冷却、聚焦或前端状态优先级。开发阶段全量 487 项测试、发布校验和真实 Dev App 状态链路均通过；修复已进入 PR #5。

2026-07-24，修复 Qoder CN 额度/套餐限制会话点击后先变空闲、数秒后又回到待处理的问题。根因是 Qoder 把持续账户阻塞写入嵌套完成原因，同时继续产生通用 `Error` 和短暂 `cancelled` 清理快照；监控器只识别到普通失败，因此聚焦成功时错误执行了查看确认。修复后，明确的账户、套餐、额度或模型配置阻塞使用 `view_ack_required=false`，并跨紧邻的清理快照保留；新的真实运行会清除旧阻塞，后续普通超时/失败仍可查看确认。Qoder/服务层 184 项、开发阶段全量 491 项测试和发布校验均通过；真实 Qoder CN 会话在点击聚焦后连续三个完整扫描周期保持待处理，Browser 可见气泡仍为待处理且控制台无错误。修复已进入 PR #5。

2026-07-28，完成功能分支的全面回归审计。审计新增并修复四个边界缺陷：ChatGPT 已查看会话在 App 仍运行时遇到一次来源缺失会提前消失、WorkBuddy 更新的 runtime 待处理信号错误继承旧数据库完成态的查看确认标记、通知接口收到与实际状态相同的值仍重复写盘、相似项目前缀窗口可能抢先匹配真实项目。随后将原先以 Zed 现场问题触发的项目窗口能力扩展为所有已注册 IDE 共用规则，并补齐常见 IDE 与独立终端宿主映射。真实 VS Code 进程树进一步暴露 Electron `Code Helper` 会被误认作窗口宿主，现已统一继续向上解析到 Code 主进程。修复前失败测试均能复现对应问题，修复后跨 IDE 专项 284 项、开发阶段全量 511 项测试通过；发布校验和最终 Dev App 证据见本节对应门禁记录。重新授予辅助功能权限后，真实 VS Code alpha / beta 双窗口已完成正反向 Pet 点击、精确 AX focused/main 复核、关闭单窗后气泡清理和剩余窗口再聚焦验收。非本机安装 IDE 只记录自动化契约，不冒充实机验收。本轮修复已进入 PR #5。

2026-07-29，用户手动在 Visual Studio Code 的 IDE 窗口内启动真实 Claude Code，确认 Pet 能正常发现并监测该会话。该记录只代表用户明确验证的 VS Code 监测主路径；双窗口精准聚焦、关闭窗口后的气泡清理继续使用 2026-07-28 的独立实机证据。

2026-07-29，PR #5 合并后的 `main` CI 曾因墙钟阈值抖动在 `0.350745666` 秒处误报失败；PR #6 将 `< 0.35 秒`断言替换为线程屏障，直接验证来源轮询是否重叠。目标、服务层、领域、全量 514 项和发布校验均通过，PR 与合并后的 `main` CI 也均通过；该修复只改测试，不改生产代码。

2026-08-05 至 2026-08-06，v0.3.0 发布后的修复候选完成新一轮源码、Dev App 和 `v0.3.1` 本地候选包回归：修复 Claude Code 长任务因来源超时、并发刷新和墙钟回拨而在“进行中 / 空闲”之间波动的问题；通知策略改为每次进入待处理最多发送一次，持续待处理不再按冷却周期重复，并使用只含哈希会话键和状态时间的本地文件延续正常重启基线。真实 Zed 与 Visual Studio Code 长任务、待处理、查看确认、精准聚焦、单窗关闭清理、通知关闭/开启、正常重启和受控通知计数均已由用户逐项确认。精确提交双包已完成独立解包与本地人工验收，但尚未推送、创建 PR、打 Tag 或发布，不改写 v0.3.0 的既有公开发布记录。

ChatGPT 与多工具功能回归范围、445 项自动化结果和最小人工验收结论以 `docs/qa/2026-07-17-chatgpt-and-multi-tool-regression-test-cases.md` 为准；v0.2.1 最终双包、SHA-256 和发布后人工验收以 `docs/qa/2026-07-17-v0.2.1-release-packaging-validation.md` 为准；v0.3.0 候选构建、SHA-256 和发布后回下载结果记录在 `docs/qa/2026-07-30-v0.3.0-release-packaging-validation.md`。下文较早章节保留历史测试名、测试数和产物名时，不代表当前用户界面或发布结构仍采用旧版本。

菜单栏头像图标中的 `Show Monitor`、外接屏跨屏拖动、气泡点击聚焦、状态稳定性已完成自动化覆盖和本地手动测试。v0.3.0 发布前的用户验收通过后，已执行 `python3 scripts/build_release.py` 生成当版发布包；2026-08-06 又从精确源码提交构建 `v0.3.1` 本地双包候选并完成独立解包验收，但未进入任何公开发布步骤。

| 项目 | 结论 |
|---|---|
| 当前公开基线 | PR #5、PR #6 与 Release PR #7 均已合并；v0.3.0 annotated tag 指向最终 `main` 提交 `ff667a38` |
| 后续修复候选 | `codex/fix-runtime-state-and-notification-dedup` 的 `v0.3.1` 本地候选已完成源码、双包和人工验收；候选包源码提交为 `9d280a02f5e4d644c87c6724f54ed35adc275ffa`，尚未推送、合并或发布 |
| 自动化测试 | v0.2.1 发布基线 445 项均通过；v0.3.0 portable 阻断修复后独立取得 `517 tests OK` 和 `release-validation-ok`；后续修复候选的最终结果见“2026-08-05 至 2026-08-06”章节 |
| Swift 编译 | 通过 |
| 发布包构建 | v0.3.0 已发布双包记录保持不变；v0.3.1 本地候选双包与 `.pyz` 已从精确提交独立构建并记录新 SHA-256 |
| 本地校验 | 通过，包含 release 校验、JS 语法、敏感信息扫描、源码 E2E、portable 包内 E2E、版本、架构、签名、包卫生和 `--no-notifications` 隔离锁定态 |
| 真实运行 | macOS 开发态 App 已多轮真实测试；v0.3.0 最终候选与 GitHub 回下载 App，以及 v0.3.1 本地候选 App，均完成对应范围的独立解包、验签、启动、非空渲染、菜单和正常退出验收 |
| 完整目标状态 | [v0.3.0](https://github.com/AutumnGao77/ai-progress-monitor/releases/tag/v0.3.0) 已正式发布；Tag、Release、两附件、回下载 SHA-256 与启动校验全部通过 |
| 外观状态 | 三态 Pet 图片、APP 头像、透明背景和发布包已完成；后续换图优先走 `pet_assets` 配置 |

## 验收范围

| 范围 | 本轮状态 |
|---|---|
| macOS 桌面 Pet | 已验收 |
| Web UI 主体验 | 已验收 |
| 服务层 `/api/sessions` / `/api/focus` | 已回归 |
| Windows 托盘版 | 代码和发布包保留入口；本轮重点验收 macOS，Windows 体验后续单独迭代 |

## 2026-07-17 ChatGPT 迁移与 Claude 目录串扰补充验收

| 项目 | 证据 | 结果 |
|---|---|---|
| 桌面产品身份 | 完整桌面会话统一显示 ChatGPT；只接收 `~/.codex/sessions` 中明确的桌面 originator；Codex 仅保留 CLI，`Codex.app` 不再生成桌面入口 | 通过 |
| Claude 目录串扰根因 | macOS 进程扫描循环中 `cwd` 没有在 Claude 分支前清空，导致 Claude 继承上一进程的目录；修复后每轮先重置 `cwd` | 通过 |
| Claude 数据绑定 | 工作目录只能来自当前进程或同 PID 且目录一致的 `~/.claude/sessions/<pid>.json`；不同目录状态不得覆盖真实进程 | 通过 |
| 真实 App 数据 | ChatGPT 对应 `monitor-project`，Claude Code CLI 对应 `sample-project`，父 GUI 为 IDE；Qoder CN 和 WorkBuddy 空闲入口仍保留 | 通过 |
| 人工聚焦与收口 | 用户确认点击 `sample-project` 气泡会回到 IDE 的 `sample-project` 窗口，退出 Claude Code 后气泡消失，其他工具不受影响 | 通过 |
| 最新回归 | v0.2.1 基线 445 项全量用例均取得通过结果；其中受限环境禁止本机回环端口的 Web API 用例已在允许 `127.0.0.1` 临时端口的环境重跑通过；严格原生验收退出码为 0 | 通过 |

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

## 2026-07-23 Zed 多窗口聚焦补充验收

| 项目 | 证据 | 结果 |
|---|---|---|
| 真实根因 | WebView 每次点击只发送一个原生 focus 消息，Zed 也只有一个 App 进程，cwd 能正确匹配目标项目窗口。问题发生在匹配之后：`activate(from:)` 返回 `accepted=true` 只代表系统接受请求，旧实现却立即执行第二次 `AXRaise` 并回报成功；100 ms 后 Zed 才真正成为前台。激活请求与目标窗口状态切换没有时序闭环，旧 main/key 窗口仍可能在 Zed 激活时被恢复 | 已证明 |
| 旧修复为何失效 | 第一版只把无来源激活改成来源感知激活，自动化/HID 检查曾显示目标窗口正确，但用户真实鼠标仍复现 SellerBooks 与“日报推送”同时跳出。该结果推翻了“`activate(from:)` 返回即完成”和“最终 AX focused/main 正确即可证明过程无双窗口”的旧结论 | 已证明并已撤回旧结论 |
| 方案对照 | 固定 sleep 依赖机器负载；最小化或隐藏其他 Zed 窗口会破坏用户状态；Zed CLI 受打开策略影响且不是精确窗口 API；私有 WindowServer 接口不可维护。最终选择系统事件 + 有界状态确认，不依赖固定等待时间 | 已评估 |
| 修复实现 | 每次点击生成唯一操作编号并取消旧监听、超时和重试；精确命中后先设置并抬升目标，连续两次确认它同时为 AX focused/main；在激活请求前注册 `NSWorkspace.didActivateApplicationNotification`，等待目标 App 真实 active/frontmost；激活后再次设置、抬升并连续确认目标。macOS 14+ 保留来源感知激活且拒绝时不回退；macOS 13 兼容请求同样等待真实激活 | 代码与编译通过 |
| 非目标边界 | AI 桌面 App 在没有可访问窗口时的普通激活逻辑不变；窗口 ID、cwd/标题匹配顺序、通知、状态算法、隐藏/退出和 Web 点击消息均未改 | 通过 |
| SellerBooks 技术链路 | 双屏现场中“日报推送”先为 Zed 的 main/focused；用户真实点击 Pet 的 SellerBooks 气泡后，日志依次出现前置稳定 2 次、协调激活接受、真实激活事件、后置稳定 2 次和 `focused-project-window` 成功；随后 AX 显示 SellerBooks 为唯一 main/focused，“日报推送”两项均为 false | 通过 |
| 自动化与发布校验 | `tests.test_macos_focus_policy` 4 项、`tests.test_macos_native_companion` 34 项均通过，Dev App Swift 编译与临时签名通过。最终全量 472/472 在正常权限下通过；此前沙箱中的 11 项错误均由临时 localhost 端口被禁止引起，对应 `tests.test_web_launch` 已在正常权限下 36/36 通过；`python3 scripts/validate_release.py` 输出 `release-validation-ok` | 通过 |
| 用户体验复核 | 用户真实点击 SellerBooks 时只出现 SellerBooks；反向点击“日报推送”时只出现“日报推送”，未再出现一次点击带出两个 Zed 项目窗口 | 通过 |
| 最小化行为对照 | 直接通过 macOS 辅助功能聚焦 SellerBooks，全程不调用 Pet，再最小化该窗口；结果仍是 SellerBooks `minimized=true`、Zed `hidden=false`、“日报推送”自动变为 `main=true / focused=true`。这证明它是 Zed 在当前主窗口最小化后接替同 App 其他窗口的行为，不由 Pet 触发；为避免改变 IDE 原有窗口状态，本次不增加持续监听，也不隐藏或最小化其他项目窗口 | 边界已证明，无需改代码 |

## 2026-07-21 系统通知开关增量验收

| 项目 | 证据 | 结果 |
|---|---|---|
| 执行 PRD | `docs/prd/2026-07-14-notification-preference-toggle-prd.md` 记录 Mac + Web 范围、菜单、偏好、API、启动参数优先级和验收矩阵 | 通过 |
| 偏好与兼容 | `notifications_enabled` 仅接受布尔值，缺失、非法或损坏配置默认开启；写入保留外观、隐藏会话、别名、自定义资源和未知字段；外观与通知并发保存使用同一进程内原子更新锁，不会互相覆盖 | 自动化通过 |
| API 契约 | `GET /api/preferences` 返回实际状态和锁定态；通知写接口只接受且必须只包含一个布尔 `enabled` 字段，成功、非法请求、无令牌、启动参数锁定和写入失败分别覆盖 `200 / 400 / 403 / 409 / 500` | 自动化通过 |
| 菜单与并发 | 右键 Pet 主菜单为“外观 > / 系统通知 > / 隐藏 Pet / 退出程序”；通知二级菜单为“开启 / 关闭”互斥勾选；串行保存保证快速连点后的最终落盘值等于最后选择，失败时回滚并提示。前端原本会跳过重复选择，但 2026-07-28 复查发现服务接口收到同值请求仍会写盘，现已补失败测试并修复为按实际状态幂等 | 自动化通过 |
| 通知边界 | 关闭后不调用系统通知 sender，但仍记录状态基线；重新开启不补发旧待处理、完成或疑似卡住通知，新状态变化恢复提醒 | 自动化通过 |
| 启动参数锁定 | `--no-notifications` 优先于用户偏好，二级菜单显示“✓ 关闭”，“开启 / 关闭”均置灰，本次运行不改写偏好文件 | 自动化通过 |
| Browser 验收 | 普通模式右键主菜单仅显示“系统通知 >”，点击父菜单不切换；子菜单显示“✓ 开启 / 关闭”或“开启 / ✓ 关闭”，选择后刷新保持。`--no-notifications` 模式显示“开启 / ✓ 关闭”，两个选项均置灰；两种模式均无控制台错误，并留存界面截图 | 通过 |
| macOS Dev App | 重新构建 arm64 Dev App，签名校验通过；原生 WebView 辅助功能树显示“外观 / 系统通知 / 隐藏 Pet / 退出程序”及互斥的“开启 / 关闭”。关闭态跨重启保持；从“✓ 关闭”选择“开启”后偏好写入 `true`，再次展开和再次重启均显示“✓ 开启”；仅展开父菜单和重复选择当前项均未改写偏好文件 | 通过 |
| 真实系统通知对照 | 使用隔离 HOME 和三个唯一待处理事件，在 macOS 通知中心按完整消息精确计数：开启事件 `1` 条、关闭事件 `0` 条、重新开启后旧事件仍为 `0` 条、重新开启后的新事件为 `1` 条 | 通过 |
| Pet 状态独立性 | 通知关闭期间，原生气泡窗口仍显示两条唯一待处理会话，窗口正常扩展为 `340 x 500`；通知开关未影响 Pet 会话状态、气泡和待处理展示 | 通过 |
| 自动化与发布校验 | PRD 明确列出的相关模块最终为 `165 tests OK`，全量 `PYTHONPATH=src python3 -m unittest discover -s tests` 最终为 `472 tests OK`；`python3 scripts/validate_release.py` 输出 `release-validation-ok`，单元测试、编译、帮助命令、JS 语法、通知帮助和敏感信息检查均通过；当前最终 Dev App 真实执行隐藏和菜单栏恢复后，`scripts/check_macos_floating_dev.sh --strict` 输出 `Manual acceptance complete` | 通过 |

## 2026-07-14 新增 AI 工具监控补充验收

| 项目 | 证据 | 结果 |
|---|---|---|
| 执行 PRD | `docs/prd/2026-07-14-ai-tool-monitoring-expansion-prd.md` 记录 WorkBuddy、Qoder、Qoder CN 的工具范围、状态映射、标题规则、点击聚焦、15 分钟收口和验收矩阵 | 通过 |
| Qoder / Qoder CN 桌面监控 | 普通 Qoder 和 Qoder CN 分别识别产品边界，读取对应日志、project session 和本地缓存标题；App 仅存活时显示空闲入口；有具体任务时显示具体气泡 | 通过 |
| Qoder 标题与多会话 | 优先使用真实会话标题；缺少真实标题时前端兜底为 `Qoder 对话 #1/#2`，不展示 `chat-1/chat-3`、task id、UUID 或内部 session 碎片；多个 task 不合并为一个桌面入口 | 通过 |
| Qoder 状态映射 | Running / streaming / prompting 显示进行中；Completed 显示完成待查看；Action Required / suspended / requiresApproval / waitingForInput 显示待处理且点击后不误清空 | 通过 |
| Qoder 持续阻塞 | 明确的额度、套餐、账户或模型配置阻塞显示待处理且 `view_ack_required=false`；紧邻的 `error -> cancelled -> error` 清理快照不误清除；同一会话出现更新的 running 后清除旧阻塞，普通超时/失败仍可查看确认 | 通过 |
| WorkBuddy 桌面监控 | WorkBuddy 桌面主程序存活时显示空闲入口；本地 sessions 数据库和 runtime log 出现明确 Running / Completed / Failed / pending-with-activity 等状态时生成 full 具体会话 | 通过 |
| WorkBuddy 标题与项目上下文 | 具体会话气泡显示软件名；对话发生在项目/文件夹下时标题包含项目/文件夹上下文，例如 `WorkBuddy Desktop - 项目名 - 对话标题` | 通过 |
| WorkBuddy 状态映射 | 运行中显示进行中；完成待查看可点击后转空闲；真正等待用户操作的 pending / approval / input 类状态保持待处理，不因点击气泡变空闲 | 通过 |
| 桌面入口收口 | 已查看后转空闲的具体桌面对话保留 15 分钟；超过 15 分钟具体对话移出；如果对应 App 仍运行，保留桌面 App 空闲入口 | 通过 |
| 点击聚焦 | Qoder、Qoder CN、WorkBuddy 均带 `focus_process_id` / `focus_app_name`；窗口匹配失败时兜底激活对应 App，而不是打开 cwd 或报无法定位窗口 | 通过 |
| 既有工具回归 | Claude Code CLI 打开但无交互保持空闲；ChatGPT Plan 模式等待用户输入显示待处理；ChatGPT Desktop / Claude Code / Codex CLI 状态规则未被新增工具改坏 | 通过 |
| 自动化测试 | 全量 `PYTHONPATH=src python3 -m unittest discover -s tests` 通过，421 个测试 OK；相关回归覆盖 `tests.test_sources`、`tests.test_service`、`tests.test_store`、`tests.test_web_ui_behavior`、`tests.test_window_focus` | 通过 |
| 发布与开发态检查 | `scripts/run_macos_floating_dev.sh --build-only`、`scripts/run_macos_floating_dev.sh --launch-only`、`scripts/check_macos_floating_dev.sh`、`python3 scripts/validate_release.py`、`python3 scripts/build_release.py` 均通过 | 通过 |

### 2026-07-24 Qoder CN 持续阻塞补充验收

| 项目 | 证据 | 结果 |
|---|---|---|
| 真实输入 | 当前 Qoder CN 会话的本地日志持续为错误，缓存完成原因包含套餐升级信号；修复前实际输出为 `needs_action + view_ack_required=true` | 已复现 |
| 测试先行 | 新增缓存套餐阻塞、清理快照继承、新运行清除旧阻塞、聚焦后持续待处理四类回归；实现前两个源测试按预期失败，实现后全部通过 | 通过 |
| 兼容边界 | 原有普通 500/timeout 失败继续为 `view_ack_required=true`；更新的 running 会阻止旧缓存阻塞污染后续普通失败 | 通过 |
| 完整回归 | `tests.test_sources` + `tests.test_service` 共 184 项通过；正常权限下全量 491 项通过；`python3 scripts/validate_release.py` 输出 `release-validation-ok`；`git diff --check` 无输出 | 通过 |
| 真实交互 | 重建并启动 Dev App；本机页面点击真实 Qoder CN 待处理气泡后成功激活 App，连续三个完整扫描周期均为 `needs_action + view_ack_required=false`，可见气泡仍显示待处理 | 通过 |
| 页面质量 | Browser 页面身份和非空渲染正常；点击前后会话气泡可见，控制台错误/警告为 0 | 通过 |

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
| AC-9b | 桌面版无文件夹对话不展示不可读 session_id | 行为级 JS 测试验证无 cwd 的 ChatGPT 兼容桌面对话显示为 `ChatGPT 对话 · 空闲`；多个无文件夹桌面对话显示为 `ChatGPT 对话 #1/#2`；安全可读标题可显示为 `ChatGPT · hello`；工具定义表中声明的自动聊天目录按无真实项目文件夹处理，后续桌面端工具只补配置 | 通过 |
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
| AC-16b | 窗口权限不可用时，ChatGPT 桌面端运行中对话仍可见 | 基于 `~/.codex/sessions` 中明确的桌面 originator 显示 ChatGPT 运行中气泡；ChatGPT App 空闲入口只显示空闲，且在具体会话存在时让位；内部 helper/app-server/sandbox 不展示 | 通过 |
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
| M-9b | 无文件夹桌面对话 | 行为级 JS 测试：无 cwd 的 ChatGPT 桌面对话不显示 session_id 碎片；工具定义表识别到自动聊天目录时显示 `ChatGPT · hello`，真实项目目录仍显示项目文件夹；同一机制可复用于其他桌面 AI 工具 | 已自动化 |
| M-10 | 隐私检查 | 行为级 JS 测试注入 `SECRET`、`safe_action` 后气泡不展示 summary 或 Yes/No | 已自动化 |
| M-11 | 旧入口检查 | 静态测试和文档对齐测试排除诊断、已隐藏、暂停、暂隐、隐藏会话、重命名等旧主路径 | 已自动化 |
| M-12 | 拖动 Pet | 行为级 JS 测试执行真实拖动事件链，拖动后点击不展开；macOS 几何测试覆盖边界 | 已自动化 |
| M-13 | 右键 Pet | 行为级 JS 测试：右键菜单打开，出现隐藏 Pet、退出程序，打开菜单本身不发送消息 | 已自动化 |
| M-14 | 隐藏 Pet | 行为级 JS 测试：点击隐藏菜单项才发送 `hide`；macOS 原生测试确认隐藏只 `orderOut`，不停止 monitor 进程 | 已自动化 |
| M-15 | 状态栏/托盘恢复 | macOS 原生测试覆盖菜单栏 `Show Monitor` 绑定、恢复窗口、恢复 Web Pet 状态；真实点击菜单栏头像图标菜单中的 `Show Monitor` 后日志出现 `Show monitor requested from menu` 和 `Restored pet web state` | 已自动化 + 真实点击 |
| M-16 | 退出程序 | 行为级 JS 测试：点击退出菜单项发送 `quit`；macOS 原生测试确认退出触发 app terminate，终止 monitor 子进程 | 已自动化 |
| M-17 | 直接终端 CLI 进程级检测 | source/service 测试 + 真实源码扫描：直接已配置 AI CLI 生成 `process_only` 气泡；Claude 终端从运行变空闲时转 `needs_action`，点击气泡成功跳回后转 `idle`；Codex、Qoder、WorkBuddy、`codebuddy` 等其他直接 CLI 仍按活跃/静默保守判断；不读终端内容 | 已自动化 + 真实扫描 |
| M-18 | 点击直接终端 CLI 气泡 | 真实点击 `sample-project · 空闲` 气泡，`/api/focus` 返回 `ok=true`；服务层确认使用对应 cwd 和父 GUI 应用 | 已自动化 + 真实点击 |
| M-19 | ChatGPT 桌面会话事件检测 | source/service 测试 + 真实会话扫描：`~/.codex/sessions` 中明确标记为桌面来源的未完成任务显示为 ChatGPT 进行中气泡，helper/app-server/sandbox 不生成假会话；ChatGPT App 只作为空闲入口且被具体会话去重 | 已自动化 + 真实扫描 |
| M-19c | 已查看桌面会话收口 | 服务层测试：已查看后转为空闲的桌面端具体对话保留 15 分钟；超过 15 分钟移出；App 仍存活时显示空闲入口 | 已自动化 |

## 用户反馈问题回归

| 问题 | 修复 | 证据 |
|---|---|---|
| 点击展开后遮挡 Pet | 气泡按 Pet 视觉外框避让，必要时下移 Pet | 浏览器展开后气泡与 Pet 分离 |
| 再点 Pet 消失 | 左键收起时重置 Pet DOM 位置，避免大窗口坐标遗留到 170×150 紧凑窗口外 | `test_native_compact_toggle_restores_pet_position_instead_of_hiding` |
| Show Monitor 无法唤醒 | Show 强制停止拖拽残留、恢复紧凑尺寸、restore + unhide + order front，并调用 `restorePetFromHost()` | 原生测试 + 日志 `Restored pet web state` |
| Pet 跑到看不到的位置 | Show 和 resize 都会夹取到当前屏幕可见区域 | `Restored monitor frame` 日志 |
| 拖动乱跑 | 原生拖动用屏幕坐标并 clamp 到可见区域 | 原生拖动测试和日志 `Moved window frame` |
| 发布包烟测/API 响应预算 | 外部进程/窗口扫描超时预算为 4 秒，避免 macOS 多个 AI/IDE 进程导致一次正常扫描被误杀；source 并发轮询避免多个外部源串行吃掉主路径预算。该配置不提高轮询频率 | `test_external_source_timeout_allows_macos_cwd_lookup_within_poll_budget`、`test_refresh_polls_independent_sources_concurrently_for_visibility_budget`、真实服务层 payload 可同时识别 ChatGPT 桌面会话和 Claude Code CLI |
| 外接显示器无法跨屏拖动 | 拖拽边界改为根据鼠标所在屏幕选择屏幕 frame，不再锁死在 window 原屏幕；展开态按右下角 Pet 的紧凑可见区域计算可拖范围 | `test_native_drag_can_cross_external_displays`、`test_native_drag_bounds_use_pet_size_not_large_bubble_window`、`tests/test_macos_geometry.py` 真实 Swift 几何执行测试，Swift 编译通过 |
| 点击 Pet 展开/收起时跳动 | host 模式不再改 Pet DOM 坐标；原生 resize 取消动画，并保持窗口右下角锚定，让 Pet 不被 170→340 的窗口扩展推走 | `test_native_host_bubble_layout_does_not_reposition_pet`、`test_native_resize_keeps_pet_anchored_to_bottom_right`、`tests/test_macos_geometry.py` 真实 Swift 几何执行测试，行为级 JS 测试 |
| 终端 Claude/Codex 对话监控不到 | 根因是 macOS 进程扫描可能超过旧预算，但旧代码超时后整批丢弃；同时直接 CLI 会话曾把“进程存在”误当作“正在工作”。已把扫描超时预算调整为 4 秒，修复 `basename -zsh` 兼容问题；Claude CLI 优先读取 Claude 自己的会话状态，读不到时再回退 CPU 和进程运行态 | `test_classifies_direct_claude_process_as_idle_when_process_is_quiet`、`test_classifies_direct_claude_process_as_running_when_cpu_or_child_is_active`、`test_classifies_direct_claude_process_status_from_claude_session_file_before_cpu`、`test_classifies_direct_claude_process_running_from_claude_session_file`、`test_classifies_direct_codex_process_as_running_basic_detection_session`、`test_external_source_timeout_allows_macos_cwd_lookup_within_poll_budget`、真实源码扫描识别到 Claude Code CLI 且均为空闲 |
| Claude 空闲状态闪成进行中 | 根因是 Claude CLI 下常驻 MCP 辅助进程或 Claude 自身短暂 CPU 活跃，叠加旧逻辑把超过 30 秒的 idle 状态视为过期并回退到进程活跃度，导致空闲会话短暂误判为进行中。已过滤常驻 MCP 辅助进程，并让 Claude CLI 明确 idle 状态持续优先于瞬时进程活跃；只有读不到、状态不匹配或过期 running 才回退到进程活跃度 | `test_posix_process_command_ignores_background_mcp_helpers_for_activity`、`test_classifies_direct_claude_process_status_from_claude_session_file_before_cpu`、`test_stale_claude_idle_session_file_stays_idle_despite_transient_process_activity` |
| 退出 Claude Code 后气泡仍残留 | 根因是 Claude 子进程仍挂在 IDE 父进程下，但已不处于前台交互终端状态。修复后直接 CLI 只有仍处于前台交互终端状态才进入气泡列表；IDE/终端/项目窗口打开只用于聚焦，不证明 Claude/Codex 会话存在 | `test_ignores_detached_direct_claude_process_after_terminal_closes`；真实 `ProcessSource` 扫描已不返回对应测试项目，开发版日志从 `total=3` 变为 `total=2` |
| 关闭单个 Zed 项目窗口后仍残留气泡并提示“无法定位窗口” | 根因是 Zed 可能短暂保留仍带前台终端标记的 Claude 子进程，单看进程不足以证明项目窗口仍可导航；Python 子进程调用的 osascript 又没有原生 App 的辅助功能权限，不能作为 App 内主清单。2026-07-24 起，原生伴随程序通过 token 保护的本地接口发布短时 AX 清单，服务按父 GUI 进程 ID 和 cwd 文件夹名核对；无匹配窗口时立即移除，匹配时回填窗口 ID。AX 未授权、单 App 读取失败、清单过期或扫描禁用时保留原进程结果，普通 Terminal/iTerm 不受该规则影响 | 自动化覆盖原生清单回传、token 鉴权、8 秒过期、空清单、单 App 失败、窗口 ID 回填及 Python 扫描降级。最终 Dev App 重新授权后，真实 AX 清单从 `1 IDE / 2 windows / 0 unavailable` 变为 `1 IDE / 1 window / 0 unavailable`；SellerBooks 气泡消失，日报推送保留且再次点击只跳对应窗口，用户确认通过 |
| 会话计数偶发从 4 闪成 0 | 根因是 `ProcessSource` 一次空扫描会被当作进程全部消失，`replace_source_updates("process", [])` 立即清空 process-only 会话。已增加 process 源一次空扫描防抖：首次空结果保留，连续两次空才清除 | `test_refresh_debounces_one_empty_process_poll_before_removing_sessions`；重启开发态后需以最新 session snapshots 为准 |
| ChatGPT 桌面端运行中对话监控不到 | 旧实现只看已退役的 `Codex.app` 主进程，既会漏掉真实运行中对话，也会把 App 打开误当成进行中。现兼容读取 `~/.codex/sessions` 中明确的桌面 originator：未完成 `task_started` 显示进行中，`task_complete` 后按刷新规则收口；ChatGPT 主程序存活只显示空闲入口，具体会话存在时该入口被去重 | `test_codex_session_source_marks_unfinished_task_as_running`、`test_codex_session_source_drops_old_completed_sessions`、`test_configured_desktop_ai_app_process_creates_idle_fallback_entry`、`test_visible_sessions_hide_generic_desktop_fallback_when_full_desktop_session_exists`、真实服务层 payload 识别到 ChatGPT 桌面会话和空闲入口去重 |
| 点击终端 process-only 气泡可能无法回到原窗口 | 直接 CLI 子进程不是 GUI 应用，旧实现只拿子进程 ID 或生成标题，无法可靠聚焦真实终端/编辑器窗口。已新增 `focus_process_id` / `focus_app_name`，从父进程链识别 IDE、Terminal、iTerm、Codex 等 GUI 应用；带 cwd 的 process-only 先按 cwd 文件夹名匹配 IDE/终端窗口，再 `AXRaise` 目标窗口。真实点击曾因 fallback 5 秒超时出现 `ok=false`，已把 fallback 超时放宽到 15 秒，并修复验收脚本只接受 `ok=true` | `test_focus_session_uses_window_metadata_when_available`、`test_macos_focus_command_does_not_raise_parent_app_first_when_cwd_is_available`、`test_macos_focus_command_matches_project_folder_window_when_cwd_is_available`、`test_focus_fallback_timeout_allows_slow_project_activation`、`test_macos_dev_acceptance_helper_rejects_failed_focus_as_manual_evidence`、真实点击 `sample-project · 空闲` 后日志 `AI Progress Monitor focus: ok=true` |
| 多屏下点击一个 IDE 项目气泡时另一个项目窗口也被带出 | 早期仅修正 Python `/api/focus` 路径，后续第一版原生修复又把“来源感知激活已接受”误当成“激活已完成”，均不足以闭环。2026-07-23 已改为前置连续选窗确认、真实激活事件等待、后置连续复核和旧操作取消；macOS 14+ 不回退无来源激活，macOS 13 兼容请求也验证真实激活 | `tests.test_macos_focus_policy`、`test_native_focus_waits_for_stable_selection_and_real_activation_before_success`、`test_new_focus_request_cancels_stale_async_work`；用户正反向真实点击均确认只出现目标窗口。单独最小化目标后同 App 其他 Zed 窗口接替，已用不经过 Pet 的对照实验复现并排除为 Pet 回归 |
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
| 点击气泡回对应窗口/页面 | `/api/focus` 服务测试和窗口聚焦命令测试；行为级 JS 测试真实点击兼容测试气泡，请求 `/api/focus` 且不请求 `/api/action`；原生 WebView 路径每次点击只产生一个 focus 请求。2026-07-23 事件驱动修复已用 SellerBooks 真实点击证明完整原生时序和最终 AX 唯一目标状态；用户正反向真实点击均只出现所选目标窗口 | 已证明 |
| 同文件夹多对话可区分 | 行为级 JS 测试验证 `checkout-flow · Codex #1/#2` | 已证明 |
| 无文件夹桌面对话可读 | 行为级 JS 测试验证无 cwd 或工具定义表识别出的自动聊天目录使用 `ChatGPT 对话` / `ChatGPT · hello` / `ChatGPT 对话 #1/#2`，不展示不可读 session_id 碎片；真实项目目录仍显示项目文件夹；Qoder 日志优先显示本地缓存或 project session 的真实标题，只有生成目录名时前端兜底为 `Qoder 对话 #1/#2`，不展示 `chat-1/chat-2` 或长内部 ID | 已证明 |
| 同一文件夹多个 wrapper 对话不互相覆盖 | macOS/Linux wrapper 在未设置 `AI_MONITOR_SESSION_ID` 时按文件夹名、时间戳和进程号生成默认唯一会话 ID；真实执行同一目录连续两次生成 2 个 session JSON | 已证明 |
| 直接终端已配置 AI CLI 会话至少可见 | 直接运行 `claude`、`codex`、`qoder`、`workbuddy`、`codebuddy` 等已配置 AI CLI 时，即使没有 wrapper，也必须生成 process-only 气泡；退出 CLI 后，即使 IDE/终端/项目窗口仍打开，也不能继续保留气泡；Claude CLI 优先使用 Claude 会话状态，回复完成后或同一会话出现新的空闲完成时间后待处理，点击气泡成功回到系统终端或 IDE 内置终端后空闲；其他直接 CLI 按进程活跃度保守判断 | 已证明；当前源码真实服务层 payload 识别到直接 CLI，并带父 GUI 聚焦信息 |
| Qoder 新增工具 full 监控 | Qoder 支持 CLI、Qoder Desktop、Qoder CN Desktop 存活入口；普通 Qoder 和 Qoder CN 的 macOS `Electron` 主进程都可识别，空闲入口和 full 会话分别显示为 `Qoder` / `Qoder CN`；Qoder/Qoder CN 日志按 `taskId` / `sessionId` 拆成具体对话，并优先使用本地缓存库或 project session 的真实标题；缺少真实标题时前端兜底显示 `Qoder 对话 #1/#2`，不展示 `chat-1/chat-3`、task id、UUID 或长内部 ID；Completed/ActionRequired/suspended/requiresApproval 转待处理，Running/streaming/prompting 转进行中，且同时间戳下待处理信号不能被 streaming 渲染快照覆盖；启动前历史完成不误弹，启动前已经处于 suspended / requiresApproval 的用户介入态仍显示待处理，启动后新完成必须待处理；Qoder 气泡点击支持 `Qoder` 与 `Qoder CN` 名称别名并回到对应 AI 工具窗口 | `test_qoder_completed_task_log_creates_needs_action_conversation`、`test_qoder_completion_after_monitor_start_is_not_filtered_as_history`、`test_qoder_completion_before_monitor_start_falls_back_to_idle_desktop_entry`、`test_qoder_user_attention_state_before_monitor_start_still_needs_action`、`test_qoder_multiple_task_logs_create_separate_conversation_updates`、`test_qoder_suspended_transition_is_not_overridden_by_same_timestamp_streaming_snapshot`、`test_qoder_suspended_payload_state_counts_as_needs_action`、`test_qoder_payload_requiring_user_input_counts_as_needs_action`、`test_qoder_log_desktop_session_payload_is_full_and_view_acknowledged_after_focus`、`test_pet_frontend_behaviors_match_prd`、`test_qoder_cn_desktop_ignores_regular_qoder_logs`、`test_regular_qoder_desktop_ignores_qoder_cn_logs`、`test_native_focus_matches_qoder_cn_when_payload_uses_qoder_display_name` |
| WorkBuddy 新增工具 full 接入 | WorkBuddy 已进入通用 AI 工具定义表，支持 `workbuddy` / `codebuddy` CLI、真实 macOS `Electron` 桌面主进程存活入口和桌面点击聚焦，并忽略 daemon / sidecar / `codebuddy --serve` 等 Electron 服务进程，避免重复气泡；直接运行 WorkBuddy CLI 仍按进程活跃度保守判断；WorkBuddy Desktop 会读取本地 sessions 数据库中明确的 `Running` / `Completed` / `Failed` 等状态和 runtime log 状态，并生成 full 级具体会话；`workbuddy-db` 与 `workbuddy-log` 都属于完整会话来源，同 PID 存在旧数据库会话时不得过滤当前 runtime-log 运行会话；默认 `Pending` 且无活动时间的空白会话不误报；WorkBuddy full 会话气泡必须显示软件名，且对项目/文件夹下的会话显示项目上下文，例如 `WorkBuddy Desktop - 项目名 - Start new chat session`；使用 `monitor_workbuddy.sh` / `monitor_workbuddy.bat` 或 `emit_event.py --tool unknown --tool-display-name WorkBuddy` 时，也可写出 full 级会话、待处理、聚焦字段和已查看收口语义；JSON 事件默认跟随 `AI_PROGRESS_MONITOR_HOME` 并原子写入 | `test_new_configured_ai_tools_create_generic_process_entries`、`test_workbuddy_desktop_scan_ignores_electron_service_processes`、`test_workbuddy_db_sessions_create_full_desktop_conversation_entries`、`test_workbuddy_db_ignores_history_and_ambiguous_pending_sessions`、`test_workbuddy_db_desktop_session_payload_is_full_and_view_acknowledged_after_focus`、`test_workbuddy_runtime_log_session_remains_visible_with_db_session_on_same_process`、`test_workbuddy_runtime_log_session_survives_one_missing_poll_and_accepts_completion`、`test_terminal_bridge_writes_generic_tool_display_name_for_full_monitoring`、`test_emit_event_default_session_dir_follows_monitor_home_and_writes_atomically`、`test_emit_event_can_publish_generic_ai_tool_full_session`、`test_generic_full_session_is_view_acknowledged_after_focus`、`test_generic_shell_wrapper_writes_tool_display_name`、`test_native_focus_only_activates_ai_desktop_apps_as_last_resort` |
| ChatGPT 桌面运行中对话可见 | macOS 窗口扫描权限不可用时，运行中的 ChatGPT 桌面会话仍要基于 `~/.codex/sessions` 中明确的桌面 originator 生成气泡；ChatGPT 主程序存活只生成空闲入口，具体会话优先 | 已证明；当前源码真实服务层 payload 识别到 ChatGPT 桌面会话并对通用入口去重 |
| 已查看桌面会话自动收口 | 已查看后转为空闲的桌面端具体对话保留 15 分钟后移出；桌面 App 仍存活时，App 空闲入口重新显示 | 已证明 |
| 进程级检测聚焦字段贯通 | source 识别出的 `focus_process_id` / `focus_app_name` 必须进入 `/api/sessions` payload，并被 `/api/focus` 使用 | `test_process_only_payload_includes_focus_metadata_for_bubble_navigation`、`test_focus_session_uses_window_metadata_when_available` |
| 完整窗口项优先于桌面进程级检测 | 若窗口扫描成功拿到同一 `process_id` 的完整桌面会话，不再重复显示 process-only 项 | `test_visible_sessions_hide_desktop_process_only_duplicate_when_window_scan_has_same_process_id` |
| source 轮询不串行拖慢主路径 | 进程源和窗口源相互独立，刷新时应并发 poll，避免外部命令超时相加 | `test_refresh_polls_independent_sources_concurrently_for_visibility_budget` |
| 角标数字显示气泡总数，颜色符合状态优先级 | 行为级 JS 测试执行 `renderBadge()`；静态测试覆盖红/绿/蓝 class | 已证明 |
| 不展示 summary、命令输出、用户输入、Yes/No | 行为级 JS 测试注入 `SECRET` 和 safe_action 后气泡不泄露；静态测试排除 `session.summary` 和 safe action 渲染 | 已证明 |
| 不展示诊断、已隐藏、暂停、暂隐等旧入口 | 静态测试排除旧入口文本和函数 | 已证明 |
| 当前文档不再宣传旧主路径 | README 和 release checklist 不再描述暂隐、会话管理、宠物内直接回复或主界面诊断 | `tests/test_docs_prd_alignment.py` |
| 不打 release 包也能试最新源码 | `scripts/run_macos_floating_dev.sh --build-only` 成功在 `build/macos-dev/AI Progress Monitor Floating Dev.app` 生成本地开发态 app；脚本不调用 `build_release.py`，不生成 release zip，不写发布目录 | `test_macos_dev_floating_runner_builds_stable_signed_app_without_release_packaging` |
| 手工验收后可读日志核对 | `scripts/check_macos_floating_dev.sh` 读取 dev app 进程和 `~/Library/Logs/AI Progress Monitor/native-monitor.log`，显示本次运行的外观切换记录，并请求当前 dev app 本机资源路由核对衬衫树懒图和防缓存响应头；不控制 GUI；session snapshot 显示总数、进行中、空闲、process-only 和 full 计数，可避免误测旧包 | `test_macos_dev_acceptance_helper_reads_logs_without_gui_control`、`test_macos_dev_acceptance_helper_checks_running_app_shirt_asset_route`、`test_macos_dev_acceptance_helper_reports_recent_pet_appearance_changes`、`test_session_snapshot_line_logs_counts_without_sensitive_content` |
| 发布包可用 | 2026-07-14 历史构建曾采用合并包；v0.2.1 已改为单 App macOS 用户包与独立 portable 包，并完成 GitHub 回下载验收 | 已证明；当前结构见 v0.2.1 验包记录 |

## 2026-07-14 历史验证命令

本节保留当时执行结果用于追溯。当前 v0.2.1 的 445 项测试、双包结构、最终 SHA-256 和发布后验收，以 `docs/qa/2026-07-17-v0.2.1-release-packaging-validation.md` 为准。

| 命令 | 结果 |
|---|---|
| `PYTHONPATH=src python3 -m unittest discover -s tests` | `421 tests OK` |
| `PYTHONPATH=src python3 -m unittest tests.test_sources tests.test_service tests.test_store tests.test_web_ui_behavior tests.test_window_focus` | 232 tests OK，覆盖 Qoder / Qoder CN / WorkBuddy 深度监控、桌面端 15 分钟收口、Store 状态、前端气泡和聚焦行为 |
| `PYTHONPATH=src python3 -m unittest tests.test_window_focus tests.test_start_scripts` | 35 tests OK，覆盖 Qoder / WorkBuddy App 聚焦、带 cwd 不抢抬父窗口、开发态检查脚本只接受 `ok=true` |
| `scripts/run_macos_floating_dev.sh` | 成功构建并启动本地开发态 app：`build/macos-dev/AI Progress Monitor Floating Dev.app` |
| `scripts/check_macos_floating_dev.sh` | 成功读取开发态状态；服务有 session snapshots，计数会随真实已配置 AI 工具进程实时变化；衬衫树懒资源路由返回已确认图片并禁用缓存 |
| 修复后真实源码扫描 | `ChatGPTSessionSource` 可识别 ChatGPT Desktop 运行中会话；`ProcessSource` 可把已配置桌面主程序识别为空闲入口，具体桌面会话存在时由服务层去重；保留的直接 CLI 带父 GUI 聚焦信息 |
| `swiftc -parse native/macos/FloatingMonitor.swift native/macos/FloatingMonitorGeometry.swift ...` | 通过 |
| `python3 scripts/validate_release.py` | 通过，由 `scripts/build_release.py` 内部执行 |
| `python3 scripts/build_release.py` | 通过；输出 `release-artifact-ok dist/ai-progress-monitor.pyz` 和 `release-bundle-ok dist/ai-progress-monitor-release.zip`；当前本地产物约 `4.2M` 和 `17M` |
| release zip 完整性检查 | 通过；包含主 `.pyz`、macOS 普通 `.app`、macOS Floating `.app`、Windows 悬浮脚本、启动脚本和 README |
| pyz 视觉资源检查 | 通过；包含三态 Pet PNG、APP 头像 PNG，资源头有效；不包含候选素材目录或 `.DS_Store` |
| macOS app 签名检查 | 通过；两个 `.app` 均为本地 ad-hoc 签名，未 Apple notarized |

## 2026-07-24 Zed 残留会话增量验证

| 验证 | 结果 |
|---|---|
| 新增失败测试 | 第一轮修复前窗口清单接口缺失，SellerBooks 与日报推送同时保留；真实 Dev App 又证明 Python osascript 因 AX 权限不可用而降级保留，两个失败原因都与现场现象一致 |
| 原生清单定向测试 | 8 tests OK，覆盖原生清单过滤与窗口 ID 回填、空清单、单 App 读取失败、8 秒过期、畸形载荷、token 鉴权和 Swift 发布钩子 |
| sources/service/聚焦/API 相关回归 | 275 tests OK |
| 完整测试套件 | 正常本机权限下 485 tests OK |
| `python3 scripts/validate_release.py` | 正常本机权限下输出 `release-validation-ok` |
| 最新 Dev App 现场复测 | 最终构建重新授权后日志为 `trusted=true`。双窗口基线同时识别 SellerBooks 与日报推送；只关闭 SellerBooks 后 AX 窗口数从 2 变 1，SellerBooks 气泡消失，日报推送保留；用户再次点击日报推送，确认只跳对应 Zed 窗口。通过 |

## 2026-07-24 WorkBuddy 运行态回归修复验证

| 验证 | 证据 | 结果 |
|---|---|---|
| 真实现象 | WorkBuddy 的 `Test again` 明确处于生成中，但 Pet 只有 WorkBuddy 空闲入口；生成结束后才出现 `WorkBuddy · Test again · 待处理` | 已复现 |
| 根因 | `ProcessSource` 在整个真实运行期均能生成 `status=running`、`status_source=workbuddy-log` 的具体会话；服务层完整进程桌面会话集合却只有 `qoder-log` 和 `workbuddy-db`。同一 PID 还有旧 `workbuddy-db` 会话时，`workbuddy-log` 被标成 `process_only` 并作为重复项过滤；完成后来源回到 `workbuddy-db`，气泡才突然出现 | 已证明 |
| 替代根因排除 | WorkBuddy GUI 主进程持续可识别，`codebuddy --serve` Agent 始终按服务进程排除；数据库行数、读取顺序、通知开关和前端渲染均不是运行态缺失原因 | 已排除 |
| 稳定修复 | 完整进程桌面会话来源统一为 `qoder-log / workbuddy-db / workbuddy-log`；只补齐来源语义，不修改状态映射、日志/数据库解析、通知、冷却、标题、会话 ID、聚焦和 UI 优先级 | 通过 |
| 定向回归 | 新增 `test_workbuddy_runtime_log_session_remains_visible_with_db_session_on_same_process` 与 `test_workbuddy_runtime_log_session_survives_one_missing_poll_and_accepts_completion`，覆盖同 PID 新旧会话并存、运行态保持、一次缺失轮询和完成态接续；`tests.test_service` 51 项、`tests.test_sources` 129 项通过 | 通过 |
| 相关功能回归 | store、Web 启动、Web 行为、macOS 原生伴随、通知与偏好共 125 项通过；Zed 关闭窗口清理和精确项目聚焦测试保持通过 | 通过 |
| 完整门禁 | `PYTHONPATH=src python3 -m unittest discover -s tests` 为 487 项全部通过；`python3 scripts/validate_release.py` 输出 `release-validation-ok`；`git diff --check` 通过 | 通过 |
| Browser 与服务现场 | Browser 页面非空、气泡与右键菜单正常、控制台无应用错误。`Test again` 连续 3 个 5 秒周期显示“进行中”，随后连续 4 个周期显示“待处理”；原生日志在 06:52:03 至 06:52:50 连续 13 次为 `running=2 / full=2`，06:52:54 起稳定为 `needs_action=1 / running=1 / full=2` | 通过 |
| 完成后查看 | 点击 `WorkBuddy · Test again · 待处理` 后变为空闲；审计记录 `focus-window / activated-app`，保持原有“完成待查看”收口语义 | 通过 |
| Zed 与原生壳回归 | “日报推送”气泡聚焦审计为 `focused-project-window`；SellerBooks 已关闭且未重新出现。真实右键隐藏与菜单栏 `Show Monitor` 恢复后，`scripts/check_macos_floating_dev.sh --strict` 六项均为 `[OK]` 并输出 `Manual acceptance complete` | 通过 |

## 2026-07-28 全面回归审计与最终验收

| 验证 | 证据 | 结果 |
|---|---|---|
| ChatGPT 15 分钟收口 | 新增 App 存活时一次 `chatgpt-session` 来源缺失仍保留已查看具体对话、App 明确退出后不保留两项测试；修复前第一项提前退化为空闲入口，修复后按 15 分钟口径保持 | 通过 |
| WorkBuddy 状态合并 | 新增 runtime 显式待处理覆盖旧数据库完成态测试；更新的 `waiting_for_input` 使用 `view_ack_required=false`，普通完成待查看仍保持原语义 | 通过 |
| 通知偏好幂等 | 新增“实际状态相同不重复写盘”测试；缺失或非法值仍按默认开启计算，同值请求返回成功且不改写文件，其他偏好和未知字段保留 | 通过 |
| 相似项目窗口 | Python 服务、Python 聚焦助手和 Swift 原生策略统一使用“完整标题 > 标准标题分段 > 有边界词元”评分；自动化证明 `ProjectAlpha-old` 不会冒充 `ProjectAlpha`，仅剩前缀窗口时目标气泡会移除 | 通过 |
| 定向回归 | 跨 IDE 窗口、服务、进程宿主、命令包装器、Swift 聚焦策略和原生伴随 284 项通过；通知偏好/通知管理/服务/API/UI/文档既有回归保持通过；Swift 解析通过 | 通过 |
| 跨 IDE 统一策略 | Zed、Cursor、Visual Studio Code / Insiders、VSCodium、Windsurf、Xcode、Nova、Sublime Text、Kiro、Trae / Trae CN、Eclipse、Fleet、Android Studio 和 JetBrains 系列均由自动化证明进入同一窗口清单、失效清理、窗口 ID 回填和安全聚焦策略；Terminal、iTerm、Warp、WezTerm、kitty、Alacritty、Ghostty、Hyper、Tabby、Rio 保持 AI 子进程生命周期，不因缺少项目窗口被误删 | 自动化通过；Zed 与 Visual Studio Code 已实机，其他宿主不冒充实机验收 |
| VS Code 宿主归属 | 隔离测试目录中的真实进程树为 `AI CLI → shell → Code Helper → Code 主进程`；修复前会停在 Helper PID，修复后来源扫描器与命令包装器都继续向上并返回同一个 Code 主进程 PID。原生 AX 清单重新授权后持续为 `trusted=true` | 通过 |
| VS Code 双窗口精确聚焦 | alpha / beta 两个真实项目窗口各启动一个隔离 AI CLI。真实点击 Pet 的 `#1` 后，精确 Code PID 的 AX focused/main 均为 alpha；点击 `#2` 后两项均为 beta。三次原生聚焦结果均为 `ok=true / focused-project-window`，没有使用按进程名查询的同名窗口结果作为证据 | 通过 |
| VS Code 单窗关闭清理 | 通过精确 Code PID 和完整窗口标题只关闭 alpha；alpha AI CLI 同步退出，下一轮 Pet 会话中 alpha 消失、beta 仍存在。再次真实点击 beta 后，AX focused/main 仍均为 beta | 通过；“窗口已关但子进程短暂残留”边界由自动化测试覆盖 |
| VS Code 用户人工监测 | 用户手动在 VS Code IDE 窗口内启动真实 Claude Code，确认 Pet 监测功能正常 | 通过；只记录用户明确验证的监测主路径 |
| 进程扫描余量 | 清除上轮 VS Code 恢复的旧隔离进程后，在两个隔离 AI CLI 与现有真实会话共存条件下连续执行 6 次 `ProcessSource.poll()`，全部成功，耗时 `2.095–3.025 秒`，低于 4 秒命令预算。此前接近超时的结果来自人为堆积的过期验收进程，不作为正常基线，也未通过增加超时规避 | 通过 |
| 完整门禁 | `PYTHONPATH=src python3 -m unittest discover -s tests` 在正常本机权限下运行 511 项并输出 `OK`；受限环境中的 13 项仅因 `127.0.0.1` 绑定被拒绝而未执行；`python3 scripts/validate_release.py` 输出全部 `[OK]` 和 `release-validation-ok`；Swift 解析通过 | 通过 |
| 受限环境区分 | 受限环境中的发布校验曾有 13 项本机端口绑定 `PermissionError`，没有断言失败；同一命令在正常本机权限下全部通过，确认属于执行环境限制而非 Web/API 回归 | 已区分 |
| Browser 页面 | 页面身份为 `AI Progress Monitor`，页面非空；实时显示 4 个会话，其中 1 个进行中。右键主菜单顺序为“外观 / 系统通知 / 隐藏 Pet / 退出程序”，通知子菜单完整显示“开启 / ✓关闭”，无裁切，控制台错误和警告为 0；未改写用户通知偏好 | 通过 |
| 最新 Dev App | 使用既有脚本重新构建、临时签名并启动最新源码；服务持续输出会话快照，衬衫资源路由与批准源一致且禁用缓存。真实完成气泡展开/收起、约 30 像素往返拖动、右键隐藏、菜单栏恢复 | 通过 |
| 辅助功能与精确聚焦 | 重建后的临时签名使旧辅助功能授权失效，首次点击明确返回 `accessibility-permission-required`，未误记为通过。重新授权后清单为 `trusted=true / 1 IDE / 3 windows / 0 unavailable`；目标气泡返回 `ok=true / focused-project-window`，前台为 Zed 的目标项目窗口 | 通过 |
| 严格原生验收 | `scripts/check_macos_floating_dev.sh --strict` 的会话、开合、拖动、隐藏、菜单恢复、气泡聚焦和资源检查全部 `[OK]`，退出码 0，输出 `Manual acceptance complete` | 通过 |

## 2026-08-05 至 2026-08-06 运行态与通知去重回归

| 验证 | 真实证据 | 结果 |
|---|---|---|
| Claude 长任务稳定性 | 真实 Zed 长任务在多个轮询周期持续显示“进行中”，未再退回空闲；任务结束后直接进入待处理，点击查看后按会话语义转为空闲 | 通过 |
| 来源超时与并发恢复 | 每个来源使用有界 poll flight；阻塞期间不重复启动同一来源，迟到结果不覆盖较新状态，后续轮询可恢复；Claude 已验证观测使用序列号和单调时钟抵抗墙钟回拨 | 自动化通过 |
| Zed 精准聚焦与单窗清理 | 两个真实 Zed 项目会话分别点击时只前置对应窗口；关闭其中一个项目窗口后只移除对应气泡，其他仍打开会话保留并可继续精准聚焦 | 用户实机通过 |
| Visual Studio Code 回归 | 真实 Claude Code 会话覆盖运行、真实等待选择、选择后继续运行、完成待查看和点击收口；点击只跳对应 VS Code 窗口，没有带出其他窗口 | 用户实机通过 |
| 通知关闭与恢复 | 通知关闭期间任务结束不弹系统通知，Pet 仍进入待处理并可精准聚焦；重新开启后不补发关闭期间旧通知，后续新状态只弹一次 | 用户实机通过 |
| 持续待处理不重复 | 清空通知中心后，以唯一受控会话进入待处理；保持超过原 300 秒冷却周期，通知中心始终只有 1 条，Pet 保持待处理 | 用户计数通过 |
| 正常重启不补发 | 受控会话保持待处理并重启最新 Dev App；持久化 `last_sent_at` 未变化，通知开启且未锁定，用户确认通知中心仍只有原来的 1 条 | 程序核对 + 用户计数通过 |
| 新待处理事件恢复通知 | 同一受控会话先稳定进入运行中，再进入待处理；持久化发送时间只更新一次，通知总数从 1 变 2，Pet 显示待处理，没有一次新增两条 | 程序核对 + 用户计数通过 |
| 通知状态隐私与容量 | 状态文件为合法 JSON，权限 `600`，不含原始会话 ID、标题或摘要；损坏和写入失败不阻塞通知；超过 7 天的条目会移除，最多保留 512 条 | 自动化 + 本机文件核对通过 |
| 测试数据清理 | 受控会话先切为空闲，再删除唯一临时 JSON 并重启 Dev App；受保护接口确认测试会话不存在，用户确认气泡消失且通知仍为 2 条、没有新增第 3 条 | 程序核对 + 用户确认通过 |
| 最终自动化门禁 | 通知、服务、Store、Web 启动与文档定向模块在正常本机权限下为 219/219；完整 discovery 共 608 项，随最终 `validate_release.py` 全部通过；编译、App/Event/E2E/Bridge/Doctor 帮助、JavaScript、通知参数和敏感信息扫描均为 `[OK]`，最终输出 `release-validation-ok` | 通过 |
| v0.3.1 精确提交构建 | 从提交 `9d280a02f5e4d644c87c6724f54ed35adc275ffa` 的独立源码归档构建 macOS、portable 和 `.pyz`；构建目录与仓库现有 `dist/` 隔离 | 通过 |
| macOS 候选包检查 | 独立解包后根目录仅含 App、README、LICENSE；版本为 `0.3.1`，架构 arm64，最低 macOS 13，App 图标与运行资源存在，严格 ad-hoc 验签通过；未包含 Swift 源码、脚本、候选素材或 `.DS_Store` | 通过；未做 Developer ID 签名或 Apple 公证 |
| portable 候选包检查 | 独立解包后包含 `.pyz`、脚本、Windows 入口、README 和 LICENSE，不含 macOS App；入口帮助、doctor、monitor command 与解包态 E2E 通过 | 通过 |
| 候选 App Zed 验收 | 候选 App 获得辅助功能权限后，真实长任务连续保持进行中，结束后进入待处理且只产生 1 条新通知；点击只跳对应 Zed 项目窗口并转为空闲；关闭项目窗口后只移除对应气泡 | 用户实机通过 |
| 候选 App VS Code 关闭通知 | 通知关闭时真实任务保持进行中直至结束并进入待处理，通知中心没有该次新通知；状态、气泡和精准跳转未受影响 | 用户实机通过 |
| 候选 App 重新开启与重启 | 重新开启后未补发关闭期间旧通知；重启同一候选 App 后开关仍为“✓ 开启”且没有旧通知；任务已结束且 App 重启后，进程型会话因没有本轮运行证据按既有规则显示空闲 | 用户观察 + 程序接口核对通过 |
| 候选 App 新通知恢复 | 重启后在同一 VS Code 会话启动新短任务，程序只观察到“进行中 → 待处理”，中间未掉空闲；通知中心只新增 1 条，点击只跳目标窗口并转为空闲 | 用户实机 + 程序连续采样通过 |
| 候选 App 隐藏与恢复 | 右键“隐藏 Pet”后 Pet 消失；菜单栏 `Show Monitor` 后正常恢复；系统通知仍显示“✓ 开启” | 用户实机通过 |
| 命令行锁定态 | 隔离偏好原值为开启并含其他字段；portable 候选使用 `--no-notifications` 后接口返回实际关闭且锁定，开启请求为 `409 notifications_forced_disabled`，偏好字节未改写、JSON 合法、权限 `600` | 通过 |
| 候选包 SHA-256 | macOS ZIP `5f5c5aea5a15e09f6f9a6514ab8a8cb72453448f17dbae3c8d88a16f60646f9a`；portable ZIP `f2efe5c69755137c5038e2cb2bf152efc8eb9614625259a1f1484ecb233c19c2`；`.pyz` `7212855f579a893d5d38fa62b2bd486893008dd51f576fb5c4dbcfb292bf4ebd` | 本地候选记录完成 |
| 发布边界 | 截至 2026-08-06，v0.3.1 候选已本地构建和验收；没有 push、PR、merge、tag、GitHub Release、附件上传或回下载验证。候选哈希锚定源码提交 `9d280a02f5e4d644c87c6724f54ed35adc275ffa`；公开发布前必须从最终合并或 Tag 提交重新构建并重算 | 未发布，符合当前范围 |

## 当前运行日志关键证据

| 日志 | 含义 |
|---|---|
| `AI Progress Monitor sessions` | 开发态 Pet 服务已被 WebView 轮询；最新逻辑应显示 ChatGPT 桌面运行中会话为 `full`，直接已配置 AI CLI 为 `process_only`，数量会随真实会话实时变化 |
| `Project window inventory: trusted=true apps=1 windows=2 unavailable=0` → `windows=1` | 最终 Dev App 的原生 AX 清单可用；关闭 SellerBooks 项目窗口后只减少一个 Zed 窗口，无窗口清单读取失败 |
| `Native focus result: ok=true method=focused-project-window` | 真实 VS Code 双窗口正反向点击和关闭 alpha 后再次点击 beta 均走精确项目窗口路径 |
| alpha 气泡消失、beta 气泡保留 | 精确关闭 alpha 后，下一轮受保护会话接口只保留 beta；再次点击 beta 后其 AX focused/main 均为 beta |
| `Manual acceptance evidence: [OK] sessions visible` | 开发态 Pet 已识别监控对象 |
| `Manual acceptance evidence: [OK] left-click open/close evidence` | 前一轮真实 CGEvent 左键展开/收起日志已通过，且没有 hide；本轮按要求未重复测试 |
| `Manual acceptance evidence: [OK] drag evidence` | 前一轮真实拖动日志已通过，窗口从外接屏区域拖到主屏可见区域；本轮按要求未重复测试 |
| `Manual acceptance evidence: [OK] hide evidence` | 前一轮真实右键菜单隐藏日志已通过，窗口数变 0 且进程仍在；本轮按要求未重复测试 |
| `Manual acceptance evidence: [OK] menu restore evidence` | 前一轮真实点击菜单栏头像图标菜单中的 `Show Monitor` 已恢复窗口；本轮按要求未重复测试 |
| `Manual acceptance evidence: [OK] bubble focus evidence` | 本轮真实点击脱敏项目气泡，日志为 `AI Progress Monitor focus: ok=true` |
| `scripts/check_macos_floating_dev.sh --strict` | 2026-07-17 最终复测退出码为 0；会话可见、左键开合、拖动、隐藏、菜单恢复、气泡聚焦和衬衫资源检查全部为 `[OK]` |
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
| 系统通知没有操作系统展示回执 | 当前去重状态记录的是通知命令发送尝试，不代表 macOS 通知中心已确认展示；若系统拒绝或抑制该通知，当前会话仍可能被记为已发送并不再重复提醒 | 保持 Pet 状态为主要真相；后续如需可观测的送达保证，应增加发送结果诊断或系统级回执能力 |
| 崩溃瞬间或状态文件不可写时可能重复通知 | 正常重启去重已通过；若系统通知已送达但进程在状态原子落盘前崩溃，或状态目录不可写，重启后可能无法继承该次发送基线 | 当前按安全降级处理，不宣称严格 exactly-once；若后续要求崩溃级保证，需引入发送意图日志与恢复协议 |
| 多个 App 实例并行存在时可能竞争状态文件 | 正常启动脚本会终止旧实例，但当前状态文件不是跨进程事务存储；异常并行实例可能相互覆盖较新的通知基线 | 正式入口保持单实例；若支持多实例，需要独立进程锁或统一状态服务 |

## 本机开发态试用入口

| 操作 | 命令/路径 | 说明 |
|---|---|---|
| 构建但不启动 | `scripts/run_macos_floating_dev.sh --build-only` | 验证最新源码能生成本地开发态 macOS Pet |
| 启动最新源码 Pet | `scripts/run_macos_floating_dev.sh` | 会启动 `build/macos-dev/AI Progress Monitor Floating Dev.app` |
| 查看手工验收日志 | `scripts/check_macos_floating_dev.sh` | 查看 dev app 是否运行、脱敏服务 URL、session snapshot、外观切换记录、host 消息、Show/Hide/Quit 日志，以及衬衫树懒资源路由是否正确 |
| 严格验收门 | `scripts/check_macos_floating_dev.sh --strict` | 有任何 `[TODO]` 时返回失败；全部真实路径有证据后才通过 |
| 手工测试重点 | 左键 Pet、右键隐藏/退出、菜单栏头像图标中的 `Show Monitor`、外接屏跨屏拖动、点击气泡聚焦 | 这些是真实鼠标路径，必须用开发态 app 试 |
