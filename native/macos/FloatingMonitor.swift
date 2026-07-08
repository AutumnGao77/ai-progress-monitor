import Cocoa
import ApplicationServices
import WebKit

final class AppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate, WKNavigationDelegate, WKScriptMessageHandler {
    private var window: NSPanel!
    private var webView: WKWebView!
    private var statusItem: NSStatusItem!
    private var monitorProcess: Process?
    private var stdoutPipe: Pipe?
    private var stderrPipe: Pipe?
    private var logHandle: FileHandle?
    private var dragTimer: Timer?
    private var lastDragMouseLocation: NSPoint?
    private let compactWindowWidth: CGFloat = 170
    private let compactWindowHeight: CGFloat = 150
    private var compactWindowSize: NSSize {
        NSSize(width: compactWindowWidth, height: compactWindowHeight)
    }
    private let prefixMatchedAppNameTargets: Set<String> = [
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
    ]

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)
        setupLogging()
        setupStatusItem()
        setupWindow()
        startMonitor()
    }

    func applicationWillTerminate(_ notification: Notification) {
        stopWindowDrag()
        monitorProcess?.terminate()
        logHandle?.closeFile()
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        writeLog("Reopen requested")
        showMonitorFromMenu()
        return false
    }

    func windowShouldClose(_ sender: NSWindow) -> Bool {
        sender.orderOut(nil)
        return false
    }

    private func setupLogging() {
        let logs = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Logs/AI Progress Monitor", isDirectory: true)
        try? FileManager.default.createDirectory(at: logs, withIntermediateDirectories: true)
        let logURL = logs.appendingPathComponent("native-monitor.log")
        FileManager.default.createFile(atPath: logURL.path, contents: nil)
        logHandle = try? FileHandle(forWritingTo: logURL)
        logHandle?.seekToEndOfFile()
        writeLog("Starting native companion")
    }

    private func setupStatusItem() {
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        if let button = statusItem.button {
            if let image = menuBarIconImage() {
                button.image = image
                button.imagePosition = .imageOnly
                button.title = ""
            } else {
                button.title = "AI"
            }
            button.toolTip = "AI Progress Monitor"
        }
        let menu = NSMenu()
        let showItem = NSMenuItem(title: "Show Monitor", action: #selector(showMonitorFromMenu), keyEquivalent: "")
        showItem.target = self
        menu.addItem(showItem)
        menu.addItem(NSMenuItem.separator())
        let quitItem = NSMenuItem(title: "Quit", action: #selector(quit), keyEquivalent: "q")
        quitItem.target = self
        menu.addItem(quitItem)
        statusItem.menu = menu
    }

    private func menuBarIconImage() -> NSImage? {
        guard let url = Bundle.main.url(forResource: "app-avatar", withExtension: "png"),
              let image = NSImage(contentsOf: url) else {
            return nil
        }
        image.size = NSSize(width: 18, height: 18)
        image.isTemplate = false
        return image
    }

    private func setupWindow() {
        let configuration = WKWebViewConfiguration()
        configuration.userContentController.add(self, name: "monitorWindow")
        webView = WKWebView(frame: .zero, configuration: configuration)
        webView.navigationDelegate = self
        webView.setValue(false, forKey: "drawsBackground")
        let width: CGFloat = 170
        let height: CGFloat = 150
        let frame = monitorFrame(width: width, height: height)
        window = NSPanel(
            contentRect: frame,
            styleMask: [.borderless, .nonactivatingPanel],
            backing: .buffered,
            defer: false
        )
        window.title = "AI Progress Monitor"
        window.contentView = webView
        window.delegate = self
        window.backgroundColor = .clear
        window.isOpaque = false
        window.hasShadow = false
        window.isReleasedWhenClosed = false
        window.level = .floating
        window.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        window.orderFrontRegardless()
        writeLog("Initial window frame: \(window.frame)")
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        writeLog("WebView finished loading")
        resizeWindow(width: 170, height: 150)
        showMonitor()
        let script = """
        (() => {
          const pet = document.querySelector('#pet');
          const img = document.querySelector('.pet-art');
          if (!pet || !img) return 'pet-missing';
          const rect = pet.getBoundingClientRect();
          return JSON.stringify({
            petWidth: Math.round(rect.width),
            petHeight: Math.round(rect.height),
            imageComplete: img.complete,
            naturalWidth: img.naturalWidth,
            naturalHeight: img.naturalHeight,
            petDisplay: getComputedStyle(pet).display
          });
        })()
        """
        webView.evaluateJavaScript(script) { [weak self] result, error in
            if let error = error {
                self?.writeLog("Pet visibility check failed: \(error)")
                return
            }
            self?.writeLog("Pet visibility check: \(String(describing: result))")
        }
    }

    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        guard message.name == "monitorWindow" else { return }
        guard let payload = message.body as? [String: Any] else { return }
        guard let type = payload["type"] as? String else { return }
        writeLog("Received host message: \(type)")
        switch type {
        case "resize":
            let rawMode = payload["mode"] as? String
            let mode = (rawMode == "compact" || rawMode == "bubbles") ? rawMode! : "unknown"
            writeLog("Received host resize mode: \(mode)")
            guard let width = payload["width"] as? NSNumber, let height = payload["height"] as? NSNumber else { return }
            resizeWindow(width: CGFloat(truncating: width), height: CGFloat(truncating: height))
        case "focus":
            handleFocusMessage(payload)
        case "start-window-drag":
            startWindowDrag()
        case "stop-window-drag":
            stopWindowDrag()
        case "window-drag":
            guard let deltaX = payload["deltaX"] as? NSNumber, let deltaY = payload["deltaY"] as? NSNumber else { return }
            moveWindowByBrowserDelta(deltaX: CGFloat(truncating: deltaX), deltaY: CGFloat(truncating: deltaY))
        case "hide":
            hideMonitor()
        case "quit":
            quit()
        default:
            return
        }
    }

    private func handleFocusMessage(_ payload: [String: Any]) {
        writeLog("Native focus requested")
        let sessionID = payload["session_id"] as? String ?? ""
        let result = focusTargetWindow(
            windowID: payload["window_id"] as? String ?? "",
            title: payload["title"] as? String ?? "",
            processID: intValue(payload["process_id"]),
            appName: payload["app_name"] as? String ?? "",
            cwd: payload["cwd"] as? String ?? ""
        )
        writeLog("Native focus result: ok=\(result.ok) method=\(result.detail)")
        if result.detail == "accessibility-permission-required" {
            openAccessibilitySettings()
        }
        if result.ok {
            restorePetWebState()
        }
        sendHostFocusResult(ok: result.ok, detail: result.detail, sessionID: sessionID)
    }

    private func focusTargetWindow(windowID: String, title: String, processID: Int32?, appName: String, cwd: String) -> (ok: Bool, detail: String) {
        let options = [kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String: true] as CFDictionary
        guard AXIsProcessTrustedWithOptions(options) else {
            return (false, "accessibility-permission-required")
        }
        let apps = runningApplications(processID: processID, appName: appName)
        guard !apps.isEmpty else {
            return (false, "application-not-found")
        }
        let cleanWindowID = windowID.trimmingCharacters(in: .whitespacesAndNewlines)
        var sawWindowListFailure = false
        for app in apps {
            let appElement = AXUIElementCreateApplication(app.processIdentifier)
            guard let windows = accessibilityWindows(for: appElement) else {
                sawWindowListFailure = true
                continue
            }
            if let window = windows.first(where: { window in
                !cleanWindowID.isEmpty && accessibilityWindowNumber(for: window) == cleanWindowID
            }) {
                return raise(window: window, app: app, appElement: appElement, detail: "focused-window-id")
            }
            let folderName = URL(fileURLWithPath: cwd).lastPathComponent
            if let window = windows.first(where: { window in
                let windowTitle = accessibilityTitle(for: window)
                return !folderName.isEmpty && (windowTitle == folderName || windowTitle.contains(folderName))
            }) {
                return raise(window: window, app: app, appElement: appElement, detail: "focused-project-window")
            }
            if let window = windows.first(where: { window in
                let windowTitle = accessibilityTitle(for: window)
                return !title.isEmpty && windowTitle.contains(title)
            }) {
                return raise(window: window, app: app, appElement: appElement, detail: "focused-title-window")
            }
        }
        if isDesktopAIApp(appName), let app = apps.first {
            return activateRunningApplication(app)
        }
        if sawWindowListFailure {
            return (false, "window-list-unavailable")
        }
        return (false, "not-found")
    }

    private func runningApplications(processID: Int32?, appName: String) -> [NSRunningApplication] {
        var apps: [NSRunningApplication] = []
        var seen = Set<pid_t>()
        if let processID = processID, let app = NSRunningApplication(processIdentifier: pid_t(processID)) {
            apps.append(app)
            seen.insert(app.processIdentifier)
        }
        let normalizedTarget = normalizedAppName(appName)
        guard !normalizedTarget.isEmpty else { return apps }
        for app in NSWorkspace.shared.runningApplications {
            if seen.contains(app.processIdentifier) {
                continue
            }
            let localized = normalizedAppName(app.localizedName ?? "")
            let bundleName = normalizedAppName(app.bundleURL?.deletingPathExtension().lastPathComponent ?? "")
            if appNameMatches(candidate: localized, target: normalizedTarget)
                || appNameMatches(candidate: bundleName, target: normalizedTarget)
            {
                apps.append(app)
                seen.insert(app.processIdentifier)
            }
        }
        return apps
    }

    private func accessibilityWindows(for appElement: AXUIElement) -> [AXUIElement]? {
        var value: CFTypeRef?
        let result = AXUIElementCopyAttributeValue(appElement, kAXWindowsAttribute as CFString, &value)
        guard result == .success else { return nil }
        return value as? [AXUIElement]
    }

    private func accessibilityTitle(for window: AXUIElement) -> String {
        var value: CFTypeRef?
        guard AXUIElementCopyAttributeValue(window, kAXTitleAttribute as CFString, &value) == .success else {
            return ""
        }
        return value as? String ?? ""
    }

    private func accessibilityWindowNumber(for window: AXUIElement) -> String {
        var value: CFTypeRef?
        guard AXUIElementCopyAttributeValue(window, "AXWindowNumber" as CFString, &value) == .success else {
            return ""
        }
        if let number = value as? NSNumber {
            return number.stringValue
        }
        return value as? String ?? ""
    }

    private func raise(window: AXUIElement, app: NSRunningApplication, appElement: AXUIElement, detail: String) -> (ok: Bool, detail: String) {
        let result = AXUIElementPerformAction(window, kAXRaiseAction as CFString)
        guard result == .success else {
            return (false, "raise-failed")
        }
        AXUIElementSetAttributeValue(appElement, kAXFocusedWindowAttribute as CFString, window)
        AXUIElementSetAttributeValue(window, kAXMainAttribute as CFString, kCFBooleanTrue)
        let activateResult = activateRunningApplication(app)
        guard activateResult.ok else {
            return activateResult
        }
        AXUIElementPerformAction(window, kAXRaiseAction as CFString)
        return (true, detail)
    }

    private func activateRunningApplication(_ app: NSRunningApplication) -> (ok: Bool, detail: String) {
        if app.activate(options: []) {
            return (true, "activated-app")
        }
        return (false, "activate-failed")
    }

    private func sendHostFocusResult(ok: Bool, detail: String, sessionID: String) {
        let payload: [String: Any] = ["ok": ok, "detail": detail, "session_id": sessionID]
        guard let data = try? JSONSerialization.data(withJSONObject: payload),
              let json = String(data: data, encoding: .utf8) else {
            return
        }
        webView.evaluateJavaScript("window.onHostFocusResult && window.onHostFocusResult(\(json))") { [weak self] _result, error in
            if let error = error {
                self?.writeLog("Native focus callback failed: \(error)")
            }
        }
    }

    private func openAccessibilitySettings() {
        guard let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility") else {
            return
        }
        NSWorkspace.shared.open(url)
        writeLog("Opened accessibility settings")
    }

    private func intValue(_ value: Any?) -> Int32? {
        if let number = value as? NSNumber {
            return number.int32Value
        }
        if let text = value as? String, let int = Int32(text.trimmingCharacters(in: .whitespacesAndNewlines)) {
            return int
        }
        return nil
    }

    private func normalizedAppName(_ value: String) -> String {
        value.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
    }

    private func appNameMatches(candidate: String, target: String) -> Bool {
        if candidate == target {
            return true
        }
        if target == "visual studio code" && (candidate == "code" || candidate.hasPrefix("code - insiders")) {
            return true
        }
        return prefixMatchedAppNameTargets.contains(target) && candidate.hasPrefix(target)
    }

    private func isDesktopAIApp(_ appName: String) -> Bool {
        let normalized = normalizedAppName(appName)
        return normalized == "codex" || normalized == "claude"
    }

    private func resizeWindow(width: CGFloat, height: CGFloat) {
        window.setFrame(resizedFrame(width: width, height: height), display: true, animate: false)
        writeLog("Resized window frame: \(window.frame)")
    }

    private func restorePetWebState() {
        let script = "window.restorePetFromHost && window.restorePetFromHost()"
        webView.evaluateJavaScript(script) { [weak self] _result, error in
            if let error = error {
                self?.writeLog("Restore pet web state failed: \(error)")
                return
            }
            self?.writeLog("Restored pet web state")
        }
    }

    private func startWindowDrag() {
        lastDragMouseLocation = NSEvent.mouseLocation
        dragTimer?.invalidate()
        let timer = Timer(timeInterval: 1.0 / 60.0, repeats: true) { [weak self] _ in
            self?.continueWindowDrag()
        }
        dragTimer = timer
        RunLoop.main.add(timer, forMode: .common)
        writeLog("Started window drag")
    }

    private func continueWindowDrag() {
        guard NSEvent.pressedMouseButtons & 1 == 1 else {
            stopWindowDrag()
            return
        }
        let current = NSEvent.mouseLocation
        guard let last = lastDragMouseLocation else {
            lastDragMouseLocation = current
            return
        }
        let deltaX = current.x - last.x
        let deltaY = current.y - last.y
        lastDragMouseLocation = current
        if abs(deltaX) > 0.1 || abs(deltaY) > 0.1 {
            moveWindowByScreenDelta(deltaX: deltaX, deltaY: deltaY, mouseLocation: current)
        }
    }

    private func stopWindowDrag() {
        dragTimer?.invalidate()
        dragTimer = nil
        lastDragMouseLocation = nil
        writeLog("Stopped window drag")
    }

    private func moveWindowByBrowserDelta(deltaX: CGFloat, deltaY: CGFloat) {
        moveWindowByScreenDelta(deltaX: deltaX, deltaY: -deltaY)
    }

    private func moveWindowByScreenDelta(deltaX: CGFloat, deltaY: CGFloat, mouseLocation: NSPoint? = nil) {
        let frame = window.frame
        let proposedFrame = frame.offsetBy(dx: deltaX, dy: deltaY)
        let screenFrame = dragScreenFrame(for: mouseLocation ?? NSEvent.mouseLocation, proposedFrame: proposedFrame)
        let draggedFrame = FloatingMonitorGeometry.draggedFrame(
            frame: frame,
            deltaX: deltaX,
            deltaY: deltaY,
            screenFrame: screenFrame,
            compactSize: compactWindowSize
        )
        window.setFrameOrigin(draggedFrame.origin)
        writeLog("Moved window frame: \(window.frame)")
    }

    private func dragScreenFrame(for mouseLocation: NSPoint, proposedFrame: NSRect) -> NSRect {
        FloatingMonitorGeometry.screenFrame(
            mouseLocation: mouseLocation,
            proposedFrame: proposedFrame,
            screenFrames: NSScreen.screens.map { $0.frame },
            fallback: selectedScreenFrame()
        )
    }

    private func resizedFrame(width: CGFloat, height: CGFloat) -> NSRect {
        let currentFrame = window.frame
        let visibleFrame = isFrameVisible(currentFrame)
            ? visibleFrameForFrame(currentFrame)
            : selectedScreenVisibleFrame()
        return FloatingMonitorGeometry.resizedFrame(
            currentFrame: currentFrame,
            requestedSize: NSSize(width: width, height: height),
            visibleFrame: visibleFrame,
            compactSize: compactWindowSize
        )
    }

    private func monitorFrame(width: CGFloat, height: CGFloat) -> NSRect {
        let visibleFrame = selectedScreenVisibleFrame()
        writeLog("Selected screen visible frame: \(visibleFrame)")
        return FloatingMonitorGeometry.monitorFrame(
            requestedSize: NSSize(width: width, height: height),
            visibleFrame: visibleFrame
        )
    }

    private func selectedScreenVisibleFrame() -> NSRect {
        let mouseLocation = NSEvent.mouseLocation
        if let mouseFrame = visibleFrameContaining(point: mouseLocation) {
            return mouseFrame
        }
        if let keyScreen = NSApp.keyWindow?.screen {
            return keyScreen.visibleFrame
        }
        if let mainScreen = NSScreen.main {
            return mainScreen.visibleFrame
        }
        return NSRect(x: 0, y: 0, width: 1280, height: 800)
    }

    private func selectedScreenFrame() -> NSRect {
        let mouseLocation = NSEvent.mouseLocation
        if let mouseFrame = screenFrameContaining(point: mouseLocation) {
            return mouseFrame
        }
        if let keyScreen = NSApp.keyWindow?.screen {
            return keyScreen.frame
        }
        if let mainScreen = NSScreen.main {
            return mainScreen.frame
        }
        return NSRect(x: 0, y: 0, width: 1280, height: 800)
    }

    private func visibleFrameContaining(point: NSPoint) -> NSRect? {
        NSScreen.screens.first(where: { NSMouseInRect(point, $0.frame, false) })?.visibleFrame
    }

    private func screenFrameContaining(point: NSPoint) -> NSRect? {
        NSScreen.screens.first(where: { NSMouseInRect(point, $0.frame, false) })?.frame
    }

    private func visibleFrameForFrame(_ frame: NSRect) -> NSRect {
        visibleFrameMostIntersecting(frame) ?? selectedScreenVisibleFrame()
    }

    private func visibleFrameMostIntersecting(_ frame: NSRect) -> NSRect? {
        NSScreen.screens
            .map { screen in (screen.visibleFrame, FloatingMonitorGeometry.intersectionArea(screen.visibleFrame, frame)) }
            .filter { $0.1 > 0 }
            .max { $0.1 < $1.1 }?
            .0
    }

    private func isFrameVisible(_ frame: NSRect) -> Bool {
        NSScreen.screens.contains { screen in
            screen.visibleFrame.intersects(frame)
        }
    }

    private func restoreMonitorToCurrentScreen() {
        let currentFrame = window.frame
        let restoredWidth = currentFrame.width > 0 ? currentFrame.width : 170
        let restoredHeight = currentFrame.height > 0 ? currentFrame.height : 150
        let restoredFrame = monitorFrame(width: restoredWidth, height: restoredHeight)
        window.setFrame(restoredFrame, display: true, animate: false)
        writeLog("Restored monitor frame: \(window.frame)")
    }

    private func startMonitor() {
        guard let pyz = Bundle.main.resourceURL?.appendingPathComponent("ai-progress-monitor.pyz") else {
            writeLog("ai-progress-monitor.pyz not found")
            return
        }
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/env")
        process.arguments = ["python3", pyz.path, "--host", "127.0.0.1", "--port", "8765"]

        let out = Pipe()
        let err = Pipe()
        stdoutPipe = out
        stderrPipe = err
        process.standardOutput = out
        process.standardError = err
        out.fileHandleForReading.readabilityHandler = { [weak self] handle in
            self?.handleOutput(String(data: handle.availableData, encoding: .utf8) ?? "")
        }
        err.fileHandleForReading.readabilityHandler = { [weak self] handle in
            self?.writeLog(String(data: handle.availableData, encoding: .utf8) ?? "")
        }

        do {
            try process.run()
            monitorProcess = process
        } catch {
            writeLog("Failed to start monitor: \(error)")
        }
    }

    private func handleOutput(_ text: String) {
        guard !text.isEmpty else { return }
        writeLog(text)
        for line in text.split(separator: "\n") {
            guard line.contains("AI Progress Monitor running at") else { continue }
            guard let range = line.range(of: "http://") else { continue }
            let urlText = String(line[range.lowerBound...]).trimmingCharacters(in: .whitespacesAndNewlines)
            guard let url = URL(string: urlText) else { continue }
            DispatchQueue.main.async { [weak self] in
                self?.webView.load(URLRequest(url: url))
                self?.showMonitor()
            }
        }
    }

    private func writeLog(_ text: String) {
        guard let data = ("\(Date()) \(text)\n").data(using: .utf8) else { return }
        logHandle?.write(data)
    }

    @objc private func showMonitor() {
        writeLog("Show monitor requested")
        if !isFrameVisible(window.frame) {
            restoreMonitorToCurrentScreen()
        }
        window.level = .floating
        NSApp.unhide(nil)
        window.orderFrontRegardless()
        NSApp.activate(ignoringOtherApps: true)
        writeLog("Show monitor completed frame: \(window.frame)")
    }

    @objc private func showMonitorFromMenu() {
        writeLog("Show monitor requested from menu")
        stopWindowDrag()
        resizeWindow(width: 170, height: 150)
        restoreMonitorToCurrentScreen()
        restorePetWebState()
        showMonitor()
    }

    @objc private func hideMonitor() {
        writeLog("Hide monitor requested")
        stopWindowDrag()
        window.orderOut(nil)
    }

    @objc private func quit() {
        writeLog("Quit requested")
        stopWindowDrag()
        NSApp.terminate(nil)
    }
}

@main
struct FloatingMonitorApp {
    static let delegate = AppDelegate()

    static func main() {
        let app = NSApplication.shared
        app.delegate = delegate
        app.run()
    }
}
