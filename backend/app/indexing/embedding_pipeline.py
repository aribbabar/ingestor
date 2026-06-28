from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from app.retrieval.embeddings import OLLAMA_PROVIDER, embed_texts, embedding_signature, get_embedding_config

OLLAMA_INDEXING_WORKERS = 4


def embed_pending_documents(documents: list[dict], chunks: list[dict], batch_size: int):
    embed_chunks(chunks, batch_size)
    yield from documents


def embed_chunks(chunks: list[dict], batch_size: int) -> None:
    effective_batch_size = max(1, batch_size)
    signature = embedding_signature()
    chunk_batches = [chunks[start : start + effective_batch_size] for start in range(0, len(chunks), effective_batch_size)]
    text_batches = [[str(chunk.pop("embedding_text")) for chunk in batch] for batch in chunk_batches]
    embedding_batches = embed_text_batches(text_batches)
    for batch, embeddings in zip(chunk_batches, embedding_batches, strict=True):
        if len(embeddings) != len(batch):
            raise RuntimeError("Embedding provider returned an unexpected number of vectors")
        for chunk, embedding in zip(batch, embeddings, strict=True):
            chunk["embedding"] = embedding
            chunk["embedding_provider"] = signature["provider"]
            chunk["embedding_model"] = signature["model"]
            chunk["embedding_dimensions"] = len(embedding)


def embed_text_batches(text_batches: list[list[str]]) -> list[list[list[float]]]:
    if not text_batches:
        return []
    config = get_embedding_config()
    if config.provider != OLLAMA_PROVIDER or len(text_batches) == 1:
        return [embed_texts(texts) for texts in text_batches]

    worker_count = min(OLLAMA_INDEXING_WORKERS, len(text_batches))
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        return list(executor.map(embed_texts, text_batches))

