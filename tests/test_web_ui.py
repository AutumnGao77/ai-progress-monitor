import unittest
import re
import struct
import zlib
from pathlib import Path

from ai_progress_monitor.web import HTML

ROOT = Path(__file__).resolve().parents[1]


class WebUiTests(unittest.TestCase):
    def test_pet_uses_generated_sloth_image_layout(self):
        self.assertIn('class="pet-art"', HTML)
        self.assertIn('src="/assets/pet/idle.png"', HTML)
        self.assertIn('draggable="false"', HTML)
        self.assertIn("pet-art-wrap", HTML)
        self.assertIn('id="petBadge"', HTML)
        self.assertIn('id="bubbleList"', HTML)
        self.assertIn("session-bubble", HTML)
        self.assertIn('<link rel="icon" href="/assets/app-avatar.png">', HTML)

    def test_pet_has_state_specific_animation_layers(self):
        self.assertIn(".pet.needs-action .pet-alert-card", HTML)
        self.assertIn(".pet.running .pet-typing-dots", HTML)
        self.assertIn(".pet.idle .pet-nap-mark", HTML)
        self.assertIn("@keyframes pet-alert-bob", HTML)
        self.assertIn("@keyframes pet-working-nod", HTML)
        self.assertIn("@keyframes pet-zzz", HTML)

    def test_pet_container_does_not_add_background_shadow(self):
        pet_rule = _css_rule(".pet")

        self.assertIn("filter: none", pet_rule)
        self.assertNotIn("drop-shadow", pet_rule)

    def test_pet_image_asset_exists_and_is_png(self):
        asset = ROOT / "src" / "ai_progress_monitor" / "assets" / "sloth-pet.png"

        self.assertTrue(asset.exists())
        self.assertEqual(asset.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")

    def test_pet_state_and_app_avatar_assets_exist_and_are_png(self):
        assets = [
            "sloth-pet-idle.png",
            "sloth-pet-running.png",
            "sloth-pet-needs-action.png",
            "app-avatar.png",
        ]

        for filename in assets:
            with self.subTest(filename=filename):
                asset = ROOT / "src" / "ai_progress_monitor" / "assets" / filename
                self.assertTrue(asset.exists())
                self.assertEqual(asset.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")

    def test_pet_state_and_app_avatar_assets_have_transparent_corners(self):
        expected_sizes = {
            "sloth-pet-idle.png": (768, 768),
            "sloth-pet-running.png": (768, 768),
            "sloth-pet-needs-action.png": (768, 768),
            "app-avatar.png": (1024, 1024),
        }

        for filename, expected_size in expected_sizes.items():
            with self.subTest(filename=filename):
                asset = ROOT / "src" / "ai_progress_monitor" / "assets" / filename
                width, height, pixels = _read_rgba_png(asset)
                self.assertEqual((width, height), expected_size)
                corner_indexes = [
                    3,
                    (width - 1) * 4 + 3,
                    ((height - 1) * width) * 4 + 3,
                    ((height * width) - 1) * 4 + 3,
                ]
                self.assertEqual([pixels[index] for index in corner_indexes], [0, 0, 0, 0])

    def test_app_avatar_keeps_only_circular_icon_without_square_background(self):
        asset = ROOT / "src" / "ai_progress_monitor" / "assets" / "app-avatar.png"
        width, height, pixels = _read_rgba_png(asset)
        self.assertEqual((width, height), (1024, 1024))
        center_x = (width - 1) / 2
        center_y = (height - 1) / 2
        radius = 500

        for y in range(0, height, 32):
            for x in range(0, width, 32):
                distance = ((x - center_x) ** 2 + (y - center_y) ** 2) ** 0.5
                alpha = pixels[(y * width + x) * 4 + 3]
                if distance > radius + 4:
                    self.assertEqual(alpha, 0, f"expected transparent square background at {(x, y)}")

        watermark_area_alphas = [
            pixels[(y * width + x) * 4 + 3]
            for y in range(940, 1024, 12)
            for x in range(820, 1024, 12)
        ]
        self.assertEqual(max(watermark_area_alphas), 0)

    def test_pet_art_switches_with_existing_status_priority(self):
        self.assertIn('const petImages = {', HTML)
        self.assertIn('idle:"/assets/pet/idle.png"', HTML)
        self.assertIn('running:"/assets/pet/running.png"', HTML)
        self.assertIn('needs_action:"/assets/pet/needs-action.png"', HTML)
        self.assertIn("petArt.src = petImages[state.status] || petImages.idle;", HTML)

    def test_pet_supports_dragging_and_persisted_position(self):
        self.assertIn("pointerdown", HTML)
        self.assertIn("monitor.pet.position", HTML)
        self.assertIn("applyPetPosition", HTML)
        self.assertIn("hasHostWindow", HTML)
        self.assertIn("localStorage.removeItem(PET_POSITION_KEY)", HTML)
        self.assertIn("resetPetDomPosition", HTML)
        self.assertIn('"start-window-drag"', HTML)
        self.assertIn('"stop-window-drag"', HTML)

    def test_small_native_window_uses_compact_layout(self):
        self.assertIn("@media (max-width: 420px)", HTML)
        self.assertIn("html, body { margin: 0; width: 100%; height: 100%; overflow: hidden; background: transparent;", HTML)
        self.assertIn('resizeHostWindow("compact")', HTML)
        self.assertIn('resizeHostWindow(willOpen ? "bubbles" : "compact")', HTML)
        self.assertIn("window.webkit.messageHandlers.monitorWindow.postMessage", HTML)
        self.assertIn("max-width: min(300px, calc(100vw - 20px))", HTML)
        self.assertIn("max-height: min(320px, calc(100vh - 190px))", HTML)

    def test_bubble_list_is_positioned_above_pet_without_overlap(self):
        self.assertIn("fitBubbleAbovePet", HTML)
        self.assertIn("scheduleBubbleLayout", HTML)
        self.assertIn("dockPetBelowBubbles", HTML)
        self.assertIn("getPetVisualRect", HTML)
        self.assertIn("VISUAL_MOTION_BUFFER", HTML)
        self.assertIn(".pet-art-wrap { position: absolute; inset: 0 3px 0 3px;", HTML)
        self.assertIn("visualRect.top - bubbleHeight - BUBBLE_GAP - VISUAL_MOTION_BUFFER", HTML)
        self.assertIn("visualTopOverflow", HTML)
        self.assertIn("bubbleList.style.maxHeight = `${bubbleHeight}px`", HTML)
        self.assertIn('if (bubbleList.classList.contains("open")) scheduleBubbleLayout();', HTML)
        self.assertIn("mode === \"bubbles\" ? {width: 340, height: 500}", HTML)
        self.assertNotIn(".pet { left: 8px !important; right: auto; top: 8px !important;", HTML)
        self.assertNotIn("Math.max(72, petRect.top - 20)", HTML)

    def test_native_host_bubble_layout_does_not_reposition_pet(self):
        dock_fn = re.search(r"function dockPetBelowBubbles\(\) \{(?P<body>.*?)\n\}", HTML, re.S)

        self.assertIsNotNone(dock_fn)
        self.assertIn("if (hasHostWindow()) return;", dock_fn.group("body"))

    def test_main_ui_removes_tool_panel_buttons(self):
        forbidden = [
            "doctorBtn",
            "showHiddenBtn",
            "pauseBtn",
            "hideBtn",
            "rename-session",
            "resetSessionTitle",
            "hideSession(",
            "unhideSession(",
            "诊断",
            "已隐藏",
            "暂停",
            "暂隐",
            "重命名",
            "恢复默认名",
        ]
        for text in forbidden:
            self.assertNotIn(text, HTML)

    def test_load_handles_backend_connection_errors(self):
        self.assertIn("catch (_error)", HTML)
        self.assertIn("连接中断", HTML)
        self.assertIn("setTimeout(load, POLL_INTERVAL_MS)", HTML)

    def test_web_poll_interval_supports_five_second_needs_action_visibility(self):
        match = re.search(r"const POLL_INTERVAL_MS = (\d+);", HTML)

        self.assertIsNotNone(match)
        self.assertLessEqual(int(match.group(1)), 5000)

    def test_badge_supports_three_status_colors_and_priority(self):
        self.assertIn("badge-needs-action", HTML)
        self.assertIn("badge-running", HTML)
        self.assertIn("badge-idle", HTML)
        self.assertIn("badgeState", HTML)
        self.assertIn("needs_action", HTML)
        self.assertIn("running", HTML)
        self.assertIn("idle", HTML)

    def test_needs_action_alert_mark_is_small_and_away_from_badge(self):
        alert_rule = _css_rule(".pet-alert-card")
        badge_rule = _css_rule(".pet-badge")

        alert_left = _css_px(alert_rule, "left")
        alert_width = _css_px(alert_rule, "width")
        alert_height = _css_px(alert_rule, "height")
        alert_font_size = _css_px(alert_rule, "font-size")

        self.assertLessEqual(alert_width, 18)
        self.assertLessEqual(alert_height, 18)
        self.assertLessEqual(alert_font_size, 12)
        self.assertLess(alert_left + alert_width, 58)
        self.assertIn("right:", badge_rule)

    def test_status_indicators_use_distinct_positions(self):
        alert_rule = _css_rule(".pet-alert-card")
        dots_rule = _css_rule(".pet-typing-dots")
        nap_rule = _css_rule(".pet-nap-mark")

        self.assertIn("left:", alert_rule)
        self.assertIn("bottom:", dots_rule)
        self.assertIn("right:", nap_rule)
        self.assertIn(".pet.needs-action .pet-alert-card", HTML)
        self.assertIn(".pet.running .pet-typing-dots", HTML)
        self.assertIn(".pet.idle .pet-nap-mark", HTML)

    def test_process_only_sessions_render_as_running_without_user_facing_basic_detection_copy(self):
        self.assertIn("monitoring_level === \"process_only\"", HTML)
        self.assertNotIn('if (session.monitoring_level === "process_only") return "idle";', HTML)
        self.assertNotIn("弱识别 ·", HTML)
        self.assertNotIn("仅确认 CLI 会话存在", HTML)
        self.assertNotIn("仅确认桌面应用存在", HTML)
        self.assertNotIn("用 wrapper 启动可准确监控", HTML)
        self.assertNotIn("showWrapperGuide", HTML)

    def test_folder_names_keep_hyphenated_project_names(self):
        self.assertIn("split(/\\s+-\\s+/)", HTML)
        self.assertIn(r'.replace(/^[-·:|\s]+/, "")', HTML)
        self.assertNotIn(".split(\"-\")", HTML)

    def test_pet_focus_does_not_show_rectangular_browser_outline(self):
        self.assertIn(".pet:focus { outline: none; }", HTML)
        self.assertIn(".pet:focus-visible .pet-focus-ring", HTML)

    def test_pet_click_toggles_bubble_list(self):
        self.assertIn("toggleBubbleList", HTML)
        self.assertIn('bubbleList.classList.toggle("open", willOpen)', HTML)
        self.assertIn("pet.onclick = () => {", HTML)
        self.assertIn("toggleBubbleList();", HTML)
        click_handler = re.search(r"pet\.onclick = \(\) => \{(?P<body>.*?)\n\};", HTML, re.S)
        self.assertIsNotNone(click_handler)
        self.assertIn("toggleBubbleList();", click_handler.group("body"))
        self.assertNotIn("hidePet", click_handler.group("body"))
        self.assertNotIn('postHostMessage("hide")', click_handler.group("body"))

    def test_native_compact_toggle_restores_pet_position_instead_of_hiding(self):
        self.assertIn("const willOpen = !bubbleList.classList.contains(\"open\");", HTML)
        self.assertIn('if (!willOpen && hasHostWindow()) resetPetDomPosition();', HTML)
        self.assertIn('resizeHostWindow(willOpen ? "bubbles" : "compact");', HTML)
        toggle_handler = re.search(r"function toggleBubbleList\(\) \{(?P<body>.*?)\n\}", HTML, re.S)
        self.assertIsNotNone(toggle_handler)
        self.assertIn("resetPetDomPosition();", toggle_handler.group("body"))
        self.assertNotIn('postHostMessage("hide")', toggle_handler.group("body"))
        self.assertNotIn("pet.style.display = \"none\"", toggle_handler.group("body"))

    def test_host_show_restores_pet_dom_state(self):
        self.assertIn("window.restorePetFromHost = restorePetFromHost;", HTML)
        self.assertIn("function restorePetFromHost()", HTML)
        self.assertIn("pet.style.display = \"\";", HTML)
        self.assertIn('bubbleList.classList.remove("open");', HTML)
        self.assertIn("closePetContextMenu();", HTML)
        self.assertIn("resetPetDomPosition();", HTML)

    def test_bubble_click_focuses_session_without_safe_actions(self):
        self.assertIn("/api/focus", HTML)
        self.assertIn("focusSessionFromButton(button)", HTML)
        self.assertIn('postHostMessage("focus"', HTML)
        self.assertIn("/api/session-viewed", HTML)
        self.assertIn("markSessionViewed(result.session_id)", HTML)
        self.assertNotIn("/api/action", HTML)
        self.assertNotIn("safe_action.options", HTML)
        self.assertNotIn("sendAction", HTML)

    def test_focus_failure_shows_lightweight_note_without_diagnostics(self):
        focus_fn = re.search(r"async function focusSession\(sessionId\) \{(?P<body>.*?)\n\}", HTML, re.S)
        self.assertIsNotNone(focus_fn)
        self.assertIn('showStatusNote("无法定位窗口")', focus_fn.group("body"))
        self.assertNotIn("doctor", focus_fn.group("body").lower())
        self.assertNotIn("诊断", focus_fn.group("body"))
        self.assertIn('showStatusNote("请允许辅助功能权限")', HTML)

    def test_bubbles_do_not_render_summary(self):
        self.assertNotIn("session.summary", HTML)
        self.assertNotIn('class="summary"', HTML)

    def test_session_bubbles_only_render_title_line_in_main_path(self):
        self.assertNotIn("processOnlyMeta(session)", HTML)
        self.assertNotIn("const metaHtml = meta ?", HTML)
        self.assertNotIn("${metaHtml}", HTML)

    def test_pet_context_menu_has_hide_and_quit(self):
        self.assertIn("contextmenu", HTML)
        self.assertIn('id="petContextMenu"', HTML)
        self.assertIn("隐藏 Pet", HTML)
        self.assertIn("退出程序", HTML)
        self.assertIn("hidePet", HTML)
        self.assertIn("quitApp", HTML)

    def test_pet_context_menu_uses_compact_visual_size(self):
        self.assertIn("min-width: 108px", HTML)
        self.assertIn(".pet-context-menu {", HTML)
        self.assertIn(".pet-context-menu button", HTML)
        self.assertIn("font-size: 13px", HTML)
        self.assertIn("padding: 5px 7px", HTML)
        self.assertNotIn("min-width: 128px", HTML)

    def test_hide_pet_does_not_call_session_hide_api(self):
        self.assertNotIn("/api/hide-session", HTML)
        self.assertIn('postHostMessage("hide")', HTML)
        self.assertIn('postHostMessage("quit")', HTML)

    def test_bubble_labels_distinguish_same_folder_sessions(self):
        self.assertIn("bubbleLabel", HTML)
        self.assertIn("sessionSequenceByGroup", HTML)
        self.assertIn("prepareBubbleSequences(sessions)", HTML)
        self.assertIn("sequenceSortKey", HTML)
        self.assertIn("session.session_id", HTML)
        self.assertIn("liveGroups", HTML)
        self.assertIn("sessionSequenceByGroup.delete(group)", HTML)
        self.assertIn("if (!liveIds.has(sessionId)) groupMap.delete(sessionId);", HTML)
        self.assertIn("sorted.map(session => sessionBubbleHtml(session, sessions))", HTML)
        self.assertIn("folderName", HTML)


def _css_rule(selector: str) -> str:
    match = re.search(rf"{re.escape(selector)} \{{(?P<body>.*?)\}}", HTML, re.S)
    if match is None:
        raise AssertionError(f"Missing CSS rule for {selector}")
    return match.group("body")


def _css_px(rule: str, property_name: str) -> int:
    match = re.search(rf"{re.escape(property_name)}:\s*(\d+)px", rule)
    if match is None:
        raise AssertionError(f"Missing {property_name} px value in {rule}")
    return int(match.group(1))


def _read_rgba_png(path: Path):
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise AssertionError("not a PNG")
    offset = 8
    width = height = None
    bit_depth = color_type = interlace = None
    idat = []
    while offset < len(data):
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        chunk_type = data[offset + 4 : offset + 8]
        chunk_data = data[offset + 8 : offset + 8 + length]
        offset += 12 + length
        if chunk_type == b"IHDR":
            width, height, bit_depth, color_type, _compression, _filter, interlace = struct.unpack(">IIBBBBB", chunk_data)
        elif chunk_type == b"IDAT":
            idat.append(chunk_data)
        elif chunk_type == b"IEND":
            break
    if bit_depth != 8 or color_type != 6 or interlace != 0:
        raise AssertionError("expected non-interlaced 8-bit RGBA PNG")
    raw = zlib.decompress(b"".join(idat))
    stride = width * 4
    rows = []
    previous = bytearray(stride)
    cursor = 0
    for _row in range(height):
        filter_type = raw[cursor]
        cursor += 1
        row = bytearray(raw[cursor : cursor + stride])
        cursor += stride
        _unfilter_png_row(row, previous, filter_type, 4)
        rows.append(bytes(row))
        previous = row
    return width, height, b"".join(rows)


def _unfilter_png_row(row: bytearray, previous: bytearray, filter_type: int, bytes_per_pixel: int) -> None:
    if filter_type == 0:
        return
    for index in range(len(row)):
        left = row[index - bytes_per_pixel] if index >= bytes_per_pixel else 0
        up = previous[index]
        upper_left = previous[index - bytes_per_pixel] if index >= bytes_per_pixel else 0
        if filter_type == 1:
            row[index] = (row[index] + left) & 0xFF
        elif filter_type == 2:
            row[index] = (row[index] + up) & 0xFF
        elif filter_type == 3:
            row[index] = (row[index] + ((left + up) // 2)) & 0xFF
        elif filter_type == 4:
            row[index] = (row[index] + _paeth(left, up, upper_left)) & 0xFF
        else:
            raise AssertionError(f"unsupported PNG filter: {filter_type}")


def _paeth(left: int, up: int, upper_left: int) -> int:
    predictor = left + up - upper_left
    left_distance = abs(predictor - left)
    up_distance = abs(predictor - up)
    upper_left_distance = abs(predictor - upper_left)
    if left_distance <= up_distance and left_distance <= upper_left_distance:
        return left
    if up_distance <= upper_left_distance:
        return up
    return upper_left


if __name__ == "__main__":
    unittest.main()
