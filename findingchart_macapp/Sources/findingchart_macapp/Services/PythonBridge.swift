import Foundation

struct BridgeConfig {
    var pythonPath: String
    var bridgeScript: String
    var repoDir: String

    static let `default`: BridgeConfig = {
        let env = ProcessInfo.processInfo.environment
        let repoRoot = env["FINDING_CHART_REPO"]
            ?? "/Users/avinash/Work/SupernovaeData/_ProjectG_FindingChart"
        return BridgeConfig(
            pythonPath: env["FINDING_CHART_PYTHON"] ?? "/usr/bin/env python3",
            bridgeScript: env["FINDING_CHART_BRIDGE"] ?? "\(repoRoot)/findingchart_macapp/bridge/findingchart_bridge.py",
            repoDir: repoRoot
        )
    }()
}

enum BridgeError: LocalizedError {
    case launchFailed(String)
    case decodeFailed(String, raw: String)
    case pipelineError(String)

    var errorDescription: String? {
        switch self {
        case .launchFailed(let message):
            return "Could not launch the Python bridge: \(message)"
        case .decodeFailed(let message, let raw):
            return "Could not decode bridge output: \(message)\n\n\(raw)"
        case .pipelineError(let message):
            return message
        }
    }
}

struct PythonBridge {
    var config: BridgeConfig = .default

    func run(_ params: PipelineParams) async throws -> PipelineResult {
        let inputData = try JSONEncoder().encode(params)
        let argv = config.pythonPath.split(separator: " ").map(String.init)
        guard let executable = argv.first else {
            throw BridgeError.launchFailed("empty Python command")
        }

        var arguments = Array(argv.dropFirst())
        arguments += [config.bridgeScript, "--repo-dir", config.repoDir]

        let process = Process()
        if executable.contains("/") {
            process.executableURL = URL(fileURLWithPath: executable)
        } else {
            process.executableURL = URL(fileURLWithPath: "/usr/bin/env")
            arguments.insert(executable, at: 0)
        }
        process.arguments = arguments

        let stdinPipe = Pipe()
        let stdoutPipe = Pipe()
        let stderrPipe = Pipe()
        process.standardInput = stdinPipe
        process.standardOutput = stdoutPipe
        process.standardError = stderrPipe

        return try await withCheckedThrowingContinuation { continuation in
            DispatchQueue.global(qos: .userInitiated).async {
                do {
                    try process.run()
                    stdinPipe.fileHandleForWriting.write(inputData)
                    stdinPipe.fileHandleForWriting.closeFile()

                    let out = stdoutPipe.fileHandleForReading.readDataToEndOfFile()
                    let err = stderrPipe.fileHandleForReading.readDataToEndOfFile()
                    process.waitUntilExit()

                    do {
                        let result = try JSONDecoder().decode(PipelineResult.self, from: out)
                        if result.ok {
                            continuation.resume(returning: result)
                        } else {
                            continuation.resume(throwing: BridgeError.pipelineError(result.error ?? "unknown bridge error"))
                        }
                    } catch {
                        let raw = String(data: out, encoding: .utf8) ?? ""
                        let errText = String(data: err, encoding: .utf8) ?? ""
                        continuation.resume(throwing: BridgeError.decodeFailed(error.localizedDescription, raw: raw.isEmpty ? errText : raw))
                    }
                } catch {
                    continuation.resume(throwing: BridgeError.launchFailed(error.localizedDescription))
                }
            }
        }
    }
}
