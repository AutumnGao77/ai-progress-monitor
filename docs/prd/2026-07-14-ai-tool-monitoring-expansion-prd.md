# 新增 AI 工具监控功能迭代 PRD

## 1. 结论

本文件是“新增 AI 工具监控”功能迭代的 AI coding 目标文档。相比基础 Pet 体验 PRD，本文件更聚焦 **监控范围扩展、状态一致性、气泡展示一致性、点击跳转一致性和可验收测试**。

本次迭代目标：在现有 Codex / Claude Code 监控基础上，新增 **WorkBuddy、Qoder、Qoder CN** 的桌面 App 与相关会话监控能力。新增工具必须复用现有 Pet + 气泡列表体验：能显示软件名、真实对话标题、三态状态、数字角标，并支持点击气泡回到对应 AI 工具窗口。

| 判断项 | 结论 |
|---|---|
| 是否适合 AI 直接执行 | 是，本文件包含实现范围、状态规则、标题规则、跳转规则、测试用例和验收标准 |
| 本次主要改动 | 进程/日志/本地缓存数据源识别，气泡标题和状态统一，macOS 聚焦兜底 |
| 本次主要测试 | `tests/test_sources.py`、`tests/test_service.py`、`tests/test_store.py`、`tests/test_web_ui_behavior.py`、`tests/test_window_focus.py` |
| 新增支持工具 | WorkBuddy、Qoder、Qoder CN |
| 不做 | 不做“用户自定义新增监控工具”、不做自动扫描生成配置、不做设置页、不读取或展示对话正文 |

## 2. 当前问题

| 当前问题 | 为什么影响用户 | 新 PRD 要求 |
|---|---|---|
| 只重点支持 Codex / Claude Code | 用户同时使用 WorkBuddy、Qoder、Qoder CN 时，Pet 无法形成统一任务视图 | 新增工具必须进入同一气泡列表和角标统计 |
| 仅识别 App 进程会显示空闲入口 | 有真实对话运行或等待操作时，用户仍看到“空闲” | 对支持深度监控的工具读取其会话数据源，输出具体对话气泡 |
| Qoder 自动目录名不可读 | `chat-1`、`chat-3` 不能代表真实对话 | 优先读取 Qoder 本地缓存中的真实会话标题 |
| WorkBuddy / Qoder 状态语义不一致 | `needs_action` 一会儿显示进行中，一会儿显示空闲，用户无法信任 Pet | 所有 AI 工具统一三态映射和 view ack 规则 |
| 点击气泡跳转失败 | 用户看到待处理但回不到对应工具窗口 | 新增工具必须具备和现有工具一致的聚焦字段与兜底激活能力 |
| 多产品共存 | Qoder 与 Qoder CN 同时运行时可能串日志、串标题 | 识别 Qoder 与 Qoder CN 产品边界，分别读取对应日志/缓存 |

## 3. 实现范围

| 类型 | 范围 |
|---|---|
| 主要修改文件 | `src/ai_progress_monitor/sources.py`、`src/ai_progress_monitor/window_focus.py` |
| 可能涉及文件 | `src/ai_progress_monitor/service.py`、`src/ai_progress_monitor/web.py`、`src/ai_progress_monitor/terminal_bridge.py` |
| 主要测试文件 | `tests/test_sources.py`、`tests/test_service.py`、`tests/test_store.py`、`tests/test_web_ui_behavior.py`、`tests/test_window_focus.py` |
| 复用后端接口 | `/api/sessions`、`/api/focus`、`/api/session-viewed` |
| 复用前端能力 | Pet 角标、气泡列表、气泡点击聚焦、会话状态排序 |
| 允许新增 | 工具定义配置、日志/SQLite 只读解析、标题兜底规则、聚焦兜底规则、自动化测试 |
| 不新增 | 新 API、设置页、用户自定义扫描流程、外部服务依赖、对话正文展示 |

## 4. AI 执行原则

| 原则 | 要求 |
|---|---|
| 与现有工具一致 | WorkBuddy、Qoder、Qoder CN 的气泡、角标、状态、跳转能力必须和 Codex / Claude Code 保持一致 |
| 先识别具体对话 | 能读取具体会话时，展示具体对话气泡；只有无法识别具体会话时才显示桌面 App 空闲入口 |
| 软件名必须可见 | 气泡中必须能看出是 WorkBuddy、Qoder 还是 Qoder CN |
| 标题优先可读 | 优先使用真实对话标题；不得把 `chat-1`、`chat-3`、UUID、task id 当作最终标题 |
| 状态统一 | 所有工具都映射为待处理、进行中、空闲三态 |
| 待处理不自欺欺人 | 需要用户选择、批准、继续的状态不能因点击气泡或看过而变空闲 |
| 完成可查看清除 | AI 已返回结果、只需用户查看的完成态，可以点击气泡后转为空闲 |
| 不展示隐私内容 | 不在气泡展示 prompt、summary、命令输出、完整回复 |
| 不扩大本次范围 | 用户自定义新增工具、自动扫描进程生成配置留到后续迭代 |

## 5. 用户故事

| 编号 | 用户故事 | 验收结果 |
|---|---|---|
| US-1 | 作为同时使用多个 AI 工具的用户，我想在一个 Pet 中看到所有 AI 工具状态 | WorkBuddy、Qoder、Qoder CN 与 Codex / Claude Code 一起进入气泡列表 |
| US-2 | 作为 Qoder CN 用户，我想看到真实对话标题，而不是 `chat-1` | Qoder CN 气泡显示真实标题，例如“围棋游戏开发” |
| US-3 | 作为 Qoder 用户，我想多个对话都显示出来 | 多个 Qoder 会话分别形成独立气泡，不合并成一个 App 空闲入口 |
| US-4 | 作为 WorkBuddy 用户，我想气泡里能看出软件名称 | WorkBuddy 具体会话气泡显示 `WorkBuddy Desktop - 对话标题` 或等价标签 |
| US-5 | 作为用户，我想 AI 工具请求我选择或批准时，Pet 显示待处理 | `requiresApproval`、`suspended`、`pending` 等用户注意状态显示待处理 |
| US-6 | 作为用户，我不想“待处理”被点击一下就误清空 | 真正等待用户操作的状态 `view_ack_required=false`，点击后仍保持待处理 |
| US-7 | 作为用户，我想 AI 返回结果后点开查看，Pet 可以安静下来 | 完成待查看状态 `view_ack_required=true`，点击聚焦成功后可转为空闲 |
| US-8 | 作为用户，我想点击 Qoder / WorkBuddy 气泡回到工具窗口 | `/api/focus` 成功或原生层兜底激活对应 App |
| US-9 | 作为同时安装 Qoder 和 Qoder CN 的用户，我不想两者互相串状态 | Qoder 与 Qoder CN 分别识别产品、日志目录和显示名称 |

## 6. 工具支持范围

### 6.1 本次新增工具

| 工具 | 产品形态 | 监控级别 | 显示名称 | 备注 |
|---|---|---|---|---|
| WorkBuddy | 桌面 App / 相关 CLI 进程 | App 存活 + 本地会话库深度监控 | `WorkBuddy` | 有具体会话时显示具体气泡；否则显示桌面空闲入口 |
| Qoder | 桌面 App / CLI | App 存活 + 日志 + 本地缓存库深度监控 | `Qoder` | 支持多个任务气泡 |
| Qoder CN | 桌面 App / CLI | App 存活 + 日志 + 本地缓存库深度监控 | `Qoder CN` | 与 Qoder 分开识别，避免串日志 |

### 6.2 既有工具保持不回归

| 工具 | 本次要求 |
|---|---|
| Codex | 桌面会话、CLI 进程、Plan 模式待用户输入状态不回归 |
| Claude Code | CLI 会话状态、待处理查看清除、进程级聚焦不回归 |
| 其他已配置 AI CLI | 继续按进程级保守监控，不因新增工具改坏 |

## 7. 数据输入与识别规则

### 7.1 WorkBuddy 输入

| 数据源 | 用途 | 要求 |
|---|---|---|
| WorkBuddy 桌面 App 进程 | 判断 App 存活，生成空闲入口 | 仅 App 存活时不能显示进行中或待处理 |
| WorkBuddy 本地会话库 | 读取具体会话标题、状态、更新时间、cwd | 只读访问；异常时回退桌面空闲入口 |
| WorkBuddy CLI / sidecar 进程 | 辅助识别产品存在 | daemon、sidecar、serve 类进程不能误判成具体用户会话 |

### 7.2 Qoder / Qoder CN 输入

| 数据源 | 用途 | 要求 |
|---|---|---|
| Qoder / Qoder CN 桌面 App 进程 | 判断 App 存活，生成空闲入口或具体会话聚焦字段 | Qoder 与 Qoder CN 分别识别 |
| `quest.log` / `agent.log` | 读取任务状态、task id、cwd、用户注意信号 | 支持 `task.status.update`、ACP 状态机、payload 状态 |
| Qoder project session JSON | 读取历史可用标题和 cwd | 作为标题辅助来源 |
| Qoder 本地缓存库 `local.db` | 读取当前任务真实会话标题 | 优先用于替换 `chat-1`、`chat-3` 目录名 |

### 7.3 产品分流规则

| 场景 | 要求 |
|---|---|
| Qoder CN App 进程 | 只读取 Qoder CN 日志和缓存 |
| Qoder App 进程 | 只读取 Qoder 日志和缓存 |
| 两者同时运行 | 两者各自产生气泡，不互相覆盖 |
| 识别不到具体产品 | 可回退所有 Qoder 日志目录，但不得错误合并显示名称 |

## 8. 状态映射

### 8.1 统一三态

| 原始状态族 | 用户状态 | 角标颜色 | 是否可查看清除 |
|---|---|---|---|
| `running`、`working`、`thinking`、`processing`、`planning`、`prompting`、`streaming` | 进行中 | 绿色 | 否 |
| `completed`、`success`、`failed`、`error`，且代表 AI 已返回结果等待用户查看 | 待处理 | 红色 | 是 |
| `requiresApproval`、`suspended`、`pending`、`waitingForInput`、`needsUserInput` 等需要用户继续操作 | 待处理 | 红色 | 否 |
| `idle`、`ready`、`stopped`、`cancelled` | 空闲 | 蓝色 | 否 |
| 无具体会话，仅桌面 App 存活 | 空闲 | 蓝色 | 否 |

### 8.2 view ack 规则

| 类型 | `view_ack_required` | 点击气泡后的状态 |
|---|---|---|
| 完成待查看 | `true` | 聚焦成功后可转为空闲 |
| 需要用户选择/批准/输入/继续 | `false` | 聚焦成功后仍保持待处理，直到工具状态真实变化 |
| 进行中 | `false` | 保持进行中 |
| 空闲入口 | `false` | 保持空闲 |

### 8.3 禁止状态误判

| 禁止行为 | 正确行为 |
|---|---|
| `suspended` 显示进行中 | 显示待处理 |
| `requiresApproval=true` 显示进行中 | 显示待处理 |
| WorkBuddy `pending` 有真实活动时显示进行中或空闲 | 显示待处理 |
| 用户点击等待操作气泡后转为空闲 | 仍显示待处理 |
| AI 完成返回后永久红色不清除 | 用户点击查看后可转为空闲 |

## 9. 气泡标题规则

### 9.1 标准结构

```text
工具名 Desktop - 对话标题 · 状态
```

前端气泡可压缩显示为：

```text
工具名 · 对话标题 · 状态
```

### 9.2 Qoder / Qoder CN 标题优先级

| 优先级 | 来源 | 示例 |
|---|---|---|
| 1 | Qoder 本地缓存库 `chat_session.session_title` | `围棋游戏开发`、`查询上海天气` |
| 2 | project session JSON 的 `title` / `conversationTitle` | `深度分析AI代码助手动向` |
| 3 | 日志 payload 中的安全标题字段 | `问候功能` |
| 4 | cwd 文件夹名 | `chat-1`，只允许作为最后兜底 |
| 5 | task id | 只允许开发兜底，不应作为用户主展示 |

### 9.3 WorkBuddy 标题优先级

| 优先级 | 来源 | 示例 |
|---|---|---|
| 1 | 用户自定义标题 | `需求复盘` |
| 2 | 会话标题 | `Start new chat session` |
| 3 | cwd 文件夹名 | `product-ops` |
| 4 | session id | 只允许兜底 |

### 9.4 标题禁止项

| 禁止展示为最终标题 | 原因 |
|---|---|
| `chat-1`、`chat-2`、`chat-3` | 自动生成目录，不代表用户意图 |
| UUID / task id | 用户不可读 |
| `.session.execution` | 技术细节 |
| 空标题、`新会话`、`new chat` | 信息不足，需要继续找更好标题 |

说明：当确实没有任何真实标题时，可以临时显示工具名桌面空闲入口；不要伪装成具体对话标题。

## 10. 多会话与排序规则

| 规则 | 要求 |
|---|---|
| 多个 Qoder 任务 | 每个 task id 生成独立气泡 |
| 多个 WorkBuddy 会话 | 每个会话 id 生成独立气泡 |
| 同一工具多个对话 | 不合并成一个 `Qoder Desktop` 或 `WorkBuddy Desktop` |
| 具体会话优先 | 有具体会话时，隐藏同工具通用桌面空闲入口，避免重复计数 |
| 排序优先级 | 待处理 > 进行中 > 空闲；同状态按后端稳定顺序或更新时间 |
| 数字角标 | 统计当前可见气泡总数 |

## 11. 点击跳转与聚焦规则

### 11.1 后端 payload 要求

| 字段 | 要求 |
|---|---|
| `session_id` | 气泡点击 `/api/focus` 的唯一参数 |
| `process_id` | 记录对应桌面 App 或具体进程 |
| `focus_process_id` | 优先传入可被原生层激活的 GUI App 进程 |
| `focus_app_name` | WorkBuddy 显示 `WorkBuddy`；Qoder 显示 `Qoder`；Qoder CN 显示 `Qoder CN` |
| `cwd` | 可传，但 AI 桌面 App 聚焦失败时不得把 cwd 当作要打开的项目目录 |

### 11.2 macOS 聚焦兜底

| 场景 | 行为 |
|---|---|
| 能匹配具体窗口 | Raise 对应窗口 |
| 有 `focus_process_id` | 尝试激活对应进程 |
| AI 桌面 App 有 `focus_app_name` 但窗口标题匹配失败 | `open -a <AppName>` 激活 App |
| 项目编辑器有 cwd 但匹配失败 | 不自动激活所有窗口，避免跳到错误项目 |
| Qoder / WorkBuddy 有 cwd 但匹配失败 | 激活 App，而不是打开 cwd |

### 11.3 跳转失败处理

| 场景 | 用户表现 |
|---|---|
| 聚焦成功 | 可保持气泡展开；完成待查看会话可标记已查看 |
| 聚焦失败 | 显示轻量失败提示，不展开诊断面板 |
| 原生辅助权限不足 | 尝试 App 级激活兜底 |
| App 已退出 | 气泡在下一次轮询后消失或回退为空闲入口 |

## 12. 启动边界与历史处理

| 场景 | 要求 |
|---|---|
| App 启动前已有历史完成会话 | 不回捞为待处理 |
| App 启动前已有且仍存活的 AI 桌面 App | 可显示空闲入口 |
| App 启动后产生的 Qoder / WorkBuddy 会话 | 纳入监控 |
| App 启动后出现用户注意状态 | 必须显示待处理，不能自动消失 |
| 已查看的完成态桌面对话 | 可转为空闲，并按现有可见时间规则收口 |

## 13. 自动化测试用例

### 13.1 Source 监控测试

建议更新 `tests/test_sources.py`。

| 测试名建议 | 断言 |
|---|---|
| `test_workbuddy_desktop_process_creates_idle_entry` | WorkBuddy App 存活但无具体会话时显示空闲入口 |
| `test_workbuddy_db_completed_session_creates_needs_action_conversation` | WorkBuddy 完成会话显示待处理且可查看清除 |
| `test_workbuddy_db_pending_user_attention_is_not_view_ack` | WorkBuddy pending / requires approval 等用户注意状态 `view_ack_required=false` |
| `test_workbuddy_bubble_title_includes_tool_name` | WorkBuddy 具体会话标题包含软件名 |
| `test_qoder_desktop_process_uses_recent_task_status_log` | Qoder 日志 running 显示进行中 |
| `test_qoder_completed_task_log_creates_needs_action_conversation` | Qoder completed 显示待处理且可查看清除 |
| `test_qoder_user_attention_state_is_not_cleared_by_view_ack` | Qoder suspended / requiresApproval `view_ack_required=false` |
| `test_qoder_uses_local_cache_session_title_instead_of_generated_chat_folder` | Qoder 标题优先读取本地缓存库真实标题 |
| `test_qoder_multiple_task_logs_create_separate_conversation_updates` | 多个 Qoder task 生成多个气泡 |
| `test_qoder_cn_desktop_ignores_regular_qoder_logs` | Qoder CN 不读取普通 Qoder 日志 |
| `test_regular_qoder_desktop_ignores_qoder_cn_logs` | 普通 Qoder 不读取 Qoder CN 日志 |

### 13.2 Store / Service 测试

| 测试文件 | 断言 |
|---|---|
| `tests/test_store.py` | `view_ack_required=false` 的待处理会话点击查看后仍保持待处理 |
| `tests/test_service.py` | WorkBuddy / Qoder full process session payload 包含 `tool_display_name`、`focus_app_name`、`focus_process_id` |
| `tests/test_service.py` | 聚焦成功只清除可查看完成态，不清除真实等待操作态 |

### 13.3 Web UI 行为测试

| 测试文件 | 断言 |
|---|---|
| `tests/test_web_ui_behavior.py` | Qoder / WorkBuddy 气泡 label 包含工具名和状态 |
| `tests/test_web_ui_behavior.py` | 无真实标题时不展示 UUID / task id 作为主标题 |
| `tests/test_web_ui_behavior.py` | 多个 Qoder 对话不合并成一个 `Qoder Desktop` |

### 13.4 聚焦测试

| 测试文件 | 断言 |
|---|---|
| `tests/test_window_focus.py` | Qoder CN 有 cwd 时，聚焦失败兜底为 `open -a "Qoder CN"` |
| `tests/test_window_focus.py` | WorkBuddy 有 cwd 时，聚焦失败兜底为激活 WorkBuddy App |
| `tests/test_window_focus.py` | 项目编辑器仍不因 cwd 匹配失败而激活所有窗口 |

### 13.5 推荐测试命令

```bash
PYTHONPATH=src python3 -m unittest tests.test_sources
PYTHONPATH=src python3 -m unittest tests.test_service tests.test_store
PYTHONPATH=src python3 -m unittest tests.test_web_ui_behavior tests.test_window_focus
PYTHONPATH=src python3 -m unittest discover -s tests
python3 scripts/validate_release.py
```

## 14. 手工验收场景

| 编号 | 场景 | 操作 | 期望 |
|---|---|---|---|
| M-1 | WorkBuddy 仅 App 存活 | 打开 WorkBuddy，不开始对话 | 气泡显示 `WorkBuddy Desktop · 空闲` 或等价空闲入口 |
| M-2 | WorkBuddy 有运行中任务 | 发起一个 WorkBuddy 任务 | 气泡显示 WorkBuddy 软件名、对话标题、进行中 |
| M-3 | WorkBuddy 等待用户操作 | 触发 pending / approval / input 类状态 | 气泡显示待处理；点击后仍保持待处理 |
| M-4 | WorkBuddy 完成返回 | 让 WorkBuddy 生成结果 | 气泡显示待处理；点击回到 WorkBuddy 后可转为空闲 |
| M-5 | Qoder 仅 App 存活 | 打开 Qoder，不开始任务 | 气泡显示 Qoder 桌面空闲入口 |
| M-6 | Qoder CN 运行任务 | 在 Qoder CN 发起任务 | 气泡显示 `Qoder CN`、真实标题、进行中 |
| M-7 | Qoder CN 等待选择 | 触发需要用户选择/批准的状态 | 气泡显示待处理；点击后仍保持待处理 |
| M-8 | Qoder CN 完成返回 | 让 Qoder CN 返回结果 | 气泡显示待处理；点击查看后可转为空闲 |
| M-9 | Qoder 标题可读性 | 新建 Qoder 对话，其目录为 `chat-1` | 气泡显示真实标题，不显示 `chat-1` 作为主标题 |
| M-10 | 多个 Qoder 对话 | 同时存在两个 Qoder / Qoder CN task | 气泡列表显示多个具体对话，不只显示一个 App 空闲入口 |
| M-11 | Qoder 与 Qoder CN 共存 | 同时打开 Qoder 和 Qoder CN | 两者显示名称正确，状态不串 |
| M-12 | 气泡跳转 | 点击 Qoder CN 气泡 | 能激活 Qoder CN App；不再提示无法定位窗口 |
| M-13 | 角标统计 | WorkBuddy、Qoder、Codex 同时有气泡 | 角标数字等于全部可见气泡数，颜色按最高优先级 |
| M-14 | 隐私检查 | 对话包含 prompt / summary / 命令输出 | 气泡不展示这些内容 |
| M-15 | 旧工具回归 | Codex Plan 模式等待用户输入 | 仍显示待处理，不误显示进行中 |
| M-16 | Claude Code 回归 | Claude Code 运行、完成、点击查看 | 状态与原逻辑一致 |

### 14.1 手工验收结果

| 验收日期 | 验收范围 | 结论 | 备注 |
|---|---|---|---|
| 2026-07-14 | M-1 至 M-16 全部手工验收场景 | 通过 | 已完成手工测试，目前未发现问题 |

## 15. 验收标准

### 15.1 P0 必须满足

| 编号 | 标准 | 验收方式 |
|---|---|---|
| AC-1 | WorkBuddy、Qoder、Qoder CN 进入已配置 AI 工具监控范围 | 自动化测试 + 手工验收 |
| AC-2 | 新增工具 App 存活但无具体会话时显示空闲入口 | 自动化测试 |
| AC-3 | 新增工具有具体会话时显示具体会话气泡 | 自动化测试 + 手工验收 |
| AC-4 | Qoder / Qoder CN 标题优先显示真实对话标题，不显示 `chat-1/chat-3` | 自动化测试 + 手工验收 |
| AC-5 | Qoder / Qoder CN 多任务分别显示，不合并为一个气泡 | 自动化测试 |
| AC-6 | WorkBuddy 具体会话气泡必须显示软件名 | 自动化测试 + 手工验收 |
| AC-7 | `requiresApproval`、`suspended`、`pending` 等用户注意状态显示待处理 | 自动化测试 |
| AC-8 | 真正等待用户操作的待处理不会因点击查看变空闲 | 自动化测试 + 手工验收 |
| AC-9 | 完成待查看状态点击聚焦成功后可转为空闲 | 自动化测试 |
| AC-10 | Qoder 与 Qoder CN 同时存在时不串日志、不串标题、不串显示名称 | 自动化测试 + 手工验收 |
| AC-11 | Qoder / WorkBuddy 气泡点击可聚焦或激活对应 App | 自动化测试 + 手工验收 |
| AC-12 | 不展示 prompt、summary、命令输出、完整回复 | 自动化测试 + 手工验收 |
| AC-13 | Codex / Claude Code 既有监控能力不回归 | 回归测试 |

### 15.2 P1 应满足

| 编号 | 标准 | 验收方式 |
|---|---|---|
| AC-14 | Qoder 日志异常或缓存库读取失败时，回退桌面空闲入口，不崩溃 | 自动化测试 |
| AC-15 | WorkBuddy 数据库异常时，回退桌面空闲入口，不崩溃 | 自动化测试 |
| AC-16 | Qoder / WorkBuddy 聚焦失败时给出轻量失败提示，不展开诊断面板 | 手工验收 |
| AC-17 | 新增工具脚本和发布校验包含对应监控入口 | 发布校验 |

## 16. 测试数据样例

### 16.1 Qoder CN 真实标题

```json
{
  "session_id": "qoder-task-alpha",
  "title": "Qoder CN Desktop - 围棋游戏开发",
  "tool": "unknown",
  "tool_display_name": "Qoder CN",
  "surface": "desktop",
  "status": "running",
  "monitoring_level": "full",
  "status_source": "qoder-log",
  "generated_conversation_path": true
}
```

期望：

| 项 | 结果 |
|---|---|
| 气泡标题 | 显示 `Qoder CN · 围棋游戏开发 · 进行中` 或等价结构 |
| 禁止展示 | 不显示 `chat-1`、task id、`.session.execution` |
| 角标 | 纳入总数，颜色按进行中参与计算 |

### 16.2 Qoder CN 等待用户操作

```json
{
  "session_id": "qoder-task-alpha",
  "title": "Qoder CN Desktop - 围棋游戏开发",
  "tool_display_name": "Qoder CN",
  "surface": "desktop",
  "status": "needs_action",
  "view_ack_required": false,
  "status_source": "qoder-log"
}
```

期望：显示红色待处理；点击气泡聚焦成功后仍保持待处理，直到 Qoder CN 状态真实变化。

### 16.3 WorkBuddy 完成待查看

```json
{
  "session_id": "workbuddy-wb-done",
  "title": "WorkBuddy Desktop - 需求复盘",
  "tool_display_name": "WorkBuddy",
  "surface": "desktop",
  "status": "needs_action",
  "view_ack_required": true,
  "status_source": "workbuddy-db"
}
```

期望：显示红色待处理；点击气泡成功回到 WorkBuddy 后可转为空闲。

## 17. 实现顺序

| 步骤 | 内容 | 完成信号 |
|---|---|---|
| 1 | 在工具定义中补充 WorkBuddy、Qoder、Qoder CN 的进程识别配置 | 进程识别测试先失败后通过 |
| 2 | 接入 WorkBuddy 本地会话库只读解析 | WorkBuddy 具体会话测试通过 |
| 3 | 接入 Qoder / Qoder CN 日志解析 | Qoder running / completed / suspended 测试通过 |
| 4 | 接入 Qoder 本地缓存库标题读取 | `chat-1/chat-3` 标题回归测试通过 |
| 5 | 统一用户注意状态与完成待查看状态的 `view_ack_required` | Store / Source / Service 测试通过 |
| 6 | 支持 Qoder 多任务输出多个气泡 | 多 task 测试通过 |
| 7 | 补充 Qoder 与 Qoder CN 产品分流 | 双产品不串日志测试通过 |
| 8 | 修正新增 AI 桌面 App 聚焦兜底 | `tests/test_window_focus.py` 通过 |
| 9 | 回归 Web 气泡 label 和角标行为 | `tests/test_web_ui_behavior.py` 通过 |
| 10 | 运行全量测试和发布校验 | `unittest discover` 与 `validate_release.py` 通过 |

## 18. 完成定义

| 条件 | 必须满足 |
|---|---|
| 新工具可见 | WorkBuddy、Qoder、Qoder CN 均能显示在 Pet 气泡列表中 |
| 具体会话可见 | 有具体会话时不只显示 App 空闲入口 |
| 标题可读 | Qoder / Qoder CN 优先显示真实标题，不显示 `chat-1/chat-3` |
| 多会话正确 | 多个 Qoder / Qoder CN 任务分别显示 |
| 状态统一 | 所有工具统一为待处理、进行中、空闲三态 |
| 待处理可信 | 用户注意状态不会被点击气泡误清为空闲 |
| 完成可收口 | 完成待查看状态可在聚焦成功后转为空闲 |
| 软件名清晰 | WorkBuddy / Qoder / Qoder CN 气泡可识别来源工具 |
| 跳转可用 | 点击新增工具气泡能聚焦具体窗口或至少激活对应 App |
| 产品分流正确 | Qoder 与 Qoder CN 不串日志、不串标题 |
| 隐私完成 | 不展示 prompt、summary、命令输出、完整回复 |
| 回归完成 | Codex / Claude Code 现有监控不回归 |
| 测试完成 | 相关自动化测试、全量测试、发布校验通过 |

### 18.1 完成检查结果

| 检查日期 | 检查项 | 结果 |
|---|---|---|
| 2026-07-14 | 第 14 章 M-1 至 M-16 手工验收场景 | 通过，当前未发现问题 |
| 2026-07-14 | PRD 第 15 章 P0 / P1 验收标准逐项对账 | 通过，均有代码实现、自动化测试或手工验收记录覆盖 |
| 2026-07-14 | Qoder / Qoder CN 生成目录名兜底复查 | 已修复，缺少真实标题时显示泛化 `Qoder 对话 #n`，不展示 `chat-1/chat-2` 或 task id |
| 2026-07-14 | `PYTHONPATH=src python3 -m unittest discover -s tests` | 通过，399 个测试 OK |
| 2026-07-14 | `python3 scripts/validate_release.py` | 通过，输出 `release-validation-ok` |
| 2026-07-14 | macOS Floating Dev 开发版启动检查 | 通过，开发版已重新构建并启动，有实时会话快照 |

## 19. 不允许 AI 自行扩展的内容

| 禁止扩展 | 原因 |
|---|---|
| 做“新增监控功能/自动扫描进程后添加配置” | 已明确留到下次迭代 |
| 做设置页或工具管理页 | 本次只新增 WorkBuddy、Qoder、Qoder CN |
| 引入远程服务或联网查询工具配置 | 桌面监控应基于本地进程、日志和缓存 |
| 展示对话正文、prompt、summary | 隐私风险 |
| 把 Qoder `chat-1/chat-3` 当作可接受标题 | 用户不可读 |
| 只改 Web 气泡，不改 App 监控源 | 产品目标是桌面 App |
| 新增工具只显示空闲入口 | 有深度数据源时必须显示具体会话状态 |
| 为了让测试通过而把待处理统一清为空闲 | 会破坏用户对状态的信任 |
