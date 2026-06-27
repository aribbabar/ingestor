# Ingestor

Ingestor is a local documentation ingestion and retrieval app for developers and agents. It indexes local files, folders, and web documentation, stores the index on your machine, and exposes the results through a desktop UI, a CLI, and agent skills.

[Download for Windows](https://github.com/aribbabar/ingestor/releases/latest)

The Windows installer is published through GitHub Releases. Install the latest setup `.exe`, open Ingestor, and the app will start its local daemon automatically.

## What It Does

- Index local documentation folders and files.
- Crawl web documentation sites with bounded depth and page limits.
- Search with hybrid retrieval over SQLite FTS and local vector search.
- Manage sources, settings, and agent skills from the desktop app.
- Expose the same data through the `ingestor` CLI for users and agents.
- Keep the index local by default in the app data directory.

## Quick Start

1. Download and install the latest Windows release.
2. Open Ingestor.
3. Add a local folder or web documentation source from the Capture page.
4. Search from the desktop app or from a terminal:

```powershell
ingestor health
ingestor list
ingestor search all "how do I configure routing?" --output json
```

The desktop app includes the supported `ingestor` CLI. Make the installed CLI available on `PATH` before using terminal commands or agent skills.

## Architecture

Ingestor is one product with three thin surfaces around one Python core:

```text
Desktop app  -> local daemon API -> Python core
CLI          -> local daemon API -> Python core
Agent skills -> ingestor CLI     -> local daemon API -> Python core
```

The desktop app is a Tauri shell with a React renderer. It starts `ingestor-daemon.exe` locally and talks to `http://127.0.0.1:8765`.

The Python daemon owns FastAPI app creation, source management, indexing, retrieval, settings, and skill sync endpoints.

The `ingestor` CLI is API-first. It calls the running daemon instead of duplicating indexing or search logic. For command-only workflows, the CLI can also start the daemon:

```powershell
ingestor daemon
ingestor --start-daemon search all "query" --output json
```

## CLI

Common commands:

```powershell
ingestor health
ingestor list --output json
ingestor search all "query" --limit 8 --mode hybrid --output json
ingestor index-local "C:\path\to\docs" --name my-docs --wait
ingestor index-web "https://example.com/docs" --name example --max-depth 2 --max-pages 100 --scope hostname --wait
ingestor reindex "<source-id>" --wait
ingestor delete "<source-id>"
```

By default, the CLI talks to `http://127.0.0.1:8765`. Override that with either:

```powershell
ingestor --api-url http://127.0.0.1:8765 health
$env:INGESTOR_API_URL = "http://127.0.0.1:8765"
```

## Agent Skills

The `skills` folder contains app-owned skills that make agents use Ingestor through the CLI:

- `ingestor-search` searches indexed documentation.
- `ingestor-manage` indexes local or web documentation.

The desktop app can sync these skills into supported local agent skill folders. The skills stay thin on purpose: they describe when to call `ingestor`, while the installed app and daemon own the actual indexing and retrieval behavior.

## Configuration

| Variable | Purpose |
| --- | --- |
| `INGESTOR_API_URL` | Base URL used by the CLI. Defaults to `http://127.0.0.1:8765`. |
| `INGESTOR_AUTO_START` | When truthy, lets CLI commands start the daemon if the API is unavailable. |
| `INGESTOR_DAEMON` | Path to a daemon executable the CLI should start. |
| `INGESTOR_DATA_DIR` | Directory for the SQLite database, job logs, and captured content. |
| `INGESTOR_SKILLS_DIR` | Source directory for app-owned skills when syncing skills. |
| `INGESTOR_AGENTS_SKILLS_DIR` | Override target folder for Agents skills. |
| `INGESTOR_CODEX_SKILLS_DIR` | Override target folder for Codex skills. |
| `INGESTOR_CLAUDE_SKILLS_DIR` | Override target folder for Claude skills. |

## Development

Requirements:

- Node.js and npm
- Rust toolchain for Tauri
- Python 3.12 or newer

Set up the frontend and backend:

```powershell
npm --prefix frontend install
python -m venv backend\.venv
backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
```

Start the desktop app:

```powershell
npm run dev
```

During development, Tauri starts Vite at `http://127.0.0.1:1420` and the Python daemon at `http://127.0.0.1:8765`.

You can also run the daemon directly:

```powershell
cd backend
.\.venv\Scripts\python.exe -m app.daemon --reload
```

Then call it from the CLI:

```powershell
.\.venv\Scripts\python.exe -m app.cli health
.\.venv\Scripts\python.exe -m app.cli search all "query" --output json
```

## Build The Installer

Build the Windows installer:

```powershell
$env:TAURI_SIGNING_PRIVATE_KEY="$env:USERPROFILE\.tauri\ingestor.key"
$env:TAURI_SIGNING_PRIVATE_KEY_PASSWORD=""
npm --prefix frontend run tauri -- build
```

The release build creates a signed Windows MSI installer and updater signature that contain the React frontend, `ingestor-daemon.exe`, the `ingestor` CLI, and app-owned skills:

```powershell
frontend\src-tauri\target\release\bundle\msi\Ingestor_0.1.0_x64_en-US.msi
frontend\src-tauri\target\release\bundle\msi\Ingestor_0.1.0_x64_en-US.msi.sig
```

Publish the MSI, `.sig`, and a `latest.json` update manifest to GitHub Releases so the Settings update check can find new versions.

## Project Layout

```text
backend/
  app/
    api/        FastAPI routes
    cli/        API-first CLI
    core/       settings and shared runtime configuration
    daemon/     FastAPI app and daemon startup
    db/         SQLite models and persistence
    domain/     request/response/domain models
    indexing/   local file, web crawl, chunking, and embedding pipeline
    retrieval/  search, embeddings, vector index, and retrieval settings
    sources/    source registration and indexing jobs
frontend/
  src/          React renderer
  src-tauri/    Tauri shell, installer config, and daemon launcher
skills/         Thin agent skills that call the Ingestor CLI
tests/          Backend ingestion and retrieval tests
```

## Verification

Useful checks before shipping changes:

```powershell
backend\.venv\Scripts\python.exe -m compileall backend\app
backend\.venv\Scripts\python.exe -m pytest tests
npm --prefix frontend run build
cd frontend\src-tauri
cargo check
```

Run the deterministic retrieval quality smoke eval:

```powershell
cd backend
.\.venv\Scripts\python.exe -m app.retrieval.evaluation
```

The default eval uses `tests/evals/retrieval/neon_fixture.json` and a temporary local database. Pass `--live` and `--dataset <path>` to evaluate an existing indexed source instead.
