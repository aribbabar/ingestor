# Ingestor

Ingestor is a Tauri desktop app for documentation ingestion and retrieval. The desktop shell starts the FastAPI backend locally, serves the React renderer, and exposes the local API at `http://127.0.0.1:8765` for agent skills.

## Start The Desktop App

```powershell
npm --prefix frontend install
backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
npm run dev
```

During development, Tauri starts Vite at `http://127.0.0.1:1420` and the Python backend at `http://127.0.0.1:8765`.

## Build

```powershell
npm run build
```

The active app code lives in `frontend`, `backend`, and `skills`. The `reference` folder is only a source reference and can be removed once this Tauri version has everything you need.

The Tauri bundle includes a packaged backend executable, the `ingestor` CLI, and app-owned skills as resources. The installed desktop app starts `ingestor-backend.exe` locally and stores data in the app data directory.

## Installed CLI

```powershell
ingestor health
ingestor list
ingestor search all "query" --output json
```

The NSIS installer adds the installed `binaries` directory to the current user's `PATH` so new terminal sessions can run `ingestor`. The desktop app must be running because the installed CLI talks to the local API at `http://127.0.0.1:8765`. Use `INGESTOR_API_URL` or `--api-url` to point the CLI at a different Ingestor API.

## Backend CLI

```powershell
cd backend
.\.venv\Scripts\python.exe -m app.cli serve
.\.venv\Scripts\python.exe -m app.cli search all "query" --output yaml
```
