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
}
