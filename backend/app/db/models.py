from __future__ import annotations

from sqlalchemy import Column, ForeignKey, Index, Integer, MetaData, String, Table, Text
from sqlmodel import Field, SQLModel


class SourceTable(SQLModel, table=True):
    __tablename__ = "sources"
    __table_args__ = (Index("idx_sources_name", "name", "version"),)

    id: str = Field(primary_key=True)
    kind: str = Field(sa_column=Column(String, nullable=False))
    name: str = Field(sa_column=Column(String, nullable=False))
    version: str = Field(sa_column=Column(String, nullable=False))
    location: str = Field(sa_column=Column(Text, nullable=False))
    status: str = Field(sa_column=Column(String, nullable=False))
    document_count: int = Field(default=0, sa_column=Column(Integer, nullable=False, server_default="0"))
    chunk_count: int = Field(default=0, sa_column=Column(Integer, nullable=False, server_default="0"))
    metadata_: str = Field(default="{}", sa_column=Column("metadata", Text, nullable=False, server_default="{}"))
    error: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    created_at: str = Field(sa_column=Column(String, nullable=False))
    updated_at: str = Field(sa_column=Column(String, nullable=False))


class JobTable(SQLModel, table=True):
    __tablename__ = "jobs"

    id: str = Field(primary_key=True)
    source_id: str = Field(sa_column=Column(String, ForeignKey("sources.id", ondelete="CASCADE"), nullable=False))
    status: str = Field(sa_column=Column(String, nullable=False))
    message: str = Field(default="", sa_column=Column(Text, nullable=False, server_default=""))
    created_at: str = Field(sa_column=Column(String, nullable=False))
    updated_at: str = Field(sa_column=Column(String, nullable=False))


class DocumentTable(SQLModel, table=True):
    __tablename__ = "documents"

    id: int | None = Field(default=None, sa_column=Column(Integer, primary_key=True, autoincrement=True))
    source_id: str = Field(sa_column=Column(String, ForeignKey("sources.id", ondelete="CASCADE"), nullable=False))
    uri: str = Field(sa_column=Column(Text, nullable=False))
    title: str = Field(sa_column=Column(Text, nullable=False))
    content: str = Field(sa_column=Column(Text, nullable=False))
    content_hash: str = Field(sa_column=Column(Text, nullable=False))
    created_at: str = Field(sa_column=Column(String, nullable=False))


class ChunkTable(SQLModel, table=True):
    __tablename__ = "chunks"
    __table_args__ = (
        Index("idx_chunks_source", "source_id"),
        Index("idx_chunks_document_ordinal", "document_id", "ordinal"),
    )

    id: int | None = Field(default=None, sa_column=Column(Integer, primary_key=True, autoincrement=True))
    source_id: str = Field(sa_column=Column(String, ForeignKey("sources.id", ondelete="CASCADE"), nullable=False))
    document_id: int = Field(sa_column=Column(Integer, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False))
    ordinal: int = Field(sa_column=Column(Integer, nullable=False))
    title: str = Field(sa_column=Column(Text, nullable=False))
    uri: str = Field(sa_column=Column(Text, nullable=False))
    content: str = Field(sa_column=Column(Text, nullable=False))
    section_path: str = Field(default="[]", sa_column=Column(Text, nullable=False, server_default="[]"))
    token_count: int = Field(sa_column=Column(Integer, nullable=False))
    embedding: str = Field(sa_column=Column(Text, nullable=False))


class AppSettingTable(SQLModel, table=True):
    __tablename__ = "app_settings"

    key: str = Field(primary_key=True)
    value: str = Field(sa_column=Column(Text, nullable=False))
    updated_at: str = Field(sa_column=Column(String, nullable=False))


fts_metadata = MetaData()
chunks_fts = Table(
    "chunks_fts",
    fts_metadata,
    Column("rowid", Integer, primary_key=True),
    Column("source_id", String),
    Column("title", Text),
    Column("uri", Text),
    Column("content", Text),
)
