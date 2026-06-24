from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import hashlib
import math
import re

import httpx

from app.config import get_settings
from app.models import EmbeddingIndexingStrategy

VECTOR_DIMENSIONS = 256
DEFAULT_EMBEDDING_BATCH_SIZE = 32
MIN_EMBEDDING_BATCH_SIZE = 1
MAX_EMBEDDING_BATCH_SIZE = 256
TOKEN_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9_./:-]{1,80}")
EMBEDDING_PROVIDER_KEY = "embedding_provider"
EMBEDDING_MODEL_KEY = "embedding_model"
EMBEDDING_INDEXING_STRATEGY_KEY = "embedding_indexing_strategy"
EMBEDDING_BATCH_SIZE_KEY = "embedding_batch_size"
LOCAL_HASHING_PROVIDER = "local-hashing"
LOCAL_HASHING_MODEL = "local-hashing-256"
OLLAMA_PROVIDER = "ollama"


class EmbeddingError(RuntimeError):
    pass


@dataclass(frozen=True)
class EmbeddingConfig:
    provider: str
    model: str
    base_url: str

    @property
    def display_name(self) -> str:
        if self.provider == OLLAMA_PROVIDER:
            return f"ollama:{self.model}"
        return self.model


def embedding_signature(config: EmbeddingConfig | None = None) -> dict[str, str]:
    current = config or get_embedding_config()
    return {
        "provider": current.provider,
        "model": current.model,
        "display_name": current.display_name,
    }


@dataclass(frozen=True)
class EmbeddingIndexingConfig:
    strategy: EmbeddingIndexingStrategy
    batch_size: int

    @property
    def effective_batch_size(self) -> int:
        if self.strategy == EmbeddingIndexingStrategy.SINGLE:
            return 1
        return self.batch_size


def tokenize(text: str) -> list[str]:
    return [token.lower() for token in TOKEN_RE.findall(text)]


@lru_cache(maxsize=1)
def get_embedding_config() -> EmbeddingConfig:
    from app.database import db

    settings = get_settings()
    provider = db.get_app_setting(EMBEDDING_PROVIDER_KEY) or LOCAL_HASHING_PROVIDER
    model = db.get_app_setting(EMBEDDING_MODEL_KEY) or LOCAL_HASHING_MODEL
    if provider != OLLAMA_PROVIDER:
        provider = LOCAL_HASHING_PROVIDER
        model = LOCAL_HASHING_MODEL
    return EmbeddingConfig(
        provider=provider,
        model=model,
        base_url=settings.ollama_base_url.rstrip("/"),
    )


def clear_embedding_config_cache() -> None:
    get_embedding_config.cache_clear()


def reset_embedding_config() -> EmbeddingConfig:
    from app.database import db

    db.delete_app_settings([EMBEDDING_PROVIDER_KEY, EMBEDDING_MODEL_KEY])
    clear_embedding_config_cache()
    return get_embedding_config()


@lru_cache(maxsize=1)
def get_embedding_indexing_config() -> EmbeddingIndexingConfig:
    from app.database import db

    strategy_value = db.get_app_setting(EMBEDDING_INDEXING_STRATEGY_KEY) or EmbeddingIndexingStrategy.BATCH
    try:
        strategy = EmbeddingIndexingStrategy(strategy_value)
    except ValueError:
        strategy = EmbeddingIndexingStrategy.BATCH

    batch_size = coerce_batch_size(db.get_app_setting(EMBEDDING_BATCH_SIZE_KEY))
    return EmbeddingIndexingConfig(strategy=strategy, batch_size=batch_size)


def clear_embedding_indexing_config_cache() -> None:
    get_embedding_indexing_config.cache_clear()


def set_embedding_indexing_config(strategy: EmbeddingIndexingStrategy, batch_size: int) -> EmbeddingIndexingConfig:
    from app.database import db

    coerced_batch_size = coerce_batch_size(batch_size)
    db.set_app_setting(EMBEDDING_INDEXING_STRATEGY_KEY, strategy.value)
    db.set_app_setting(EMBEDDING_BATCH_SIZE_KEY, str(coerced_batch_size))
    clear_embedding_indexing_config_cache()
    return EmbeddingIndexingConfig(strategy=strategy, batch_size=coerced_batch_size)


def reset_embedding_indexing_config() -> EmbeddingIndexingConfig:
    from app.database import db

    db.delete_app_settings([EMBEDDING_INDEXING_STRATEGY_KEY, EMBEDDING_BATCH_SIZE_KEY])
    clear_embedding_indexing_config_cache()
    return get_embedding_indexing_config()


def coerce_batch_size(value: object) -> int:
    try:
        parsed = int(str(value))
    except (TypeError, ValueError):
        return DEFAULT_EMBEDDING_BATCH_SIZE
    return min(MAX_EMBEDDING_BATCH_SIZE, max(MIN_EMBEDDING_BATCH_SIZE, parsed))


def list_ollama_models() -> list[str]:
    settings = get_settings()
    try:
        response = httpx.get(
            f"{settings.ollama_base_url.rstrip('/')}/api/tags",
            timeout=settings.ollama_timeout_seconds,
        )
        response.raise_for_status()
    except httpx.HTTPError as error:
        raise EmbeddingError(
            f"Ollama is not installed or not running at {settings.ollama_base_url}. "
            "Install and start Ollama only if you want optional stronger semantic embeddings."
        ) from error

    payload = response.json()
    models = payload.get("models", [])
    names = [model.get("name", "") for model in models if isinstance(model, dict)]
    return sorted((name for name in names if name), key=ollama_model_sort_key)


def ollama_model_sort_key(name: str) -> tuple[int, str]:
    lowered = name.lower()
    is_likely_embedding = "embed" in lowered or "minilm" in lowered
    return (0 if is_likely_embedding else 1, lowered)


def require_ollama_model(model: str) -> None:
    available_models = list_ollama_models()
    if model not in available_models:
        raise EmbeddingError(f"Ollama model is not installed locally: {model}")


def embed_text(text: str) -> list[float]:
    config = get_embedding_config()
    if config.provider == OLLAMA_PROVIDER:
        return embed_text_with_ollama(text, config)
    return embed_text_with_local_hashing(text)


def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    config = get_embedding_config()
    if config.provider == OLLAMA_PROVIDER:
        return embed_texts_with_ollama(texts, config)
    return [embed_text_with_local_hashing(text) for text in texts]


def embed_text_with_local_hashing(text: str) -> list[float]:
    vector = [0.0] * VECTOR_DIMENSIONS
    for token in tokenize(text):
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        value = int.from_bytes(digest, "big")
        index = value % VECTOR_DIMENSIONS
        sign = 1.0 if (value >> 8) & 1 else -1.0
        vector[index] += sign

    magnitude = math.sqrt(sum(value * value for value in vector))
    if not magnitude:
        return vector
    return [round(value / magnitude, 6) for value in vector]


def embed_text_with_ollama(text: str, config: EmbeddingConfig) -> list[float]:
    settings = get_settings()
    try:
        response = httpx.post(
            f"{config.base_url}/api/embed",
            json={"model": config.model, "input": text},
            timeout=settings.ollama_timeout_seconds,
        )
        response.raise_for_status()
    except httpx.HTTPError as error:
        raise EmbeddingError(f"Ollama embedding failed for model: {config.model}") from error

    payload = response.json()
    embeddings = payload.get("embeddings")
    if not isinstance(embeddings, list) or not embeddings:
        raise EmbeddingError("Ollama did not return an embedding vector")

    vector = embeddings[0]
    if not isinstance(vector, list) or not all(isinstance(value, (int, float)) for value in vector):
        raise EmbeddingError("Ollama returned an invalid embedding vector")

    return normalize_vector([float(value) for value in vector])


def embed_texts_with_ollama(texts: list[str], config: EmbeddingConfig) -> list[list[float]]:
    if not texts:
        return []
    settings = get_settings()
    try:
        response = httpx.post(
            f"{config.base_url}/api/embed",
            json={"model": config.model, "input": texts},
            timeout=settings.ollama_timeout_seconds,
        )
        response.raise_for_status()
    except httpx.HTTPError as error:
        raise EmbeddingError(f"Ollama embedding failed for model: {config.model}") from error

    payload = response.json()
    embeddings = payload.get("embeddings")
    if not isinstance(embeddings, list) or not embeddings:
        raise EmbeddingError("Ollama did not return an embedding vector")
    if len(embeddings) != len(texts):
        raise EmbeddingError("Ollama returned an unexpected number of embeddings")

    normalized_embeddings: list[list[float]] = []
    for vector in embeddings:
        if not isinstance(vector, list) or not all(isinstance(value, (int, float)) for value in vector):
            raise EmbeddingError("Ollama returned an invalid embedding vector")
        normalized_embeddings.append(normalize_vector([float(value) for value in vector]))

    return normalized_embeddings


def normalize_vector(vector: list[float]) -> list[float]:
    magnitude = math.sqrt(sum(value * value for value in vector))
    if not magnitude:
        return vector
    return [round(value / magnitude, 6) for value in vector]


def cosine(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    return sum(a * b for a, b in zip(left, right, strict=False))
