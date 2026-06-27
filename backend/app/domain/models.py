from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, HttpUrl


def utc_now() -> datetime:
    return datetime.now(UTC)


class SourceKind(StrEnum):
    LOCAL = "local"
    WEB = "web"


class SourceStatus(StrEnum):
    REGISTERED = "registered"
    INDEXING = "indexing"
    INDEXED = "indexed"
    FAILED = "failed"


class JobStatus(StrEnum):
    RUNNING = "running"
    CANCELLING = "cancelling"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class SearchMode(StrEnum):
    HYBRID = "hybrid"
    KEYWORD = "keyword"
    VECTOR = "vector"


class EmbeddingIndexingStrategy(StrEnum):
    BATCH = "batch"
    SINGLE = "single"


class LocalSourceRequest(BaseModel):
    paths: list[Path] = Field(default_factory=list)
    path: Path | None = None
    name: str = Field(min_length=1, max_length=120)
    version: str | None = None

    def selected_paths(self) -> list[Path]:
        return self.paths or ([self.path] if self.path else [])


class WebSourceRequest(BaseModel):
    url: HttpUrl
    name: str = Field(min_length=1, max_length=120)
    version: str | None = None
    max_depth: int = Field(default=3, ge=0, le=10)
    max_pages: int = Field(default=1000, ge=1, le=1000)
    scope: Literal["subpages", "hostname", "domain"] = "hostname"
    include_patterns: list[str] = Field(default_factory=list)
    exclude_patterns: list[str] = Field(default_factory=list)


class SourceRecord(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    kind: SourceKind
    name: str
    version: str = "latest"
    location: str
    status: SourceStatus = SourceStatus.REGISTERED
    document_count: int = 0
    chunk_count: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class JobRecord(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    source_id: str
    status: JobStatus = JobStatus.RUNNING
    message: str = ""
    progress_current: int = 0
    progress_total: int | None = None
    progress_label: str = ""
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class SearchRequest(BaseModel):
    source_id: str | None = None
    source: str | None = None
    query: str
    limit: int = Field(default=8, ge=1, le=50)
    mode: SearchMode | None = None


class SearchResult(BaseModel):
    source_id: str
    source_name: str
    title: str
    uri: str
    content: str
    summary: str = ""
    code: str | None = None
    section_path: list[str] = Field(default_factory=list)
    score: float
    keyword_score: float = 0
    vector_score: float = 0


class SearchResponse(BaseModel):
    command: list[str]
    results: list[SearchResult]
    stdout: str = ""
    stderr: str = ""


class EmbeddingSettingsUpdate(BaseModel):
    model: str = Field(min_length=1, max_length=200)


class RetrievalSettingsUpdate(BaseModel):
    mode: SearchMode


class EmbeddingIndexingSettingsUpdate(BaseModel):
    strategy: EmbeddingIndexingStrategy
    batch_size: int = Field(ge=1, le=256)


class SourceRegistrationResponse(BaseModel):
    source: SourceRecord
    command_preview: list[str]


class SourceDeletionResponse(BaseModel):
    deleted_source: SourceRecord


class FolderPickResponse(BaseModel):
    path: str | None


class FilePickResponse(BaseModel):
    paths: list[str]
