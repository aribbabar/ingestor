from __future__ import annotations

from app.retrieval.embeddings import embed_texts


def embed_pending_documents(documents: list[dict], chunks: list[dict], batch_size: int):
    embed_chunks(chunks, batch_size)
    yield from documents


def embed_chunks(chunks: list[dict], batch_size: int) -> None:
    effective_batch_size = max(1, batch_size)
    for start in range(0, len(chunks), effective_batch_size):
        batch = chunks[start : start + effective_batch_size]
        texts = [str(chunk.pop("embedding_text")) for chunk in batch]
        embeddings = embed_texts(texts)
        if len(embeddings) != len(batch):
            raise RuntimeError("Embedding provider returned an unexpected number of vectors")
        for chunk, embedding in zip(batch, embeddings, strict=True):
            chunk["embedding"] = embedding

