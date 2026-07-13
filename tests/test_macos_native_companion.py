import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def native_sources() -> str:
    macos = ROOT / "native" / "macos"
    return "\n".join(
        [
            (macos / "FloatingMonitor.swift").read_text(),
            (macos / "FloatingMonitorGeometry.swift").read_text(),
        ]
    )


class MacOSNativeCompanionTests(unittest.TestCase):
    def test_native_companion_is_floating_and_restorable(self):
        source = native_sources()

        self.assertIn("NSStatusBar.system.statusItem", source)
        self.assertIn("window.level = .floating", source)
        self.assertIn("styleMask: [.borderless, .nonactivatingPanel]", source)
        self.assertIn("window.backgroundColor = .clear", source)
        self.assertIn("window.isOpaque = false", source)
        self.assertIn('webView.setValue(false, forKey: "drawsBackground")', source)
        self.assertIn("WKScriptMessageHandler", source)
        self.assertIn("WKNavigationDelegate", source)
        self.assertIn('configuration.userContentController.add(self, name: "monitorWindow")', source)
        self.assertIn("webView.navigationDelegate = self", source)
        self.assertIn("resizeWindow(width:", source)
        self.assertIn("let width: CGFloat = 170", source)
        self.assertIn("let height: CGFloat = 150", source)
        self.assertIn("width: width, height: height", source)
        self.assertIn("NSScreen.main", source)
        self.assertIn("monitorFrame(width: width, height: height)", source)
        self.assertIn("selectedScreenVisibleFrame()", source)
        self.assertIn("NSEvent.mouseLocation", source)
        self.assertIn("NSMouseInRect(point", source)
        self.assertIn("FloatingMonitorGeometry.monitorFrame", source)
        self.assertIn("visibleFrame.maxX - clampedWidth - margin", source)
        self.assertIn("visibleFrame.minY + margin", source)
        self.assertIn("func windowShouldClose", source)
        self.assertIn("sender.orderOut(nil)", source)
        self.assertIn("Show Monitor", source)
        self.assertIn("#selector(showMonitorFromMenu)", source)
        self.assertIn("Quit", source)

    def test_status_menu_items_target_app_delegate_directly(self):
        source = native_sources()

        self.assertIn("statusItem.menu = menu", source)
        self.assertNotIn("statusItem.button?.action = #selector(showMonitorFromMenu)", source)
        self.assertNotIn("statusItem.button?.sendAction", source)
        self.assertIn('let showItem = NSMenuItem(title: "Show Monitor", action: #selector(showMonitorFromMenu), keyEquivalent: "")', source)
        self.assertIn("showItem.target = self", source)
        self.assertIn("menu.addItem(showItem)", source)
        self.assertIn('let quitItem = NSMenuItem(title: "Quit", action: #selector(quit), keyEquivalent: "q")', source)
        self.assertIn("quitItem.target = self", source)
        self.assertIn("menu.addItem(quitItem)", source)

    def test_status_item_uses_app_avatar_image_not_ai_text(self):
        source = native_sources()

        self.assertIn("NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)", source)
        self.assertIn("menuBarIconImage()", source)
        self.assertIn('Bundle.main.url(forResource: "app-avatar", withExtension: "png")', source)
        self.assertIn("button.image = image", source)
        self.assertIn("button.imagePosition = .imageOnly", source)
        self.assertIn('button.title = ""', source)
        self.assertNotIn('statusItem.button?.title = "AI"', source)

    def test_native_companion_verifies_pet_after_webview_loads(self):
        source = native_sources()

        self.assertIn("func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!)", source)
        self.assertIn("WebView finished loading", source)
        self.assertIn("resizeWindow(width: 170, height: 150)", source)
        self.assertIn("resizedFrame(width: width, height: height)", source)
        self.assertIn("let currentFrame = window.frame", source)
        self.assertIn("showMonitor()", source)
        self.assertIn("document.querySelector('#pet')", source)
        self.assertIn("document.querySelector('.pet-art')", source)
        self.assertIn("Pet visibility check", source)

    def test_native_companion_handles_pet_hide_and_quit_messages(self):
        source = native_sources()

        self.assertIn('payload["type"] as? String', source)
        self.assertIn('case "focus"', source)
        self.assertIn("handleFocusMessage(payload)", source)
        self.assertIn('case "start-window-drag"', source)
        self.assertIn("startWindowDrag()", source)
        self.assertIn('case "stop-window-drag"', source)
        self.assertIn("stopWindowDrag()", source)
        self.assertIn('case "window-drag"', source)
        self.assertIn("moveWindowByBrowserDelta(deltaX:", source)
        self.assertIn("Timer(timeInterval: 1.0 / 60.0", source)
        self.assertIn("NSEvent.pressedMouseButtons", source)
        self.assertIn("NSEvent.mouseLocation", source)
        self.assertIn("moveWindowByScreenDelta", source)
        self.assertIn("window.setFrameOrigin", source)
        self.assertIn("Started window drag", source)
        self.assertIn("Stopped window drag", source)
        self.assertIn("Moved window frame", source)
        self.assertIn("dragScreenFrame(for:", source)
        self.assertIn("screenFrameContaining(point:", source)
        self.assertIn("frame.origin.x + deltaX", source)
        self.assertIn("moveWindowByScreenDelta(deltaX: deltaX, deltaY: -deltaY)", source)
        self.assertIn("frame.origin.y + deltaY", source)
        self.assertIn('case "hide"', source)
        self.assertIn("hideMonitor()", source)
        self.assertIn('case "quit"', source)
        self.assertIn("quit()", source)
        self.assertIn("@objc private func hideMonitor()", source)
        self.assertIn("stopWindowDrag()", source)
        self.assertIn("window.orderOut(nil)", source)
        self.assertIn("monitorProcess?.terminate()", source)

    def test_native_focus_uses_accessibility_api_for_specific_ide_window(self):
        source = native_sources()

        self.assertIn("import ApplicationServices", source)
        self.assertIn("AXIsProcessTrustedWithOptions", source)
        self.assertIn("AXUIElementCreateApplication", source)
        self.assertIn("kAXWindowsAttribute", source)
        self.assertIn("kAXTitleAttribute", source)
        self.assertIn("AXUIElementPerformAction(window, kAXRaiseAction as CFString)", source)
        self.assertIn("focused-project-window", source)
        self.assertIn("focused-title-window", source)
        self.assertIn("window.onHostFocusResult", source)
        self.assertIn("accessibility-permission-required", source)
        self.assertIn("openAccessibilitySettings()", source)
        self.assertIn("Privacy_Accessibility", source)
        self.assertIn('writeLog("Opened accessibility settings")', source)

    def test_native_focus_prefers_exact_window_id_before_folder_or_title(self):
        source = native_sources()

        self.assertIn('windowID: payload["window_id"] as? String ?? ""', source)
        self.assertIn("private func focusTargetWindow(windowID: String", source)
        self.assertIn("let cleanWindowID = windowID.trimmingCharacters", source)
        self.assertIn("accessibilityWindowNumber(for: window) == cleanWindowID", source)
        self.assertIn('"AXWindowNumber" as CFString', source)
        self.assertIn('return raise(window: window, app: app, appElement: appElement, detail: "focused-window-id")', source)
        self.assertLess(source.index("accessibilityWindowNumber(for: window)"), source.index("let folderName = URL(fileURLWithPath: cwd).lastPathComponent"))

    def test_native_focus_matches_common_ide_name_variants(self):
        source = native_sources()

        self.assertIn("prefixMatchedAppNameTargets", source)
        for app_name in [
            "android studio",
            "clion",
            "goland",
            "intellij idea",
            "phpstorm",
            "pycharm",
            "rider",
            "rubymine",
            "sublime text",
            "visual studio code",
            "webstorm",
        ]:
            self.assertIn(f'"{app_name}"', source)
        self.assertIn('target == "visual studio code"', source)
        self.assertIn('candidate == "code"', source)
        self.assertIn("candidate.hasPrefix", source)

    def test_native_focus_tries_all_matching_apps_before_window_list_failure(self):
        source = native_sources()

        self.assertIn("private func runningApplications(processID: Int32?, appName: String) -> [NSRunningApplication]", source)
        self.assertIn("for app in apps", source)
        self.assertIn("var sawWindowListFailure = false", source)
        self.assertIn("sawWindowListFailure = true", source)
        self.assertIn("continue", source)
        self.assertIn('return (false, "window-list-unavailable")', source)

    def test_native_focus_only_activates_ai_desktop_apps_as_last_resort(self):
        source = native_sources()

        self.assertIn("private func isDesktopAIApp(_ appName: String) -> Bool", source)
        self.assertIn("let aiDesktopApps: Set<String>", source)
        for app_name in ["claude", "codex", "chatgpt", "gemini", "perplexity", "poe", "workbuddy", "qoder", "qoder cn"]:
            self.assertIn(f'"{app_name}"', source)
        self.assertIn("private func activateRunningApplication", source)
        self.assertIn("app.activate(options: [])", source)
        self.assertIn('return (true, "activated-app")', source)
        self.assertIn("if isDesktopAIApp(appName), let app = apps.first", source)

    def test_native_focus_matches_qoder_cn_when_payload_uses_qoder_display_name(self):
        source = native_sources()

        self.assertIn("private func appNameAliases(for target: String) -> Set<String>", source)
        self.assertIn('if target == "qoder"', source)
        self.assertIn('return ["qoder", "qoder cn"]', source)
        self.assertIn("for alias in appNameAliases(for: normalizedTarget)", source)
        self.assertIn("appNameMatches(candidate: localized, target: alias)", source)
        self.assertIn("appNameMatches(candidate: bundleName, target: alias)", source)

    def test_native_focus_activates_target_app_and_reraises_specific_window(self):
        source = native_sources()

        self.assertIn("private func raise(window: AXUIElement, app: NSRunningApplication, appElement: AXUIElement, detail: String)", source)
        self.assertIn("AXUIElementSetAttributeValue(appElement, kAXFocusedWindowAttribute as CFString, window)", source)
        self.assertIn("AXUIElementSetAttributeValue(window, kAXMainAttribute as CFString, kCFBooleanTrue)", source)
        self.assertIn("let activateResult = activateRunningApplication(app)", source)
        self.assertIn("guard activateResult.ok else", source)
        self.assertIn("AXUIElementPerformAction(window, kAXRaiseAction as CFString)", source)
        self.assertGreater(source.count("AXUIElementPerformAction(window, kAXRaiseAction as CFString)"), 1)

    def test_native_focus_success_compacts_pet_without_showing_error(self):
        source = native_sources()
        focus_body = source[source.index("private func handleFocusMessage") :]
        focus_body = focus_body[: focus_body.index("private func focusTargetWindow")]

        self.assertIn("if result.ok", focus_body)
        self.assertIn("restorePetWebState()", focus_body)
        self.assertIn("let sessionID = payload[\"session_id\"] as? String ?? \"\"", focus_body)
        self.assertIn("sendHostFocusResult(ok: result.ok, detail: result.detail, sessionID: sessionID)", focus_body)
        self.assertIn('"session_id": sessionID', source)

    def test_native_focus_does_not_treat_pet_as_the_obstructing_window(self):
        source = native_sources()

        self.assertNotIn("private func tuckPetBehindFocusedWindow", source)
        self.assertNotIn("Tucked pet behind focused window", source)
        self.assertNotIn("window.level = .normal", source)

    def test_native_show_monitor_restores_floating_pet_level(self):
        source = native_sources()
        show_body = source[source.index("@objc private func showMonitor()") :]
        show_body = show_body[: show_body.index("@objc private func showMonitorFromMenu()")]

        self.assertIn("window.level = .floating", show_body)
        self.assertIn("window.orderFrontRegardless()", show_body)

    def test_native_hide_keeps_monitor_process_running_and_quit_terminates_it(self):
        source = native_sources()
        hide_body = source[source.index("@objc private func hideMonitor()") :]
        hide_body = hide_body[: hide_body.index("@objc private func quit()")]
        quit_body = source[source.index("@objc private func quit()") :]
        quit_body = quit_body[: quit_body.index("}\n}")]
        terminate_body = source[source.index("func applicationWillTerminate") :]
        terminate_body = terminate_body[: terminate_body.index("func applicationShouldHandleReopen")]

        self.assertIn("window.orderOut(nil)", hide_body)
        self.assertNotIn("monitorProcess?.terminate()", hide_body)
        self.assertNotIn("NSApp.terminate(nil)", hide_body)
        self.assertIn("NSApp.terminate(nil)", quit_body)
        self.assertIn("monitorProcess?.terminate()", terminate_body)

    def test_native_drag_can_cross_external_displays(self):
        source = native_sources()

        self.assertIn("private func dragScreenFrame(for mouseLocation: NSPoint, proposedFrame: NSRect) -> NSRect", source)
        self.assertIn("FloatingMonitorGeometry.screenFrame", source)
        self.assertIn("screenFrames: NSScreen.screens.map { $0.frame }", source)
        self.assertIn("let proposedFrame = frame.offsetBy(dx: deltaX, dy: deltaY)", source)
        self.assertIn("moveWindowByScreenDelta(deltaX: deltaX, deltaY: deltaY, mouseLocation: current)", source)
        move_fn = source[source.index("private func moveWindowByScreenDelta"):]
        move_fn = move_fn[:move_fn.index("private func resizedFrame")]
        self.assertNotIn("window.screen?.visibleFrame ?? selectedScreenVisibleFrame()", move_fn)

    def test_native_drag_bounds_use_pet_size_not_large_bubble_window(self):
        source = native_sources()

        self.assertIn("private let compactWindowWidth: CGFloat = 170", source)
        self.assertIn("private let compactWindowHeight: CGFloat = 150", source)
        self.assertIn("FloatingMonitorGeometry.draggedFrame", source)
        self.assertIn("compactSize: compactWindowSize", source)
        self.assertIn("let dragWidth = min(frame.width, compactSize.width)", source)
        self.assertIn("let dragHeight = min(frame.height, compactSize.height)", source)
        self.assertIn("min: screenFrame.minX - (frame.width - dragWidth)", source)
        self.assertIn("max: screenFrame.maxX - frame.width", source)
        self.assertIn("min: screenFrame.minY", source)
        self.assertIn("max: screenFrame.maxY - dragHeight", source)

    def test_native_resize_keeps_pet_anchored_to_bottom_right(self):
        source = native_sources()

        resized_fn = source[source.index("private func resizedFrame"):]
        resized_fn = resized_fn[:resized_fn.index("private func monitorFrame")]
        self.assertIn("FloatingMonitorGeometry.resizedFrame", resized_fn)
        self.assertIn("currentFrame: currentFrame", resized_fn)
        self.assertIn("compactSize: compactWindowSize", resized_fn)
        self.assertIn("currentFrame.maxX - clampedWidth", source)
        self.assertIn("currentFrame.minY", source)
        self.assertNotIn("currentOrigin", resized_fn)

    def test_native_resize_does_not_animate_pet_window(self):
        source = native_sources()

        self.assertIn("window.setFrame(resizedFrame(width: width, height: height), display: true, animate: false)", source)
        self.assertIn("window.setFrame(restoredFrame, display: true, animate: false)", source)

    def test_native_resize_does_not_force_pet_window_to_front(self):
        source = native_sources()
        resize_fn = source[source.index("private func resizeWindow"):]
        resize_fn = resize_fn[:resize_fn.index("private func restorePetWebState")]

        self.assertIn("window.setFrame(resizedFrame(width: width, height: height), display: true, animate: false)", resize_fn)
        self.assertNotIn("window.orderFrontRegardless()", resize_fn)

    def test_native_show_restores_hidden_or_offscreen_pet_to_current_screen(self):
        source = native_sources()

        self.assertIn("func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool", source)
        self.assertIn('writeLog("Reopen requested")', source)
        self.assertIn("showMonitorFromMenu()", source)
        self.assertIn("return false", source)
        self.assertIn("@objc private func showMonitorFromMenu()", source)
        self.assertIn("restoreMonitorToCurrentScreen()", source)
        self.assertIn("private func isFrameVisible(_ frame: NSRect) -> Bool", source)
        self.assertIn("visibleFrame.intersects(frame)", source)
        self.assertIn("if !isFrameVisible(window.frame)", source)
        self.assertIn("Restored monitor frame", source)
        self.assertIn("let currentFrame = window.frame", source)
        self.assertIn("let visibleFrame = isFrameVisible(currentFrame)", source)
        self.assertIn("? visibleFrameForFrame(currentFrame)", source)
        self.assertIn(": selectedScreenVisibleFrame()", source)
        self.assertIn("window.setFrame(restoredFrame", source)
        self.assertIn("NSApp.unhide(nil)", source)
        self.assertIn('writeLog("Show monitor completed frame: \\(window.frame)")', source)

    def test_native_menu_show_resets_web_pet_state_and_compact_size(self):
        source = native_sources()

        self.assertIn("private func restorePetWebState()", source)
        self.assertIn("window.restorePetFromHost", source)
        self.assertIn("restorePetWebState()", source)
        self.assertIn("resizeWindow(width: 170, height: 150)", source)
        show_menu = source[source.index("@objc private func showMonitorFromMenu()"):]
        show_menu = show_menu[:show_menu.index("@objc private func hideMonitor()")]
        self.assertIn("stopWindowDrag()", show_menu)
        self.assertIn("resizeWindow(width: 170, height: 150)", show_menu)
        self.assertIn("restoreMonitorToCurrentScreen()", show_menu)
        self.assertIn("restorePetWebState()", show_menu)
        self.assertIn("showMonitor()", show_menu)

    def test_native_logs_host_messages_for_hide_resize_debugging(self):
        source = native_sources()

        self.assertIn('writeLog("Received host message: \\(type)")', source)
        self.assertIn('writeLog("Received host resize mode: \\(mode)")', source)
        self.assertIn('rawMode == "menu"', source)

    def test_native_menu_actions_are_logged_for_show_hide_and_quit(self):
        source = native_sources()

        self.assertIn('writeLog("Show monitor requested")', source)
        self.assertIn('writeLog("Show monitor requested from menu")', source)
        self.assertIn('writeLog("Hide monitor requested")', source)
        self.assertIn('writeLog("Quit requested")', source)

    def test_native_companion_loads_local_monitor_url(self):
        source = native_sources()

        self.assertIn("AI Progress Monitor running at", source)
        self.assertIn("webView.load", source)
        self.assertIn("ai-progress-monitor.pyz", source)

    def test_native_companion_keeps_window_scanning_enabled_by_default(self):
        source = native_sources()

        self.assertNotIn('"--no-windows"', source)

    def test_release_build_uses_writable_swift_module_caches(self):
        source = (ROOT / "scripts" / "build_release.py").read_text()

        self.assertIn("CLANG_MODULE_CACHE_PATH", source)
        self.assertIn("SWIFT_MODULE_CACHE_PATH", source)
        self.assertIn("/private/tmp/ai-progress-monitor-clang-cache", source)
        self.assertIn("/private/tmp/ai-progress-monitor-swift-cache", source)


if __name__ == "__main__":
    unittest.main()
