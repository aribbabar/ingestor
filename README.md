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

The Tauri bundle includes the backend source and app-owned skills as resources. A fully standalone installer still needs a packaged Python backend binary or embedded runtime; the current launcher uses the local backend virtualenv in development and falls back to `python.exe` in installed builds.

## Backend CLI

```powershell
cd backend
.\.venv\Scripts\python.exe -m app.cli serve
.\.venv\Scripts\python.exe -m app.cli search all "query" --output yaml
```
