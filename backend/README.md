# Ingestor Backend

Standalone documentation ingestion and retrieval service.

```powershell
cd backend
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m app.cli serve
```

CLI examples:

```powershell
.\.venv\Scripts\python.exe -m app.cli index-local ..\references\docs-mcp-server\README.md --name docs-mcp-server
.\.venv\Scripts\python.exe -m app.cli search docs-mcp-server "local folder indexing" --output yaml
```

The index lives in `backend/data/ingestor.sqlite`. Hybrid retrieval uses SQLite FTS5 keyword search, local embedding similarity, Reciprocal Rank Fusion, and nearby chunk context expansion.
