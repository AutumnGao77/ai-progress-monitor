import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class MacOSLoggingTests(unittest.TestCase):
    def test_log_errors_and_concurrent_shutdown_do_not_abort(self):
        source = (ROOT / "native/macos/FloatingMonitor.swift").read_text()
        start = source.index("final class NativeLogWriter")
        end = source.index("final class AppDelegate")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            logger = root / "Logger.swift"
            logger.write_text("import Foundation\n" + source[start:end])
            main = root / "main.swift"
            main.write_text(r'''import Foundation

func check(_ condition: Bool, _ message: String) {
    if !condition { fatalError(message) }
}
let url = URL(fileURLWithPath: CommandLine.arguments[1])
FileManager.default.createFile(atPath: url.path, contents: nil)
let handle = try FileHandle(forWritingTo: url)
let logger = NativeLogWriter(handle: handle)
DispatchQueue.concurrentPerform(iterations: 1000) { index in
    logger.write(Data("line-\(index)\n".utf8))
}
logger.close()
logger.write(Data("ignored\n".utf8))
logger.close()
let lines = try String(contentsOf: url).split(separator: "\n")
check(lines.count == 1000, "concurrent writes must preserve all records")
check(Set(lines).count == 1000, "records must remain distinct")

let closed = try FileHandle(forWritingTo: url)
try closed.close()
let closedLogger = NativeLogWriter(handle: closed)
closedLogger.write(Data("ignored\n".utf8))
closedLogger.close()

let readOnly = try FileHandle(forReadingFrom: url)
let failing = NativeLogWriter(handle: readOnly)
failing.write(Data("ignored\n".utf8))
failing.write(Data("ignored\n".utf8))
failing.close()

let racing = NativeLogWriter(handle: try FileHandle(forWritingTo: url))
DispatchQueue.concurrentPerform(iterations: 2000) { index in
    if index % 13 == 0 { racing.close() }
    else { racing.write(Data("race\n".utf8)) }
}
racing.close()
print("logging-safety-ok")
''')
            executable = root / "logging-check"
            compile_result = subprocess.run(
                ["swiftc", str(logger), str(main), "-o", str(executable)],
                capture_output=True, text=True, timeout=120,
            )
            self.assertEqual(compile_result.returncode, 0, compile_result.stderr)
            result = subprocess.run(
                [str(executable), str(root / "test.log")],
                capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("logging-safety-ok", result.stdout)


if __name__ == "__main__":
    unittest.main()
