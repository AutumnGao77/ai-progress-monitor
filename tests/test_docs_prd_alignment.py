from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class DocsPrdAlignmentTests(unittest.TestCase):
    def test_readme_and_release_checklist_do_not_advertise_removed_pet_main_path_features(self):
        combined = "\n".join(
            [
                (ROOT / "README.md").read_text(),
                (ROOT / "docs" / "release-checklist.md").read_text(),
            ]
        )

        forbidden_phrases = [
            "临时暂隐宠物",
            "暂隐",
            "会话重命名/恢复默认名",
            "重命名",
            "已隐藏",
            "页面内环境诊断",
            "宠物内点击 Yes/No",
            "点击 `Yes`",
            "Web Companion 展开面板中点击“诊断”",
            "Yes/No 回写链路",
            "端到端回写",
        ]
        for phrase in forbidden_phrases:
            self.assertNotIn(phrase, combined)

    def test_readme_dev_helper_points_to_native_floating_log_and_session_counts(self):
        readme = (ROOT / "README.md").read_text()

        self.assertIn("~/Library/Logs/AI Progress Monitor/native-monitor.log", readme)
        self.assertIn("脱敏会话计数", readme)
        self.assertIn("running=1 idle=3", readme)
        self.assertIn("scripts/check_macos_floating_dev.sh --strict", readme)
        self.assertIn("Manual acceptance incomplete", readme)

    def test_docs_do_not_advertise_process_only_explanation_inside_bubbles(self):
        combined = "\n".join(
            [
                (ROOT / "README.md").read_text(),
                (ROOT / "docs" / "release-checklist.md").read_text(),
                (ROOT / "docs" / "prd" / "2026-07-01-ai-sloth-pet-monitor-ai-coding-prd.md").read_text(),
                (ROOT / "docs" / "qa" / "2026-07-02-macos-sloth-pet-monitor-acceptance.md").read_text(),
            ]
        )

        forbidden_phrases = [
            "弱识别气泡",
            "气泡 meta",
            "meta 显示弱识别说明",
            "气泡 meta 必须展示弱识别说明",
            "文案必须说明“弱识别",
            "说明仅确认 CLI 会话存在",
        ]
        for phrase in forbidden_phrases:
            self.assertNotIn(phrase, combined)

    def test_docs_do_not_treat_process_existence_as_always_running(self):
        combined = "\n".join(
            [
                (ROOT / "README.md").read_text(),
                (ROOT / "docs" / "release-checklist.md").read_text(),
                (ROOT / "docs" / "prd" / "2026-07-01-ai-sloth-pet-monitor-ai-coding-prd.md").read_text(),
            ]
        )

        forbidden_phrases = [
            "直接启动 `claude` / `codex` 时显示绿色“进行中”气泡",
            "直接 CLI 标记为 `process_only`，显示绿色进行中",
            "直接运行 `claude` / `codex` 时至少显示绿色进行中气泡",
            "若直接识别到正在运行的 `claude` / `codex` 进程，用户侧必须至少显示为绿色 `进行中` 气泡",
            "process_only` | 可显示为进行中气泡；直接 CLI 或桌面主进程存在时显示为进行中",
            "桌面主进程显示为绿色",
            "运行中的桌面主进程仍要生成 process-only 气泡",
            "桌面 App 进程级检测",
            "ProcessSource` 识别到 1 个 Codex Desktop 为 `running process_only`",
        ]
        for phrase in forbidden_phrases:
            self.assertNotIn(phrase, combined)

    def test_docs_describe_claude_cli_session_state_priority(self):
        combined = "\n".join(
            [
                (ROOT / "README.md").read_text(),
                (ROOT / "docs" / "prd" / "2026-07-01-ai-sloth-pet-monitor-ai-coding-prd.md").read_text(),
                (ROOT / "docs" / "prd" / "2026-07-01-ai-sloth-pet-monitor-iteration-prd.md").read_text(),
                (ROOT / "docs" / "qa" / "2026-07-02-macos-sloth-pet-monitor-acceptance.md").read_text(),
            ]
        )

        self.assertIn("Claude CLI 优先", combined)
        self.assertIn("~/.claude/sessions/<pid>.json", combined)
        self.assertIn("读不到时", combined)

    def test_docs_define_generic_ai_tool_registry_and_desktop_idle_fallback(self):
        combined = "\n".join(
            [
                (ROOT / "README.md").read_text(),
                (ROOT / "docs" / "prd" / "2026-07-01-ai-sloth-pet-monitor-ai-coding-prd.md").read_text(),
                (ROOT / "docs" / "qa" / "2026-07-02-macos-sloth-pet-monitor-acceptance.md").read_text(),
            ]
        )

        self.assertIn("通用 AI 工具识别配置", combined)
        self.assertIn("空闲入口", combined)
        self.assertIn("具体会话优先", combined)
        self.assertIn("工具定义表", combined)

    def test_docs_define_badge_number_as_total_bubble_count(self):
        combined = "\n".join(
            [
                (ROOT / "docs" / "prd" / "2026-07-01-ai-sloth-pet-monitor-ai-coding-prd.md").read_text(),
                (ROOT / "docs" / "prd" / "2026-07-01-ai-sloth-pet-monitor-iteration-prd.md").read_text(),
            ]
        )

        forbidden_phrases = [
            "角标永远显示最高优先级状态的数量",
            "角标数字和颜色均按最高优先级状态显示",
            "角标优先显示待处理数量",
            "显示进行中对话数量",
            "角标显示 `1` 且为红色",
        ]
        for phrase in forbidden_phrases:
            self.assertNotIn(phrase, combined)
        self.assertIn("角标数字显示当前气泡列表中的会话总数", combined)
        self.assertIn("角标颜色按待处理 > 进行中 > 空闲", combined)

    def test_docs_define_desktop_sessions_without_folder_use_readable_conversation_labels(self):
        combined = "\n".join(
            [
                (ROOT / "README.md").read_text(),
                (ROOT / "docs" / "prd" / "2026-07-01-ai-sloth-pet-monitor-ai-coding-prd.md").read_text(),
                (ROOT / "docs" / "qa" / "2026-07-02-macos-sloth-pet-monitor-acceptance.md").read_text(),
            ]
        )

        self.assertIn("Codex 对话", combined)
        self.assertIn("不可读 session_id 碎片", combined)
        self.assertIn("无文件夹桌面对话", combined)
        self.assertIn("自动聊天目录", combined)
        self.assertIn("工具配置", combined)
        self.assertIn("工具定义表", combined)

    def test_docs_define_viewed_desktop_idle_retention_and_app_fallback(self):
        combined = "\n".join(
            [
                (ROOT / "README.md").read_text(),
                (ROOT / "docs" / "prd" / "2026-07-01-ai-sloth-pet-monitor-ai-coding-prd.md").read_text(),
                (ROOT / "docs" / "prd" / "2026-07-01-ai-sloth-pet-monitor-iteration-prd.md").read_text(),
                (ROOT / "docs" / "release-checklist.md").read_text(),
                (ROOT / "docs" / "qa" / "2026-07-02-macos-sloth-pet-monitor-acceptance.md").read_text(),
            ]
        )

        self.assertIn("已查看", combined)
        self.assertIn("15 分钟", combined)
        self.assertIn("App 空闲入口", combined)

    def test_qa_report_records_packaged_release_artifacts(self):
        qa = (ROOT / "docs" / "qa" / "2026-07-02-macos-sloth-pet-monitor-acceptance.md").read_text()

        forbidden_phrases = [
            "等待用户本地测试确认后再打包",
            "本轮按用户要求未执行",
            "按用户要求未重新打包",
            "等待用户确认",
            "待确认后执行",
            "本轮未执行，等待用户确认",
            "待本轮最终执行",
            "上轮 `194 tests OK`",
        ]
        for phrase in forbidden_phrases:
            self.assertNotIn(phrase, qa)
        self.assertIn("296 tests OK", qa)
        self.assertIn("dist/ai-progress-monitor-release.zip", qa)
        self.assertIn("2.74 MiB", qa)
        self.assertIn("12.26 MiB", qa)

    def test_docs_define_three_state_pet_assets_and_configurable_overrides(self):
        combined = "\n".join(
            [
                (ROOT / "AGENTS.md").read_text(),
                (ROOT / "README.md").read_text(),
                (ROOT / "docs" / "release-checklist.md").read_text(),
                (ROOT / "docs" / "prd" / "2026-07-01-ai-sloth-pet-monitor-ai-coding-prd.md").read_text(),
                (ROOT / "docs" / "prd" / "2026-07-01-ai-sloth-pet-monitor-iteration-prd.md").read_text(),
                (ROOT / "docs" / "qa" / "2026-07-02-macos-sloth-pet-monitor-acceptance.md").read_text(),
            ]
        )

        self.assertIn("/assets/pet/idle.png", combined)
        self.assertIn("/assets/pet/running.png", combined)
        self.assertIn("/assets/pet/needs-action.png", combined)
        self.assertIn("/assets/app-avatar.png", combined)
        self.assertIn("pet_assets.idle", combined)
        self.assertIn("pet_assets.running", combined)
        self.assertIn("pet_assets.needs_action", combined)
        self.assertIn("pet_assets.app_avatar", combined)
        self.assertIn("不额外添加 `drop-shadow`", combined)
        self.assertIn("水印和圆外方框背景", combined)
        self.assertIn("(0,0,0,0)", combined)
        self.assertIn("AppIcon.icns", combined)
        self.assertIn("CFBundleIconFile", combined)
        self.assertIn("菜单栏状态项显示 APP 头像图标", combined)

        forbidden_phrases = [
            "菜单栏 `AI`",
            "菜单栏 AI",
            "AI -> Show Monitor",
            "menu bar AI -> Show Monitor",
        ]
        for phrase in forbidden_phrases:
            self.assertNotIn(phrase, combined)

    def test_historical_prd_points_to_current_ai_coding_prd(self):
        historical = (ROOT / "docs" / "prd" / "2026-06-30-ai-work-progress-monitor-prd.md").read_text()

        self.assertIn("历史基线", historical)
        self.assertIn("2026-07-01-ai-sloth-pet-monitor-ai-coding-prd.md", historical)
        self.assertIn("当前执行目标", historical)

    def test_historical_superpowers_plan_points_to_current_prd(self):
        plan = (ROOT / "docs" / "superpowers" / "plans" / "2026-06-30-ai-progress-monitor.md").read_text()

        self.assertIn("历史计划", plan)
        self.assertIn("docs/prd/2026-07-01-ai-sloth-pet-monitor-ai-coding-prd.md", plan)
        self.assertIn("不要按本历史计划恢复旧工具面板或宠物内 Yes/No 主路径", plan)

    def test_docs_define_exited_cli_sessions_do_not_remain_because_ide_window_is_open(self):
        combined = "\n".join(
            [
                (ROOT / "README.md").read_text(),
                (ROOT / "docs" / "prd" / "2026-07-01-ai-sloth-pet-monitor-ai-coding-prd.md").read_text(),
                (ROOT / "docs" / "qa" / "2026-07-02-macos-sloth-pet-monitor-acceptance.md").read_text(),
            ]
        )

        self.assertIn("前台交互终端状态", combined)
        self.assertIn("退出 CLI 后", combined)
        self.assertIn("IDE", combined)
        self.assertIn("项目窗口", combined)
        self.assertIn("不应继续保留气泡", combined)


if __name__ == "__main__":
    unittest.main()
