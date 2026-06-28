from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from urllib.parse import urlparse

from app.indexing.content import compact_text
from app.retrieval.embeddings import get_embedding_indexing_config, tokenize
from app.indexing.embedding_pipeline import embed_chunks

CHUNK_TARGET_CHARS = 1400
CHUNK_OVERLAP_CHARS = 200
CHUNK_MIN_CHARS = 450
CHUNK_MAX_CHARS = 2200
PARENT_CONTEXT_MAX_CHARS = 4800
CODE_BLOCK_RE = re.compile(r"```[\s\S]*?```")
FENCE_START_RE = re.compile(r"^\s*```")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$")
LIST_ITEM_RE = re.compile(r"^\s{0,3}(?:[-*+]|\d+[.)])\s+")
TABLE_SEPARATOR_RE = re.compile(r"\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?")


@dataclass(frozen=True)
class ContentBlock:
    kind: str
    text: str


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
        for piece in split_section_content(section_content):
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
                    parent_content=section_content,
                ),
                "embedding_text": f"{chunk_title}\n{piece}",
            }
            chunks.append(chunk)
            ordinal += 1
    chunks = merge_tiny_text_chunks(chunks, document_title=title)
    if embed:
        embed_chunks(chunks, get_embedding_indexing_config().effective_batch_size)
    return chunks


def merge_tiny_text_chunks(chunks: list[dict], *, document_title: str) -> list[dict]:
    merged: list[dict] = []
    for chunk in chunks:
        if merged and should_merge_tiny_chunk(merged[-1], chunk):
            merged[-1] = merge_chunk_pair(merged[-1], chunk, document_title=document_title)
            continue
        merged.append(chunk)
    for ordinal, chunk in enumerate(merged):
        chunk["ordinal"] = ordinal
    return merged


def should_merge_tiny_chunk(left: dict, right: dict) -> bool:
    left_path = list(left.get("section_path") or [])
    right_path = list(right.get("section_path") or [])
    if not left_path or not right_path:
        return False
    if left_path[:-1] != right_path[:-1]:
        return False
    if starts_major_heading(str(right.get("content") or "")):
        return False
    if left.get("uri") != right.get("uri"):
        return False
    if left.get("content_type") != right.get("content_type"):
        return False
    if left.get("parent_chunk_id") is not None or right.get("parent_chunk_id") is not None:
        return False
    if safe_chunk_kind(left) != "text" or safe_chunk_kind(right) != "text":
        return False
    left_content = str(left.get("content") or "").strip()
    right_content = str(right.get("content") or "").strip()
    combined = f"{left_content}\n\n{right_content}".strip()
    if len(combined) > CHUNK_TARGET_CHARS:
        return False
    return len(left_content) < CHUNK_MIN_CHARS or len(right_content) < CHUNK_MIN_CHARS


def merge_chunk_pair(left: dict, right: dict, *, document_title: str) -> dict:
    section_path = list(left.get("section_path") or [])[:-1]
    content = f"{str(left.get('content') or '').strip()}\n\n{str(right.get('content') or '').strip()}".strip()
    title = " > ".join(section_path) or document_title
    content_type = str(left.get("content_type") or infer_content_type(str(left.get("uri") or "")))
    merged = {
        **left,
        "title": title,
        "content": content,
        "content_type": content_type,
        "section_path": section_path,
        "token_count": len(tokenize(content)),
        "metadata": chunk_metadata(
            uri=str(left["uri"]),
            title=document_title,
            section_path=section_path,
            content_type=content_type,
            content=content,
            parent_content=content,
        ),
        "embedding_text": f"{title}\n{content}",
    }
    return merged


def safe_chunk_kind(chunk: dict) -> str:
    metadata = chunk.get("metadata")
    if isinstance(metadata, dict):
        kind = metadata.get("chunk_kind")
        if isinstance(kind, str):
            return kind
    return infer_chunk_kind(str(chunk.get("content") or ""))


def chunk_metadata(
    *,
    uri: str,
    title: str,
    section_path: list[str],
    content_type: str,
    content: str,
    parent_content: str | None = None,
) -> dict[str, object]:
    parent_text = parent_content or content
    return {
        "document_uri": uri,
        "document_title": title,
        "section_path": section_path,
        "content_type": content_type,
        "chunk_kind": infer_chunk_kind(content),
        "parent_key": parent_key(uri, section_path, parent_text),
        "parent_section_path": section_path,
        "parent_context": bounded_parent_context(parent_text, content),
    }


def parent_key(uri: str, section_path: list[str], content: str) -> str:
    key_source = "\n".join([uri, *section_path, content])
    return hashlib.sha1(key_source.encode("utf-8")).hexdigest()[:16]


def bounded_parent_context(parent_content: str, child_content: str) -> str:
    parent = parent_content.strip()
    if len(parent) <= PARENT_CONTEXT_MAX_CHARS:
        return parent

    child = child_content.strip()
    index = parent.find(child[: min(len(child), 200)]) if child else -1
    if index < 0:
        return trim_at_boundary(parent[:PARENT_CONTEXT_MAX_CHARS])

    half_window = PARENT_CONTEXT_MAX_CHARS // 2
    start = max(0, index - half_window)
    end = min(len(parent), start + PARENT_CONTEXT_MAX_CHARS)
    start = max(0, end - PARENT_CONTEXT_MAX_CHARS)
    context = parent[start:end]
    if start > 0:
        boundary = max(context.find("\n\n"), context.find(". "))
        if 0 <= boundary < len(context) // 3:
            context = context[boundary + 1 :].lstrip()
    if end < len(parent):
        context = trim_at_boundary(context)
    return context.strip()


def trim_at_boundary(text: str) -> str:
    cutoff = max(text.rfind("\n\n"), text.rfind(". "))
    if cutoff < len(text) // 2:
        return text.rstrip()
    return text[:cutoff].rstrip(" .") + "."


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
        if TABLE_SEPARATOR_RE.fullmatch(separator):
            return True
    return False


def split_markdown_sections(content: str) -> list[tuple[list[str], str]]:
    sections: list[tuple[list[str], list[str]]] = [([], [])]
    current_path: list[str] = []
    in_fence = False
    for line in content.splitlines():
        if FENCE_START_RE.match(line):
            in_fence = not in_fence
        match = HEADING_RE.match(line) if not in_fence else None
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


def split_section_content(text: str) -> list[str]:
    pieces: list[str] = []
    for block in split_content_blocks(text):
        if block.kind in {"code", "table"}:
            pieces.extend(split_oversized_structured_block(block.text))
        elif block.kind == "list":
            pieces.extend(recursive_split_text(block.text, CHUNK_TARGET_CHARS, CHUNK_OVERLAP_CHARS))
        else:
            pieces.extend(recursive_split_text(block.text, CHUNK_TARGET_CHARS, CHUNK_OVERLAP_CHARS))
    return greedy_merge_chunks([piece for piece in pieces if piece.strip()])


def split_content_blocks(text: str) -> list[ContentBlock]:
    blocks: list[ContentBlock] = []
    pending: list[str] = []
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        if FENCE_START_RE.match(line):
            flush_text_block(blocks, pending)
            code_lines = [line]
            index += 1
            while index < len(lines):
                code_lines.append(lines[index])
                if FENCE_START_RE.match(lines[index]):
                    index += 1
                    break
                index += 1
            blocks.append(ContentBlock("code", "\n".join(code_lines).strip()))
            continue
        if is_table_start(lines, index):
            flush_text_block(blocks, pending)
            table_lines = collect_table(lines, index)
            blocks.append(ContentBlock("table", "\n".join(table_lines).strip()))
            index += len(table_lines)
            continue
        if LIST_ITEM_RE.match(line):
            flush_text_block(blocks, pending)
            list_lines = collect_list(lines, index)
            blocks.append(ContentBlock("list", "\n".join(list_lines).strip()))
            index += len(list_lines)
            continue
        pending.append(line)
        index += 1
    flush_text_block(blocks, pending)
    return blocks


def flush_text_block(blocks: list[ContentBlock], pending: list[str]) -> None:
    text = "\n".join(pending).strip()
    if text:
        blocks.append(ContentBlock("text", text))
    pending.clear()


def is_table_start(lines: list[str], index: int) -> bool:
    if index + 1 >= len(lines):
        return False
    return "|" in lines[index] and TABLE_SEPARATOR_RE.fullmatch(lines[index + 1].strip()) is not None


def collect_table(lines: list[str], start: int) -> list[str]:
    table_lines: list[str] = []
    index = start
    while index < len(lines):
        line = lines[index]
        if not line.strip() or "|" not in line:
            break
        table_lines.append(line)
        index += 1
    return table_lines


def collect_list(lines: list[str], start: int) -> list[str]:
    list_lines: list[str] = []
    index = start
    while index < len(lines):
        line = lines[index]
        if not line.strip():
            list_lines.append(line)
            index += 1
            continue
        if LIST_ITEM_RE.match(line) or line.startswith(("  ", "\t")):
            list_lines.append(line)
            index += 1
            continue
        break
    return list_lines


def split_oversized_structured_block(text: str) -> list[str]:
    if len(text) <= CHUNK_MAX_CHARS:
        return [text]
    return recursive_split_text(text, CHUNK_MAX_CHARS, CHUNK_OVERLAP_CHARS)


def split_large_text(text: str) -> list[str]:
    return recursive_split_text(text, CHUNK_TARGET_CHARS, CHUNK_OVERLAP_CHARS)


def recursive_split_text(text: str, target_chars: int, overlap_chars: int) -> list[str]:
    text = text.strip()
    if len(text) <= target_chars:
        return [text] if text else []
    separators = ["\n\n", "\n", ". ", " "]
    return split_by_separators(text, target_chars, overlap_chars, separators)


def split_by_separators(text: str, target_chars: int, overlap_chars: int, separators: list[str]) -> list[str]:
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + target_chars, len(text))
        if end < len(text):
            boundary = best_split_boundary(text, start, end, separators)
            if boundary > start + target_chars // 2:
                end = boundary
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = max(0, end - overlap_chars)
    return chunks


def best_split_boundary(text: str, start: int, end: int, separators: list[str]) -> int:
    for separator in separators:
        boundary = text.rfind(separator, start, end)
        if boundary > start:
            return boundary + len(separator)
    return end


def greedy_merge_chunks(pieces: list[str]) -> list[str]:
    merged: list[str] = []
    current = ""
    for piece in pieces:
        text = piece.strip()
        if not text:
            continue
        if not current:
            current = text
            continue
        combined = f"{current}\n\n{text}"
        if should_merge(current, text, combined):
            current = combined
            continue
        merged.append(current)
        current = text
    if current:
        merged.append(current)
    return merged


def should_merge(current: str, next_piece: str, combined: str) -> bool:
    if len(combined) > CHUNK_MAX_CHARS:
        return False
    if starts_major_heading(next_piece) and len(current) >= CHUNK_MIN_CHARS:
        return False
    if len(current) < CHUNK_MIN_CHARS:
        return True
    return len(combined) <= CHUNK_TARGET_CHARS and compatible_chunk_kinds(current, next_piece)


def starts_major_heading(text: str) -> bool:
    first_line = text.lstrip().splitlines()[0] if text.strip() else ""
    match = HEADING_RE.match(first_line)
    return bool(match and len(match.group(1)) <= 2)


def compatible_chunk_kinds(left: str, right: str) -> bool:
    left_kind = infer_chunk_kind(left)
    right_kind = infer_chunk_kind(right)
    if "table" in {left_kind, right_kind}:
        return False
    if "code" in {left_kind, right_kind} and "mixed" not in {left_kind, right_kind}:
        return False
    return True

