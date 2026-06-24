from __future__ import annotations

import html
import re
from pathlib import Path
from urllib.parse import urlparse

FRONT_MATTER_RE = re.compile(r"\A---\s*\n.*?\n---\s*(?:\n|$)", re.DOTALL)
FASTAPI_INCLUDE_RE = re.compile(r"\{\*\s+(?P<target>[^\s*]+)(?P<options>[^*]*)\*\}")
MDX_EXAMPLE_RE = re.compile(r"<(?P<tag>ExampleTabs|ExampleCode|ExamplePreview)\s+name=\"(?P<name>[^\"]+)\"\s*/>")
MARKDOWN_IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]+\)")
LOW_VALUE_WEB_LINE_PATTERNS = (
    re.compile(r"^ask ai$", re.IGNORECASE),
    re.compile(r"^copy page$", re.IGNORECASE),
    re.compile(r"^search(?:\.\.\.)?(?:\s*[⌘/]?\s*k)?$", re.IGNORECASE),
    re.compile(r"^thank you for your feedback!?$", re.IGNORECASE),
    re.compile(r"^was this page helpful\??$", re.IGNORECASE),
    re.compile(r"^yes\s*no$", re.IGNORECASE),
)
WEB_TOC_HEADINGS = {"contents", "on this page", "table of contents"}
CODE_LANGUAGE_BY_SUFFIX = {
    ".js": "js",
    ".jsx": "jsx",
    ".py": "py",
    ".ts": "ts",
    ".tsx": "tsx",
}


def normalize_content(raw: str, suffix: str, path: Path | None = None, root: Path | None = None) -> str:
    if suffix.lower() in {".html", ".htm"}:
        return html_to_markdown(raw)
    content = raw.replace("\r\n", "\n").replace("\r", "\n")
    if suffix.lower() in {".md", ".mdx"}:
        content = strip_front_matter(content)
        if path is not None:
            content = expand_markdown_includes(content, path, root or path.parent)
            content = expand_mdx_examples(content, path, root or path.parent)
    return content


def normalize_web_content(content: str, url: str | None = None) -> str:
    if looks_like_html(content):
        content = extract_main_markdown(content, url=url) or html_to_markdown(content)
    return clean_web_markdown(content)


def extract_main_markdown(raw_html: str, url: str | None = None) -> str:
    try:
        from trafilatura import extract

        extracted = extract(
            raw_html,
            url=url,
            output_format="markdown",
            include_comments=False,
            include_links=True,
            include_tables=True,
            deduplicate=True,
            favor_precision=True,
        )
    except Exception:
        return ""
    if not isinstance(extracted, str):
        return ""
    extracted = extracted.strip()
    return extracted if is_substantial_extraction(extracted) else ""


def html_to_markdown(raw: str) -> str:
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(raw, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside", "noscript", "svg"]):
            tag.decompose()
        root = soup.find(["main", "article"]) or soup.body or soup
        html_fragment = str(root)

        try:
            from markdownify import markdownify

            return compact_text(
                markdownify(
                    html_fragment,
                    bullets="-",
                    heading_style="ATX",
                    strip=["script", "style", "nav", "footer", "header", "aside", "noscript", "svg"],
                )
            )
        except Exception:
            return compact_text(markdown_from_soup_node(root))
    except Exception:
        text = re.sub(r"(?is)<(script|style).*?</\1>", "", raw)
        text = re.sub(r"(?s)<[^>]+>", " ", text)
        return html.unescape(text)


def markdown_from_soup_node(node: object, *, in_pre: bool = False) -> str:
    from bs4 import NavigableString, Tag

    if isinstance(node, NavigableString):
        return html.unescape(str(node))
    if not isinstance(node, Tag):
        return ""

    name = node.name.lower()
    if name in {"script", "style", "nav", "footer", "header", "aside", "noscript", "svg"}:
        return ""
    if name == "br":
        return "\n"
    if name in {"h1", "h2", "h3", "h4", "h5", "h6"}:
        level = int(name[1])
        return f"\n\n{'#' * level} {children_to_markdown(node).strip()}\n\n"
    if name == "pre":
        code = node.get_text("\n").strip()
        return f"\n\n```\n{code}\n```\n\n" if code else ""
    if name == "code" and not in_pre:
        code = node.get_text(" ").strip()
        return f"`{code}`" if code else ""
    if name == "a":
        text = children_to_markdown(node).strip() or node.get_text(" ", strip=True)
        href = str(node.get("href") or "").strip()
        return f"[{text}]({href})" if text and href else text
    if name in {"strong", "b"}:
        text = children_to_markdown(node).strip()
        return f"**{text}**" if text else ""
    if name in {"em", "i"}:
        text = children_to_markdown(node).strip()
        return f"*{text}*" if text else ""
    if name in {"li"}:
        return f"- {children_to_markdown(node).strip()}\n"
    if name in {"ul", "ol"}:
        return "\n" + children_to_markdown(node).strip() + "\n\n"
    if name in {"p", "div", "section", "article", "main", "blockquote", "table"}:
        text = children_to_markdown(node).strip()
        return f"\n\n{text}\n\n" if text else ""
    return children_to_markdown(node)


def children_to_markdown(node: object) -> str:
    children = getattr(node, "children", [])
    return "".join(markdown_from_soup_node(child) for child in children)


def clean_web_markdown(content: str) -> str:
    lines: list[str] = []
    skip_toc = False
    for raw_line in content.replace("\r\n", "\n").replace("\r", "\n").splitlines():
        line = MARKDOWN_IMAGE_RE.sub("", raw_line).rstrip()
        normalized = normalize_markdown_line(line)
        if normalized in WEB_TOC_HEADINGS:
            skip_toc = True
            continue
        if skip_toc:
            if line.startswith("#"):
                skip_toc = False
            elif not line.strip() or re.match(r"^\s*[-*]\s+", line):
                continue
        if is_low_value_web_line(normalized):
            continue
        lines.append(line)
    return compact_text("\n".join(lines))


def is_substantial_extraction(content: str) -> bool:
    words = re.findall(r"\w+", content)
    return len(words) >= 25


def has_obvious_web_chrome(content: str) -> bool:
    hits = 0
    for line in content.splitlines():
        normalized = normalize_markdown_line(line)
        if normalized in WEB_TOC_HEADINGS or is_low_value_web_line(normalized):
            hits += 1
    return hits >= 2


def normalize_markdown_line(line: str) -> str:
    text = MARKDOWN_IMAGE_RE.sub("", line)
    text = re.sub(r"\[[^\]]*\]\([^)]*\)", "", text)
    text = re.sub(r"^\s{0,3}#{1,6}\s+", "", text)
    text = re.sub(r"\s+", " ", text).strip().lower()
    return text


def is_low_value_web_line(normalized_line: str) -> bool:
    if not normalized_line:
        return False
    return any(pattern.fullmatch(normalized_line) for pattern in LOW_VALUE_WEB_LINE_PATTERNS)


def looks_like_html(content: str) -> bool:
    return bool(re.search(r"(?is)<(?:!doctype\s+html|html|body|main|article|section|h[1-6]|p|pre|code|ul|ol|li|a)\b", content))


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
