from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.core.config import get_settings
from app.db import db
from app.retrieval.embeddings import (
    EMBEDDING_MODEL_KEY,
    EMBEDDING_PROVIDER_KEY,
    OLLAMA_PROVIDER,
    DEFAULT_EMBEDDING_BATCH_SIZE,
    EmbeddingError,
    clear_embedding_config_cache,
    get_embedding_config,
    get_embedding_indexing_config,
    list_ollama_models,
    require_ollama_model,
    reset_embedding_config,
    reset_embedding_indexing_config,
    set_embedding_indexing_config,
)
from app.api.folders import router as folders_router
from app.api.skills import router as skills_router
from app.domain.models import (
    EmbeddingSettingsUpdate,
    EmbeddingIndexingSettingsUpdate,
    LocalSourceRequest,
    RetrievalSettingsUpdate,
    SearchRequest,
    SearchResponse,
    SourceDeletionResponse,
    SourceRegistrationResponse,
    WebSourceRequest,
)
from app.retrieval.search import SourceNotQueryableError, current_embedding_display, search_chunks, stale_indexed_source_count
from app.retrieval.settings import get_default_search_mode, reset_default_search_mode, set_default_search_mode
from app.sources.service import delete_source as delete_registered_source
from app.sources.service import read_job_log, register_local_source, register_web_source, start_index_job

router = APIRouter(prefix="/api")
router.include_router(folders_router)
router.include_router(skills_router)


@router.get("/health")
def health() -> dict:
    settings = get_settings()
    embedding_config = get_embedding_config()
    return {
        "ok": True,
        "database": str(settings.database_path),
        "embedding": embedding_config.display_name,
    }


@router.get("/settings")
def settings() -> dict:
    current = get_settings()
    embedding_config = get_embedding_config()
    indexing_config = get_embedding_indexing_config()
    default_search_mode = get_default_search_mode()
    return {
        "data_dir": str(current.resolved_data_dir),
        "database": str(current.database_path),
        "local_source_dir": str(current.local_source_dir),
        "default_search_mode": default_search_mode.value,
        "embedding": {
            "provider": embedding_config.provider,
            "model": embedding_config.model,
            "display_name": embedding_config.display_name,
            "ollama_base_url": current.ollama_base_url,
            "indexing": {
                "strategy": indexing_config.strategy.value,
                "batch_size": indexing_config.batch_size,
                "effective_batch_size": indexing_config.effective_batch_size,
                "default_strategy": "batch",
                "default_batch_size": DEFAULT_EMBEDDING_BATCH_SIZE,
            },
        },
        "retrieval": {
            "keyword": "sqlite-fts5",
            "embedding": embedding_config.display_name,
            "hybrid": "reciprocal rank fusion",
        },
        "source_compatibility": {
            "current_embedding": current_embedding_display(),
            "stale_indexed_source_count": stale_indexed_source_count(),
        },
    }


@router.get("/ollama/models")
def ollama_models() -> dict:
    current = get_settings()
    selected = get_embedding_config()
    try:
        models = list_ollama_models()
    except EmbeddingError as error:
        return {
            "base_url": current.ollama_base_url,
            "models": [],
            "selected_model": selected.model if selected.provider == OLLAMA_PROVIDER else None,
            "reachable": False,
            "error": str(error),
        }

    return {
        "base_url": current.ollama_base_url,
        "models": models,
        "selected_model": selected.model if selected.provider == OLLAMA_PROVIDER else None,
        "reachable": True,
        "error": None,
    }


@router.put("/settings/embedding")
def update_embedding_settings(request: EmbeddingSettingsUpdate) -> dict:
    model = request.model.strip()
    try:
        require_ollama_model(model)
    except EmbeddingError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error

    db.set_app_setting(EMBEDDING_PROVIDER_KEY, OLLAMA_PROVIDER)
    db.set_app_setting(EMBEDDING_MODEL_KEY, model)
    clear_embedding_config_cache()
    return settings()


@router.put("/settings/embedding/indexing")
def update_embedding_indexing_settings(request: EmbeddingIndexingSettingsUpdate) -> dict:
    set_embedding_indexing_config(request.strategy, request.batch_size)
    return settings()


@router.post("/settings/embedding/indexing/reset")
def reset_embedding_indexing_settings() -> dict:
    reset_embedding_indexing_config()
    return settings()


@router.post("/settings/reset")
def reset_all_settings() -> dict:
    reset_embedding_config()
    reset_embedding_indexing_config()
    reset_default_search_mode()
    return settings()


@router.put("/settings/retrieval")
def update_retrieval_settings(request: RetrievalSettingsUpdate) -> dict:
    set_default_search_mode(request.mode)
    return settings()


@router.get("/sources")
def list_sources() -> dict:
    return {"sources": db.list_sources(), "jobs": db.list_jobs()}


@router.post("/sources/local-folder", response_model=SourceRegistrationResponse)
def create_local_source(request: LocalSourceRequest) -> SourceRegistrationResponse:
    try:
        source = register_local_source(request)
    except (FileNotFoundError, ValueError) as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error
    return SourceRegistrationResponse(
        source=source,
        command_preview=["ingestor", "index-local", source.location, "--name", source.name],
    )


@router.post("/sources/web", response_model=SourceRegistrationResponse)
def create_web_source(request: WebSourceRequest) -> SourceRegistrationResponse:
    try:
        source = register_web_source(request)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error
    return SourceRegistrationResponse(
        source=source,
        command_preview=["ingestor", "index-web", source.location, "--name", source.name],
    )


@router.post("/sources/{source_id}/index")
def index_source_route(source_id: str) -> dict:
    if db.get_source(source_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source not found")
    try:
        return {"job": start_index_job(source_id)}
    except RuntimeError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error


@router.get("/sources/jobs")
def list_jobs() -> dict:
    return {"jobs": db.list_jobs()}


@router.get("/sources/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    job = db.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return {"job": job, "logs": read_job_log(job_id)}


@router.post("/sources/search", response_model=SearchResponse)
def search(request: SearchRequest) -> SearchResponse:
    mode = request.mode or get_default_search_mode()
    try:
        results = search_chunks(
            query=request.query,
            source_id=request.source_id,
            source_name=request.source,
            limit=request.limit,
            mode=mode,
        )
    except SourceNotQueryableError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    source_arg = request.source or request.source_id or "all"
    return SearchResponse(
        command=["ingestor", "search", source_arg, request.query, "--mode", mode.value, "--output", "json"],
        results=results,
        stdout="",
        stderr="",
    )


@router.delete("/sources/{source_id}", response_model=SourceDeletionResponse)
def delete_source(source_id: str) -> SourceDeletionResponse:
    deleted = delete_registered_source(source_id)
    if deleted is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source not found")
    return SourceDeletionResponse(deleted_source=deleted)


@router.post("/sources/{source_id}/delete", response_model=SourceDeletionResponse)
def delete_source_action(source_id: str) -> SourceDeletionResponse:
    return delete_source(source_id)

