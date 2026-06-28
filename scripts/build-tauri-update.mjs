import { copyFileSync, existsSync, mkdirSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import { basename, join } from "node:path";
import { spawn } from "node:child_process";
import {
  frontendDir,
  readReleaseEnv,
  readTauriConfig,
  releaseEnvPath,
  repoRoot,
} from "./release-env.mjs";

function run(command, args, options = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      cwd: options.cwd,
      env: { ...process.env, ...options.env },
      stdio: "inherit",
    });
    child.on("error", reject);
    child.on("exit", (code) => {
      if (code === 0) {
        resolve();
      } else {
        reject(new Error(`${command} ${args.join(" ")} exited with ${code}`));
      }
    });
  });
}

function runNpm(args, options = {}) {
  if (process.env.npm_execpath) {
    return run(process.execPath, [process.env.npm_execpath, ...args], options);
  }
  return run(process.platform === "win32" ? "npm.cmd" : "npm", args, options);
}

function findReleaseMsi(version) {
  const msiDir = join(frontendDir, "src-tauri", "target", "release", "bundle", "msi");
  const candidates = readdirSync(msiDir)
    .filter((name) => name.endsWith(".msi") && name.includes(version))
    .map((name) => join(msiDir, name));

  if (candidates.length === 0) {
    throw new Error(`No MSI found for version ${version} in ${msiDir}`);
  }
  return candidates[0];
}

function githubRepoFromEndpoint(config) {
  const endpoint = config.plugins?.updater?.endpoints?.[0] ?? "";
  const match = endpoint.match(/^https:\/\/github\.com\/([^/]+\/[^/]+)\/releases\//);
  if (!match) {
    throw new Error(`Could not infer GitHub repository from updater endpoint: ${endpoint}`);
  }
  return match[1];
}

async function main() {
  const releaseEnv = readReleaseEnv();
  const privateKey = releaseEnv.TAURI_SIGNING_PRIVATE_KEY ?? releaseEnv.TAURI_SIGNING_PRIVATE_KEY_PATH;
  const keyPath = releaseEnv.TAURI_SIGNING_PRIVATE_KEY_PATH ?? privateKey;
  const password = releaseEnv.TAURI_SIGNING_PRIVATE_KEY_PASSWORD;

  if (!privateKey) {
    throw new Error(
      `Missing TAURI_SIGNING_PRIVATE_KEY in ${releaseEnvPath}.\n` +
        "Run: npm run release:setup-updater"
    );
  }
  if (keyPath && !existsSync(keyPath)) {
    throw new Error(`Signing key file does not exist: ${keyPath}`);
  }
  if (!password) {
    throw new Error(
      `Missing TAURI_SIGNING_PRIVATE_KEY_PASSWORD in ${releaseEnvPath}.\n` +
        "Run: npm run release:setup-updater"
    );
  }

  await runNpm(["--prefix", "frontend", "run", "tauri", "--", "build"], {
    cwd: repoRoot,
    env: {
      TAURI_SIGNING_PRIVATE_KEY: privateKey,
      TAURI_SIGNING_PRIVATE_KEY_PATH: keyPath,
      TAURI_SIGNING_PRIVATE_KEY_PASSWORD: password,
    },
  });

  const config = readTauriConfig();
  const version = config.version;
  const tag = process.env.INGESTOR_RELEASE_TAG || `v${version}`;
  const githubRepo = githubRepoFromEndpoint(config);
  const releaseDir = join(repoRoot, "release", tag);
  const msiPath = findReleaseMsi(version);
  const sigPath = `${msiPath}.sig`;

  if (!existsSync(sigPath)) {
    throw new Error(`Missing updater signature: ${sigPath}`);
  }

  mkdirSync(releaseDir, { recursive: true });
  copyFileSync(msiPath, join(releaseDir, basename(msiPath)));
  copyFileSync(sigPath, join(releaseDir, basename(sigPath)));

  const manifest = {
    version,
    notes: process.env.INGESTOR_RELEASE_NOTES || "See the GitHub release notes.",
    pub_date: new Date().toISOString(),
    platforms: {
      "windows-x86_64": {
        signature: readFileSync(sigPath, "utf8").trim(),
        url: `https://github.com/${githubRepo}/releases/download/${tag}/${basename(msiPath)}`,
      },
    },
  };

  writeFileSync(join(releaseDir, "latest.json"), `${JSON.stringify(manifest, null, 2)}\n`);

  console.log(`Release artifacts staged in ${releaseDir}`);
  console.log(`Upload ${basename(msiPath)}, ${basename(sigPath)}, and latest.json to GitHub Release ${tag}.`);
}

main().catch((error) => {
  console.error(error.message);
  process.exit(1);
});
