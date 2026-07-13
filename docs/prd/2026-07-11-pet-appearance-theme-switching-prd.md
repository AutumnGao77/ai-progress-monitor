# Pet 外观主题切换 AI Coding PRD

## 1. 结论

本文件是 2026-07-11 Pet 外观主题切换功能的执行 PRD。基础 Pet 主路径仍以 `2026-07-01-ai-sloth-pet-monitor-ai-coding-prd.md` 为准；本文件只定义新增的“外观”子菜单、两套 Pet 外观、偏好保存、资源路由、接口和验收边界。

| 项目 | 结论 |
|---|---|
| 本次目标 | 右键 Pet 后可在“背带裤树懒”和“衬衫树懒”之间切换 |
| 默认外观 | 背带裤树懒，继续使用现有空闲、进行中、待处理三态图片 |
| 新增外观 | 衬衫树懒，首版三态共用 `sloth-pet-shirt.png` |
| 影响范围 | 只切换 Pet 本体，不切换 APP 头像、菜单栏图标、favicon |
| 稳定策略 | 偏好文件保存、非法值回退、防缓存、自动化和开发态 App 检查共同兜底 |
| 非目标 | 不改变状态算法、角标、气泡、拖动、隐藏、退出、通知、会话识别和聚焦逻辑 |

## 2. 用户故事

| 编号 | 用户故事 | 验收标准 |
|---|---|---|
| US-1 | 作为用户，我想在两套 Pet 形象间切换 | 右键 Pet 后进入“外观”子菜单，可以选择两套外观 |
| US-2 | 作为用户，我想知道当前正在使用哪套外观 | 当前项前显示对勾 |
| US-3 | 作为用户，我希望选择能长期保存 | 重启 App 后保持上次选择 |
| US-4 | 作为用户，我希望切换只影响 Pet 形象 | 角标、气泡、APP 图标、菜单栏图标不变化 |
| US-5 | 作为未来用户，我希望还能继续配置自己的图片 | 现有 `pet_assets.*` 覆盖能力保留，并覆盖最终 Pet 图片 |

## 3. 交互要求

主菜单：

```text
外观  >
隐藏 Pet
退出程序
```

外观子菜单：

```text
✓ 背带裤树懒
  衬衫树懒
```

切到衬衫树懒后：

```text
  背带裤树懒
✓ 衬衫树懒
```

| 场景 | 期望 |
|---|---|
| 右键 Pet | 主菜单只显示“外观 / 隐藏 Pet / 退出程序” |
| 鼠标移到外观 | 展开“背带裤树懒 / 衬衫树懒”子菜单 |
| 点击背带裤树懒 | 切回三态背带裤外观，并保存 |
| 点击衬衫树懒 | 切到衬衫树懒外观，并保存 |
| 打开菜单本身 | 不发送隐藏、退出或聚焦消息 |
| 点击外观项 | 不触发隐藏 Pet 或退出程序 |
| 保存失败 | 回滚到已确认外观，并显示轻提示 |

## 4. 主题定义

| 主题值 | 菜单名 | 图片规则 |
|---|---|---|
| `default` | 背带裤树懒 | 空闲、进行中、待处理分别使用现有三张背带裤树懒图 |
| `shirt` | 衬衫树懒 | 空闲、进行中、待处理均使用 `/assets/pet/shirt.png` |

## 5. 资源要求

| 资源 | 路由 | 文件 | 要求 |
|---|---|---|---|
| 背带裤空闲 | `/assets/pet/idle.png` | `src/ai_progress_monitor/assets/sloth-pet-idle.png` | 保持现有三态图 |
| 背带裤进行中 | `/assets/pet/running.png` | `src/ai_progress_monitor/assets/sloth-pet-running.png` | 保持现有三态图 |
| 背带裤待处理 | `/assets/pet/needs-action.png` | `src/ai_progress_monitor/assets/sloth-pet-needs-action.png` | 保持现有三态图 |
| 衬衫树懒 | `/assets/pet/shirt.png` | `src/ai_progress_monitor/assets/sloth-pet-shirt.png` | 来源为 `docs/promo/assets/sloth-mascot-transparent.png`，首版三态共用 |
| APP 头像 | `/assets/app-avatar.png` | `src/ai_progress_monitor/assets/app-avatar.png` | 不随 Pet 外观切换 |

资源规则：

| 规则 | 说明 |
|---|---|
| 透明背景 | Pet 资源应保持透明背景，避免原生悬浮窗出现灰底 |
| 防缓存 | 运行时响应带 `cache-control: no-store`，避免 App WebView 使用旧图 |
| 发布包 | `sloth-pet-shirt.png` 必须进入 pyz 和 release zip |
| 候选素材 | `sloth-candidates/` 仍不进入发布包 |

## 6. 偏好配置

偏好文件新增字段：

```json
{
  "pet_appearance": "shirt"
}
```

| 值 | 行为 |
|---|---|
| 缺失 | 回退 `default` |
| `default` | 使用背带裤树懒三态外观 |
| `shirt` | 使用衬衫树懒外观 |
| 非法值 | 回退 `default` |

保留字段：

| 字段 | 要求 |
|---|---|
| `hidden_sessions` | 写入外观偏好时不得丢失 |
| `session_aliases` | 写入外观偏好时不得丢失 |
| `pet_assets.*` | 继续可覆盖最终 Pet 图片 |

覆盖顺序：

| 步骤 | 规则 |
|---|---|
| 1 | `pet_appearance` 先决定内置主题 |
| 2 | 有效的 `pet_assets.idle/running/needs_action` 覆盖对应最终图片 |
| 3 | 无效路径、格式或大小异常回退内置资源 |
| 4 | `pet_assets.app_avatar` 仍只影响 APP 头像资源，不受主题影响 |

## 7. 本地 API

| 方法 | 路由 | 作用 |
|---|---|---|
| `GET` | `/api/preferences` | 返回当前 Pet 外观 |
| `POST` | `/api/preferences/pet-appearance` | 保存 Pet 外观 |

API 速记：`GET /api/preferences`、`POST /api/preferences/pet-appearance`。

响应示例：

```json
{
  "pet_appearance": "default"
}
```

```json
{
  "ok": true,
  "pet_appearance": "shirt"
}
```

错误规则：

| 场景 | 响应 |
|---|---|
| 无 token | `403` |
| 非法 theme | `400` 和 `invalid_pet_appearance` |
| 写入失败 | `500` 和 `preferences_write_failed` |

## 8. 实现映射

| PRD 要求 | 软件变动 | 自动化证据 |
|---|---|---|
| 主题偏好读写 | `src/ai_progress_monitor/preferences.py` 新增 `pet_appearance()`、`set_pet_appearance()` 和允许值校验 | `tests/test_preferences.py` |
| 衬衫资源路由 | `src/ai_progress_monitor/web.py` 新增 `/assets/pet/shirt.png` 和主题映射 | `tests/test_web_launch.py`、`tests/test_web_ui.py` |
| 偏好 API | `src/ai_progress_monitor/web.py` 新增 `/api/preferences`、`/api/preferences/pet-appearance` | `tests/test_web_launch.py` |
| 右键外观子菜单 | `src/ai_progress_monitor/web.py` 更新 HTML/CSS/JS 菜单结构 | `tests/test_web_ui.py`、`tests/test_web_ui_behavior.py` |
| 三态切图 | 前端 `petThemes`、`applyPetAppearance()`、`selectPetAppearance()`、`refreshPetArt()` | `tests/test_web_ui_behavior.py` |
| 保存失败回滚 | 前端保存队列和 `confirmedPetAppearance` 回滚 | `tests/test_web_ui_behavior.py` |
| App WebView 防旧图 | 所有响应 `cache-control: no-store`，开发态检查脚本请求运行中 App 资源路由 | `tests/test_web_launch.py`、`tests/test_start_scripts.py` |
| 发布包包含新图 | `scripts/build_release.py` pyz 过滤规则保留 `sloth-pet-shirt.png` | `tests/test_release_bundle.py` |
| 原生壳适配 | macOS 悬浮窗口保持菜单和聚焦路径可用 | `tests/test_macos_native_companion.py` |
| 文档同步 | README、release checklist、QA 和本 PRD 互相指向 | `tests/test_docs_prd_alignment.py` |

## 9. 验收矩阵

| 验收项 | 通过标准 |
|---|---|
| 菜单结构 | 右键 Pet 只出现“外观 / 隐藏 Pet / 退出程序” |
| 子菜单 | Hover 或 focus “外观”后展示两个外观项 |
| 当前选择 | 当前外观项前有 `✓` |
| 切到衬衫树懒 | Pet 立即使用 `/assets/pet/shirt.png` |
| 衬衫三态 | 空闲、进行中、待处理均使用同一衬衫图，角标颜色和数字仍按状态变化 |
| 切回背带裤树懒 | 三态图片恢复为 idle/running/needs-action 三张图 |
| 重启保存 | 重启 App 后保持上次外观 |
| 自定义图片 | 有效 `pet_assets.*` 继续覆盖最终 Pet 图片 |
| 失败处理 | 保存失败回滚，不破坏当前运行 |
| 原生 App | macOS Floating Dev App 中真实看到切换结果，不只在浏览器端验证 |

## 10. 测试计划

必须覆盖：

```bash
PYTHONPATH=src python3 -m unittest tests.test_preferences tests.test_web_launch tests.test_web_ui tests.test_web_ui_behavior tests.test_release_bundle tests.test_start_scripts tests.test_macos_native_companion tests.test_docs_prd_alignment
python3 scripts/validate_release.py
```

开发态 App 手工验收：

严格验收命令：`scripts/check_macos_floating_dev.sh --strict`。

| 场景 | 通过标准 |
|---|---|
| 启动 macOS Floating Dev App | Pet 正常显示 |
| 右键 Pet | 主菜单和子菜单结构正确 |
| 选择衬衫树懒 | Pet 立即变成指定衬衫图 |
| 状态变化 | 衬衫外观保持不变，角标正常变色和计数 |
| 选择背带裤树懒 | 三态背带裤图恢复 |
| 重启 App | 外观偏好保持 |
| 点击气泡聚焦 | 继续聚焦原窗口，不受外观切换影响 |

## 11. 非目标与风险

| 项 | 说明 |
|---|---|
| 不替换 APP 图标 | APP 头像、菜单栏图标和 favicon 独立维护 |
| 不改状态算法 | 外观主题不影响待处理、进行中、空闲判定 |
| 不改会话识别 | Claude/Codex/通用 AI 工具监控规则不在本 PRD 内变更 |
| 不移动已发布 tag | 已发布版本保持不可变，新功能后续按新版本发布 |
| 不依赖浏览器缓存 | App 形态以运行时资源路由和 no-store 校验为准 |

## 12. 文档同步关系

| 文档 | 同步内容 |
|---|---|
| `AGENTS.md` | 项目级资源路由、偏好字段、API 和菜单边界 |
| `README.md` | 中文用户入口、外观切换说明和 PRD 链接 |
| `README.en.md` | 英文用户入口、Appearance 说明和 PRD 链接 |
| `docs/release-checklist.md` | 发布前必须验收外观子菜单和新资源 |
| `docs/qa/2026-07-02-macos-sloth-pet-monitor-acceptance.md` | 增量验收证据和交付边界 |
| `tests/test_docs_prd_alignment.py` | 自动检查 PRD、README、发布清单和 QA 不漂移 |
