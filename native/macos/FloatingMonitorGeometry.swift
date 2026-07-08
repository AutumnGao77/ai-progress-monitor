import CoreGraphics

struct FloatingMonitorGeometry {
    static func draggedFrame(
        frame: CGRect,
        deltaX: CGFloat,
        deltaY: CGFloat,
        screenFrame: CGRect,
        compactSize: CGSize
    ) -> CGRect {
        let dragWidth = min(frame.width, compactSize.width)
        let dragHeight = min(frame.height, compactSize.height)
        let x = clamp(
            frame.origin.x + deltaX,
            min: screenFrame.minX - (frame.width - dragWidth),
            max: screenFrame.maxX - frame.width
        )
        let y = clamp(
            frame.origin.y + deltaY,
            min: screenFrame.minY,
            max: screenFrame.maxY - dragHeight
        )
        return CGRect(x: x, y: y, width: frame.width, height: frame.height)
    }

    static func resizedFrame(
        currentFrame: CGRect,
        requestedSize: CGSize,
        visibleFrame: CGRect,
        compactSize: CGSize
    ) -> CGRect {
        let clampedWidth = min(requestedSize.width, max(80, visibleFrame.width - 16))
        let clampedHeight = min(requestedSize.height, max(80, visibleFrame.height - 16))
        let anchorWidth = min(clampedWidth, compactSize.width)
        let anchorHeight = min(clampedHeight, compactSize.height)
        let x = clamp(
            currentFrame.maxX - clampedWidth,
            min: visibleFrame.minX - (clampedWidth - anchorWidth),
            max: visibleFrame.maxX - clampedWidth
        )
        let y = clamp(
            currentFrame.minY,
            min: visibleFrame.minY,
            max: visibleFrame.maxY - anchorHeight
        )
        return CGRect(x: x, y: y, width: clampedWidth, height: clampedHeight)
    }

    static func monitorFrame(
        requestedSize: CGSize,
        visibleFrame: CGRect,
        margin: CGFloat = 24
    ) -> CGRect {
        let clampedWidth = min(requestedSize.width, max(80, visibleFrame.width - 16))
        let clampedHeight = min(requestedSize.height, max(80, visibleFrame.height - 16))
        return CGRect(
            x: visibleFrame.maxX - clampedWidth - margin,
            y: visibleFrame.minY + margin,
            width: clampedWidth,
            height: clampedHeight
        )
    }

    static func screenFrame(
        mouseLocation: CGPoint,
        proposedFrame: CGRect,
        screenFrames: [CGRect],
        fallback: CGRect
    ) -> CGRect {
        if let mouseScreen = screenFrames.first(where: { $0.contains(mouseLocation) }) {
            return mouseScreen
        }
        if let intersectingScreen = screenFrames
            .map({ frame in (frame, intersectionArea(frame, proposedFrame)) })
            .filter({ $0.1 > 0 })
            .max(by: { $0.1 < $1.1 })?
            .0 {
            return intersectingScreen
        }
        return fallback
    }

    static func intersectionArea(_ first: CGRect, _ second: CGRect) -> CGFloat {
        let intersection = first.intersection(second)
        if intersection.isNull || intersection.isEmpty {
            return 0
        }
        return intersection.width * intersection.height
    }

    static func clamp(_ value: CGFloat, min: CGFloat, max: CGFloat) -> CGFloat {
        Swift.max(min, Swift.min(max, value))
    }
}
