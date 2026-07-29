import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
POLICY_SOURCE = ROOT / "native" / "macos" / "FloatingMonitorFocusPolicy.swift"


class MacOSFocusPolicyTests(unittest.TestCase):
    def test_requires_two_consecutive_target_confirmations(self):
        output = run_policy_case(
            """
            let first = FloatingMonitorFocusPolicy.decision(
                targetSelected: true,
                stableReadCount: 0,
                attempt: 0
            )
            check(first == .retry(stableReadCount: 1), "one matching read must not activate")

            let second = FloatingMonitorFocusPolicy.decision(
                targetSelected: true,
                stableReadCount: 1,
                attempt: 1
            )
            check(second == .complete, "two consecutive matching reads should complete")
            print("ok")
            """
        )

        self.assertEqual(output, "ok")

    def test_mismatch_resets_consecutive_confirmation_count(self):
        output = run_policy_case(
            """
            let decision = FloatingMonitorFocusPolicy.decision(
                targetSelected: false,
                stableReadCount: 1,
                attempt: 1
            )
            check(
                decision == .retry(stableReadCount: 0),
                "a mismatch must reset the stable-read count"
            )
            print("ok")
            """
        )

        self.assertEqual(output, "ok")

    def test_stabilization_is_bounded(self):
        output = run_policy_case(
            """
            let decision = FloatingMonitorFocusPolicy.decision(
                targetSelected: false,
                stableReadCount: 0,
                attempt: FloatingMonitorFocusPolicy.maximumStabilizationAttempts - 1
            )
            check(decision == .fail, "the last failed attempt must stop retrying")
            print("ok")
            """
        )

        self.assertEqual(output, "ok")

    def test_timing_budget_is_short_but_not_a_single_fixed_sleep(self):
        output = run_policy_case(
            """
            check(
                FloatingMonitorFocusPolicy.requiredStableReadCount >= 2,
                "selection must be observed more than once"
            )
            check(
                FloatingMonitorFocusPolicy.stabilizationInterval <= 0.05,
                "selection checks should stay responsive"
            )
            check(
                FloatingMonitorFocusPolicy.maximumStabilizationDuration <= 0.5,
                "selection stabilization must have a bounded sub-second budget"
            )
            check(
                FloatingMonitorFocusPolicy.activationTimeout >= 0.5,
                "real application activation needs a separate timeout"
            )
            print("ok")
            """
        )

        self.assertEqual(output, "ok")

    def test_project_window_title_scoring_prefers_real_segment_over_prefix(self):
        output = run_policy_case(
            """
            let exactSegment = FloatingMonitorFocusPolicy.projectWindowTitleMatchScore(
                folderName: "SellerBooks",
                windowTitle: "SellerBooks — app.py"
            )
            let prefixOnly = FloatingMonitorFocusPolicy.projectWindowTitleMatchScore(
                folderName: "SellerBooks",
                windowTitle: "SellerBooks-old — README.md"
            )
            let middleSegment = FloatingMonitorFocusPolicy.projectWindowTitleMatchScore(
                folderName: "日报推送",
                windowTitle: "SKILL.md — 日报推送 — Zed"
            )
            check(exactSegment > prefixOnly, "real project segment must outrank a prefix-only title")
            check(prefixOnly == 0, "a different hyphenated project must not count as the target")
            check(middleSegment == exactSegment, "project segment should match anywhere in an IDE title")
            check(
                FloatingMonitorFocusPolicy.projectWindowTitleMatchScore(
                    folderName: "SellerBooks",
                    windowTitle: "[SellerBooks] app.py"
                ) > 0,
                "title boundaries should still match the real project"
            )
            print("ok")
            """
        )

        self.assertEqual(output, "ok")

    def test_all_supported_ide_families_use_the_same_native_project_policy(self):
        output = run_policy_case(
            """
            let projectEditors = [
                "Android Studio",
                "CLion",
                "Code",
                "Cursor",
                "Eclipse",
                "Fleet",
                "GoLand 2026.1",
                "IntelliJ IDEA Ultimate",
                "Kiro",
                "Nova",
                "PhpStorm",
                "PyCharm CE",
                "Rider",
                "RubyMine",
                "Sublime Text",
                "Trae",
                "Trae CN",
                "VSCodium",
                "Visual Studio Code",
                "Visual Studio Code - Insiders",
                "WebStorm",
                "Windsurf",
                "Xcode",
                "Zed",
            ]
            for appName in projectEditors {
                check(
                    FloatingMonitorFocusPolicy.isProjectEditorApplicationName(appName),
                    "\\(appName) must use project-window inventory and exact focus"
                )
            }
            for appName in [
                "Terminal",
                "iTerm",
                "Warp",
                "WezTerm",
                "kitty",
                "Alacritty",
                "Ghostty",
                "Hyper",
                "Tabby",
                "Rio",
            ] {
                check(
                    !FloatingMonitorFocusPolicy.isProjectEditorApplicationName(appName),
                    "\\(appName) must keep terminal process lifecycle semantics"
                )
            }
            print("ok")
            """
        )

        self.assertEqual(output, "ok")


def run_policy_case(case_source: str) -> str:
    with tempfile.TemporaryDirectory() as temp_dir:
        main = Path(temp_dir) / "main.swift"
        executable = Path(temp_dir) / "focus-policy-test"
        main.write_text(
            textwrap.dedent(
                f"""
                import Foundation

                func check(_ condition: @autoclosure () -> Bool, _ message: String) {{
                    if !condition() {{
                        print(message)
                        Foundation.exit(1)
                    }}
                }}

                {case_source}
                """
            ),
            encoding="utf-8",
        )
        cache = Path(temp_dir) / "swift-cache"
        cache.mkdir()
        compile_result = subprocess.run(
            [
                "swiftc",
                str(POLICY_SOURCE),
                str(main),
                "-o",
                str(executable),
                "-module-cache-path",
                str(cache),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        if compile_result.returncode != 0:
            raise AssertionError(compile_result.stdout + compile_result.stderr)
        run_result = subprocess.run([str(executable)], capture_output=True, text=True)
        if run_result.returncode != 0:
            raise AssertionError(run_result.stdout + run_result.stderr)
        return run_result.stdout.strip()


if __name__ == "__main__":
    unittest.main()
