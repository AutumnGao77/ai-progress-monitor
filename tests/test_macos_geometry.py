import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GEOMETRY_SOURCE = ROOT / "native" / "macos" / "FloatingMonitorGeometry.swift"


class MacOSGeometryTests(unittest.TestCase):
    def test_resize_keeps_bottom_right_anchor_when_bubble_window_expands(self):
        output = run_geometry_case(
            """
            let current = CGRect(x: 1246, y: 24, width: 170, height: 150)
            let visible = CGRect(x: 0, y: 0, width: 1440, height: 870)
            let resized = FloatingMonitorGeometry.resizedFrame(
                currentFrame: current,
                requestedSize: CGSize(width: 340, height: 500),
                visibleFrame: visible,
                compactSize: CGSize(width: 170, height: 150)
            )
            check(resized.minX == 1076, "expanded x should grow left from the same right edge")
            check(resized.minY == 24, "expanded y should keep the same bottom edge")
            check(resized.maxX == current.maxX, "expanded window should keep pet right edge stable")
            print("ok")
            """
        )

        self.assertEqual(output, "ok")

    def test_dragged_expanded_window_can_reach_left_edge_by_pet_size(self):
        output = run_geometry_case(
            """
            let frame = CGRect(x: 100, y: 24, width: 340, height: 500)
            let screen = CGRect(x: 0, y: 0, width: 1440, height: 900)
            let dragged = FloatingMonitorGeometry.draggedFrame(
                frame: frame,
                deltaX: -600,
                deltaY: 0,
                screenFrame: screen,
                compactSize: CGSize(width: 170, height: 150)
            )
            check(dragged.minX == -170, "expanded transparent area may extend left while pet stays visible")
            check(dragged.minX + 340 - 170 == 0, "pet visual left edge should reach screen left")
            print("ok")
            """
        )

        self.assertEqual(output, "ok")

    def test_dragged_expanded_window_keeps_pet_inside_right_and_top_edges(self):
        output = run_geometry_case(
            """
            let frame = CGRect(x: 1100, y: 760, width: 340, height: 500)
            let screen = CGRect(x: 0, y: 0, width: 1440, height: 900)
            let dragged = FloatingMonitorGeometry.draggedFrame(
                frame: frame,
                deltaX: 600,
                deltaY: 600,
                screenFrame: screen,
                compactSize: CGSize(width: 170, height: 150)
            )
            check(dragged.maxX == 1440, "expanded window right edge should stay within screen")
            check(dragged.minY == 750, "pet visual top edge should stay within screen")
            print("ok")
            """
        )

        self.assertEqual(output, "ok")

    def test_drag_screen_follows_mouse_screen_for_cross_display_drag(self):
        output = run_geometry_case(
            """
            let main = CGRect(x: 0, y: 0, width: 1440, height: 900)
            let external = CGRect(x: -1920, y: 0, width: 1920, height: 1080)
            let selected = FloatingMonitorGeometry.screenFrame(
                mouseLocation: CGPoint(x: -10, y: 200),
                proposedFrame: CGRect(x: -120, y: 60, width: 170, height: 150),
                screenFrames: [main, external],
                fallback: main
            )
            check(selected.minX == external.minX, "mouse on external display should select external screen")
            print("ok")
            """
        )

        self.assertEqual(output, "ok")


def run_geometry_case(case_source: str) -> str:
    with tempfile.TemporaryDirectory() as temp_dir:
        main = Path(temp_dir) / "main.swift"
        executable = Path(temp_dir) / "geometry-test"
        main.write_text(
            textwrap.dedent(
                f"""
                import CoreGraphics
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
                str(GEOMETRY_SOURCE),
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
