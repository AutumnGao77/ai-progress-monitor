# 原创树懒 Pet 监控助手 AI Coding PRD

## 1. 结论

本文件是后续 AI coding 的目标文档。相比产品评审版 PRD，本文件更强调 **可执行、可测试、可验收**。

本次迭代目标：把当前 Web Companion 从“工具面板式 AI Monitor”改成 **原创树懒 Pet + 气泡会话列表 + 状态数字角标 + 右键 Pet 菜单**。用户主界面只保留看状态、看数量、点气泡回到原窗口、右键隐藏或退出四件事。

2026-07-17 桌面产品身份已迁移为 ChatGPT Desktop：桌面完整会话只接收 `~/.codex/sessions` 中明确标记为 `Codex Desktop` 或 `ChatGPT Desktop` originator 的兼容事件，用户界面统一显示 ChatGPT；Codex 仅保留 CLI 监控，不再把 `Codex.app` 当作桌面产品。

当前右键菜单已由 `2026-07-11-pet-appearance-theme-switching-prd.md` 扩展为“外观 / 隐藏 Pet / 退出程序”。本文件中“隐藏 / 退出”仍是基础控制能力，不应被理解为要求删除已交付的“外观”子菜单。

| 判断项 | 结论 |
|---|---|
| 是否适合 AI 直接执行 | 是，本文件包含实现范围、状态算法、交互规则、测试用例和验收标准 |
| 本次主要改动 | `src/ai_progress_monitor/web.py` 的 HTML / CSS / JS；必要时同步原生壳 |
| 本次主要测试 | `tests/test_web_ui.py`、`tests/test_web_launch.py`、`tests/test_web_ui_behavior.py`、`tests/test_preferences.py`、原生 companion 测试，必要时补充服务层回归测试 |
| 不做 | 不新增 API，不引入外部版权角色素材，不做复杂设置页；允许增加向后兼容的只读 payload 字段 |

## 2. 当前问题

| 当前实现问题 | 为什么影响 coding | 新 PRD 要求 |
|---|---|---|
| 产品版 PRD 偏体验描述 | AI 不知道具体改哪些文件、删哪些入口 | 明确实现范围和禁止项 |
| 缺少状态算法 | AI 可能把角标总数、颜色、排序做错 | 写清角标总数和状态颜色优先级 |
| 缺少同文件夹多对话规则 | AI 可能只显示文件夹名，导致气泡重复 | 写清气泡命名和稳定序号 |
| 缺少测试用例 | AI 改完无法判断是否达标 | 给出自动化测试、手工验收、边界场景 |
| 缺少完成定义 | AI 容易只做 UI 但漏掉跳转、隐私、旧入口清理 | 给出 Done Checklist |

## 3. 实现范围

| 类型 | 范围 |
|---|---|
| 主要修改文件 | `src/ai_progress_monitor/web.py` |
| 原生壳修改 | `native/macos/FloatingMonitor.swift`、`native/windows/FloatingMonitor.ps1`，用于隐藏/退出和状态栏/托盘唤醒 |
| 主要测试文件 | `tests/test_web_ui.py`、`tests/test_macos_native_companion.py`、`tests/test_windows_native_companion.py` |
| 可复用后端接口 | `/api/sessions`、`/api/focus` |
| 可复用前端能力 | 轮询、拖动、位置记忆、窗口尺寸调整 |
| 允许保留但不暴露 | `/api/action`、`/api/pause`、`/api/doctor`、会话隐藏/恢复/重命名相关 API |
| 不新增 | 新 API、数据库、外部图片资源、版权角色素材 |

## 4. AI 执行原则

| 原则 | 要求 |
|---|---|
| 主路径极简 | 主界面只出现 Pet、数字角标、气泡列表 |
| 信息最小化 | 不展示 `summary`、命令输出、完整对话、用户输入 |
| 回原窗口处理 | 不在 Pet 内做 Yes/No、Allow/Deny、Continue/Stop |
| Pet 级控制 | 右键 Pet 提供外观、隐藏 Pet、退出程序，不提供会话管理 |
| 不破坏后端 | 不新增 API，不改变已有字段含义；可增加向后兼容的只读字段用于聚焦和弱识别 |
| 不引入 IP 风险 | 树懒必须是原创形象，不复刻电影角色 |
| 测试先行 | coding 前先更新或新增测试断言，再改实现 |

## 5. 用户故事

| 编号 | 用户故事 | 验收结果 |
|---|---|---|
| US-1 | 作为同时开多个 AI 会话的用户，我想看到一个低干扰 Pet，而不是工具面板 | 默认只显示 Pet 和角标 |
| US-2 | 作为用户，我想在收起态知道有几个对话需要关注 | Pet 右上角显示数字角标 |
| US-3 | 作为用户，我想通过角标颜色判断最紧急状态 | 待处理红色、进行中绿色、空闲蓝色 |
| US-4 | 作为用户，我想点击 Pet 展开会话列表 | 点击 Pet 后显示气泡列表 |
| US-5 | 作为用户，我想点击某条气泡回到对应 ChatGPT Desktop、Claude Code、Codex CLI 或其他已配置工具窗口 | 点击气泡调用 `/api/focus` |
| US-6 | 作为用户，我不想在主界面看到诊断、暂停、隐藏等工具按钮 | 主界面不渲染这些入口 |
| US-7 | 作为用户，我不想泄露对话内容 | 气泡不展示 `summary` 或 prompt |
| US-8 | 作为同一文件夹开多个对话的用户，我想区分每个对话 | 气泡显示文件夹名 + 对话标识 + 状态 |
| US-8b | 作为使用桌面版 AI 且未绑定文件夹的用户，我不想看到不可读的 session_id 碎片 | 气泡显示 `工具名 对话` 或安全短标题 + 状态 |
| US-9 | 作为用户，我想临时不看到 Pet，但让监控继续运行 | 右键 Pet 选择隐藏后，Pet 消失，程序继续运行 |
| US-10 | 作为用户，我想彻底关闭监控 | 右键 Pet 选择退出程序后，Pet 和本地监控服务退出 |

## 6. 数据输入与状态映射

### 6.1 输入数据

继续使用 `/api/sessions` 返回的数据，不新增接口。

| 字段 | 用途 | 是否必须 |
|---|---|---|
| `session_id` | 气泡唯一 key、点击 `/api/focus` 参数、短 ID 兜底 | 是 |
| `title` | 提取文件夹名和安全短标题 | 是 |
| `tool` | 生成 `Claude` / `Codex` 工具标识 | 是 |
| `status` | 映射三态、角标颜色、排序 | 是 |
| `monitoring_level` | 区分 `full` 和 `process_only` | 否 |
| `age_seconds` | 可选辅助排序，不在气泡中展示 | 否 |
| `summary` | 不用于主界面展示 | 否 |
| `safe_action` | 不用于主界面展示 | 否 |
| `focus_process_id` | 弱识别终端会话点击气泡时，优先聚焦父 GUI 应用 | 否 |
| `focus_app_name` | macOS 辅助权限不足时，用于退一步激活父应用 | 否 |

### 6.2 三态映射

| 后端状态 | 用户状态 | 文案 | 角标颜色 | 优先级 |
|---|---|---|---|---|
| `needs_action` | 待处理 | 待处理 | 红色 | 1 |
| `running` | 进行中 | 进行中 | 绿色 | 2 |
| `stuck` | 进行中 | 进行中 | 绿色 | 2 |
| `idle` | 空闲 | 空闲 | 蓝色 | 3 |
| `unknown` | 空闲 | 空闲 | 蓝色 | 3 |

说明：用户主界面只理解三态。`stuck` 和 `unknown` 暂不独立展示，避免回到复杂工具面板。

### 6.3 监控起点规则

结论：打开这个 App 之后，才开始监控所有已配置 AI 工具对话的进度并按状态反馈；打开前已经沉淀在历史文件里的桌面/JSON 会话不纳入本轮气泡列表。当前仍存活的 CLI 对话属于现场，要显示为空闲或当前状态，后续活动继续更新。

| 规则 | 要求 |
|---|---|
| App 启动前已经存在的 AI 桌面/JSON 历史会话文件 | 不纳入本轮气泡列表 |
| App 启动前已经存在且当前仍存活的已配置 AI CLI 进程 | 纳入本轮气泡列表；安静显示空闲，后续有活动再更新为进行中/待处理 |
| App 启动前已经打开且当前仍存活的已配置 AI 桌面 App 主程序 | 可显示为桌面端空闲入口；不能仅因主程序存活显示进行中或待处理 |
| App 启动前已经写入的 wrapper/JSON 会话文件 | 不纳入本轮气泡列表 |
| App 启动后新产生的会话、新进程或新状态事件 | 纳入本轮监控 |
| App 启动后出现的待处理 | 必须保留到用户点击查看/处理，不能因为时间过长自动消失 |
| 已查看后的桌面端具体对话 | 转为空闲后在气泡列表保留 15 分钟；超过 15 分钟自动移出 |
| 桌面端具体对话都被移出且 App 仍存活 | 保留该工具的桌面端 App 空闲入口 |
| App 关闭期间发生并结束的对话 | 下次启动时不补历史、不展示为待处理 |

产品原则：Pet 是“从我打开它之后开始看现场”的轻量监控，不是历史会话 inbox。当前仍活着的 CLI 和桌面 App 是现场的一部分，需要显示为空闲入口或当前状态；已经沉淀在历史文件里的旧桌面/JSON 会话不回捞，避免一启动就出现大量旧待处理角标。

补充：`monitoring_level === "process_only"` 只能证明已配置的 AI CLI 或桌面 App 进程存在，不能读取或展示终端内容、具体命令输出或用户输入。直接 CLI 气泡必须对应当前仍处于前台交互终端状态的 AI 会话；即使 CLI 在 App 启动前已经打开，只要进程仍存在，也要显示为空闲或当前状态；当用户退出 CLI 后，即使 IDE、终端或项目窗口仍打开，也不应继续显示该气泡。直接识别到 `claude` CLI 进程时，优先读取 `~/.claude/sessions/<pid>.json` 中 Claude 自己记录的会话状态；扫描必须在每个进程前重置 `cwd` 等临时字段，工作目录只能来自当前进程或同 PID 且目录一致的 Claude 状态记录，不能继承上一进程的目录或虚构其他项目会话。运行中显示 `进行中`；明确空闲时保持 `空闲`，不能因短暂 CPU/MCP 活跃翻成 `进行中`；从运行变为空闲，或同一会话出现新的空闲完成时间时，先显示 `待处理`；点击气泡成功回到系统终端或 IDE 内置终端后标记已查看并转为空闲；读不到、状态不匹配或过期 running 时，再按 CPU、进程运行态和过滤后的活跃子进程做保守映射。直接识别到其他已配置 CLI 时，先按进程活跃度做保守映射。已配置桌面 App 主程序存活时，只显示空闲入口；只有具体会话事件或窗口会话信号才能显示 `进行中` / `待处理`。ChatGPT 桌面端兼容读取 `~/.codex/sessions` 中明确的桌面会话事件来生成具体对话气泡：App 启动后有未完成 `task_started` 时显示绿色 `进行中`，有可见回复并 `task_complete` 后显示 `待处理`，点击气泡成功回到 ChatGPT 后转为空闲；已查看后转为空闲的桌面端具体对话在气泡列表保留 15 分钟后移出；具体桌面会话出现后，自动隐藏同工具的通用桌面空闲入口，避免重复计数；当具体桌面会话都被移出且桌面 App 仍存活时，重新显示 App 空闲入口。主气泡仍只展示文件夹/对话标识和状态，不常驻展示技术说明。

## 7. 角标算法

### 7.1 显示规则

| 会话状态组合 | 角标数字 | 角标颜色 |
|---|---|---|
| 0 个会话 | 不显示 | 无 |
| 1 个待处理 | `1` | 红色 |
| 1 待处理 + 2 进行中 + 3 空闲 | `6` | 红色 |
| 0 待处理 + 2 进行中 + 3 空闲 | `5` | 绿色 |
| 0 待处理 + 0 进行中 + 3 空闲 | `3` | 蓝色 |

### 7.2 混合状态优先级

角标数字显示当前气泡列表中的会话总数；角标颜色按待处理 > 进行中 > 空闲选择最高优先级状态。

| 输入 | 输出 |
|---|---|
| 1 待处理 + 2 进行中 + 3 空闲 | 红色 `6` |
| 0 待处理 + 2 进行中 + 3 空闲 | 绿色 `5` |
| 0 待处理 + 0 进行中 + 3 空闲 | 蓝色 `3` |

### 7.3 推荐实现

| 函数 | 职责 |
|---|---|
| `displayStatus(session)` | 把后端 status 映射成 `needs_action` / `running` / `idle` 三态之一 |
| `badgeState(sessions)` | 返回 `{count, status, colorClass}` |
| `renderBadge(sessions)` | 根据 `badgeState` 更新数字和颜色 |

## 8. 气泡列表算法

### 8.1 过滤规则

| 类型 | 处理 |
|---|---|
| `monitoring_level === "full"` | 正常显示为对话气泡 |
| `monitoring_level === "process_only"` | 可显示为气泡；直接 CLI 需仍处于前台交互终端状态；Claude CLI 优先使用 Claude 会话状态且明确 idle 时保持空闲，其他直接 CLI 按活跃/静默映射；已配置桌面 App 主程序只显示空闲入口，有具体桌面会话时该入口让位，气泡不展示技术说明 |
| 隐藏会话 API 返回的数据 | 主界面不提供入口，本次不主动展示 |

### 8.2 排序规则

| 优先级 | 规则 |
|---|---|
| 1 | 待处理在最上方 |
| 2 | 进行中在中间 |
| 3 | 空闲在最后 |
| 4 | 同状态内保持后端返回顺序，避免刷新跳动 |

### 8.3 气泡文案结构

标准结构：

```text
文件夹名 · 对话标识 · 状态
```

单文件夹单对话可省略对话标识：

```text
文件夹名 · 状态
```

### 8.4 文件夹名提取

| 输入 title 示例 | 文件夹名输出 |
|---|---|
| `Codex - checkout-flow` | `checkout-flow` |
| `Claude Code - docs/prd` | `prd` 或安全短标题 |
| `AI Progress Monitor` | `AI 会话` |
| 空字符串 | `AI 会话` |

首版允许用保守策略：从 `title` 中移除 `Claude Code`、`Codex`、`Terminal` 等工具词后，取最清晰的短片段；无法提取时使用 `AI 会话`。

补充：桌面版 AI 会话可能没有 cwd/文件夹。此时不能把 `session_id`、UUID、短 slug 或类似 `he-l` 的不可读碎片当作文件夹名展示。无文件夹桌面对话的气泡命名规则如下：

| 场景 | 气泡文案 |
|---|---|
| 单个无文件夹 ChatGPT 桌面对话，标题不可读 | `ChatGPT 对话 · 空闲` |
| 多个无文件夹 ChatGPT 桌面对话，标题不可读 | `ChatGPT 对话 #1 · 空闲`、`ChatGPT 对话 #2 · 进行中` |
| 无文件夹桌面对话有安全可读短标题 | `ChatGPT · hello · 空闲` |
| 工具定义表中声明的自动聊天工作目录，例如 ChatGPT 兼容会话的 `Documents/ChatGPT/YYYY-MM-DD/hello` | 视为无真实项目文件夹，显示 `ChatGPT · hello · 空闲`；这不是 ChatGPT 特例，后续桌面端 AI 工具通过配置 `key/display_name` 和自动聊天目录 pattern 接入 |
| 只是桌面 App 主程序存活，不是具体对话 | `ChatGPT Desktop · 空闲` |

### 8.5 同文件夹多对话标识

| 场景 | 气泡文案 |
|---|---|
| 单文件夹单 Codex | `checkout-flow · 进行中` |
| 同文件夹两个 Codex | `checkout-flow · Codex #1 · 进行中`、`checkout-flow · Codex #2 · 待处理` |
| 同文件夹 Claude + Codex | `checkout-flow · Claude #1 · 进行中`、`checkout-flow · Codex #1 · 待处理` |
| 有安全短标题 | `checkout-flow · PRD polish · 空闲` |
| 标题不可用 | `AI 会话 · Claude #1 · 进行中` |

### 8.6 稳定序号要求

| 要求 | 说明 |
|---|---|
| 同一次前端运行周期内稳定 | 同一个 `session_id` 每次渲染序号不变 |
| 不因排序变化改变编号 | 待处理排到上面后，原编号仍保持 |
| 可用内存 Map 实现 | 例如 `sessionSequenceByGroup` |
| 不要求跨重启稳定 | 刷新页面后重新编号可接受 |

## 9. UI 结构要求

### 9.1 DOM 结构

| 元素 | 建议 ID / class | 要求 |
|---|---|---|
| Pet 容器 | `#pet` / `.pet` | 保留拖动能力 |
| 树懒图片 | `#petArt` / `.pet-art` | 使用本地内置原创资源，按三态切换 |
| 数字角标 | `#petBadge` / `.pet-badge` | 右上角显示数字 |
| 气泡列表 | `#bubbleList` / `.bubble-list` | 展开态显示在 Pet 上方 |
| 单条气泡 | `.session-bubble` | 可点击，带 `data-session-id` |

### 9.2 主界面禁止出现

以下文字或按钮不得出现在主界面 HTML 中：

| 禁止项 | 原因 |
|---|---|
| `诊断` | 排障能力，不属于主路径 |
| `已隐藏` | 管理能力过重 |
| `暂停` | 主路径复杂化 |
| `暂隐` | 收起由点击 Pet 完成 |
| `隐藏会话` / session row hide | 气泡不是管理面板 |
| `重命名` | 本次不做管理功能 |
| `恢复默认名` | 本次不做管理功能 |
| `Yes` / `No` 操作按钮 | 回原窗口处理 |
| 完整 `summary` | 隐私风险 |

说明：后端 API 可以保留，禁止的是主界面入口和气泡主路径展示。`隐藏 Pet` 是右键菜单能力，允许出现；它不能和“隐藏会话”混为一谈。

### 9.3 Pet 动效

| 用户状态 | 视觉表现 | 验收方式 |
|---|---|---|
| 待处理 | 树懒轻微抬头/挥手，角标红色 | CSS class 存在，例如 `.pet.needs-action` |
| 进行中 | 缓慢点头或手部轻动，角标绿色 | CSS class 存在，例如 `.pet.running` |
| 空闲 | 呼吸或打盹，角标蓝色 | CSS class 存在，例如 `.pet.idle` |

### 9.4 Pet 图片资源

| 用途 | 运行时路由 | 默认资源 | 要求 |
|---|---|---|---|
| 空闲 | `/assets/pet/idle.png` | `sloth-pet-idle.png` | 透明背景 PNG，当前尺寸 768 x 768 |
| 进行中 | `/assets/pet/running.png` | `sloth-pet-running.png` | 透明背景 PNG，当前尺寸 768 x 768 |
| 待处理 | `/assets/pet/needs-action.png` | `sloth-pet-needs-action.png` | 透明背景 PNG，当前尺寸 768 x 768 |
| APP 头像 | `/assets/app-avatar.png` | `app-avatar.png` | 透明圆形 PNG，当前尺寸 1024 x 1024；源图和运行图均不得保留水印或圆外方框背景，透明像素应为 `(0,0,0,0)`；同时用于 favicon、macOS 菜单栏图标和 `.app` bundle 图标 |

图片替换只改变动画人物外观，不改变角标、气泡列表、拖动、右键菜单和状态算法。Web 容器必须保持透明，`.pet` 不额外添加 `drop-shadow`，避免原生悬浮窗口出现灰底或阴影边。macOS 原生壳的状态栏入口应显示 APP 头像图标，不显示文字 `AI`。`~/.ai-progress-monitor/preferences.json` 可用 `pet_assets.idle`、`pet_assets.running`、`pet_assets.needs_action`、`pet_assets.app_avatar` 覆盖本地图片路径；配置异常时回退内置资源。

## 10. 点击与失败处理

| 场景 | 行为 | 验收 |
|---|---|---|
| 点击 Pet | 切换 `.bubble-list.open` | 不调用后端 |
| 拖动 Pet 后松手 | 更新位置，不展开气泡 | `dragMoved` 逻辑保留 |
| 点击气泡 | POST `/api/focus`，body 含 `session_id` | 不调用 `/api/action` |
| `/api/focus` 成功 | 可保持气泡展开，不强制收起 | 不显示多余提示 |
| `/api/focus` 失败 | 在气泡或 Pet 附近显示轻量失败文案 | 不展开诊断 |
| 后端连接失败 | Pet 显示弱错误态，继续轮询 | 不弹窗 |

## 11. 右键菜单、隐藏与退出

### 11.1 右键菜单项

| 菜单项 | 行为 | 验收 |
|---|---|---|
| 隐藏 Pet | 隐藏桌面 Pet，不停止本地监控程序 | Pet 消失，后台轮询/监控继续 |
| 退出程序 | 退出 Pet 和本地监控服务 | 原生壳关闭，子进程被终止 |

### 11.2 唤醒入口

| 系统 | 入口 | 行为 |
|---|---|---|
| macOS | 菜单栏状态图标 | 选择显示或点击入口后重新显示 Pet |
| Windows | 系统托盘图标 | 双击或选择显示后重新显示 Pet |
| 纯浏览器 Web | 无系统状态栏能力 | 可以提供页面内隐藏 fallback，但正式桌面体验以原生壳为准 |

### 11.3 实现边界

| 层 | 要求 |
|---|---|
| Web UI | 右键 Pet 时展示轻量 context menu；当前菜单包含外观、隐藏 Pet、退出程序 |
| macOS 原生壳 | 支持接收 Web 消息或原生菜单动作：隐藏窗口、退出程序；菜单栏保留显示入口 |
| Windows 原生壳 | 支持右键/上下文菜单隐藏窗口、退出程序；托盘保留显示入口 |
| 后端服务 | 隐藏 Pet 不停止服务；退出程序需要终止本地 monitor 子进程 |

### 11.4 命名边界

| 名称 | 含义 |
|---|---|
| 隐藏 Pet | 隐藏整个桌面宠物，程序继续运行 |
| 隐藏会话 | 隐藏某一条 Claude/Codex 会话，本次主体验不提供 |
| 退出程序 | 关闭桌面壳和本地监控服务 |

## 12. 自动化测试用例

### 12.1 Web UI 静态结构测试

建议更新 `tests/test_web_ui.py`。

| 测试名建议 | 断言 |
|---|---|
| `test_pet_uses_sloth_bubble_layout` | HTML 包含 `sloth-avatar`、`petBadge`、`bubbleList`、`session-bubble` |
| `test_main_ui_removes_tool_panel_buttons` | HTML 不包含 `诊断`、`已隐藏`、`暂停`、`暂隐`、`重命名`、`恢复默认名` |
| `test_badge_supports_three_status_colors` | HTML/JS 包含红色、绿色、蓝色角标 class 或颜色映射 |
| `test_pet_click_toggles_bubble_list` | HTML/JS 包含 bubble list open/close 切换逻辑 |
| `test_pet_context_menu_has_hide_and_quit` | HTML/JS 包含 Pet 右键菜单，具备外观、隐藏 Pet、退出程序且无会话管理项 |
| `test_hide_pet_does_not_call_session_hide_api` | 隐藏 Pet 不调用 `/api/hide-session` |
| `test_bubble_click_focuses_session` | HTML/JS 包含 `/api/focus`，并通过 `session_id` 聚焦 |
| `test_bubbles_do_not_render_safe_action_buttons` | 气泡渲染逻辑不遍历 `safe_action.options` 生成按钮 |
| `test_bubbles_do_not_render_summary` | 气泡渲染逻辑不输出 `session.summary` |
| `test_pet_dragging_still_persists_position` | 保留 `pointerdown`、`monitor.pet.position`、`applyPetPosition` |
| `test_poll_interval_still_under_five_seconds` | `POLL_INTERVAL_MS <= 5000` |

### 12.2 前端算法测试建议

如果继续用 HTML 字符串测试，可通过函数名和关键规则做静态断言；如果后续拆出 JS 文件，再补充真实函数测试。

| 函数 | 输入 | 期望 |
|---|---|---|
| `displayStatus` | `needs_action` | `needs_action` |
| `displayStatus` | `running` | `running` |
| `displayStatus` | `stuck` | `running` |
| `displayStatus` | `idle` | `idle` |
| `displayStatus` | `unknown` | `idle` |
| `displayStatus` | `running` + `process_only` | `running`，气泡仍只展示文件夹/对话标识和状态 |
| `badgeState` | 1 待处理 + 2 进行中 | 红色 `3` |
| `badgeState` | 0 待处理 + 2 进行中 | 绿色 `2` |
| `badgeState` | 0 待处理 + 0 进行中 + 3 空闲 | 蓝色 `3` |
| `badgeState` | 空数组 | 不显示 |
| `bubbleLabel` | 同文件夹 2 个 Codex | 生成 `Codex #1` / `Codex #2` |
| `hidePet` | 用户选择隐藏 Pet | 隐藏 Pet 容器，不停止轮询 |
| `quitApp` | 用户选择退出程序 | 发送 host bridge 退出消息，纯浏览器 fallback 给轻提示 |

### 12.3 原生 companion 测试

| 测试文件 | 目的 |
|---|---|
| `tests/test_macos_native_companion.py` | macOS 有菜单栏状态图标、显示入口、退出入口、隐藏后可恢复 |
| `tests/test_windows_native_companion.py` | Windows 有托盘图标、显示入口、退出入口、隐藏后可恢复 |

### 12.4 服务回归测试

本次不要求改服务层，但需要确认原有聚焦能力没被破坏。

| 测试文件 | 目的 |
|---|---|
| `tests/test_service.py` | `/api/focus` 仍能用 session_id 找到窗口信息 |
| `tests/test_window_focus.py` | macOS / Windows 聚焦命令仍可构造 |
| `tests/test_web_security.py` | 本地 API token 保护不被破坏 |

### 12.5 推荐测试命令

```bash
PYTHONPATH=src python3 -m unittest tests.test_web_ui
PYTHONPATH=src python3 -m unittest tests.test_macos_native_companion tests.test_windows_native_companion
PYTHONPATH=src python3 -m unittest tests.test_service tests.test_window_focus tests.test_web_security
PYTHONPATH=src python3 -m unittest discover -s tests
```

## 13. 手工验收场景

| 编号 | 场景 | 操作 | 期望 |
|---|---|---|---|
| M-1 | 无会话 | 启动 demo 或空数据 | 只显示原创树懒 Pet，不显示角标或显示弱状态 |
| M-2 | 单个进行中 | 注入 1 个 running session | 角标显示 `1`，绿色 |
| M-3 | 单个待处理 | 注入 1 个 needs_action session，并长时间不点击 | 角标显示 `1`，红色，Pet 待处理动作；待处理不因时间过长自动消失 |
| M-4 | 单个空闲 | 注入 1 个 idle session | 角标显示 `1`，蓝色 |
| M-5 | 混合状态 | 注入 1 待处理 + 2 进行中 + 3 空闲 | 角标显示红色 `6` |
| M-6 | 点击 Pet | 点击 Pet 一次 | 气泡列表展开 |
| M-7 | 再次点击 Pet | 气泡已展开时点击 Pet | 气泡列表收起 |
| M-8 | 点击气泡 | 点击某条气泡 | 调用对应 session 的 `/api/focus` |
| M-9 | 同文件夹多对话 | 注入同一文件夹 2 个 Codex | 气泡可区分为 `Codex #1`、`Codex #2` |
| M-10 | 隐私检查 | session 带 summary 和 safe_action | 气泡不显示 summary，不显示 Yes/No 按钮 |
| M-11 | 旧入口检查 | 查看主界面 | 不出现诊断、已隐藏、暂停、暂隐、隐藏会话、重命名 |
| M-12 | 拖动 Pet | 拖动 Pet 到新位置 | 位置保存，松手不展开气泡 |
| M-13 | 右键 Pet | 右键点击 Pet | 出现外观、隐藏 Pet、退出程序三个主菜单项 |
| M-14 | 隐藏 Pet | 选择隐藏 Pet | Pet 消失，程序继续运行 |
| M-15 | 状态栏/托盘恢复 | 从 macOS 菜单栏或 Windows 托盘选择显示 | Pet 重新出现 |
| M-16 | 退出程序 | 右键 Pet 选择退出程序 | Pet 关闭，本地监控服务退出 |
| M-17 | 直接终端 CLI 进程级检测 | 直接运行 `claude` 或 `codex`，不使用 wrapper | Pet 出现 process-only 气泡；Claude CLI 优先使用 Claude 会话状态，明确 idle 时不因短暂 CPU/MCP 活跃翻成进行中；其他直接 CLI 按活跃/静默映射，不展示终端内容或技术说明 |
| M-18 | 点击直接终端 CLI 气泡 | 点击 process-only 气泡 | 调用 `/api/focus`，优先用 `focus_process_id` / `focus_app_name` 回到父 GUI 应用 |
| M-19 | ChatGPT 桌面会话事件检测 | ChatGPT 桌面端存在 2 个未完成任务，且窗口权限不可用 | 基于 `~/.codex/sessions` 中明确的桌面 originator 显示 2 个 ChatGPT 进行中气泡；如果同时存在 ChatGPT 桌面空闲入口，具体会话优先且入口不重复计数 |
| M-19b | 通用 AI 桌面存活入口 | 已配置 AI 桌面 App 已打开，但没有 App 启动后的具体会话事件 | 显示该工具的桌面端空闲入口；不显示为进行中或待处理 |
| M-19c | 已查看桌面会话收口 | 桌面端具体对话待处理，用户点击气泡查看后转为空闲，并等待 15 分钟 | 15 分钟内仍显示具体对话为空闲；15 分钟后具体对话从气泡列表移出；若桌面 App 仍存活，则显示 App 空闲入口 |
| M-20 | 启动前历史会话不导入 | 先产生 ChatGPT 桌面或 wrapper 历史会话，再启动 Pet | 启动后不显示这些历史文件会话；只有打开 App 后新产生的事件进入气泡列表 |
| M-20b | 启动前已存在的 CLI 仍显示 | 先打开 Claude/Codex CLI 并保持进程存活，再启动 Pet | Pet 显示该 CLI 对话；安静显示空闲，后续活动按进行中/待处理更新 |
| M-21 | 启动后待处理不自动消失 | Pet 已启动后产生待处理，长时间不点击 | 待处理持续显示红色角标，直到用户点击查看/处理或会话源真实消失 |

## 14. 验收标准

### 14.1 P0 必须满足

| 编号 | 标准 | 验收方式 |
|---|---|---|
| AC-1 | 主界面从工具面板变为原创树懒 Pet | 手工验收 + HTML 结构测试 |
| AC-2 | Pet 右上角数字角标显示气泡列表总数，并按状态变色 | 自动化测试 + 手工验收 |
| AC-3 | 待处理红色、进行中绿色、空闲蓝色 | 自动化测试 + 手工验收 |
| AC-4 | 多状态并存时，角标数字显示总数，颜色按待处理 > 进行中 > 空闲显示 | 前端算法测试 |
| AC-5 | 点击 Pet 展开/收起气泡列表 | 自动化测试 + 手工验收 |
| AC-6 | 点击气泡调用 `/api/focus`，不调用 `/api/action` | 自动化测试 |
| AC-7 | 主界面不展示 `summary`、命令输出、用户输入 | 自动化测试 + 手工验收 |
| AC-8 | 主界面不展示诊断、已隐藏、暂停、暂隐、隐藏会话、重命名等旧入口 | 自动化测试 |
| AC-9 | 同文件夹多个对话可区分 | 自动化测试或手工注入数据验收 |
| AC-10 | 轮询间隔不超过 5 秒 | 自动化测试 |
| AC-11 | 右键 Pet 展示外观、隐藏 Pet、退出程序 | 自动化测试 + 手工验收 |
| AC-12 | 隐藏 Pet 不停止本地监控程序，可从状态栏/托盘恢复 | 原生 companion 测试 + 手工验收 |
| AC-13 | 退出程序会关闭 Pet 和本地监控服务 | 原生 companion 测试 + 手工验收 |

### 14.2 P1 应满足

| 编号 | 标准 | 验收方式 |
|---|---|---|
| AC-14 | Pet 拖动和位置记忆保留 | 自动化测试 + 手工验收 |
| AC-15 | 聚焦失败时显示轻量失败提示，不展开诊断 | 手工验收 |
| AC-16 | `process_only` 不读取终端内容，但直接 CLI 会话必须可见；Claude CLI 优先使用 Claude 会话状态，其他直接 CLI 可区分活跃与静默 | 自动化测试 + 手工验收 |
| AC-17 | 小窗口和移动窄屏不出现文字重叠 | 手工验收 |
| AC-18 | 待处理 Pet 动作比进行中/空闲更明显 | 手工验收 |

## 15. 测试数据样例

### 15.1 待处理 + 进行中 + 空闲

```json
[
  {
    "session_id": "codex-prd-1",
    "title": "Codex - checkout-flow",
    "tool": "codex",
    "surface": "desktop",
    "status": "needs_action",
    "summary": "这里的内容不能出现在气泡中",
    "monitoring_level": "full"
  },
  {
    "session_id": "codex-prd-2",
    "title": "Codex - checkout-flow",
    "tool": "codex",
    "surface": "desktop",
    "status": "running",
    "summary": "这里的内容不能出现在气泡中",
    "monitoring_level": "full"
  },
  {
    "session_id": "claude-doc-1",
    "title": "Claude Code - docs",
    "tool": "claude_code",
    "surface": "terminal",
    "status": "idle",
    "summary": "这里的内容不能出现在气泡中",
    "monitoring_level": "full"
  }
]
```

期望：

| 项 | 结果 |
|---|---|
| 角标 | 红色 `3` |
| 气泡排序 | 待处理在最上，进行中其次，空闲最后 |
| 同文件夹 Codex | 能区分两个 `checkout-flow` 对话 |
| 隐私 | 不显示任何 `summary` 内容 |

### 15.2 仅进行中

```json
[
  {
    "session_id": "codex-run-1",
    "title": "Codex - pricing-page",
    "tool": "codex",
    "surface": "desktop",
    "status": "running",
    "summary": "这里的内容不能出现在气泡中",
    "monitoring_level": "full"
  }
]
```

期望：角标绿色 `1`，气泡为 `pricing-page · 进行中` 或等价安全短标题。

### 15.3 仅空闲

```json
[
  {
    "session_id": "claude-idle-1",
    "title": "Claude Code - release-checklist",
    "tool": "claude_code",
    "surface": "terminal",
    "status": "idle",
    "summary": "这里的内容不能出现在气泡中",
    "monitoring_level": "full"
  }
]
```

期望：角标蓝色 `1`，Pet 空闲动作。

## 16. 实现顺序

| 步骤 | 内容 | 完成信号 |
|---|---|---|
| 1 | 更新 `tests/test_web_ui.py`，删除旧工具面板断言，新增 Pet / 气泡 / 角标断言 | Web UI 测试先失败 |
| 2 | 改 `src/ai_progress_monitor/web.py` HTML 结构，新增 `petBadge`、`bubbleList`、`session-bubble` | 结构测试通过 |
| 3 | 加状态映射、角标算法、颜色 class | 角标测试通过 |
| 4 | 加气泡 label 生成和同文件夹稳定序号 | 多对话测试通过 |
| 5 | 改点击逻辑：Pet 控制气泡展开，气泡调用 `/api/focus` | 点击相关测试通过 |
| 6 | 增加 Pet 右键菜单，支持外观、隐藏 Pet、退出程序 | 右键菜单测试通过 |
| 7 | 同步 macOS 菜单栏、Windows 托盘的恢复/退出行为 | 原生 companion 测试通过 |
| 8 | 移除主界面旧按钮和 safe action 按钮 | 禁止项测试通过 |
| 9 | 保留拖动、位置记忆、轮询和 host resize | 回归测试通过 |
| 10 | 运行完整测试 | 全部相关测试通过 |

## 17. 完成定义

| 条件 | 必须满足 |
|---|---|
| 体验完成 | 默认只看到原创树懒 Pet 和状态角标 |
| 气泡完成 | 点击 Pet 可展开/收起气泡列表 |
| 跳转完成 | 点击气泡调用 `/api/focus` |
| 直接 CLI 可见 | 直接运行已配置 AI CLI 时显示 process-only 气泡；Claude CLI 优先使用 Claude 会话状态，明确 idle 时保持空闲，回复完成后或同一会话出现新的空闲完成时间后待处理，点击气泡成功回到系统终端或 IDE 内置终端后空闲；其他直接 CLI 活跃显示进行中、静默显示空闲 |
| 桌面存活入口可见 | 已配置 AI 桌面 App 主程序存活但没有具体会话事件时，显示桌面端空闲入口；不得仅因主程序存活显示进行中或待处理 |
| ChatGPT 桌面会话可见 | ChatGPT 桌面端存在运行中对话时，只基于 `~/.codex/sessions` 中明确的桌面 originator 显示对应会话气泡；具体会话优先于通用桌面空闲入口 |
| 启动边界完成 | 打开 App 后才开始监控所有对话进度；App 启动前已有的 AI 桌面、wrapper 历史文件会话不纳入本轮监控；启动前已存在但当前仍存活的 CLI 和桌面 App 要显示为空闲入口或当前状态；App 启动后产生的新事件继续更新 |
| 进程级检测跳转 | process-only 气泡点击时尽量聚焦父 GUI 应用 |
| 角标完成 | 数字等于气泡列表总数，红/绿/蓝颜色优先级正确 |
| 区分完成 | 同文件夹多个对话不会显示成完全相同气泡 |
| 右键完成 | 右键 Pet 可切换外观、隐藏 Pet 或退出程序 |
| 恢复完成 | 隐藏 Pet 后可从 macOS 菜单栏 / Windows 托盘恢复 |
| 隐私完成 | 主界面不展示具体对话内容 |
| 减负完成 | 主界面不展示诊断、隐藏会话、暂停、暂隐、重命名、Yes/No |
| 测试完成 | 自动化测试覆盖 P0 标准，手工验收覆盖主要 UI 场景 |

## 18. 不允许 AI 自行扩展的内容

| 禁止扩展 | 原因 |
|---|---|
| 新增复杂设置页 | 偏离轻量 Pet 目标 |
| 引入第三方动画库 | 增加依赖和发布复杂度 |
| 使用电影角色素材或名称 | 有版权和商用风险 |
| 在气泡中展示完整 summary | 有隐私风险 |
| 继续保留旧大面板作为主入口 | 与本次目标冲突 |
| 自动替用户点击 Yes/No | 本次明确回原窗口处理 |
