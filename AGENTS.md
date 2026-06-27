# Repository Guidelines

## Project Structure & Module Organization

Ingestor is a Tauri desktop app around one Python backend core.

- `backend/app/`: Python app. Important packages are `api/`, `cli/`, `daemon/`, `db/`, `indexing/`, `retrieval/`, and `sources/`.
- `frontend/src/`: React renderer, with pages in `pages/`, reusable UI in `components/`, and the desktop bridge in `desktop.ts`.
- `frontend/src-tauri/`: Rust Tauri shell, daemon launcher, capabilities, icons, and installer config.
- `skills/`: thin agent skills that call the installed `ingestor` CLI.
- `tests/`: backend ingestion and retrieval tests.

## Build, Test, and Development Commands

Run from the repository root unless noted.

- `npm --prefix frontend install`: install frontend/Tauri dependencies.
- `python -m venv backend\.venv`; `backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt`: create the backend environment.
- `npm run dev`: start the Tauri app, Vite renderer, and local daemon.
- `npm run backend:serve`: run the daemon on `127.0.0.1:8765`.
- `backend\.venv\Scripts\python.exe -m compileall backend\app`: catch Python import/syntax issues.
- `backend\.venv\Scripts\python.exe -m pytest tests`: run backend tests.
- `npm --prefix frontend run lint`: check TypeScript/React lint rules.
- `npm --prefix frontend run build`: type-check and build the renderer.
- `npm run build`: build the Tauri installer bundle.

## Coding Style & Naming Conventions

Python uses 4-space indentation, typed functions where practical, and explicit imports. Keep ingestion cleanup in `backend/app/indexing/` and search behavior in `backend/app/retrieval/`. Test methods use `test_*` names.

TypeScript/React uses component modules, CSS modules for scoped styles, PascalCase component filenames, and camelCase utilities. Reuse existing UI components before adding primitives.

## Testing Guidelines

Add backend tests in `tests/` for indexing, source, and retrieval behavior. Prefer deterministic fixtures, temporary directories, and local SQLite data over live network calls. For UI or installer changes, pair build/lint checks with a real app or installer smoke test.

## Commit & Pull Request Guidelines

Recent history uses concise subjects such as `feat: add CLI path management and update functionality`, `docs: update README...`, and `Refactor Ingestor backend structure and CLI`. Prefer an imperative, scoped subject with `feat:`, `fix:`, `docs:`, `test:`, or `refactor:`.

Pull requests should explain the user-facing change, list verification commands, call out installer/daemon/CLI impacts, and include screenshots for UI changes. Link issues when relevant and note data migration or environment variable changes.

## Security & Configuration Tips

Do not commit local runtime state, `.venv`, build artifacts, `.agents`, `.codex`, or app data. Keep daemon access local by default. Use `INGESTOR_API_URL`, `INGESTOR_DATA_DIR`, and related variables only for explicit development or verification flows.
