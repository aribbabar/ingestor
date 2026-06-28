import { readFileSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { repoRoot, tauriConfigPath } from "./release-env.mjs";

const frontendPackagePath = join(repoRoot, "frontend", "package.json");
const frontendLockPath = join(repoRoot, "frontend", "package-lock.json");
const cargoTomlPath = join(repoRoot, "frontend", "src-tauri", "Cargo.toml");
const cargoLockPath = join(repoRoot, "frontend", "src-tauri", "Cargo.lock");
const backendPyprojectPath = join(repoRoot, "backend", "pyproject.toml");

const allowedBumps = new Set(["major", "minor", "patch", "none"]);

function readJson(path) {
  return JSON.parse(readFileSync(path, "utf8"));
}

function writeJson(path, value) {
  const original = readFileSync(path, "utf8");
  const updated = `${JSON.stringify(value, null, 2)}\n`;
  if (updated !== original) {
    writeFileSync(path, updated);
  }
}

function parseSemver(version) {
  const match = String(version).match(/^(\d+)\.(\d+)\.(\d+)$/);
  if (!match) {
    throw new Error(`Release versions must be plain SemVer values like 0.1.1. Got: ${version}`);
  }
  return {
    major: Number(match[1]),
    minor: Number(match[2]),
    patch: Number(match[3]),
  };
}

function incrementVersion(version, bump) {
  const parsed = parseSemver(version);
  if (bump === "major") {
    return `${parsed.major + 1}.0.0`;
  }
  if (bump === "minor") {
    return `${parsed.major}.${parsed.minor + 1}.0`;
  }
  if (bump === "patch") {
    return `${parsed.major}.${parsed.minor}.${parsed.patch + 1}`;
  }
  return version;
}

function parseArgs(args) {
  const options = {
    bump: "patch",
    version: null,
  };

  for (let index = 0; index < args.length; index += 1) {
    const arg = args[index];
    if (arg === "--no-bump") {
      options.bump = "none";
      continue;
    }
    if (arg === "--bump") {
      options.bump = args[index + 1];
      index += 1;
      continue;
    }
    if (arg.startsWith("--bump=")) {
      options.bump = arg.slice("--bump=".length);
      continue;
    }
    if (arg === "--version") {
      options.version = args[index + 1];
      options.bump = "none";
      index += 1;
      continue;
    }
    if (arg.startsWith("--version=")) {
      options.version = arg.slice("--version=".length);
      options.bump = "none";
      continue;
    }
    throw new Error(`Unknown release version option: ${arg}`);
  }

  if (!allowedBumps.has(options.bump)) {
    throw new Error(`--bump must be one of: ${[...allowedBumps].join(", ")}`);
  }
  if (options.version) {
    parseSemver(options.version);
  }
  return options;
}

function replaceTomlVersion(path, sectionName, nextVersion) {
  const original = readFileSync(path, "utf8");
  const sectionPattern = new RegExp(
    `(\\[${sectionName}\\][\\s\\S]*?^version\\s*=\\s*")([^"]+)(")`,
    "m"
  );
  if (!sectionPattern.test(original)) {
    throw new Error(`Could not find [${sectionName}] version in ${path}`);
  }
  const updated = original.replace(sectionPattern, `$1${nextVersion}$3`);
  if (updated !== original) {
    writeFileSync(path, updated);
  }
}

function replaceCargoLockPackageVersion(nextVersion) {
  const original = readFileSync(cargoLockPath, "utf8");
  const packagePattern = /(\[\[package\]\]\r?\nname = "ingestor"\r?\nversion = ")([^"]+)(")/;
  if (!packagePattern.test(original)) {
    throw new Error(`Could not find ingestor package version in ${cargoLockPath}`);
  }
  const updated = original.replace(packagePattern, `$1${nextVersion}$3`);
  if (updated !== original) {
    writeFileSync(cargoLockPath, updated);
  }
}

function currentReleaseVersion() {
  const config = readJson(tauriConfigPath);
  parseSemver(config.version);
  return config.version;
}

export function updateReleaseVersion(args = []) {
  const options = parseArgs(args);
  const previousVersion = currentReleaseVersion();
  const nextVersion = options.version ?? incrementVersion(previousVersion, options.bump);

  const tauriConfig = readJson(tauriConfigPath);
  tauriConfig.version = nextVersion;
  writeJson(tauriConfigPath, tauriConfig);

  const frontendPackage = readJson(frontendPackagePath);
  frontendPackage.version = nextVersion;
  writeJson(frontendPackagePath, frontendPackage);

  const frontendLock = readJson(frontendLockPath);
  frontendLock.version = nextVersion;
  frontendLock.packages ??= {};
  frontendLock.packages[""] ??= {};
  frontendLock.packages[""].version = nextVersion;
  writeJson(frontendLockPath, frontendLock);

  replaceTomlVersion(cargoTomlPath, "package", nextVersion);
  replaceCargoLockPackageVersion(nextVersion);
  replaceTomlVersion(backendPyprojectPath, "project", nextVersion);

  const mode = options.version ? "set" : options.bump === "none" ? "kept" : `${options.bump} bumped`;
  return {
    previousVersion,
    version: nextVersion,
    mode,
  };
}

const isMain = resolve(process.argv[1] ?? "") === resolve(fileURLToPath(import.meta.url));

if (isMain) {
  try {
    const result = updateReleaseVersion(process.argv.slice(2));
    console.log(`Release version ${result.mode}: ${result.previousVersion} -> ${result.version}`);
  } catch (error) {
    console.error(error.message);
    process.exit(1);
  }
}
