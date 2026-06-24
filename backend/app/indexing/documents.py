from __future__ import annotations

from app.indexing.chunking import (
    CHUNK_OVERLAP_CHARS,
    CHUNK_TARGET_CHARS,
    build_chunks,
    build_document,
    split_large_text,
    split_markdown_sections,
)
from app.indexing.content import (
    clean_web_markdown,
    compact_text,
    expand_markdown_includes,
    expand_mdx_examples,
    extract_main_markdown,
    find_example_file,
    has_obvious_web_chrome,
    html_to_markdown,
    infer_title,
    infer_web_title,
    is_within_or_near_root,
    normalize_content,
    normalize_web_content,
    parse_highlight_lines,
    select_highlighted_lines,
    strip_front_matter,
)
from app.indexing.discovery import (
    SKIP_DIRS,
    SUPPORTED_SUFFIXES,
    document_from_file,
    document_uri,
    documents_from_paths,
    iter_documents_from_paths,
    iter_files,
)
from app.indexing.embedding_pipeline import embed_chunks, embed_pending_documents


def document_from_web_page(url: str, content: str, title: str | None = None) -> dict | None:
    normalized = normalize_web_content(content, url=url)
    if not normalized.strip():
        return None
    inferred_title = title or infer_web_title(url)
    return build_document(url, inferred_title, normalized)

