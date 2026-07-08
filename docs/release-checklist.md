# Release Checklist

结论：每次交付前必须先证明核心逻辑、事件接入、原生悬浮入口、进程探测边界、Pet 左键/右键边界和隐私减负主路径都可用。

## 必跑检查

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
| 敏感信息扫描 | `python3 scripts/validate_release.py` 内置检查 | 无本机真实姓名精确命中 |
| Web API 冒烟 | 启动服务后用页面令牌请求 `/api/sessions` | 返回会话 JSON |
| API 安全冒烟 | 不带令牌请求 `/api/sessions` | 返回 403 |
| 三态 Pet 资源 | `PYTHONPATH=src python3 -m unittest tests.test_web_ui tests.test_web_launch tests.test_web_ui_behavior tests.test_preferences` | 三态图片路由、APP 头像、可配置资源、透明角和状态切图均通过；APP 头像源图和运行图为透明圆形，无水印和圆外方框背景 |
| 原生透明背景 | `PYTHONPATH=src python3 -m unittest tests.test_web_ui` | `.pet` 不添加 `drop-shadow`；WebView 背景保持透明 |
| 发布包构建 | `python3 scripts/build_release.py` | 生成 `dist/ai-progress-monitor.pyz` 和 `dist/ai-progress-monitor-release.zip` |
| macOS App 外壳 | 解压 release zip | 包含 `AI Progress Monitor.app` 和 `AI Progress Monitor Floating.app` |
| macOS App 图标 | 检查两个 `.app/Contents/Resources/` 和 `Info.plist` | 包含 `app-avatar.png`、`AppIcon.icns`，且 `CFBundleIconFile` 为 `AppIcon` |
| 发布包视觉资源 | 检查 `dist/ai-progress-monitor.pyz` 内容 | 包含 `sloth-pet-idle.png`、`sloth-pet-running.png`、`sloth-pet-needs-action.png`、`app-avatar.png` |
| 发布包资源收口 | 检查 `dist/ai-progress-monitor.pyz` 内容 | 不包含 `assets/sloth-candidates/` 或 `.DS_Store` |
| 终端桥接 | `python3 scripts/monitor_command.py --help` | 正常显示参数 |
| 一键启动 | `python3 dist/ai-progress-monitor.pyz --help` | 参数包含 `--open` |
| 通知开关 | `python3 dist/ai-progress-monitor.pyz --help` | 参数包含 `--no-notifications` |
| 会话清理 | `python3 dist/ai-progress-monitor.pyz --help` | 参数包含 `--cleanup-after-seconds` |
| 响应目录 | `python3 dist/ai-progress-monitor.pyz --help` | 参数包含 `--response-dir` |
| 环境诊断 | `python3 scripts/doctor.py` | 输出 Python、平台、目录、通知、窗口适配检查 |
| 进程探测边界 | `PYTHONPATH=src python3 -m unittest tests.test_sources tests.test_service tests.test_web_ui` | 直接 CLI 标记为 `process_only`；Claude 终端回复完成后显示待处理，点击气泡成功回到系统终端或 IDE 内置终端后转空闲；Codex CLI 按进程活跃度保守判断；桌面端具体对话已查看后转空闲并保留 15 分钟后移出；不展示终端内容 |
| 原生浮窗 | `PYTHONPATH=src python3 -m unittest tests.test_macos_native_companion tests.test_windows_native_companion` | macOS / Windows 浮窗置顶、收起、恢复、进程级检测边界被覆盖 |
| 端到端冒烟 | `python3 scripts/e2e_smoke.py --artifact dist/ai-progress-monitor.pyz` | 临时启动 Web 服务和 Claude/Codex wrapper，验证服务、事件接入和状态更新链路；新版 Pet 主界面不展示直接回复按钮 |

## 人工验收

| 场景 | 期望结果 |
|---|---|
| Demo 模式启动 | 浏览器访问 `http://127.0.0.1:8765` 能看到 3 个会话 |
| macOS 双击启动 | 双击 `AI Progress Monitor.app` | 自动启动服务并打开浏览器 |
| macOS 悬浮入口 | 双击 `AI Progress Monitor Floating.app` | 小窗置顶；关闭只隐藏；菜单栏头像图标可恢复/退出 |
| Windows 悬浮入口 | 双击 `scripts\start_floating_monitor.bat` | 小窗置顶；关闭只隐藏；托盘可恢复/退出 |
| API 令牌 | 页面能读取启动令牌并请求会话 API |
| 系统通知 | needs_action 触发通知，重复刷新不反复弹 |
| 需要处理状态 | 页面右下角宠物显示“待处理” |
| 三态换图 | 空闲、进行中、待处理分别显示对应 Pet 图片；右上角数字角标仍显示总气泡数 |
| 悬浮窗透明 | 原生悬浮入口只显示 Pet、角标和气泡，不出现灰底、白底或额外阴影边 |
| 菜单栏图标 | macOS 菜单栏状态项显示 APP 头像图标，不显示文字 `AI` |
| 终端桥接 | 用 `scripts/monitor_codex.*` 或 `scripts/monitor_claude.*` 包装命令后，输出能进入 Web Companion |
| 直接 CLI 探测 | 直接运行 `claude` / `codex` | 显示 process-only 气泡；Claude 终端回复完成后进入“待处理”，点击气泡跳回对应终端后转“空闲”；Codex CLI 活跃为“进行中”、静默为“空闲”；气泡不展示终端内容或技术说明 |
| 桌面端已查看收口 | Codex 桌面端具体对话进入待处理后点击气泡查看 | 转为空闲后保留 15 分钟；超过 15 分钟具体对话从气泡列表移出，桌面 App 仍存活时显示 App 空闲入口 |
| process-only 去重 | 同一个进程已被桥接脚本监控 | 只显示完整监控项，不再显示重复的 process-only 项 |
| 复杂交互 | 不展示直接回复按钮，引导回原窗口 |
| 窗口定位 | 点击气泡后尝试激活对应窗口；直接 CLI 优先聚焦父 GUI 应用 |
| 左键 Pet | 只展开/收起气泡列表，不隐藏 Pet |
| 右键 Pet | 只出现隐藏 Pet、退出程序；隐藏后程序继续运行 |
| 低侵入体验 | 默认只显示 Pet、角标和气泡列表，不出现工具面板 |

## 当前发布说明

| 项 | 说明 |
|---|---|
| 默认界面 | 本地 Web Companion；桌面宠物体验推荐 macOS / Windows 原生悬浮入口 |
| 实验界面 | Tkinter 悬浮窗，受系统 Tk 版本影响，暂不作为默认交付入口 |
| 数据接入 | 推荐终端桥接脚本或 JSON 事件源；直接 Claude CLI 可用本地会话状态识别回复后待处理，Codex CLI 仍保守判断活跃/空闲 |
| GitHub 公开发布 | `dist/` 产物不提交源码仓库；release zip 作为 GitHub Release 附件上传；当前 macOS `.app` 未 notarized |
| 隐私策略 | 本地运行，不上传会话内容 |
| 当前发布包 | `ai-progress-monitor-release.zip`，macOS / Windows 均可在 Python 3.9+ 下运行 |
| 诊断工具 | `scripts/doctor.py` 可用于定位权限、目录和平台适配问题 |
| Pet 外观配置 | `~/.ai-progress-monitor/preferences.json` 支持 `pet_assets.idle`、`pet_assets.running`、`pet_assets.needs_action`、`pet_assets.app_avatar` 本地路径；无效路径自动回退内置资源 |
