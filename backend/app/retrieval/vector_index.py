from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence

import sqlite_vec
from sqlalchemy import Column, Integer, LargeBinary, MetaData, String, Table

CHUNKS_VEC_TABLE = "chunks_vec"
VECTOR_INDEX_META_TABLE = "vector_index_meta"
VECTOR_INDEX_DIMENSIONS_KEY = "dimensions"

chunks_vec = Table(
    CHUNKS_VEC_TABLE,
    MetaData(),
    Column("rowid", Integer, primary_key=True),
    Column("source_id", String),
    Column("embedding", LargeBinary),
)


def load(connection: sqlite3.Connection) -> None:
    try:
        connection.enable_load_extension(True)
        sqlite_vec.load(connection)
    except Exception as exc:
        raise RuntimeError("sqlite-vec is required but could not be loaded") from exc
    finally:
        try:
            connection.enable_load_extension(False)
        except Exception:
            pass


def serialize(vector: Sequence[float]) -> bytes:
    return sqlite_vec.serialize_float32([float(value) for value in vector])


def parse_embedding(value: object) -> list[float] | None:
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return None
    else:
        parsed = value
    if not isinstance(parsed, list) or not parsed:
        return None
    if not all(isinstance(item, (int, float)) for item in parsed):
        return None
    return [float(item) for item in parsed]


def ensure_meta_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {VECTOR_INDEX_META_TABLE} (
          key TEXT PRIMARY KEY,
          value TEXT NOT NULL
        )
        """
    )


def table_exists(connection: sqlite3.Connection, table_name: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE name = ? AND type IN ('table', 'virtual table')",
        (table_name,),
    ).fetchone()
    return row is not None


def current_dimensions(connection: sqlite3.Connection) -> int | None:
    ensure_meta_table(connection)
    row = connection.execute(
        f"SELECT value FROM {VECTOR_INDEX_META_TABLE} WHERE key = ?",
        (VECTOR_INDEX_DIMENSIONS_KEY,),
    ).fetchone()
    if row is None:
        return None
    try:
        return int(row[0])
    except (TypeError, ValueError):
        return None


def record_dimensions(connection: sqlite3.Connection, dimensions: int) -> None:
    ensure_meta_table(connection)
    connection.execute(
        f"""
        INSERT INTO {VECTOR_INDEX_META_TABLE} (key, value)
        VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (VECTOR_INDEX_DIMENSIONS_KEY, str(dimensions)),
    )


def create_index_table(connection: sqlite3.Connection, dimensions: int) -> None:
    connection.execute(f"DROP TABLE IF EXISTS {CHUNKS_VEC_TABLE}")
    connection.execute(
        f"""
        CREATE VIRTUAL TABLE {CHUNKS_VEC_TABLE}
        USING vec0(
          source_id TEXT partition key,
          embedding float[{dimensions}]
        )
        """
    )
    record_dimensions(connection, dimensions)


def ensure_index_table(connection: sqlite3.Connection, dimensions: int) -> None:
    if dimensions <= 0:
        raise ValueError("Vector index dimensions must be positive")
    if not table_exists(connection, CHUNKS_VEC_TABLE) or current_dimensions(connection) != dimensions:
        create_index_table(connection, dimensions)


def insert_row(session: object, chunk_id: int, source_id: str, embedding: object) -> None:
    vector = parse_embedding(embedding)
    if vector is None:
        return
    ensure_index_table(driver_connection(session), len(vector))
    session.execute(
        chunks_vec.insert().prefix_with("OR REPLACE").values(
            rowid=chunk_id,
            source_id=source_id,
            embedding=serialize(vector),
        )
    )


def delete_rows(session: object, chunk_ids: Sequence[int]) -> None:
    ids = list(chunk_ids)
    if not ids:
        return
    if not table_exists(driver_connection(session), CHUNKS_VEC_TABLE):
        return
    session.execute(chunks_vec.delete().where(chunks_vec.c.rowid.in_(ids)))


def rebuild(session: object, rows: Sequence[tuple[int, str, object]]) -> None:
    vectors: list[tuple[int, str, list[float]]] = []
    dimensions: int | None = None
    for chunk_id, source_id, embedding in rows:
        vector = parse_embedding(embedding)
        if vector is None:
            continue
        if dimensions is None:
            dimensions = len(vector)
        if len(vector) == dimensions:
            vectors.append((chunk_id, source_id, vector))
    if dimensions is None:
        return

    ensure_index_table(driver_connection(session), dimensions)
    session.execute(chunks_vec.delete())
    for chunk_id, source_id, vector in vectors:
        session.execute(
            chunks_vec.insert().prefix_with("OR REPLACE").values(
                rowid=chunk_id,
                source_id=source_id,
                embedding=serialize(vector),
            )
        )


def driver_connection(session: object) -> sqlite3.Connection:
    return session.connection().connection.driver_connection


def query(
    connection: sqlite3.Connection,
    vector: Sequence[float],
    *,
    source_id: str | None = None,
    limit: int,
) -> list[tuple[int, float]]:
    if not table_exists(connection, CHUNKS_VEC_TABLE):
        raise RuntimeError("sqlite-vec chunk index has not been created")
    if current_dimensions(connection) != len(vector):
        return []
    serialized = serialize(vector)
    if source_id is None:
        rows = connection.execute(
            f"""
            SELECT rowid AS chunk_id, distance
            FROM {CHUNKS_VEC_TABLE}
            WHERE embedding MATCH ?
              AND k = ?
            ORDER BY distance
            """,
            (serialized, limit),
        ).fetchall()
    else:
        rows = connection.execute(
            f"""
            SELECT rowid AS chunk_id, distance
            FROM {CHUNKS_VEC_TABLE}
            WHERE embedding MATCH ?
              AND k = ?
              AND source_id = ?
            ORDER BY distance
            """,
            (serialized, limit, source_id),
        ).fetchall()
    return [(int(row["chunk_id"]), float(row["distance"])) for row in rows]
