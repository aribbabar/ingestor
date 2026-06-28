from __future__ import annotations

import asyncio
import logging
import re
import shutil
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

from app.core.config import get_settings
from app.indexing.crawler import iter_web_documents
from app.db import db
from app.indexing.discovery import SKIP_DIRS as SNAPSHOT_SKIP_DIRS
from app.retrieval.embeddings import embedding_signature, get_embedding_config, get_embedding_indexing_config
from app.indexing.documents import iter_documents_from_paths
from app.domain.models import (
    JobRecord,
    JobStatus,
    LocalSourceRequest,
    SourceKind,
    SourceRecord,
    SourceStatus,
    WebSourceRequest,
)

logger = logging.getLogger(__name__)
active_job_ids: set[str] = set()
active_jobs_lock = threading.Lock()
CANCELLATION_PENDING_MESSAGE = "Cancellation requested. Waiting for the current page fetch to finish."


class IndexCancelled(RuntimeError):
    """Raised when a running indexing job receives a cancellation request."""


def register_local_source(request: LocalSourceRequest) -> SourceRecord:
    paths = [path.expanduser().resolve() for path in request.selected_paths()]
    if not paths:
        raise FileNotFoundError("Select at least one local folder or file.")
    for path in paths:
        if not path.exists():
            raise FileNotFoundError(f"Path does not exist: {path}")
    name = require_unique_source_name(request.name)
    duplicate = find_duplicate_local_path(paths)
    if duplicate is not None:
        path, source = duplicate
        raise ValueError(f'{path} is already registered as "{source.name}". Reindex or delete that source instead.')
    source = SourceRecord(
        kind=SourceKind.LOCAL,
        name=name,
        version=request.version or internal_version(),
        location="; ".join(str(path) for path in paths),
    )
    snapshot = snapshot_local_paths(source, paths)
    source.metadata = {
        "original_paths": [str(path) for path in paths],
        "snapshot_dir": str(snapshot["snapshot_dir"]),
        "snapshot_paths": [str(path) for path in snapshot["snapshot_paths"]],
        "path_mappings": snapshot["path_mappings"],
        "paths": [str(path) for path in snapshot["snapshot_paths"]],
    }
    return db.upsert_source(source)


def find_duplicate_local_path(paths: list[Path]) -> tuple[Path, SourceRecord] | None:
    selected = {path_key(path) for path in paths}
    for source in db.list_sources():
        if source.kind != SourceKind.LOCAL:
            continue
        for original_path in local_source_original_paths(source):
            if path_key(original_path) in selected:
                return original_path, source
    return None


def local_source_original_paths(source: SourceRecord) -> list[Path]:
    metadata_paths = source.metadata.get("original_paths")
    if isinstance(metadata_paths, list):
        return [Path(str(path)).expanduser().resolve() for path in metadata_paths if str(path).strip()]
    return [Path(path.strip()).expanduser().resolve() for path in source.location.split(";") if path.strip()]


def path_key(path: Path) -> str:
    return str(path.expanduser().resolve()).casefold()


def snapshot_local_paths(source: SourceRecord, paths: list[Path]) -> dict:
    settings = get_settings()
    snapshot_dir = unique_snapshot_dir(settings.local_source_dir, f"{internal_version()}-{source.id[:8]}-{safe_path_name(source.name)}")
    snapshot_dir.mkdir(parents=True, exist_ok=False)

    snapshot_paths: list[Path] = []
    mappings: list[dict[str, str]] = []
    used_names: set[str] = set()
    try:
        for path in paths:
            target_name = unique_target_name(path.name or "selection", used_names)
            target = snapshot_dir / target_name
            if path.is_dir():
                shutil.copytree(path, target, ignore=ignore_snapshot_entries)
                kind = "directory"
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)
                kind = "file"
            snapshot_paths.append(target)
            mappings.append({"original": str(path), "stored": str(target), "kind": kind})
    except Exception:
        shutil.rmtree(snapshot_dir, ignore_errors=True)
        raise

    return {
        "snapshot_dir": snapshot_dir,
        "snapshot_paths": snapshot_paths,
        "path_mappings": mappings,
    }


def unique_snapshot_dir(root: Path, name: str) -> Path:
    candidate = root / name
    index = 2
    while candidate.exists():
        candidate = root / f"{name}-{index}"
        index += 1
    return candidate


def ignore_snapshot_entries(directory: str, names: list[str]) -> set[str]:
    return {name for name in names if name in SNAPSHOT_SKIP_DIRS}


def unique_target_name(name: str, used_names: set[str]) -> str:
    candidate = name
    stem = Path(name).stem or "selection"
    suffix = Path(name).suffix
    index = 2
    while candidate.lower() in used_names:
        candidate = f"{stem}-{index}{suffix}"
        index += 1
    used_names.add(candidate.lower())
    return candidate


def safe_path_name(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-._")
    return safe[:48] or "local-docs"


def local_source_paths(source: SourceRecord) -> tuple[list[Path], list[Path] | None]:
    snapshot_paths = metadata_path_list(source, "snapshot_paths")
    original_paths = local_source_original_paths(source)
    if original_paths and should_refresh_local_snapshot(source) and all(path.exists() for path in original_paths):
        return refresh_local_snapshot(source, original_paths), original_paths

    if snapshot_paths and all(path.exists() for path in snapshot_paths):
        return snapshot_paths, None

    if snapshot_paths and original_paths:
        return refresh_local_snapshot(source, original_paths), original_paths

    legacy_paths = metadata_path_list(source, "paths")
    if legacy_paths and all(path.exists() for path in legacy_paths):
        return legacy_paths, None

    if original_paths:
        return refresh_local_snapshot(source, original_paths), original_paths

    raise FileNotFoundError(f"No local paths are available to re-index {source.name}. Re-add the source from its original files.")


def should_refresh_local_snapshot(source: SourceRecord) -> bool:
    return source.status != SourceStatus.REGISTERED or source.document_count > 0 or source.chunk_count > 0


def metadata_path_list(source: SourceRecord, key: str) -> list[Path]:
    paths = source.metadata.get(key, [])
    if not isinstance(paths, list):
        return []
    return [Path(str(path)).expanduser().resolve() for path in paths if str(path).strip()]


def refresh_local_snapshot(source: SourceRecord, original_paths: list[Path]) -> list[Path]:
    missing = [path for path in original_paths if not path.exists()]
    if missing:
        missing_text = "; ".join(str(path) for path in missing)
        raise FileNotFoundError(
            f"Local snapshot for {source.name} is unavailable and original path(s) are missing: {missing_text}. "
            "Re-add the source from an existing folder or file."
        )

    previous_snapshot_dir = source.metadata.get("snapshot_dir")
    snapshot = snapshot_local_paths(source, original_paths)
    source.metadata = {
        **source.metadata,
        "original_paths": [str(path) for path in original_paths],
        "snapshot_dir": str(snapshot["snapshot_dir"]),
        "snapshot_paths": [str(path) for path in snapshot["snapshot_paths"]],
        "path_mappings": snapshot["path_mappings"],
        "paths": [str(path) for path in snapshot["snapshot_paths"]],
    }
    db.upsert_source(source)
    remove_local_snapshot_dir(previous_snapshot_dir, skip=snapshot["snapshot_dir"])
    return list(snapshot["snapshot_paths"])


def remove_local_snapshot(source: SourceRecord) -> None:
    remove_local_snapshot_dir(source.metadata.get("snapshot_dir"))


def remove_local_snapshot_dir(snapshot_dir: object, *, skip: Path | None = None) -> None:
    if not snapshot_dir:
        return
    settings = get_settings()
    root = settings.local_source_dir.resolve()
    target = Path(str(snapshot_dir)).expanduser().resolve()
    if skip and target == skip.expanduser().resolve():
        return
    if target == root or root not in target.parents:
        return
    shutil.rmtree(target, ignore_errors=True)


def delete_source(source_id: str) -> SourceRecord | None:
    deleted = db.delete_source(source_id)
    if deleted and deleted.kind == SourceKind.LOCAL:
        remove_local_snapshot(deleted)
    return deleted


def register_web_source(request: WebSourceRequest) -> SourceRecord:
    name = require_unique_source_name(request.name)
    source = SourceRecord(
        kind=SourceKind.WEB,
        name=name,
        version=request.version or internal_version(),
        location=str(request.url),
        metadata={
            "max_depth": request.max_depth,
            "max_pages": request.max_pages,
            "scope": request.scope,
            "include_patterns": clean_patterns(request.include_patterns),
            "exclude_patterns": clean_patterns(request.exclude_patterns),
        },
    )
    return db.upsert_source(source)


def index_source(source_id: str, job: JobRecord | None = None) -> SourceRecord:
    source = db.get_source(source_id)
    if source is None:
        raise KeyError("Source not found")
    started_at = datetime.now(UTC)
    started_timer = time.perf_counter()
    embedding_config = get_embedding_config()
    indexing_config = get_embedding_indexing_config()
    source.status = SourceStatus.INDEXING
    source.error = None
    db.upsert_source(source)
    log(job, f"Indexing {source.name} ({source.kind})")

    try:
        ensure_job_not_cancelled(job)
        if source.kind == SourceKind.LOCAL:
            indexed = index_local_source_incrementally(source, job)
        else:
            indexed = asyncio.run(index_web_source_incrementally(source, job))
        finished_at = datetime.now(UTC)
        indexed.metadata = {
            **indexed.metadata,
            "embedding": embedding_signature(embedding_config),
            "last_index": {
                "started_at": started_at.isoformat(),
                "finished_at": finished_at.isoformat(),
                "duration_seconds": round(time.perf_counter() - started_timer, 3),
                "document_count": indexed.document_count,
                "chunk_count": indexed.chunk_count,
                "indexing_strategy": indexing_config.strategy.value,
                "embedding_batch_size": indexing_config.batch_size,
                "effective_embedding_batch_size": indexing_config.effective_batch_size,
            },
        }
        indexed = db.upsert_source(indexed)
        log(job, f"Indexed {indexed.document_count} documents into {indexed.chunk_count} chunks")
        if job:
            db.update_job(job, JobStatus.SUCCEEDED, "Index complete")
        return indexed
    except IndexCancelled as exc:
        source = db.get_source(source.id) or source
        source.status = SourceStatus.REGISTERED
        source.error = str(exc)
        db.upsert_source(source)
        log(job, str(exc))
        if job:
            db.update_job(job, JobStatus.CANCELLED, str(exc))
        raise
    except Exception as exc:
        source.status = SourceStatus.FAILED
        source.error = str(exc)
        db.upsert_source(source)
        log(job, f"Index failed: {exc}")
        if job:
            db.update_job(job, JobStatus.FAILED, str(exc))
        raise


def start_index_job(source_id: str) -> JobRecord:
    running_job = db.find_running_job_for_source(source_id)
    if running_job is not None:
        raise RuntimeError(f"Indexing is already running for this source as job {running_job.id}.")

    job = db.create_job(source_id)
    with active_jobs_lock:
        active_job_ids.add(job.id)
    thread = threading.Thread(target=_run_job, args=(source_id, job), daemon=True)
    thread.start()
    return job


def cancel_index_job(job_id: str) -> JobRecord | None:
    job = db.get_job(job_id)
    if job is None:
        return None
    if job.status == JobStatus.CANCELLED:
        mark_source_cancelled(job.source_id)
        return job
    with active_jobs_lock:
        is_active = job.id in active_job_ids
    if job.status == JobStatus.CANCELLING and not is_active:
        log(job, "Indexing cancelled")
        mark_source_cancelled(job.source_id)
        return db.update_job(job, JobStatus.CANCELLED, "Indexing cancelled.")
    if job.status == JobStatus.CANCELLING:
        return job
    if job.status != JobStatus.RUNNING:
        raise RuntimeError(f"Only running jobs can be cancelled. Job {job.id} is {job.status}.")
    if not is_active:
        log(job, "Indexing cancelled")
        mark_source_cancelled(job.source_id)
        return db.update_job(job, JobStatus.CANCELLED, "Indexing cancelled.")
    log(job, CANCELLATION_PENDING_MESSAGE)
    return db.update_job(job, JobStatus.CANCELLING, CANCELLATION_PENDING_MESSAGE)


def _run_job(source_id: str, job: JobRecord) -> None:
    try:
        index_source(source_id, job)
    except IndexCancelled:
        return
    except Exception:
        logger.exception("Index job %s failed for source %s", job.id, source_id)
        return
    finally:
        with active_jobs_lock:
            active_job_ids.discard(job.id)


def index_local_source_incrementally(source: SourceRecord, job: JobRecord | None) -> SourceRecord:
    paths, uri_paths = local_source_paths(source)
    db.clear_source_documents(source)
    indexed = source
    log(job, "Scanning local snapshot for supported docs")

    def on_scan(current: int, total: int, file_path: Path) -> None:
        update_job_progress(job, current, total, f"Scanning {file_path.name}")

    for document in iter_documents_from_paths(
        paths,
        uri_paths,
        on_scan=on_scan,
        should_cancel=lambda: ensure_job_not_cancelled(job),
    ):
        ensure_job_not_cancelled(job)
        indexed = db.add_source_document(source, document)
        if job:
            update_job_progress(job, job.progress_current, job.progress_total, document["uri"])
        log(
            job,
            f"Indexed file {indexed.document_count}: {document['uri']} "
            f"({indexed.chunk_count} chunks total)",
        )

    indexed = db.get_source(source.id) or indexed
    if indexed.document_count == 0:
        raise RuntimeError("No supported documentation files or pages were found.")
    indexed.status = SourceStatus.INDEXED
    indexed.error = None
    return db.upsert_source(indexed)


async def index_web_source_incrementally(source: SourceRecord, job: JobRecord | None) -> SourceRecord:
    db.clear_source_documents(source)
    indexed = source
    log(job, "Crawling website and indexing pages as they are discovered")

    async for document in iter_web_documents(
        source.location,
        max_depth=int(source.metadata.get("max_depth", 3)),
        max_pages=int(source.metadata.get("max_pages", 1000)),
        scope=str(source.metadata.get("scope", "hostname")),
        include_patterns=list(source.metadata.get("include_patterns", [])),
        exclude_patterns=list(source.metadata.get("exclude_patterns", [])),
        should_cancel=lambda: ensure_job_not_cancelled(job),
    ):
        ensure_job_not_cancelled(job)
        indexed = db.add_source_document(source, document)
        update_job_progress(
            job,
            indexed.document_count,
            None,
            document["uri"],
        )
        log(
            job,
            f"Indexed page {indexed.document_count}: {document['uri']} "
            f"({indexed.chunk_count} chunks total)",
        )

    indexed = db.get_source(source.id) or indexed
    if indexed.document_count == 0:
        raise RuntimeError("No supported documentation files or pages were found.")
    indexed.status = SourceStatus.INDEXED
    indexed.error = None
    return db.upsert_source(indexed)


def ensure_job_not_cancelled(job: JobRecord | None) -> None:
    if job is None:
        return
    current = db.get_job(job.id)
    if current and current.status in {JobStatus.CANCELLING, JobStatus.CANCELLED}:
        raise IndexCancelled("Indexing cancelled.")


def update_job_progress(job: JobRecord | None, current: int, total: int | None, label: str) -> None:
    if job is None:
        return
    db.update_job(
        job,
        progress_current=current,
        progress_total=total,
        progress_label=label,
    )


def mark_source_cancelled(source_id: str) -> None:
    source = db.get_source(source_id)
    if source is None:
        return
    source.status = SourceStatus.REGISTERED
    source.error = "Indexing cancelled."
    db.upsert_source(source)


def log(job: JobRecord | None, message: str) -> None:
    if job is None:
        return
    settings = get_settings()
    log_path = settings.job_log_dir / f"{job.id}.log"
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(f"{message}\n")
    db.update_job(job, message=message)


def read_job_log(job_id: str) -> str:
    path = get_settings().job_log_dir / f"{job_id}.log"
    return path.read_text(encoding="utf-8") if path.exists() else ""


def require_unique_source_name(name: str) -> str:
    normalized = name.strip()
    if not normalized:
        raise ValueError("Source name is required.")
    if db.find_source_by_name(normalized):
        raise ValueError(f'A source named "{normalized}" already exists.')
    return normalized


def clean_patterns(patterns: list[str]) -> list[str]:
    return [pattern.strip() for pattern in patterns if pattern.strip()]


def internal_version() -> str:
    return datetime.now(UTC).strftime("ingest-%Y%m%d-%H%M%S")

