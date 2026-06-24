from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from pathlib import Path

from app.config import get_settings
from app.models import JobRecord, JobStatus, SourceKind, SourceRecord, SourceStatus, utc_now


class Database:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or get_settings().database_path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def initialize(self) -> None:
        with sqlite3.connect(self.path) as connection:
            connection.executescript(
                """
                PRAGMA journal_mode = WAL;
                CREATE TABLE IF NOT EXISTS sources (
                  id TEXT PRIMARY KEY,
                  kind TEXT NOT NULL,
                  name TEXT NOT NULL,
                  version TEXT NOT NULL,
                  location TEXT NOT NULL,
                  status TEXT NOT NULL,
                  document_count INTEGER NOT NULL DEFAULT 0,
                  chunk_count INTEGER NOT NULL DEFAULT 0,
                  metadata TEXT NOT NULL DEFAULT '{}',
                  error TEXT,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS jobs (
                  id TEXT PRIMARY KEY,
                  source_id TEXT NOT NULL,
                  status TEXT NOT NULL,
                  message TEXT NOT NULL DEFAULT '',
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  FOREIGN KEY(source_id) REFERENCES sources(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS documents (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  source_id TEXT NOT NULL,
                  uri TEXT NOT NULL,
                  title TEXT NOT NULL,
                  content TEXT NOT NULL,
                  content_hash TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  FOREIGN KEY(source_id) REFERENCES sources(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS chunks (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  source_id TEXT NOT NULL,
                  document_id INTEGER NOT NULL,
                  ordinal INTEGER NOT NULL,
                  title TEXT NOT NULL,
                  uri TEXT NOT NULL,
                  content TEXT NOT NULL,
                  section_path TEXT NOT NULL DEFAULT '[]',
                  token_count INTEGER NOT NULL,
                  embedding TEXT NOT NULL,
                  FOREIGN KEY(source_id) REFERENCES sources(id) ON DELETE CASCADE,
                  FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS app_settings (
                  key TEXT PRIMARY KEY,
                  value TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                );
                CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts
                USING fts5(source_id UNINDEXED, title, uri, content);
                CREATE INDEX IF NOT EXISTS idx_sources_name ON sources(name, version);
                CREATE INDEX IF NOT EXISTS idx_chunks_source ON chunks(source_id);
                CREATE INDEX IF NOT EXISTS idx_chunks_document_ordinal ON chunks(document_id, ordinal);
                """
            )
            self._ensure_column(connection, "chunks", "section_path", "TEXT NOT NULL DEFAULT '[]'")

    def upsert_source(self, source: SourceRecord) -> SourceRecord:
        source.updated_at = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO sources (
                  id, kind, name, version, location, status, document_count,
                  chunk_count, metadata, error, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  kind=excluded.kind,
                  name=excluded.name,
                  version=excluded.version,
                  location=excluded.location,
                  status=excluded.status,
                  document_count=excluded.document_count,
                  chunk_count=excluded.chunk_count,
                  metadata=excluded.metadata,
                  error=excluded.error,
                  updated_at=excluded.updated_at
                """,
                self._source_values(source),
            )
        return source

    def list_sources(self) -> list[SourceRecord]:
        with self.connect() as connection:
            rows = connection.execute("SELECT * FROM sources ORDER BY updated_at DESC").fetchall()
        return [self._source_from_row(row) for row in rows]

    def get_source(self, source_id: str) -> SourceRecord | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
        return self._source_from_row(row) if row else None

    def find_source(self, key: str) -> SourceRecord | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM sources WHERE id = ?", (key,)).fetchone()
            if row is None:
                row = connection.execute(
                    "SELECT * FROM sources WHERE lower(name) = lower(?) ORDER BY updated_at DESC LIMIT 1",
                    (key,),
                ).fetchone()
        return self._source_from_row(row) if row else None

    def find_source_by_name(self, name: str) -> SourceRecord | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM sources WHERE lower(name) = lower(?) ORDER BY updated_at DESC LIMIT 1",
                (name,),
            ).fetchone()
        return self._source_from_row(row) if row else None

    def delete_source(self, source_id: str) -> SourceRecord | None:
        source = self.get_source(source_id)
        if source is None:
            return None
        with self.connect() as connection:
            chunk_ids = [row["id"] for row in connection.execute("SELECT id FROM chunks WHERE source_id = ?", (source_id,))]
            for chunk_id in chunk_ids:
                connection.execute("DELETE FROM chunks_fts WHERE rowid = ?", (chunk_id,))
            connection.execute("DELETE FROM sources WHERE id = ?", (source_id,))
        return source

    def create_job(self, source_id: str) -> JobRecord:
        job = JobRecord(source_id=source_id)
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO jobs (id, source_id, status, message, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (job.id, job.source_id, job.status, job.message, job.created_at.isoformat(), job.updated_at.isoformat()),
            )
        return job

    def update_job(self, job: JobRecord, status: JobStatus | None = None, message: str | None = None) -> JobRecord:
        if status is not None:
            job.status = status
        if message is not None:
            job.message = message
        job.updated_at = utc_now()
        with self.connect() as connection:
            connection.execute(
                "UPDATE jobs SET status = ?, message = ?, updated_at = ? WHERE id = ?",
                (job.status, job.message, job.updated_at.isoformat(), job.id),
            )
        return job

    def get_job(self, job_id: str) -> JobRecord | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return self._job_from_row(row) if row else None

    def list_jobs(self) -> list[JobRecord]:
        with self.connect() as connection:
            rows = connection.execute("SELECT * FROM jobs ORDER BY created_at DESC LIMIT 50").fetchall()
        return [self._job_from_row(row) for row in rows]

    def get_app_setting(self, key: str) -> str | None:
        with self.connect() as connection:
            row = connection.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
        return str(row["value"]) if row else None

    def set_app_setting(self, key: str, value: str) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO app_settings (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                  value=excluded.value,
                  updated_at=excluded.updated_at
                """,
                (key, value, utc_now().isoformat()),
            )

    def delete_app_settings(self, keys: Iterable[str]) -> None:
        key_list = list(keys)
        if not key_list:
            return
        placeholders = ",".join("?" for _ in key_list)
        with self.connect() as connection:
            connection.execute(f"DELETE FROM app_settings WHERE key IN ({placeholders})", key_list)

    def replace_source_documents(self, source: SourceRecord, documents: Iterable[dict]) -> SourceRecord:
        with self.connect() as connection:
            self._clear_source_documents(connection, source.id)

            document_count = 0
            chunk_count = 0
            for document in documents:
                inserted = self._insert_document(connection, source.id, document)
                document_count += 1
                chunk_count += inserted

            source.document_count = document_count
            source.chunk_count = chunk_count
            source.status = SourceStatus.INDEXED
            source.error = None
            connection.execute(
                """
                UPDATE sources SET status = ?, document_count = ?, chunk_count = ?,
                error = NULL, updated_at = ? WHERE id = ?
                """,
                (source.status, document_count, chunk_count, utc_now().isoformat(), source.id),
            )
        return source

    def clear_source_documents(self, source: SourceRecord) -> SourceRecord:
        with self.connect() as connection:
            self._clear_source_documents(connection, source.id)
            source.document_count = 0
            source.chunk_count = 0
            source.status = SourceStatus.INDEXING
            source.error = None
            connection.execute(
                """
                UPDATE sources SET status = ?, document_count = 0, chunk_count = 0,
                error = NULL, updated_at = ? WHERE id = ?
                """,
                (source.status, utc_now().isoformat(), source.id),
            )
        return source

    def add_source_document(self, source: SourceRecord, document: dict) -> SourceRecord:
        with self.connect() as connection:
            self._insert_document(connection, source.id, document)
            counts = connection.execute(
                """
                SELECT
                  (SELECT count(*) FROM documents WHERE source_id = ?) AS document_count,
                  (SELECT count(*) FROM chunks WHERE source_id = ?) AS chunk_count
                """,
                (source.id, source.id),
            ).fetchone()
            source.document_count = int(counts["document_count"])
            source.chunk_count = int(counts["chunk_count"])
            source.status = SourceStatus.INDEXING
            connection.execute(
                """
                UPDATE sources SET status = ?, document_count = ?, chunk_count = ?,
                error = NULL, updated_at = ? WHERE id = ?
                """,
                (
                    source.status,
                    source.document_count,
                    source.chunk_count,
                    utc_now().isoformat(),
                    source.id,
                ),
            )
        return source

    def _source_values(self, source: SourceRecord) -> tuple:
        return (
            source.id,
            source.kind,
            source.name,
            source.version,
            source.location,
            source.status,
            source.document_count,
            source.chunk_count,
            json.dumps(source.metadata),
            source.error,
            source.created_at.isoformat(),
            source.updated_at.isoformat(),
        )

    def _clear_source_documents(self, connection: sqlite3.Connection, source_id: str) -> None:
        chunk_ids = [row["id"] for row in connection.execute("SELECT id FROM chunks WHERE source_id = ?", (source_id,))]
        for chunk_id in chunk_ids:
            connection.execute("DELETE FROM chunks_fts WHERE rowid = ?", (chunk_id,))
        connection.execute("DELETE FROM documents WHERE source_id = ?", (source_id,))

    def _insert_document(self, connection: sqlite3.Connection, source_id: str, document: dict) -> int:
        cursor = connection.execute(
            """
            INSERT INTO documents (source_id, uri, title, content, content_hash, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                source_id,
                document["uri"],
                document["title"],
                document["content"],
                document["content_hash"],
                utc_now().isoformat(),
            ),
        )
        document_id = int(cursor.lastrowid)
        chunk_count = 0
        for chunk in document["chunks"]:
            chunk_cursor = connection.execute(
                """
                INSERT INTO chunks (
                  source_id, document_id, ordinal, title, uri, content,
                  section_path, token_count, embedding
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source_id,
                    document_id,
                    chunk["ordinal"],
                    chunk["title"],
                    chunk["uri"],
                    chunk["content"],
                    json.dumps(chunk.get("section_path", [])),
                    chunk["token_count"],
                    json.dumps(chunk["embedding"]),
                ),
            )
            chunk_id = int(chunk_cursor.lastrowid)
            connection.execute(
                "INSERT INTO chunks_fts (rowid, source_id, title, uri, content) VALUES (?, ?, ?, ?, ?)",
                (chunk_id, source_id, chunk["title"], chunk["uri"], chunk["content"]),
            )
            chunk_count += 1
        return chunk_count

    def _source_from_row(self, row: sqlite3.Row) -> SourceRecord:
        return SourceRecord(
            id=row["id"],
            kind=SourceKind(row["kind"]),
            name=row["name"],
            version=row["version"],
            location=row["location"],
            status=SourceStatus(row["status"]),
            document_count=row["document_count"],
            chunk_count=row["chunk_count"],
            metadata=json.loads(row["metadata"] or "{}"),
            error=row["error"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _job_from_row(self, row: sqlite3.Row) -> JobRecord:
        return JobRecord(
            id=row["id"],
            source_id=row["source_id"],
            status=JobStatus(row["status"]),
            message=row["message"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _ensure_column(self, connection: sqlite3.Connection, table: str, column: str, definition: str) -> None:
        columns = {row[1] for row in connection.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in columns:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


db = Database()
