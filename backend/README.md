# Ingestor Backend

Standalone documentation ingestion and retrieval package.

```powershell
cd backend
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m app.daemon
```

CLI examples:

```powershell
.\.venv\Scripts\python.exe -m app.cli health
.\.venv\Scripts\python.exe -m app.cli index-local ..\references\docs-mcp-server\README.md --name docs-mcp-server
.\.venv\Scripts\python.exe -m app.cli search docs-mcp-server "local folder indexing" --output json
```

The CLI talks to the daemon API at `http://127.0.0.1:8765`. The index lives in `backend/data/ingestor.sqlite` unless `INGESTOR_DATA_DIR` is set. Hybrid retrieval uses SQLite FTS5 keyword search, local embedding similarity, Reciprocal Rank Fusion, and nearby chunk context expansion.
