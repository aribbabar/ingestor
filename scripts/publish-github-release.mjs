import { existsSync, readdirSync } from "node:fs";
import { basename, join } from "node:path";
import { spawnSync } from "node:child_process";
import { readTauriConfig, repoRoot } from "./release-env.mjs";

function run(command, args, options = {}) {
  const result = spawnSync(command, args, {
    cwd: options.cwd ?? repoRoot,
    encoding: "utf8",
    stdio: options.stdio ?? "pipe",
  });

  if (result.error) {
    throw result.error;
  }
  if (result.status !== 0 && options.check !== false) {
    const detail = result.stderr?.trim() || result.stdout?.trim();
    throw new Error(`${command} ${args.join(" ")} failed${detail ? `:\n${detail}` : ""}`);
  }
  return result;
}

function parseArgs(args) {
  const options = {
    dryRun: false,
    draft: false,
    prerelease: false,
    replaceAssets: false,
    allowDirty: false,
    generateNotes: true,
    notes: null,
    notesFile: null,
    title: null,
  };

  for (let index = 0; index < args.length; index += 1) {
    const arg = args[index];
    if (arg === "--dry-run") {
      options.dryRun = true;
    } else if (arg === "--draft") {
      options.draft = true;
    } else if (arg === "--prerelease") {
      options.prerelease = true;
    } else if (arg === "--replace-assets") {
      options.replaceAssets = true;
    } else if (arg === "--allow-dirty") {
      options.allowDirty = true;
    } else if (arg === "--no-generate-notes") {
      options.generateNotes = false;
    } else if (arg === "--title") {
      options.title = args[index + 1];
      index += 1;
    } else if (arg.startsWith("--title=")) {
      options.title = arg.slice("--title=".length);
    } else if (arg === "--notes") {
      options.notes = args[index + 1];
      options.generateNotes = false;
      index += 1;
    } else if (arg.startsWith("--notes=")) {
      options.notes = arg.slice("--notes=".length);
      options.generateNotes = false;
    } else if (arg === "--notes-file") {
      options.notesFile = args[index + 1];
      options.generateNotes = false;
      index += 1;
    } else if (arg.startsWith("--notes-file=")) {
      options.notesFile = arg.slice("--notes-file=".length);
      options.generateNotes = false;
    } else {
      throw new Error(`Unknown release publish option: ${arg}`);
    }
  }

  if (options.notes && options.notesFile) {
    throw new Error("Use either --notes or --notes-file, not both.");
  }
  return options;
}

function githubRepoFromEndpoint(config) {
  const endpoint = config.plugins?.updater?.endpoints?.[0] ?? "";
  const match = endpoint.match(/^https:\/\/github\.com\/([^/]+\/[^/]+)\/releases\//);
  if (!match) {
    throw new Error(`Could not infer GitHub repository from updater endpoint: ${endpoint}`);
  }
  return match[1];
}

function releaseArtifacts(tag, version) {
  const releaseDir = join(repoRoot, "release", tag);
  if (!existsSync(releaseDir)) {
    throw new Error(`Release artifact directory does not exist: ${releaseDir}`);
  }

  const msiName = readdirSync(releaseDir).find(
    (name) => name.endsWith(".msi") && name.includes(version)
  );
  if (!msiName) {
    throw new Error(`No MSI for version ${version} found in ${releaseDir}`);
  }

  const msiPath = join(releaseDir, msiName);
  const sigPath = join(releaseDir, `${msiName}.sig`);
  const manifestPath = join(releaseDir, "latest.json");
  for (const path of [msiPath, sigPath, manifestPath]) {
    if (!existsSync(path)) {
      throw new Error(`Missing release artifact: ${path}`);
    }
  }

  return [msiPath, sigPath, manifestPath];
}

function gitState() {
  const status = run("git", ["status", "--porcelain"], { check: false }).stdout.trim();
  const head = run("git", ["rev-parse", "HEAD"]).stdout.trim();
  const upstream = run("git", ["rev-parse", "@{u}"], { check: false }).stdout.trim();
  const hasUpstream = upstream.length > 0;
  return { status, head, upstream, hasUpstream };
}

function validateGitReady(options) {
  const state = gitState();
  const problems = [];
  if (state.status && !options.allowDirty) {
    problems.push("the worktree has uncommitted changes");
  }
  if (!state.hasUpstream) {
    problems.push("the current branch has no upstream");
  } else if (state.head !== state.upstream) {
    problems.push("the current HEAD is not pushed to its upstream");
  }

  if (problems.length && !options.dryRun) {
    throw new Error(
      `Refusing to publish because ${problems.join(" and ")}.\n` +
        "Commit and push the release version bump first, then rerun npm run release:publish."
    );
  }

  if (problems.length) {
    console.warn(`Dry run warning: publish would stop because ${problems.join(" and ")}.`);
  }
  return state;
}

function releaseExists(tag, githubRepo) {
  const result = run("gh", ["release", "view", tag, "--repo", githubRepo], {
    check: false,
  });
  return result.status === 0;
}

function printCommand(args) {
  console.log(["gh", ...args.map((arg) => (arg.includes(" ") ? `"${arg}"` : arg))].join(" "));
}

function main() {
  const options = parseArgs(process.argv.slice(2));
  const config = readTauriConfig();
  const version = config.version;
  const tag = process.env.INGESTOR_RELEASE_TAG || `v${version}`;
  const githubRepo = githubRepoFromEndpoint(config);
  const artifacts = releaseArtifacts(tag, version);
  const state = validateGitReady(options);
  const exists = releaseExists(tag, githubRepo);

  let args;
  if (exists) {
    if (!options.replaceAssets) {
      throw new Error(
        `GitHub Release ${tag} already exists. Use --replace-assets to upload these artifacts again.`
      );
    }
    args = ["release", "upload", tag, ...artifacts, "--repo", githubRepo, "--clobber"];
  } else {
    args = [
      "release",
      "create",
      tag,
      ...artifacts,
      "--repo",
      githubRepo,
      "--target",
      state.head,
      "--title",
      options.title ?? `Ingestor ${tag}`,
    ];

    if (options.generateNotes) {
      args.push("--generate-notes");
    } else if (options.notesFile) {
      args.push("--notes-file", options.notesFile);
    } else {
      args.push("--notes", options.notes ?? "See the repository changes for this release.");
    }
    if (options.draft) {
      args.push("--draft");
    }
    if (options.prerelease) {
      args.push("--prerelease");
    }
  }

  if (options.dryRun) {
    console.log(`Would publish ${tag} to ${githubRepo} with:`);
    printCommand(args);
    console.log("Artifacts:");
    for (const artifact of artifacts) {
      console.log(`- ${basename(artifact)}`);
    }
    return;
  }

  run("gh", args, { stdio: "inherit" });
  console.log(`Published GitHub Release ${tag}.`);
}

try {
  main();
} catch (error) {
  console.error(error.message);
  process.exit(1);
}
