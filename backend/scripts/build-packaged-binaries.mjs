import { spawnSync } from "node:child_process";
import { existsSync, mkdirSync, rmSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(scriptDir, "..", "..");
const backendDir = join(repoRoot, "backend");
const frontendTauriDir = join(repoRoot, "frontend", "src-tauri");
const binaryDir = join(frontendTauriDir, "binaries");
const buildDir = join(backendDir, "build", "pyinstaller");
const isWindows = process.platform === "win32";

const python = resolvePython();

run(python, ["-m", "pip", "install", "-r", join(backendDir, "requirements-build.txt")]);

rmSync(binaryDir, { recursive: true, force: true });
mkdirSync(binaryDir, { recursive: true });

const commonOutputArgs = [
  "--noconfirm",
  "--clean",
  "--onefile",
  "--distpath",
  binaryDir,
  "--workpath",
  buildDir,
  "--specpath",
  buildDir,
];

run(python, [
  "-m",
  "PyInstaller",
  ...commonOutputArgs,
  ...(isWindows ? ["--noconsole"] : []),
  "--paths",
  backendDir,
  "--collect-all",
  "crawl4ai",
  "--collect-all",
  "sqlite_vec",
  "--collect-submodules",
  "app",
  "--name",
  "ingestor-daemon",
  join(backendDir, "app", "daemon", "server.py"),
]);

run(python, [
  "-m",
  "PyInstaller",
  ...commonOutputArgs,
  "--name",
  "ingestor",
  join(backendDir, "app", "cli", "main.py"),
]);

function resolvePython() {
  const venvPython = join(backendDir, ".venv", isWindows ? "Scripts/python.exe" : "bin/python");
  const candidates = [process.env.PYTHON, venvPython, isWindows ? "python" : "python3", "python"].filter(Boolean);

  for (const candidate of candidates) {
    if (candidate.includes("/") || candidate.includes("\\")) {
      if (!existsSync(candidate)) {
        continue;
      }
    }
    const result = spawnSync(candidate, ["--version"], { encoding: "utf8" });
    if (result.status === 0) {
      return candidate;
    }
  }

  throw new Error("Could not find Python. Set PYTHON to the interpreter that should build Ingestor.");
}

function run(command, args) {
  const result = spawnSync(command, args, {
    cwd: repoRoot,
    stdio: "inherit",
    shell: false,
  });
  if (result.error) {
    throw result.error;
  }
  if (result.status !== 0) {
    process.exit(result.status ?? 1);
  }
}
