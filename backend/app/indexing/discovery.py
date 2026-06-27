from __future__ import annotations

from pathlib import Path

from app.indexing.chunking import build_document
from app.indexing.content import infer_title, normalize_content
from app.retrieval.embeddings import get_embedding_indexing_config
from app.indexing.embedding_pipeline import embed_pending_documents

SUPPORTED_SUFFIXES = {
    ".md",
    ".mdx",
    ".txt",
    ".rst",
    ".html",
    ".htm",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
}
SKIP_DIRS = {
    ".cache",
    ".codex",
    ".git",
    ".hg",
    ".idea",
    ".mypy_cache",
    ".next",
    ".nuxt",
    ".pytest_cache",
    ".ruff_cache",
    ".svn",
    ".tox",
    ".venv",
    ".vscode",
    "__pycache__",
    "build",
    "coverage",
    "dist",
    "node_modules",
    "out",
    "target",
    "venv",
}


def documents_from_paths(paths: list[Path], uri_paths: list[Path] | None = None) -> list[dict]:
    return list(iter_documents_from_paths(paths, uri_paths))


def iter_documents_from_paths(paths: list[Path], uri_paths: list[Path] | None = None):
    pending_documents: list[dict] = []
    pending_chunks: list[dict] = []
    indexing_config = get_embedding_indexing_config()
    batch_size = indexing_config.effective_batch_size

    for index, selected_path in enumerate(paths):
        path = selected_path.expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"Path does not exist: {path}")
        uri_path = uri_paths[index].expanduser().resolve() if uri_paths and index < len(uri_paths) else path
        candidates = [path] if path.is_file() else iter_files(path)
        for file_path in candidates:
            document = document_from_file(
                file_path,
                path if path.is_dir() else path.parent,
                uri_path=uri_path,
                uri_is_file=path.is_file(),
                embed=False,
            )
            if document:
                pending_documents.append(document)
                pending_chunks.extend(document["chunks"])
                if len(pending_chunks) >= batch_size:
                    yield from embed_pending_documents(pending_documents, pending_chunks, batch_size)
                    pending_documents = []
                    pending_chunks = []

    if pending_documents:
        yield from embed_pending_documents(pending_documents, pending_chunks, batch_size)


def iter_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES:
            files.append(path)
    return sorted(files)


def document_from_file(
    path: Path,
    root: Path,
    uri_path: Path | None = None,
    uri_is_file: bool = False,
    embed: bool = True,
) -> dict | None:
    if path.suffix.lower() not in SUPPORTED_SUFFIXES:
        return None
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    content = normalize_content(raw, path.suffix, path=path, root=root)
    if not content.strip():
        return None
    try:
        relative = path.relative_to(root)
    except ValueError:
        relative = path.name
    title = infer_title(content, Path(relative).stem)
    return build_document(document_uri(path, root, uri_path, uri_is_file), title, content, embed=embed)


def document_uri(path: Path, root: Path, uri_path: Path | None, uri_is_file: bool = False) -> str:
    if uri_path is None:
        return str(path)
    if uri_is_file:
        return str(uri_path)
    try:
        return str(uri_path / path.relative_to(root))
    except ValueError:
        return str(uri_path / path.name)

