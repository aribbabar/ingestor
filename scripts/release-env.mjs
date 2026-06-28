import { existsSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

export const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
export const frontendDir = join(repoRoot, "frontend");
export const tauriConfigPath = join(repoRoot, "frontend", "src-tauri", "tauri.conf.json");
export const releaseEnvPath = join(repoRoot, ".env.release");
export const defaultKeyPath = join(process.env.USERPROFILE ?? process.env.HOME ?? repoRoot, ".tauri", "ingestor.key");

export function readReleaseEnv() {
  if (!existsSync(releaseEnvPath)) {
    return {};
  }

  const values = {};
  for (const line of readFileSync(releaseEnvPath, "utf8").split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) {
      continue;
    }

    const separator = trimmed.indexOf("=");
    if (separator === -1) {
      continue;
    }

    const key = trimmed.slice(0, separator).trim();
    let value = trimmed.slice(separator + 1).trim();
    if (
      (value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1);
    }
    values[key] = value;
  }
  return values;
}

export function readTauriConfig() {
  return JSON.parse(readFileSync(tauriConfigPath, "utf8"));
}
