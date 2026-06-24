from __future__ import annotations

import hashlib
import re

from app.content import compact_text
from app.embedding import get_embedding_indexing_config, tokenize
from app.embedding_pipeline import embed_chunks

CHUNK_TARGET_CHARS = 3600
CHUNK_OVERLAP_CHARS = 400


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
            chunk = {
                "ordinal": ordinal,
                "title": chunk_title,
                "uri": uri,
                "content": piece.strip(),
                "section_path": section_path,
                "token_count": len(tokenize(piece)),
                "embedding_text": f"{chunk_title}\n{piece}",
            }
            chunks.append(chunk)
            ordinal += 1
    if embed:
        embed_chunks(chunks, get_embedding_indexing_config().effective_batch_size)
    return chunks


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
