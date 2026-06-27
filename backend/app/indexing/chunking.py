from __future__ import annotations

import hashlib
import re
from pathlib import PurePosixPath
from urllib.parse import urlparse

from app.indexing.content import compact_text
from app.retrieval.embeddings import get_embedding_indexing_config, tokenize
from app.indexing.embedding_pipeline import embed_chunks

CHUNK_TARGET_CHARS = 3600
CHUNK_OVERLAP_CHARS = 400
CODE_BLOCK_RE = re.compile(r"```[\s\S]*?```")


def build_document(uri: str, title: str, content: str, embed: bool = True) -> dict:
    clean = compact_text(content)
    chunks = build_chunks(uri, title, clean, embed=embed)
    return {
        "uri": uri,
        "title": title,
        "content": clean,
        "content_hash": hashlib.sha256(clean.encode("utf-8")).hexdigest(),
        "chunks": chunks,
    }


def build_chunks(uri: str, title: str, content: str, embed: bool = True) -> list[dict]:
    sections = split_markdown_sections(content)
    chunks: list[dict] = []
    ordinal = 0
    for section_path, section_content in sections:
        for piece in split_large_text(section_content):
            if not piece.strip():
                continue
            chunk_title = " > ".join(section_path) or title
            content_type = infer_content_type(uri)
            chunk = {
                "ordinal": ordinal,
                "title": chunk_title,
                "uri": uri,
                "content": piece.strip(),
                "content_type": content_type,
                "parent_chunk_id": None,
                "section_path": section_path,
                "token_count": len(tokenize(piece)),
                "metadata": chunk_metadata(
                    uri=uri,
                    title=title,
                    section_path=section_path,
                    content_type=content_type,
                    content=piece,
                ),
                "embedding_text": f"{chunk_title}\n{piece}",
            }
            chunks.append(chunk)
            ordinal += 1
    if embed:
        embed_chunks(chunks, get_embedding_indexing_config().effective_batch_size)
    return chunks


def chunk_metadata(
    *,
    uri: str,
    title: str,
    section_path: list[str],
    content_type: str,
    content: str,
) -> dict[str, object]:
    return {
        "document_uri": uri,
        "document_title": title,
        "section_path": section_path,
        "content_type": content_type,
        "chunk_kind": infer_chunk_kind(content),
    }


def infer_content_type(uri: str) -> str:
    parsed = urlparse(uri)
    suffix = PurePosixPath(parsed.path or uri).suffix.lower()
    if suffix in {".md", ".mdx"}:
        return "markdown"
    if suffix in {".html", ".htm"}:
        return "html"
    if suffix == ".json":
        return "json"
    if suffix in {".yaml", ".yml"}:
        return "yaml"
    if suffix == ".toml":
        return "toml"
    if suffix == ".rst":
        return "rst"
    if suffix == ".txt":
        return "text"
    if parsed.scheme in {"http", "https"}:
        return "web"
    return "text"


def infer_chunk_kind(content: str) -> str:
    has_code = bool(CODE_BLOCK_RE.search(content))
    has_table = has_markdown_table(content)
    if has_table:
        return "table"
    if has_code:
        plain = CODE_BLOCK_RE.sub("", content).strip()
        return "mixed" if len(tokenize(plain)) >= 5 else "code"
    return "text"


def has_markdown_table(content: str) -> bool:
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    for index, line in enumerate(lines[:-1]):
        if "|" not in line:
            continue
        separator = lines[index + 1]
        if re.fullmatch(r"\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?", separator):
            return True
    return False


def split_markdown_sections(content: str) -> list[tuple[list[str], str]]:
    sections: list[tuple[list[str], list[str]]] = [([], [])]
    current_path: list[str] = []
    for line in content.splitlines():
        match = re.match(r"^(#{1,3})\s+(.+)$", line)
        if match and sections[-1][1]:
            level = len(match.group(1))
            current_path = current_path[: level - 1]
            current_path.append(match.group(2).strip())
            sections.append((current_path.copy(), [line]))
        else:
            sections[-1][1].append(line)
            if match:
                level = len(match.group(1))
                current_path = current_path[: level - 1]
                current_path.append(match.group(2).strip())
                sections[-1] = (current_path.copy(), sections[-1][1])
    return [(title, "\n".join(lines).strip()) for title, lines in sections if "\n".join(lines).strip()]


def split_large_text(text: str) -> list[str]:
    if len(text) <= CHUNK_TARGET_CHARS:
        return [text]
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + CHUNK_TARGET_CHARS, len(text))
        if end < len(text):
            boundary = max(text.rfind("\n\n", start, end), text.rfind(". ", start, end))
            if boundary > start + CHUNK_TARGET_CHARS // 2:
                end = boundary + 1
        chunks.append(text[start:end])
        if end >= len(text):
            break
        start = max(0, end - CHUNK_OVERLAP_CHARS)
    return chunks

