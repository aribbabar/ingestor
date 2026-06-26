# Ingestor Backend

Internal Python backend for the Ingestor desktop app, local daemon, and CLI.

The backend exposes two entrypoints used by the packaged app:

- `ingestor` calls a running local Ingestor daemon API.
- `ingestor-daemon` starts the local FastAPI daemon.

## Usage

Run against an already running desktop app or daemon:

```powershell
ingestor health
ingestor list --output json
ingestor search all "query" --output json
```

Start the daemon directly:

```powershell
ingestor daemon
```

Or let a CLI command start the daemon when it is not already reachable:

```powershell
ingestor --start-daemon search all "query" --output json
```

By default, the CLI talks to `http://127.0.0.1:8765`. Use `--api-url` or `INGESTOR_API_URL` to point it at a different local daemon.

## Development

```powershell
cd backend
.\.venv\Scripts\python.exe -m app.daemon
.\.venv\Scripts\python.exe -m app.cli health
```

The index lives in `backend/data/ingestor.sqlite` during local development unless `INGESTOR_DATA_DIR` is set. Hybrid retrieval uses SQLite FTS5 keyword search, local embedding similarity, Reciprocal Rank Fusion, and nearby chunk context expansion.
