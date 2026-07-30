# Pet 系统通知开关功能迭代 PRD

> 状态：通知偏好、发送边界、API 和“系统通知 > / 开启 / 关闭”二级菜单已完成开发、自动化、Browser 与 macOS Dev App 验收，并随 PR #5 于 2026-07-29 合并到 `main`（`770d447`）；CI 并发测试抖动随后由 PR #6 单独修复并合并（`ed468b8`）。该能力不属于已发布的 v0.2.1，现进入 v0.3.0 发布候选流程。

## 1. 结论

本次迭代为 Pet 增加“系统通知”用户开关：用户可在 macOS App 与共享 Web Pet 的右键菜单中关闭或开启原生系统通知。关闭后，状态识别、Pet 三态、角标、气泡列表和点击回到现场继续正常工作，只是不再弹出系统通知窗口，避免在状态变化频繁时持续打扰用户。

| 项目 | 结论 |
|---|---|
| 本次目标 | 支持用户关闭系统通知弹窗 |
| 默认策略 | 默认开启通知，延续现有提醒能力 |
| 用户入口 | 右键 Pet 菜单新增“系统通知 > / 开启 / 关闭”二级菜单 |
| 保存策略 | 写入本地偏好文件，重启 App 后保持上次选择 |
| 平台范围 | Mac + Web；Windows 原生预览壳维持当前默认禁用通知，不在本次改造范围 |
| 影响范围 | 只影响原生系统通知，不影响 Pet 视觉状态、角标、气泡、会话识别和跳转 |
| 实现原则 | 先加测试，再改偏好、通知管理、API、前端菜单和文档 |
| 非目标 | 不改状态算法、不改 macOS 通知中心样式、不做通知声音/免打扰时段/按会话细分通知 |

## 2. 背景与问题

当前产品已经具备原生通知能力：会话进入“需要处理”、从“进行中”转为空闲、从“进行中”转为疑似卡住时，系统可能弹出通知。该能力能降低用户错过处理点的风险，但在多会话、高频状态变化或用户专注写作时，macOS 通知中心弹窗会造成持续干扰。

| 当前问题 | 用户影响 | 迭代方向 |
|---|---|---|
| 系统通知弹窗不可在 Pet 内关闭 | 用户只能忍受弹窗或退出程序 | 提供 Pet 内可见开关 |
| 状态变化可能连续触发通知 | 用户被多次打断 | 关闭后只保留 Pet 轻量状态提示 |
| 启动参数 `--no-notifications` 不适合普通用户 | 用户需要懂命令行且每次启动都要配置 | 改为菜单内可操作偏好 |
| 关闭通知可能被误解为暂停监控 | 用户担心错过状态 | 明确只关闭弹窗，不关闭监控 |

## 3. 用户故事

| 编号 | 用户故事 | 验收标准 |
|---|---|---|
| US-1 | 作为用户，我希望能关闭系统通知弹窗 | 右键 Pet 后可看到“系统通知”开关，并能切到关闭 |
| US-2 | 作为用户，我关闭通知后仍想看到 Pet 状态 | 关闭通知后，Pet 三态、角标和气泡列表仍正常更新 |
| US-3 | 作为用户，我希望选择能被记住 | 重启 App 后保持上次通知开关状态 |
| US-4 | 作为用户，我希望能随时恢复通知 | 右键 Pet 后可重新开启“系统通知” |
| US-5 | 作为用户，我希望知道当前通知是否开启 | 菜单项能明确展示当前开关状态 |

## 4. 方案对比

| 方案 | 做法 | 优点 | 缺点 | 结论 |
|---|---|---|---|---|
| 推荐方案：Pet 菜单开关 | 右键 Pet 菜单新增“系统通知”开关，偏好持久化 | 用户入口自然，且不会与 Pet 角标、气泡等应用内提示混淆 | 菜单会多一个选项 | 采用 |
| 仅保留启动参数 | 继续使用 `--no-notifications` | 实现成本最低 | 普通用户难发现、难长期使用 | 不满足诉求 |
| 跟随系统免打扰 | 引导用户去系统设置关闭通知 | 不需要改 App | 颗粒度粗，会影响其他通知，无法在 Pet 内恢复 | 不采用 |

## 5. 交互要求

右键 Pet 菜单建议更新为：

```text
外观  >
系统通知  >
隐藏 Pet
退出程序
```

点击“系统通知”后展开二级菜单。通知开启时：

```text
✓ 开启
关闭
```

通知关闭时：

```text
开启
✓ 关闭
```

| 场景 | 期望 |
|---|---|
| 右键 Pet | 主菜单展示“外观 > / 系统通知 > / 隐藏 Pet / 退出程序” |
| 点击或悬停“系统通知” | 展开“开启 / 关闭”二级菜单，不直接修改当前设置 |
| 通知开启 | “开启”前侧显示 `✓`，“关闭”前侧保留等宽空白占位 |
| 通知关闭 | “关闭”前侧显示 `✓`，“开启”前侧保留等宽空白占位 |
| 点击“开启” | 立即开启系统通知并保存偏好；已开启时保持当前状态，不重复写入 |
| 点击“关闭” | 立即关闭系统通知并保存偏好；已关闭时保持当前状态，不重复写入 |
| 选项关系 | “开启”和“关闭”为互斥单选项，任一时刻只能有一个选项显示 `✓` |
| 视觉一致性 | 复用“外观”二级菜单的前置勾选列、文字起始位置、行高、内边距、悬停态和禁用态，不新增另一套单选样式 |
| 保存成功 | 菜单勾选状态与实际偏好一致 |
| 保存失败 | 回滚到已确认状态，并显示轻提示“系统通知设置保存失败” |
| 重新开启 | 不补发关闭期间已经发生的待处理、完成或疑似卡住通知；只响应后续新变化 |
| 通知关闭时进入待处理 | 不弹系统通知；Pet 待处理状态、红色角标和气泡仍更新 |
| 通知关闭时任务完成或疑似卡住 | 不弹系统通知；Pet 视觉状态仍按现有规则更新 |
| 使用 `--no-notifications` 启动 | 二级菜单显示“✓ 关闭”；“开启”和“关闭”均置灰，不允许改写持久化偏好 |

## 6. 通知开关定义

| 字段值 | 用户含义 | 系统行为 |
|---|---|---|
| `true` | 系统通知开启 | 允许发送原生系统通知 |
| `false` | 系统通知关闭 | `NotificationManager` 不发送原生系统通知，但继续记录状态基线 |
| 缺失 | 默认开启 | 兼容旧版本用户 |
| 非布尔值 | 默认开启 | 避免异常配置导致用户错过提醒 |

## 7. 偏好配置

偏好文件新增字段：

```json
{
  "notifications_enabled": false
}
```

| 字段 | 要求 |
|---|---|
| `notifications_enabled` | 控制原生系统通知是否发送 |
| `pet_appearance` | 写入通知偏好时不得丢失 |
| `hidden_sessions` | 写入通知偏好时不得丢失 |
| `session_aliases` | 写入通知偏好时不得丢失 |
| `pet_assets.*` | 写入通知偏好时不得丢失 |

兼容规则：

| 场景 | 行为 |
|---|---|
| 用户首次安装 | 默认 `notifications_enabled=true` |
| 老用户升级 | 偏好缺失时默认开启，保持原体验 |
| 用户通过 `--no-notifications` 启动 | 本次运行不发通知；“系统通知 >”仍可展示实际状态，二级菜单显示“✓ 关闭”且两个选项均置灰，偏好文件不被改写 |
| 用户在菜单中关闭通知 | 写入偏好并立即影响本次运行 |
| 用户在菜单中重新开启通知 | 写入偏好并恢复后续通知，不补发关闭期间的旧状态 |

优先级规则：

| 优先级 | 来源 | 行为 |
|---|---|---|
| 1 | `--no-notifications` 启动参数 | 最高优先级；本次进程强制不发系统通知 |
| 2 | `notifications_enabled` 偏好 | 未使用启动参数时生效 |
| 3 | 默认值 | 偏好缺失或非法时默认开启 |

AI coding 约束：

| 约束 | 要求 |
|---|---|
| 不要改状态判断 | 不修改 `SessionStatus`、会话来源识别和状态映射 |
| 不要改通知文案策略 | 通知标题和消息内容沿用现有逻辑，只增加是否允许发送的开关 |
| 不要吞掉 Pet 更新 | 关闭通知只能阻止 `sender(...)`，不能阻止 `sessions_payload()`、轮询、渲染和聚焦 |
| 不要破坏现有外观偏好 | 新增字段必须和 `pet_appearance` 共存 |
| 不要依赖系统设置 | 不要求用户去 macOS 系统设置里关闭通知 |

## 8. 本地 API

建议复用现有偏好 API 体系，在 token 保护下新增通知偏好读写。

| 方法 | 路由 | 作用 |
|---|---|---|
| `GET` | `/api/preferences` | 返回当前 Pet 外观和通知开关 |
| `POST` | `/api/preferences/notifications` | 保存通知开关 |

API 速记：`GET /api/preferences`、`POST /api/preferences/notifications`。

`GET /api/preferences` 响应示例：

```json
{
  "pet_appearance": "default",
  "notifications_enabled": true,
  "notifications_locked": false
}
```

`POST /api/preferences/notifications` 请求示例：

```json
{
  "enabled": false
}
```

成功响应：

```json
{
  "ok": true,
  "notifications_enabled": false,
  "notifications_locked": false
}
```

错误规则：

| 场景 | 响应 |
|---|---|
| 无 token | `403` |
| `enabled` 不是布尔值 | `400` 和 `invalid_notifications_enabled` |
| `--no-notifications` 锁定本次运行 | `409` 和 `notifications_forced_disabled` |
| 写入失败 | `500` 和 `preferences_write_failed` |

## 9. 实现映射

| PRD 要求 | 软件变动 | 自动化证据 |
|---|---|---|
| 通知偏好读写 | `src/ai_progress_monitor/preferences.py` 新增 `notifications_enabled()`、`set_notifications_enabled()` | `tests/test_preferences.py` |
| 服务运行时同步 | `MonitorService` 或启动流程将偏好状态传给 `NotificationManager.enabled` | `tests/test_service.py` |
| 偏好 API | `src/ai_progress_monitor/web.py` 扩展 `/api/preferences`，新增 `/api/preferences/notifications` | `tests/test_web_launch.py` |
| 右键菜单开关 | `src/ai_progress_monitor/web.py` HTML/CSS/JS 新增“系统通知 >”二级菜单、“开启 / 关闭”互斥勾选态和锁定态 | `tests/test_web_ui.py`、`tests/test_web_ui_behavior.py` |
| 保存失败回滚 | 前端保存失败后恢复已确认通知状态并显示轻提示 | `tests/test_web_ui_behavior.py` |
| 通知关闭不弹窗 | `NotificationManager.notify_for_sessions()` 关闭时不调用 sender，但继续记录状态并抑制旧状态补发 | `tests/test_notifier.py`、`tests/test_service.py` |
| 命令行参数兼容 | `--no-notifications` 继续可用，且不破坏偏好读取 | `tests/test_web_launch.py` |
| 发布验收 | 发布清单增加通知开关验收项 | `docs/release-checklist.md`、`tests/test_docs_prd_alignment.py` |

## 10. AI Coding 实施顺序

建议按以下顺序实现，避免前后端状态不一致。

| 顺序 | 文件 | 任务 | 完成标准 |
|---|---|---|---|
| 1 | `tests/test_preferences.py` | 先补通知偏好默认值、读写、非法值、保留已有字段的测试 | 测试先失败，失败原因指向缺少通知偏好能力 |
| 2 | `src/ai_progress_monitor/preferences.py` | 增加 `notifications_enabled()`、`set_notifications_enabled()` 和布尔校验 | 偏好测试通过 |
| 3 | `tests/test_notifier.py` | 补关闭后不发送 needs_action、completed、stuck 通知的测试 | 测试覆盖三类现有通知 |
| 4 | `src/ai_progress_monitor/notifier.py` | 保持 `enabled` 作为唯一发送闸门 | 关闭时不调用 `sender` |
| 5 | `tests/test_service.py` | 补服务刷新时会按偏好同步通知开关的测试 | 菜单修改后无需重启即可生效 |
| 6 | `src/ai_progress_monitor/service.py` | 提供读取和更新通知偏好的服务方法，并同步 `notifier.enabled` | API 保存后本轮运行立即生效 |
| 7 | `tests/test_web_launch.py` | 补 `GET /api/preferences` 返回通知字段、`POST /api/preferences/notifications` 成功和失败测试 | API 契约固定 |
| 8 | `src/ai_progress_monitor/web.py` | 扩展偏好 API、注入前端初始状态、新增菜单项与保存逻辑 | 浏览器端能切换、回滚和提示 |
| 9 | `tests/test_web_ui.py`、`tests/test_web_ui_behavior.py` | 补菜单文案、勾选态、保存请求、失败回滚、窗口尺寸测试 | UI 行为可自动回归 |
| 10 | `docs/release-checklist.md`、QA 文档、README | 同步用户说明和发布验收项 | 文档与实现不漂移 |

## 11. 关键代码契约

| 模块 | 契约 |
|---|---|
| `MonitorPreferences.notifications_enabled()` | 返回布尔值；缺失、非法类型、JSON 损坏时返回 `True` |
| `MonitorPreferences.set_notifications_enabled(enabled)` | 只接受布尔值；写入时保留所有未知字段和已有偏好 |
| `NotificationManager.enabled` | 所有原生通知发送前必须检查；为 `False` 时不能调用 `sender` |
| `MonitorService` | 保存通知偏好后立即同步当前 `NotificationManager.enabled` |
| `GET /api/preferences` | 返回 `pet_appearance`、实际 `notifications_enabled` 和 `notifications_locked` |
| `POST /api/preferences/notifications` | 请求体只接受 `{"enabled": true/false}` |
| 前端菜单 | 主菜单固定显示“系统通知 >”；二级菜单固定显示“开启 / 关闭”，当前生效项前侧显示 `✓`，布局与“外观”二级菜单一致 |
| 失败提示 | API 保存失败时显示“系统通知设置保存失败”，并回滚到已确认状态 |

前端建议状态变量：

| 变量 | 用途 |
|---|---|
| `window.NOTIFICATIONS_ENABLED` | 当前乐观显示状态 |
| `confirmedNotificationsEnabled` | 最近一次服务端确认状态 |
| `queuedNotificationsEnabled` | 保存期间记录用户最后一次选择 |
| `notificationsSaveInFlight` | 保证通知偏好请求串行发送，避免旧请求最后落盘 |

连续点击规则：

| 场景 | 行为 |
|---|---|
| 用户快速关闭再开启 | UI 可乐观切换，请求串行发送，最终落盘状态等于最后一次选择 |
| 旧请求返回 | 先更新已确认状态，再继续保存队列中的最新选择，不覆盖当前乐观 UI |
| 最新请求失败 | 回滚到 `confirmedNotificationsEnabled` |

## 12. 验收矩阵

| 验收项 | 通过标准 |
|---|---|
| 菜单入口 | 右键 Pet 可看到“系统通知 >”，点击或悬停后出现“开启 / 关闭”二级菜单 |
| 当前状态 | 通知开启时显示“✓ 开启”；通知关闭时显示“✓ 关闭”；两个选项不得同时勾选，未选项保留等宽勾选占位 |
| 关闭通知 | 点击二级菜单“关闭”后系统通知不再弹出 |
| 开启通知 | 点击二级菜单“开启”后系统通知恢复 |
| 重启保存 | 重启 App 后保持上次通知设置 |
| 同值选择 | 选择当前已经生效的“开启”或“关闭”时返回成功，但不重复写入偏好文件 |
| Pet 状态 | 关闭通知不影响空闲、进行中、待处理三态 |
| 角标气泡 | 关闭通知不影响红色角标、气泡列表和排序 |
| 点击跳转 | 关闭通知不影响点击气泡回到对应窗口 |
| 多会话待处理 | 通知关闭时多个会话待处理也不弹汇总通知 |
| 保存失败 | 菜单状态回滚，并出现“系统通知设置保存失败” |
| 命令行兼容 | `--no-notifications` 仍能关闭本次运行通知，二级菜单显示“✓ 关闭”，两个选项均置灰 |
| 历史状态 | 重新开启后不补发关闭期间的旧通知；新状态变化恢复提醒 |

## 13. 测试用例清单

| 测试文件 | 新增用例 | 断言重点 |
|---|---|---|
| `tests/test_preferences.py` | `test_notifications_enabled_defaults_to_true` | 新用户默认开启 |
| `tests/test_preferences.py` | `test_notifications_enabled_reads_false` | 可读取关闭状态 |
| `tests/test_preferences.py` | `test_notifications_enabled_uses_safe_default_for_invalid_values` | 非布尔值、缺失值和损坏 JSON 均回退开启 |
| `tests/test_preferences.py` | `test_set_notifications_enabled_preserves_existing_preferences` | 不丢失外观、隐藏会话、别名和自定义资源 |
| `tests/test_preferences.py` | `test_set_notifications_enabled_does_not_rewrite_effectively_unchanged_value` | 当前实际状态相同时返回成功且不重复写盘 |
| `tests/test_notifier.py` | `test_disabled_notifications_track_state_without_replaying_old_events` | 关闭后不发三类通知，重新开启不补发旧状态 |
| `tests/test_service.py` | `test_notification_preference_controls_notifier_immediately` | API 保存后无需重启 |
| `tests/test_web_launch.py` | `test_preferences_api_reads_and_updates_system_notifications` | GET/POST 返回实际状态和锁定态 |
| `tests/test_web_launch.py` | `test_preferences_api_rejects_invalid_system_notification_value` | 非布尔值、额外字段和非对象 JSON 均返回 400 |
| `tests/test_web_ui.py` | `test_pet_context_menu_has_system_notification_toggle` | 主菜单包含“系统通知 >”，二级菜单包含互斥的“开启 / 关闭”，且窗口尺寸足够 |
| `tests/test_web_ui_behavior.py` | `test_system_notification_toggle_serializes_latest_choice_and_rolls_back_failure` | 串行保存最后选择，失败回滚并提示 |
| `tests/test_docs_prd_alignment.py` | `test_system_notification_toggle_increment_is_documented_and_mapped` | 文档、代码、测试映射一致 |

## 14. 测试计划

必须覆盖：

```bash
PYTHONPATH=src python3 -m unittest tests.test_preferences tests.test_notifier tests.test_service tests.test_web_launch tests.test_web_ui tests.test_web_ui_behavior tests.test_docs_prd_alignment
python3 scripts/validate_release.py
```

手工验收：

| 场景 | 通过标准 |
|---|---|
| 默认启动 App | 右键菜单显示“系统通知 >”；展开后默认显示“✓ 开启”，样式与“外观”选中项一致 |
| 构造待处理会话 | macOS 通知中心出现一次待处理通知 |
| 关闭通知后再构造待处理 | 不出现系统通知，Pet 仍显示待处理 |
| 重新开启通知 | 不补发当前旧状态；后续新待处理恢复系统通知 |
| 重启 App | 菜单开关保持上次选择 |
| 启动时带 `--no-notifications` | 本次运行不弹通知；展开“系统通知 >”后显示“✓ 关闭”，两个选项均置灰 |

## 15. AI Coding 验收提示词

给 AI coding agent 派发实现任务时，建议直接使用下面这段：

```text
请按 docs/prd/2026-07-14-notification-preference-toggle-prd.md 实现 Pet 通知开关。
先写失败测试，再实现。严格保持范围：只新增通知开关，不修改状态算法、Pet 外观逻辑、会话识别和窗口聚焦。
通知关闭后必须满足：NotificationManager 不调用 sender，但 sessions payload、Pet 三态、角标、气泡和点击跳转继续正常。
实现顺序按 PRD 的“AI Coding 实施顺序”执行，最后运行 PRD 测试计划里的命令。
```

## 16. 非目标与风险

| 项 | 说明 |
|---|---|
| 不修改系统通知中心 | macOS 通知样式、关闭按钮和通知中心行为由系统控制 |
| 不做按工具/按会话通知配置 | 首版只做全局通知开关，降低理解成本 |
| 不做免打扰时段 | 时间策略后续可独立迭代 |
| 不做声音配置 | 当前问题是弹窗打扰，声音不进入本次范围 |
| 不暂停监控 | 关闭通知不是暂停，所有状态仍应继续识别和展示 |
| 不改 Windows 原生预览 | Windows 预览壳继续使用 `--no-notifications`；共享 Web 能力仍保留 |

| 风险 | 说明 | 应对 |
|---|---|---|
| 用户关闭后错过待处理 | 系统通知不再主动弹窗 | Pet 角标和气泡继续明显展示待处理 |
| 菜单项增多 | 右键菜单从 3 项变 4 项 | 保持命名短、位置固定、勾选态清晰 |
| 启动参数和偏好冲突 | `--no-notifications` 与偏好开启可能同时存在 | 明确启动参数只影响本次运行，并在 UI 中体现实际运行状态 |
| 偏好写入失败 | 本地文件权限或磁盘异常 | 前端回滚并轻提示，不影响监控主流程 |

## 17. 文档同步关系

| 文档 | 同步内容 |
|---|---|
| `AGENTS.md` | 右键菜单、偏好字段和通知边界 |
| `README.md` | 中文用户入口增加关闭通知说明 |
| `README.en.md` | 英文用户入口增加 notification toggle 说明 |
| `docs/release-checklist.md` | 发布前增加通知开关验收 |
| `docs/qa/2026-07-02-macos-sloth-pet-monitor-acceptance.md` | 增量记录通知关闭和恢复的手工验收 |
| `tests/test_docs_prd_alignment.py` | 自动检查 PRD、README、发布清单和 QA 不漂移 |
