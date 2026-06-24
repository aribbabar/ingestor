from __future__ import annotations

import hashlib
import html
import re
from pathlib import Path
from urllib.parse import urlparse

from app.embedding import embed_texts, get_embedding_indexing_config, tokenize

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
SKIP_DIRS = {".git", ".hg", ".svn", "node_modules", ".venv", "venv", "__pycache__", "dist", "build"}
CHUNK_TARGET_CHARS = 3600
CHUNK_OVERLAP_CHARS = 400
FRONT_MATTER_RE = re.compile(r"\A---\s*\n.*?\n---\s*(?:\n|$)", re.DOTALL)
FASTAPI_INCLUDE_RE = re.compile(r"\{\*\s+(?P<target>[^\s*]+)(?P<options>[^*]*)\*\}")
MDX_EXAMPLE_RE = re.compile(r"<(?P<tag>ExampleTabs|ExampleCode|ExamplePreview)\s+name=\"(?P<name>[^\"]+)\"\s*/>")
MARKDOWN_IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]+\)")
WEB_CHROME_EXACT_LINES = {
    "ask ai",
    "company",
    "community",
    "compliance",
    "copy neon init command",
    "copy page",
    "neon docs",
    "resources",
    "search...",
    "set up neon with ai",
    "thank you for your feedback!",
    "was this page helpful?",
    "yesno",
}
WEB_CHROME_PREFIXES = (
    "a databricks company",
    "all rights reserved",
    "full neon documentation index:",
    "search...",
)
WEB_CHROME_CONTAINS = (
    "ccpacompliant",
    "gdprcompliant",
    "iso 27001certified",
    "iso 27701certified",
    "read the changelog",
    "soc 2certified",
    "trust center",
)
CODE_LANGUAGE_BY_SUFFIX = {
    ".js": "js",
    ".jsx": "jsx",
    ".py": "py",
    ".ts": "ts",
    ".tsx": "tsx",
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


def document_from_web_page(url: str, content: str, title: str | None = None) -> dict | None:
    normalized = clean_web_markdown(normalize_content(content, ".md"))
    if not normalized.strip():
        return None
    inferred_title = title or infer_web_title(url)
    return build_document(url, inferred_title, normalized)


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


def normalize_content(raw: str, suffix: str, path: Path | None = None, root: Path | None = None) -> str:
    if suffix.lower() in {".html", ".htm"}:
        return html_to_text(raw)
    content = raw.replace("\r\n", "\n").replace("\r", "\n")
    if suffix.lower() in {".md", ".mdx"}:
        content = strip_front_matter(content)
        if path is not None:
            content = expand_markdown_includes(content, path, root or path.parent)
            content = expand_mdx_examples(content, path, root or path.parent)
    return content


def clean_web_markdown(content: str) -> str:
    lines: list[str] = []
    skip_on_this_page = False
    skip_footer = False
    for raw_line in content.splitlines():
        line = MARKDOWN_IMAGE_RE.sub("", raw_line).rstrip()
        normalized = normalize_chrome_line(line)
        if normalized == "### on this page" or normalized == "on this page":
            skip_on_this_page = True
            continue
        if skip_on_this_page:
            if line.startswith("#"):
                skip_on_this_page = False
            elif re.match(r"^\s*[-*]\s+\[", line):
                continue
        if normalized in {"neon docs", "company", "resources", "community", "compliance"}:
            skip_footer = True
            continue
        if skip_footer:
            if line.startswith("#"):
                skip_footer = False
            elif not line.strip() or re.match(r"^\s*[-*]\s+", line) or normalized in WEB_CHROME_EXACT_LINES:
                continue
        if is_web_chrome_line(line):
            continue
        lines.append(line)
    return compact_text("\n".join(lines))


def is_web_chrome_line(line: str) -> bool:
    normalized = normalize_chrome_line(line)
    if not normalized:
        return False
    if normalized in WEB_CHROME_EXACT_LINES:
        return True
    if normalized.startswith(WEB_CHROME_PREFIXES):
        return True
    if any(fragment in normalized for fragment in WEB_CHROME_CONTAINS):
        return True
    if re.fullmatch(r"\*\s+\[[^\]]+\]\(https://trust\.neon\.com[^)]*\)", line.strip(), re.IGNORECASE):
        return True
    return False


def normalize_chrome_line(line: str) -> str:
    text = MARKDOWN_IMAGE_RE.sub("", line)
    text = re.sub(r"\[[^\]]*\]\([^)]*\)", "", text)
    text = re.sub(r"\s+", " ", text).strip().lower()
    return text


def strip_front_matter(content: str) -> str:
    return FRONT_MATTER_RE.sub("", content, count=1).lstrip()


def expand_markdown_includes(content: str, path: Path, root: Path) -> str:
    def replace_include(match: re.Match[str]) -> str:
        target = (path.parent / match.group("target")).resolve()
        if not is_within_or_near_root(target, root) or not target.is_file():
            return match.group(0)
        try:
            raw = target.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return match.group(0)

        selected = select_highlighted_lines(raw, match.group("options"))
        language = CODE_LANGUAGE_BY_SUFFIX.get(target.suffix.lower(), target.suffix.lower().lstrip("."))
        return f"```{language}\n{selected.rstrip()}\n```"

    return FASTAPI_INCLUDE_RE.sub(replace_include, content)


def expand_mdx_examples(content: str, path: Path, root: Path) -> str:
    def replace_example(match: re.Match[str]) -> str:
        name = match.group("name")
        target = find_example_file(root, name)
        if target is None:
            return f"Example: {name}"
        try:
            raw = target.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return f"Example: {name}"
        language = CODE_LANGUAGE_BY_SUFFIX.get(target.suffix.lower(), target.suffix.lower().lstrip("."))
        return f"Example: {name}\n\n```{language}\n{raw.rstrip()}\n```"

    return MDX_EXAMPLE_RE.sub(replace_example, content)


def is_within_or_near_root(path: Path, root: Path) -> bool:
    resolved_root = root.resolve()
    return path == resolved_root or resolved_root in path.parents or resolved_root.parent in path.parents


def select_highlighted_lines(raw: str, options: str) -> str:
    line_numbers = parse_highlight_lines(options)
    if not line_numbers:
        return raw
    lines = raw.splitlines()
    selected = [lines[index - 1] for index in line_numbers if 1 <= index <= len(lines)]
    return "\n".join(selected) or raw


def parse_highlight_lines(options: str) -> list[int]:
    match = re.search(r"hl\[(?P<spec>[^\]]+)\]", options)
    if not match:
        return []
    line_numbers: list[int] = []
    for part in re.split(r"[,\s]+", match.group("spec").strip()):
        if not part:
            continue
        if ":" in part:
            start_raw, end_raw = part.split(":", 1)
            try:
                start = int(start_raw)
                end = int(end_raw)
            except ValueError:
                continue
            line_numbers.extend(range(start, end + 1))
            continue
        try:
            line_numbers.append(int(part))
        except ValueError:
            continue
    return list(dict.fromkeys(line_numbers))


def find_example_file(root: Path, name: str) -> Path | None:
    normalized = name.replace("/", "-").replace("\\", "-")
    stems = {name.split("/")[-1], normalized}
    suffixes = {".tsx", ".jsx", ".ts", ".js", ".py"}
    try:
        candidates = [
            candidate
            for candidate in root.rglob("*")
            if candidate.is_file() and candidate.suffix.lower() in suffixes and candidate.stem in stems
        ]
    except OSError:
        return None
    if not candidates:
        return None
    return sorted(candidates, key=lambda candidate: (len(candidate.parts), str(candidate)))[0]


def html_to_text(raw: str) -> str:
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(raw, "html.parser")
        for tag in soup(["script", "style", "nav", "footer"]):
            tag.decompose()
        return soup.get_text("\n")
    except Exception:
        text = re.sub(r"(?is)<(script|style).*?</\1>", "", raw)
        text = re.sub(r"(?s)<[^>]+>", " ", text)
        return html.unescape(text)


def compact_text(content: str) -> str:
    lines = [line.rstrip() for line in content.splitlines()]
    compacted = "\n".join(lines)
    compacted = re.sub(r"\n{4,}", "\n\n\n", compacted)
    return compacted.strip()


def infer_title(content: str, fallback: str) -> str:
    for line in content.splitlines()[:40]:
        match = re.match(r"^#\s+(.+)$", line.strip())
        if match:
            return match.group(1).strip()
    return fallback.replace("-", " ").replace("_", " ").strip().title() or "Untitled"


def infer_web_title(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path.strip("/").split("/")[-1] or parsed.netloc
    return path.replace("-", " ").replace("_", " ").title()
