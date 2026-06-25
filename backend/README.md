# ingestor-docs

Python package for the Ingestor local documentation daemon and CLI.

The package exposes two console commands:

- `ingestor` calls a running local Ingestor daemon API.
- `ingestor-daemon` starts the local FastAPI daemon.

## Usage

Run against an already running desktop app or daemon:

```powershell
uvx --from ingestor-docs ingestor health
uvx --from ingestor-docs ingestor list --output json
uvx --from ingestor-docs ingestor search all "query" --output json
```

Start the daemon from the package:

```powershell
uvx --from ingestor-docs ingestor daemon
```

Or let a CLI command start the daemon when it is not already reachable:

```powershell
uvx --from ingestor-docs ingestor --start-daemon search all "query" --output json
```

By default, the CLI talks to `http://127.0.0.1:8765`. Use `--api-url` or `INGESTOR_API_URL` to point it at a different local daemon.

## Development

```powershell
cd backend
.\.venv\Scripts\python.exe -m app.daemon
.\.venv\Scripts\python.exe -m app.cli health
```

The index lives in `backend/data/ingestor.sqlite` during local development unless `INGESTOR_DATA_DIR` is set. Hybrid retrieval uses SQLite FTS5 keyword search, local embedding similarity, Reciprocal Rank Fusion, and nearby chunk context expansion.
