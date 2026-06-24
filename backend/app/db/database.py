from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from pathlib import Path

from sqlalchemy import delete, event, func, inspect, text
from sqlmodel import Session, SQLModel, create_engine, select

from app.core.config import get_settings
from app.db.models import AppSettingTable, ChunkTable, DocumentTable, JobTable, SourceTable, chunks_fts
from app.domain.models import JobRecord, JobStatus, SourceKind, SourceRecord, SourceStatus, utc_now
from app.retrieval import vector_index


class Database:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or get_settings().database_path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        sqlite_url = f"sqlite:///{self.path.resolve().as_posix()}"
        self.engine = create_engine(sqlite_url, connect_args={"timeout": 30})
        self._configure_sqlite()
        self.initialize()

    def _configure_sqlite(self) -> None:
        @event.listens_for(self.engine, "connect")
        def set_sqlite_pragmas(dbapi_connection: sqlite3.Connection, _connection_record: object) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys = ON")
            cursor.execute("PRAGMA journal_mode = WAL")
            cursor.close()
            vector_index.load(dbapi_connection)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        vector_index.load(connection)
        return connection

    def initialize(self) -> None:
        SQLModel.metadata.create_all(self.engine)
        with self.engine.begin() as connection:
            # FTS5 virtual tables are SQLite-specific and are not represented by SQLModel.
            connection.exec_driver_sql(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts
                USING fts5(source_id UNINDEXED, title, uri, content)
                """
            )
            connection.exec_driver_sql(
                f"""
                CREATE TABLE IF NOT EXISTS {vector_index.VECTOR_INDEX_META_TABLE} (
                  key TEXT PRIMARY KEY,
                  value TEXT NOT NULL
                )
                """
            )
        self._ensure_column("chunks", "section_path", "TEXT NOT NULL DEFAULT '[]'")
        self._ensure_vector_index()

    def upsert_source(self, source: SourceRecord) -> SourceRecord:
        source.updated_at = utc_now()
        with Session(self.engine) as session:
            row = session.get(SourceTable, source.id)
            if row is None:
                row = self._source_to_table(source)
                session.add(row)
            else:
                self._assign_source(row, source)
            session.commit()
        return source

    def list_sources(self) -> list[SourceRecord]:
        with Session(self.engine) as session:
            rows = session.exec(select(SourceTable).order_by(SourceTable.updated_at.desc())).all()
        return [self._source_from_table(row) for row in rows]

    def get_source(self, source_id: str) -> SourceRecord | None:
        with Session(self.engine) as session:
            row = session.get(SourceTable, source_id)
        return self._source_from_table(row) if row else None

    def find_source(self, key: str) -> SourceRecord | None:
        with Session(self.engine) as session:
            row = session.get(SourceTable, key)
            if row is None:
                row = session.exec(
                    select(SourceTable)
                    .where(func.lower(SourceTable.name) == key.lower())
                    .order_by(SourceTable.updated_at.desc())
                    .limit(1)
                ).first()
        return self._source_from_table(row) if row else None

    def find_source_by_name(self, name: str) -> SourceRecord | None:
        with Session(self.engine) as session:
            row = session.exec(
                select(SourceTable)
                .where(func.lower(SourceTable.name) == name.lower())
                .order_by(SourceTable.updated_at.desc())
                .limit(1)
            ).first()
        return self._source_from_table(row) if row else None

    def delete_source(self, source_id: str) -> SourceRecord | None:
        with Session(self.engine) as session:
            row = session.get(SourceTable, source_id)
            if row is None:
                return None
            source = self._source_from_table(row)
            self._delete_fts_rows_for_source(session, source_id)
            session.delete(row)
            session.commit()
        return source

    def create_job(self, source_id: str) -> JobRecord:
        job = JobRecord(source_id=source_id)
        with Session(self.engine) as session:
            session.add(self._job_to_table(job))
            session.commit()
        return job

    def update_job(self, job: JobRecord, status: JobStatus | None = None, message: str | None = None) -> JobRecord:
        if status is not None:
            job.status = status
        if message is not None:
            job.message = message
        job.updated_at = utc_now()
        with Session(self.engine) as session:
            row = session.get(JobTable, job.id)
            if row is not None:
                row.status = self._enum_value(job.status)
                row.message = job.message
                row.updated_at = job.updated_at.isoformat()
                session.add(row)
                session.commit()
        return job

    def get_job(self, job_id: str) -> JobRecord | None:
        with Session(self.engine) as session:
            row = session.get(JobTable, job_id)
        return self._job_from_table(row) if row else None

    def list_jobs(self) -> list[JobRecord]:
        with Session(self.engine) as session:
            rows = session.exec(select(JobTable).order_by(JobTable.created_at.desc()).limit(50)).all()
        return [self._job_from_table(row) for row in rows]

    def get_app_setting(self, key: str) -> str | None:
        with Session(self.engine) as session:
            row = session.get(AppSettingTable, key)
        return row.value if row else None

    def set_app_setting(self, key: str, value: str) -> None:
        with Session(self.engine) as session:
            row = session.get(AppSettingTable, key)
            if row is None:
                row = AppSettingTable(key=key, value=value, updated_at=utc_now().isoformat())
            else:
                row.value = value
                row.updated_at = utc_now().isoformat()
            session.add(row)
            session.commit()

    def delete_app_settings(self, keys: Iterable[str]) -> None:
        key_list = list(keys)
        if not key_list:
            return
        with Session(self.engine) as session:
            session.execute(delete(AppSettingTable).where(AppSettingTable.key.in_(key_list)))
            session.commit()

    def replace_source_documents(self, source: SourceRecord, documents: Iterable[dict]) -> SourceRecord:
        with Session(self.engine) as session:
            self._clear_source_documents(session, source.id)

            document_count = 0
            chunk_count = 0
            for document in documents:
                inserted = self._insert_document(session, source.id, document)
                document_count += 1
                chunk_count += inserted

            source.document_count = document_count
            source.chunk_count = chunk_count
            source.status = SourceStatus.INDEXED
            source.error = None
            source.updated_at = utc_now()
            self._upsert_source_row(session, source)
            session.commit()
        return source

    def clear_source_documents(self, source: SourceRecord) -> SourceRecord:
        with Session(self.engine) as session:
            self._clear_source_documents(session, source.id)
            source.document_count = 0
            source.chunk_count = 0
            source.status = SourceStatus.INDEXING
            source.error = None
            source.updated_at = utc_now()
            self._upsert_source_row(session, source)
            session.commit()
        return source

    def add_source_document(self, source: SourceRecord, document: dict) -> SourceRecord:
        with Session(self.engine) as session:
            self._insert_document(session, source.id, document)
            source.document_count = self._count(session, DocumentTable.id, DocumentTable.source_id == source.id)
            source.chunk_count = self._count(session, ChunkTable.id, ChunkTable.source_id == source.id)
            source.status = SourceStatus.INDEXING
            source.error = None
            source.updated_at = utc_now()
            self._upsert_source_row(session, source)
            session.commit()
        return source

    def _upsert_source_row(self, session: Session, source: SourceRecord) -> SourceTable:
        row = session.get(SourceTable, source.id)
        if row is None:
            row = self._source_to_table(source)
        else:
            self._assign_source(row, source)
        session.add(row)
        return row

    def _source_to_table(self, source: SourceRecord) -> SourceTable:
        return SourceTable(
            id=source.id,
            kind=self._enum_value(source.kind),
            name=source.name,
            version=source.version,
            location=source.location,
            status=self._enum_value(source.status),
            document_count=source.document_count,
            chunk_count=source.chunk_count,
            metadata_=json.dumps(source.metadata),
            error=source.error,
            created_at=source.created_at.isoformat(),
            updated_at=source.updated_at.isoformat(),
        )

    def _assign_source(self, row: SourceTable, source: SourceRecord) -> None:
        row.kind = self._enum_value(source.kind)
        row.name = source.name
        row.version = source.version
        row.location = source.location
        row.status = self._enum_value(source.status)
        row.document_count = source.document_count
        row.chunk_count = source.chunk_count
        row.metadata_ = json.dumps(source.metadata)
        row.error = source.error
        row.updated_at = source.updated_at.isoformat()

    def _job_to_table(self, job: JobRecord) -> JobTable:
        return JobTable(
            id=job.id,
            source_id=job.source_id,
            status=self._enum_value(job.status),
            message=job.message,
            created_at=job.created_at.isoformat(),
            updated_at=job.updated_at.isoformat(),
        )

    def _clear_source_documents(self, session: Session, source_id: str) -> None:
        self._delete_fts_rows_for_source(session, source_id)
        session.execute(delete(DocumentTable).where(DocumentTable.source_id == source_id))

    def _delete_fts_rows_for_source(self, session: Session, source_id: str) -> None:
        chunk_ids = session.exec(select(ChunkTable.id).where(ChunkTable.source_id == source_id)).all()
        if chunk_ids:
            session.execute(chunks_fts.delete().where(chunks_fts.c.rowid.in_(chunk_ids)))
            self._delete_vector_rows(session, [int(chunk_id) for chunk_id in chunk_ids if chunk_id is not None])

    def _insert_document(self, session: Session, source_id: str, document: dict) -> int:
        document_row = DocumentTable(
            source_id=source_id,
            uri=document["uri"],
            title=document["title"],
            content=document["content"],
            content_hash=document["content_hash"],
            created_at=utc_now().isoformat(),
        )
        session.add(document_row)
        session.flush()
        if document_row.id is None:
            raise RuntimeError("Document insert did not return an id")

        chunk_count = 0
        for chunk in document["chunks"]:
            chunk_row = ChunkTable(
                source_id=source_id,
                document_id=document_row.id,
                ordinal=chunk["ordinal"],
                title=chunk["title"],
                uri=chunk["uri"],
                content=chunk["content"],
                section_path=json.dumps(chunk.get("section_path", [])),
                token_count=chunk["token_count"],
                embedding=json.dumps(chunk["embedding"]),
            )
            session.add(chunk_row)
            session.flush()
            if chunk_row.id is None:
                raise RuntimeError("Chunk insert did not return an id")
            self._insert_vector_row(session, chunk_row.id, source_id, chunk["embedding"])
            session.execute(
                chunks_fts.insert().values(
                    rowid=chunk_row.id,
                    source_id=source_id,
                    title=chunk["title"],
                    uri=chunk["uri"],
                    content=chunk["content"],
                )
            )
            chunk_count += 1
        return chunk_count

    def _insert_vector_row(self, session: Session, chunk_id: int, source_id: str, embedding: object) -> None:
        vector = vector_index.parse_embedding(embedding)
        if vector is None:
            return
        connection = session.connection().connection.driver_connection
        vector_index.ensure_index_table(connection, len(vector))
        serialized = vector_index.serialize(vector)
        session.execute(
            text(
                f"""
                INSERT OR REPLACE INTO {vector_index.CHUNKS_VEC_TABLE} (rowid, source_id, embedding)
                VALUES (:rowid, :source_id, :embedding)
                """
            ),
            {"rowid": chunk_id, "source_id": source_id, "embedding": serialized},
        )

    def _delete_vector_rows(self, session: Session, chunk_ids: list[int]) -> None:
        if not chunk_ids:
            return
        connection = session.connection().connection.driver_connection
        if not vector_index.table_exists(connection, vector_index.CHUNKS_VEC_TABLE):
            return
        for chunk_id in chunk_ids:
            session.execute(
                text(f"DELETE FROM {vector_index.CHUNKS_VEC_TABLE} WHERE rowid = :rowid"),
                {"rowid": chunk_id},
            )

    def _ensure_vector_index(self) -> None:
        with self.connect() as connection:
            rows = connection.execute("SELECT id, source_id, embedding FROM chunks").fetchall()
            vectors: list[tuple[int, str, list[float]]] = []
            dimensions: int | None = None
            for row in rows:
                vector = vector_index.parse_embedding(row["embedding"])
                if vector is None:
                    continue
                if dimensions is None:
                    dimensions = len(vector)
                if len(vector) == dimensions:
                    vectors.append((int(row["id"]), str(row["source_id"]), vector))
            if dimensions is None:
                return
            vector_index.ensure_index_table(connection, dimensions)
            for chunk_id, source_id, vector in vectors:
                connection.execute(
                    f"""
                    INSERT OR REPLACE INTO {vector_index.CHUNKS_VEC_TABLE} (rowid, source_id, embedding)
                    VALUES (?, ?, ?)
                    """,
                    (chunk_id, source_id, vector_index.serialize(vector)),
                )
            connection.commit()

    def _source_from_table(self, row: SourceTable) -> SourceRecord:
        return SourceRecord(
            id=row.id,
            kind=SourceKind(row.kind),
            name=row.name,
            version=row.version,
            location=row.location,
            status=SourceStatus(row.status),
            document_count=row.document_count,
            chunk_count=row.chunk_count,
            metadata=json.loads(row.metadata_ or "{}"),
            error=row.error,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    def _job_from_table(self, row: JobTable) -> JobRecord:
        return JobRecord(
            id=row.id,
            source_id=row.source_id,
            status=JobStatus(row.status),
            message=row.message,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    def _count(self, session: Session, column: object, condition: object) -> int:
        return int(session.exec(select(func.count(column)).where(condition)).one())

    def _ensure_column(self, table: str, column: str, definition: str) -> None:
        columns = {item["name"] for item in inspect(self.engine).get_columns(table)}
        if column not in columns:
            with self.engine.begin() as connection:
                connection.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def _enum_value(self, value: object) -> str:
        return str(getattr(value, "value", value))


db = Database()

