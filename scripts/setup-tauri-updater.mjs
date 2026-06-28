import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { tmpdir } from "node:os";
import { spawn } from "node:child_process";
import {
  defaultKeyPath,
  repoRoot,
  releaseEnvPath,
  tauriConfigPath,
} from "./release-env.mjs";

const force = process.argv.includes("--force");
const keyPath = defaultKeyPath;
const publicKeyPath = `${keyPath}.pub`;

function promptHidden(label) {
  return new Promise((resolve, reject) => {
    const stdin = process.stdin;
    if (!stdin.isTTY) {
      reject(new Error("Password prompt requires an interactive terminal."));
      return;
    }

    let value = "";
    process.stdout.write(label);
    stdin.setRawMode(true);
    stdin.resume();
    stdin.setEncoding("utf8");

    function cleanup() {
      stdin.setRawMode(false);
      stdin.pause();
      stdin.off("data", onData);
    }

    function onData(char) {
      if (char === "\u0003") {
        cleanup();
        process.stdout.write("\n");
        reject(new Error("Aborted."));
        return;
      }
      if (char === "\r" || char === "\n") {
        cleanup();
        process.stdout.write("\n");
        resolve(value);
        return;
      }
      if (char === "\u007f" || char === "\b") {
        value = value.slice(0, -1);
        return;
      }
      value += char;
    }

    stdin.on("data", onData);
  });
}

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

function updateTauriPublicKey() {
  if (!existsSync(publicKeyPath)) {
    throw new Error(
      `Missing public key file: ${publicKeyPath}\n` +
        "If this key predates the public key file, regenerate it with: npm run release:setup-updater -- --force"
    );
  }

  const publicKey = readFileSync(publicKeyPath, "utf8").trim();
  const config = JSON.parse(readFileSync(tauriConfigPath, "utf8"));
  config.plugins ??= {};
  config.plugins.updater ??= {};
  config.plugins.updater.pubkey = publicKey;
  writeFileSync(tauriConfigPath, `${JSON.stringify(config, null, 2)}\n`);
  console.log(`Updated ${tauriConfigPath}`);
}

function writeReleaseEnv(password) {
  const body = [
    "# Local release signing secrets. Do not commit this file.",
    `TAURI_SIGNING_PRIVATE_KEY=${keyPath}`,
    `TAURI_SIGNING_PRIVATE_KEY_PATH=${keyPath}`,
    `TAURI_SIGNING_PRIVATE_KEY_PASSWORD=${password}`,
    "",
  ].join("\n");
  writeFileSync(releaseEnvPath, body);
  console.log(`Wrote ${releaseEnvPath}`);
}

async function verifyExistingKeyPassword(password) {
  const testFile = join(tmpdir(), `ingestor-updater-sign-test-${process.pid}.txt`);
  writeFileSync(testFile, "signing test\n");
  try {
    await runNpm(
      [
        "--prefix",
        "frontend",
        "run",
        "tauri",
        "--",
        "signer",
        "sign",
        testFile,
      ],
      {
        cwd: repoRoot,
        env: {
          TAURI_SIGNING_PRIVATE_KEY_PATH: keyPath,
          TAURI_SIGNING_PRIVATE_KEY_PASSWORD: password,
        },
      }
    );
  } finally {
    rmSync(testFile, { force: true });
    rmSync(`${testFile}.sig`, { force: true });
  }
}

async function main() {
  mkdirSync(dirname(keyPath), { recursive: true });

  const keyExists = existsSync(keyPath);
  const password = await promptHidden(
    keyExists && !force
      ? "Private key password to store in .env.release: "
      : "New private key password: "
  );

  if (!password) {
    throw new Error("Use a non-empty updater signing password.");
  }

  if (!keyExists || force) {
    const confirm = await promptHidden("New private key password again: ");
    if (password !== confirm) {
      throw new Error("Passwords did not match.");
    }

    const args = [
      "--prefix",
      "frontend",
      "run",
      "tauri",
      "--",
      "signer",
      "generate",
      "-w",
      keyPath,
      "--password",
      password,
    ];
    if (force) {
      args.push("--force");
    }
    await runNpm(args, { cwd: repoRoot });
  } else {
    console.log(`Using existing private key: ${keyPath}`);
    await verifyExistingKeyPassword(password);
  }

  updateTauriPublicKey();
  writeReleaseEnv(password);

  console.log("Updater signing is configured.");
}

main().catch((error) => {
  console.error(error.message);
  process.exit(1);
});
