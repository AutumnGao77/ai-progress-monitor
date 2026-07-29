import Foundation

enum FloatingMonitorFocusStabilizationDecision: Equatable {
    case retry(stableReadCount: Int)
    case complete
    case fail
}

struct FloatingMonitorFocusPolicy {
    static let requiredStableReadCount = 2
    static let maximumStabilizationAttempts = 8
    static let stabilizationInterval: TimeInterval = 0.02
    static let activationTimeout: TimeInterval = 1.0
    private static let projectTitleSeparators = [
        " — ",
        " – ",
        " - ",
        " | ",
        " · ",
        " :: ",
        " / ",
        " \\ ",
    ]
    private static let exactProjectEditorApplicationNames: Set<String> = [
        "code",
        "cursor",
        "eclipse",
        "fleet",
        "kiro",
        "nova",
        "vscodium",
        "windsurf",
        "xcode",
        "zed",
    ]
    private static let prefixProjectEditorApplicationNames: Set<String> = [
        "android studio",
        "clion",
        "goland",
        "intellij idea",
        "phpstorm",
        "pycharm",
        "rider",
        "rubymine",
        "sublime text",
        "trae",
        "visual studio code",
        "webstorm",
    ]

    static var maximumStabilizationDuration: TimeInterval {
        stabilizationInterval * Double(maximumStabilizationAttempts - 1)
    }

    static func decision(
        targetSelected: Bool,
        stableReadCount: Int,
        attempt: Int
    ) -> FloatingMonitorFocusStabilizationDecision {
        let nextAttempt = attempt + 1
        let nextStableReadCount = targetSelected ? stableReadCount + 1 : 0
        if nextStableReadCount >= requiredStableReadCount {
            return .complete
        }
        if nextAttempt >= maximumStabilizationAttempts {
            return .fail
        }
        return .retry(stableReadCount: nextStableReadCount)
    }

    static func projectWindowTitleMatchScore(
        folderName: String,
        windowTitle: String
    ) -> Int {
        let folder = normalizedProjectTitle(folderName)
        let title = normalizedProjectTitle(windowTitle)
        guard !folder.isEmpty, !title.isEmpty else { return 0 }
        if title == folder {
            return 3
        }
        var segmentedTitle = title
        for separator in projectTitleSeparators {
            segmentedTitle = segmentedTitle.replacingOccurrences(
                of: separator,
                with: "\u{0}"
            )
        }
        let segments = segmentedTitle.components(separatedBy: "\u{0}").map {
            $0.trimmingCharacters(in: .whitespacesAndNewlines)
        }
        if segments.contains(folder)
            || title.hasPrefix("\(folder) [")
            || title.hasPrefix("\(folder) (")
            || title.hasPrefix("\(folder): ")
        {
            return 2
        }
        return containsProjectTitleBoundary(folder: folder, title: title) ? 1 : 0
    }

    static func isProjectEditorApplicationName(_ value: String) -> Bool {
        let normalized = normalizedApplicationName(value)
        return exactProjectEditorApplicationNames.contains(normalized)
            || prefixProjectEditorApplicationNames.contains {
                normalized.hasPrefix($0)
            }
    }

    static func projectEditorApplicationNameMatches(
        candidate: String,
        target: String
    ) -> Bool {
        let normalizedCandidate = normalizedApplicationName(candidate)
        let normalizedTarget = normalizedApplicationName(target)
        if normalizedCandidate == normalizedTarget {
            return true
        }
        if normalizedTarget == "visual studio code"
            && (normalizedCandidate == "code"
                || normalizedCandidate.hasPrefix("code - insiders"))
        {
            return true
        }
        return prefixProjectEditorApplicationNames.contains(normalizedTarget)
            && normalizedCandidate.hasPrefix(normalizedTarget)
    }

    private static func normalizedApplicationName(_ value: String) -> String {
        value.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
    }

    private static func normalizedProjectTitle(_ value: String) -> String {
        value.precomposedStringWithCanonicalMapping
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased()
    }

    private static func containsProjectTitleBoundary(
        folder: String,
        title: String
    ) -> Bool {
        var searchStart = title.startIndex
        while searchStart < title.endIndex,
              let range = title.range(
                of: folder,
                range: searchStart..<title.endIndex
              )
        {
            let before = range.lowerBound == title.startIndex
                ? nil
                : title[title.index(before: range.lowerBound)]
            let after = range.upperBound == title.endIndex
                ? nil
                : title[range.upperBound]
            if !isProjectNameContinuation(before)
                && !isProjectNameContinuation(after)
            {
                return true
            }
            searchStart = title.index(after: range.lowerBound)
        }
        return false
    }

    private static func isProjectNameContinuation(_ character: Character?) -> Bool {
        guard let character = character else { return false }
        if character == "_" || character == "-" {
            return true
        }
        return character.unicodeScalars.allSatisfy {
            CharacterSet.alphanumerics.contains($0)
        }
    }
}
