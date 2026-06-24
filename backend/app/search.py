from __future__ import annotations

import json
import re
import sqlite3

from app.db import db
from app.embedding import EmbeddingError, cosine, embed_text, embedding_signature, tokenize
from app.ingestion import clean_web_markdown
from app.models import SearchMode, SearchResult, SourceRecord, SourceStatus


class SourceNotQueryableError(RuntimeError):
    pass


RRF_K = 60
KEYWORD_RRF_WEIGHT = 1.0
VECTOR_RRF_WEIGHT = 1.0
CONTEXT_WINDOW = 1
CODE_BLOCK_RE = re.compile(r"```(?P<language>[\w.+-]*)[^\n]*\n(?P<code>.*?)(?:\n```|$)", re.DOTALL)
SENTENCE_RE = re.compile(r"(?<=[.!?])\s+|\n{2,}")
STOP_TERMS = {
    "about",
    "and",
    "are",
    "can",
    "does",
    "for",
    "from",
    "how",
    "into",
    "the",
    "this",
    "that",
    "use",
    "using",
    "what",
    "when",
    "where",
    "with",
}

CHANGELOG_TERMS = {"changelog", "change", "changes", "release", "releases", "version", "versions", "migration", "migrate", "upgrade", "upgrading"}
TROUBLESHOOTING_TERMS = {
    "bug",
    "bugs",
    "broken",
    "error",
    "errors",
    "fail",
    "failed",
    "failing",
    "issue",
    "issues",
    "not",
    "problem",
    "problems",
    "troubleshoot",
    "troubleshooting",
    "work",
    "working",
}
CLOUD_TERMS = {"aws", "cloud", "cloudrun", "cloud-run", "lambda", "serverless"}

QUERY_EXPANSIONS = [
    (
        {"populate", "populating", "relation", "relations", "nested"},
        ["populate", "populateWhere", "populateOrderBy", "populateHints", "nested populate", "loading strategy"],
    ),
    (
        {"collection", "collections"},
        ["Collection", "collection.init", "init", "matching", "loadItems"],
    ),
    (
        {"filter", "filters", "where", "condition", "conditions"},
        ["where", "populateWhere", "filter", "conditions", "QueryBuilder", "qb.where"],
    ),
    (
        {"order", "ordered", "ordering", "sort", "sorted"},
        ["orderBy", "populateOrderBy", "sort", "QueryBuilder"],
    ),
    (
        {"limit", "limits", "paginate", "pagination", "offset"},
        ["limit", "offset", "populateHints"],
    ),
    (
        {"response", "model", "models", "exclude", "unset", "none", "fields"},
        ["response_model", "response_model_exclude_unset", "response_model_exclude_none", "response_model_exclude_defaults"],
    ),
    (
        {"upload", "uploads", "file", "files", "form", "forms"},
        ["UploadFile", "File", "Form", "multipart/form-data"],
    ),
    (
        {"dependency", "dependencies", "yield", "cleanup", "teardown"},
        ["Depends", "yield", "finally", "scope", "request"],
    ),
    (
        {"responsive", "breakpoint", "breakpoints"},
        ["responsive design", "breakpoints", "hideFrom", "hideBelow", "mdToXl", "lgOnly", "smDown"],
    ),
    (
        {"dark", "mode", "color"},
        ["color mode", "ColorModeButton", "useColorMode", "useColorModeValue", "next-themes"],
    ),
    (
        {"theme", "theming", "recipe", "recipes", "component", "styles"},
        ["defineRecipe", "defineSlotRecipe", "defineConfig", "createSystem", "slotRecipes"],
    ),
    (
        {"iconify", "react", "icon", "icons", "component"},
        ["@iconify/react", "Icon component", "<Icon", "icon=\"mdi-light:home\""],
    ),
    (
        {"iconify", "tailwind", "css", "selector", "selectors"},
        ["@iconify/tailwind", "addIconSelectors", "addDynamicIconSelectors", "icon-[", "dynamic icon selectors"],
    ),
    (
        {"custom", "json", "collection", "collections", "icon", "icons", "set", "sets"},
        ["addCollection", "IconifyJSON", "@iconify-json", "icon set", "custom icons"],
    ),
    (
        {"remotion", "composition", "compositions", "render", "video"},
        ["<Composition", "Composition", "npx remotion render", "renderMedia", "render video"],
    ),
    (
        {"sequence", "sequences", "interpolate", "animate", "animation", "animations"},
        ["<Sequence", "Sequence", "interpolate", "useCurrentFrame"],
    ),
    (
        {"offthreadvideo", "offthread", "static", "file", "files", "audio", "video"},
        ["OffthreadVideo", "staticFile", "<OffthreadVideo", "getStaticFiles"],
    ),
]


def search_chunks(
    *,
    query: str,
    source_id: str | None = None,
    source_name: str | None = None,
    limit: int = 8,
    mode: SearchMode = SearchMode.HYBRID,
) -> list[SearchResult]:
    if not query.strip():
        return []

    source_filters = resolve_queryable_source_filters(source_id, source_name)
    if source_filters == []:
        return []
    expanded_query = expand_query(query)
    keyword = keyword_search(expanded_query, source_filters, limit * 6) if mode != SearchMode.VECTOR else {}
    vector = vector_search(query, source_filters, limit * 6) if mode != SearchMode.KEYWORD else {}

    chunk_ids = set(keyword) | set(vector)
    if not chunk_ids:
        return []

    rows = fetch_chunks(chunk_ids)
    keyword_ranks = rank_lookup(keyword)
    vector_ranks = rank_lookup(vector)
    query_terms = meaningful_terms(query)
    expanded_terms = meaningful_terms(expanded_query)
    ranked = []
    for row in rows:
        keyword_score = keyword.get(row["id"], 0.0)
        vector_score = vector.get(row["id"], 0.0)
        relevance_text = row_relevance_text(row)
        coverage = term_coverage(query_terms, relevance_text)
        concept_coverage = query_concept_coverage(query_terms, relevance_text)
        if mode == SearchMode.KEYWORD:
            score = keyword_score
        elif mode == SearchMode.VECTOR:
            score = vector_score
        else:
            score = rrf_score(keyword_ranks.get(row["id"]), vector_ranks.get(row["id"]))
        score *= (
            (0.25 + (0.45 * coverage) + (0.3 * concept_coverage))
            * specificity_multiplier(query_terms, relevance_text)
            * source_quality_multiplier(row, query_terms)
            * relevance_multiplier(row, query_terms, expanded_terms)
        )
        ranked.append((score, keyword_score, vector_score, row))

    ranked.sort(key=lambda item: item[0], reverse=True)
    selected = diversify_by_document(ranked, limit)
    results: list[SearchResult] = []
    for score, keyword_score, vector_score, row in selected:
        result_context = assemble_context(row)
        shaped = shape_result(row, result_context, query_terms, expanded_terms)
        results.append(
            SearchResult(
                source_id=row["source_id"],
                source_name=row["source_name"],
                title=row["title"],
                uri=row["uri"],
                content=shaped["content"] or shaped["summary"],
                summary=shaped["summary"],
                code=shaped["code"],
                section_path=parse_section_path(row["section_path"]),
                score=round(score, 6),
                keyword_score=round(keyword_score, 6),
                vector_score=round(vector_score, 6),
            )
        )
    return results


def resolve_queryable_source_filters(source_id: str | None, source_name: str | None) -> list[str] | None:
    if source_id:
        source = db.get_source(source_id)
        if source is None:
            return ["__missing__"]
        require_source_queryable(source)
        return [source.id]
    if source_name:
        source = db.find_source(source_name)
        if source is None:
            return ["__missing__"]
        require_source_queryable(source)
        return [source.id]
    return [source.id for source in db.list_sources() if is_source_queryable(source)]


def is_source_queryable(source: SourceRecord) -> bool:
    if source.status != SourceStatus.INDEXED:
        return False
    return source_embedding_matches_current(source)


def require_source_queryable(source: SourceRecord) -> None:
    if is_source_queryable(source):
        return
    source_embedding = source.metadata.get("embedding")
    current = embedding_signature()
    if not isinstance(source_embedding, dict):
        raise SourceNotQueryableError(
            f'Source "{source.name}" must be re-indexed before searching. It does not have embedding model metadata.'
        )
    source_model = str(source_embedding.get("display_name") or source_embedding.get("model") or "unknown")
    raise SourceNotQueryableError(
        f'Source "{source.name}" must be re-indexed before searching. '
        f"It was indexed with {source_model}, but the current embedding model is {current['display_name']}."
    )


def source_embedding_matches_current(source: SourceRecord) -> bool:
    source_embedding = source.metadata.get("embedding")
    if not isinstance(source_embedding, dict):
        return False
    current = embedding_signature()
    return (
        source_embedding.get("provider") == current["provider"]
        and source_embedding.get("model") == current["model"]
    )


def source_embedding_display(source: SourceRecord) -> str:
    source_embedding = source.metadata.get("embedding")
    if not isinstance(source_embedding, dict):
        return "Unknown"
    return str(source_embedding.get("display_name") or source_embedding.get("model") or "Unknown")


def current_embedding_display() -> str:
    return embedding_signature()["display_name"]


def stale_indexed_source_count() -> int:
    return sum(1 for source in db.list_sources() if source.status == SourceStatus.INDEXED and not is_source_queryable(source))


def expand_query(query: str) -> str:
    terms = meaningful_terms(query)
    additions: list[str] = []
    for triggers, expansions in QUERY_EXPANSIONS:
        if terms & triggers:
            additions.extend(expansions)
    if not additions:
        return query
    unique_additions = list(dict.fromkeys(additions))
    return " ".join([query, *unique_additions])


def meaningful_terms(text: str) -> set[str]:
    return {term for term in tokenize(text) if term not in STOP_TERMS}


def row_relevance_text(row: sqlite3.Row) -> str:
    return "\n".join(
        [
            str(row["title"] or ""),
            str(row["uri"] or ""),
            " ".join(parse_section_path(row["section_path"])),
            str(row["content"] or ""),
        ]
    )


def relevance_multiplier(row: sqlite3.Row, query_terms: set[str], expanded_terms: set[str]) -> float:
    text = row_relevance_text(row)
    text_terms = set(tokenize(text))
    title_terms = set(tokenize(str(row["title"] or "")))
    uri_terms = set(tokenize(str(row["uri"] or "")))
    section_terms = set(tokenize(" ".join(parse_section_path(row["section_path"]))))

    query_hits = len(query_terms & text_terms)
    expanded_hits = len(expanded_terms & text_terms)
    heading_hits = len(expanded_terms & (title_terms | uri_terms | section_terms))

    multiplier = 1.0
    multiplier += min(0.5, query_hits * 0.08)
    multiplier += min(0.45, expanded_hits * 0.05)
    multiplier += min(0.4, heading_hits * 0.12)

    lowered_text = text.lower()
    for phrase in expected_phrases(query_terms):
        if phrase.lower() in lowered_text:
            multiplier += 0.12
    for symbol in expected_symbols(query_terms):
        if symbol.lower() in lowered_text:
            multiplier += 0.18
            if symbol.lower() in str(row["title"] or "").lower():
                multiplier += 0.22
            if symbol.lower() in str(row["uri"] or "").lower():
                multiplier += 0.16

    return min(multiplier, 3.0)


def specificity_multiplier(query_terms: set[str], text: str) -> float:
    phrases = expected_phrases(query_terms)
    lowered = text.lower()
    if not (query_terms & {"upgrade", "upgrading", "migration", "migrate"}) and (
        "upgrading-" in lowered or "migration" in lowered
    ):
        path_penalty = 0.55
    elif not (query_terms & CHANGELOG_TERMS) and (
        "release-notes" in lowered or "changelog" in lowered or "\\blog\\" in lowered or "/blog/" in lowered
    ):
        path_penalty = 0.45
    elif not (query_terms & {"guide", "tutorial", "walkthrough"}) and ("/guide/" in lowered or "\\guide\\" in lowered):
        path_penalty = 0.72
    else:
        path_penalty = 1.0
    if not phrases:
        return path_penalty
    phrase_hits = sum(1 for phrase in phrases if phrase.lower() in lowered)
    if phrase_hits == 0:
        return path_penalty * 0.38
    return path_penalty * min(1.5, 0.85 + (phrase_hits * 0.08))


def source_quality_multiplier(row: sqlite3.Row, query_terms: set[str]) -> float:
    uri = str(row["uri"] or "").lower()
    section = " ".join(parse_section_path(row["section_path"])).lower()
    title = str(row["title"] or "").lower()
    text = "\n".join([uri, section, title])

    multiplier = 1.0
    if not (query_terms & CHANGELOG_TERMS) and ("release-notes" in text or "changelog" in text):
        multiplier *= 0.42
    if not (query_terms & {"blog", "announcement", "announce"}) and ("\\blog\\" in text or "/blog/" in text):
        multiplier *= 0.65
    if not (query_terms & {"figma", "design", "kit"}) and "figma" in text:
        multiplier *= 0.58
    if not (query_terms & TROUBLESHOOTING_TERMS) and (
        "troubleshoot" in text
        or "troubleshooting" in text
        or "issues" in text
        or "issue" in title
        or "does not work" in text
        or "do not work" in text
        or "problem" in title
    ):
        multiplier *= 0.55
    if not (query_terms & CLOUD_TERMS) and ("cloudrun" in text or "cloud-run" in text or "lambda" in text):
        multiplier *= 0.48
    if "docs" in uri or "\\docs\\" in uri:
        multiplier *= 1.08
    if "\\content\\docs\\" in uri or "/content/docs/" in uri:
        multiplier *= 1.08
    if "\\content\\guides\\" in uri or "/content/guides/" in uri:
        multiplier *= 0.9
    if query_terms & {"responsive", "breakpoint", "breakpoints"} and "responsive-design" in text:
        multiplier *= 1.25
    if query_terms & {"dark", "mode", "color"} and ("color-mode" in text or "dark-mode" in text):
        multiplier *= 1.25
    if query_terms & {"theme", "theming", "recipe", "recipes"} and "recipes" in text:
        multiplier *= 1.25
    if query_terms & {"tailwind", "css", "selector", "selectors"}:
        if "tailwind" in text or "@iconify/tailwind" in text:
            multiplier *= 1.35
        if "addiconselectors" in text or "adddynamiciconselectors" in text or "icon-[" in text:
            multiplier *= 1.25
    if query_terms & {"react", "component"} and "iconify" in query_terms:
        if "@iconify/react" in text or "iconify-icon/react" in text or "react.html" in uri:
            multiplier *= 1.35
        if "@iconify-react/" in text and "@iconify/react" not in text:
            multiplier *= 0.72
    if query_terms & {"json", "custom", "collection", "collections", "set", "sets"} and (
        "addcollection" in text or "@iconify-json" in text or "custom-icons" in text or "json" in uri
    ):
        multiplier *= 1.28
    if query_terms & {"composition", "compositions", "render"} and "remotion" in query_terms:
        if "composition" in text or "brownfield-installation" in uri or "render.mdx" in uri or "render-media" in uri:
            multiplier *= 1.25
        if "cloudrun" in text or "lambda" in text:
            multiplier *= 0.68
    if "offthreadvideo" in query_terms:
        if "offthreadvideo" in title or "offthreadvideo" in uri:
            multiplier *= 2.35
        elif "staticfile" in text or "getstaticfiles" in text:
            multiplier *= 0.95
    if query_terms & {"sequence", "sequences", "interpolate", "animate", "animation", "animations"}:
        if "sequence" in title or "interpolate" in title or "sequence" in uri or "interpolate" in uri:
            multiplier *= 1.3
    return multiplier


def query_concept_coverage(query_terms: set[str], text: str) -> float:
    groups: list[set[str]] = []
    if query_terms & {"populate", "populating", "nested"}:
        groups.append({"populate", "populating", "populateorderby", "populatewhere", "populatehints"})
    if query_terms & {"relation", "relations", "one-to-many", "many-to-one", "manytomany"}:
        groups.append({"relation", "relations", "one-to-many", "many-to-one", "manytomany", "onetomany"})
    if query_terms & {"collection", "collections"}:
        groups.append({"collection", "collections", "collection.init", "matching"})
    if query_terms & {"filter", "filters", "where", "condition", "conditions"}:
        groups.append({"filter", "filters", "where", "populatewhere", "conditions"})
    if query_terms & {"order", "ordered", "ordering", "sort", "sorted"}:
        groups.append({"order", "orderby", "populateorderby", "sort", "sorted"})
    if query_terms & {"limit", "limits", "paginate", "pagination", "offset"}:
        groups.append({"limit", "limits", "offset", "pagination"})
    if query_terms & {"iconify", "react"}:
        groups.append({"iconify", "@iconify/react", "iconify-icon/react"})
        groups.append({"react", "component", "<icon"})
    if query_terms & {"tailwind", "selector", "selectors"}:
        groups.append({"tailwind", "@iconify/tailwind"})
        groups.append({"selector", "selectors", "addiconselectors", "adddynamiciconselectors", "icon-["})
    if query_terms & {"custom", "json", "collection", "collections"} and query_terms & {"icon", "icons", "iconify"}:
        groups.append({"addcollection", "custom", "json", "iconifyjson", "@iconify-json"})
    if query_terms & {"composition", "compositions"} and query_terms & {"render", "video", "remotion"}:
        groups.append({"composition", "<composition"})
        groups.append({"render", "rendermedia", "npx remotion render"})
    if query_terms & {"sequence", "sequences", "interpolate", "animate", "animation", "animations"}:
        groups.append({"sequence", "<sequence"})
        groups.append({"interpolate", "usecurrentframe", "animation", "animate"})
    if "offthreadvideo" in query_terms:
        groups.append({"offthreadvideo", "<offthreadvideo"})
        if query_terms & {"static", "file", "files", "audio", "video"}:
            groups.append({"staticfile", "getstaticfiles", "audio", "video"})
    if not groups:
        return 1.0

    lowered = text.lower()
    hits = 0
    for group in groups:
        if any(term in lowered for term in group):
            hits += 1
    return hits / len(groups)


def expected_phrases(query_terms: set[str]) -> list[str]:
    phrases: list[str] = []
    if query_terms & {"populate", "populating", "relation", "relations", "nested"}:
        phrases.extend(["populateOrderBy", "populateWhere", "populateHints", "nested populate"])
    if query_terms & {"collection", "collections"}:
        phrases.extend(["collection.init", "Collection", "matching"])
    if query_terms & {"filter", "filters", "where", "condition", "conditions"}:
        phrases.extend(["where", "populateWhere"])
    if query_terms & {"order", "ordered", "ordering", "sort", "sorted"}:
        phrases.extend(["orderBy", "populateOrderBy"])
    if query_terms & {"limit", "limits", "paginate", "pagination", "offset"}:
        phrases.extend(["limit", "offset"])
    if query_terms & {"iconify", "react", "icon", "icons", "component"}:
        phrases.extend(["@iconify/react", "<Icon", "Icon component"])
    if query_terms & {"tailwind", "css", "selector", "selectors"}:
        phrases.extend(["@iconify/tailwind", "addIconSelectors", "addDynamicIconSelectors", "icon-["])
    if query_terms & {"custom", "json", "collection", "collections", "set", "sets"}:
        phrases.extend(["addCollection", "IconifyJSON", "@iconify-json", "custom icons"])
    if query_terms & {"composition", "compositions", "render", "video"}:
        phrases.extend(["<Composition", "npx remotion render", "renderMedia", "render video"])
    if query_terms & {"sequence", "sequences", "interpolate", "animate", "animation", "animations"}:
        phrases.extend(["<Sequence", "interpolate", "useCurrentFrame"])
    if "offthreadvideo" in query_terms or query_terms & {"offthread"}:
        phrases.extend(["OffthreadVideo", "<OffthreadVideo", "staticFile"])
    phrases.extend(expected_symbols(query_terms))
    return list(dict.fromkeys(phrases))


def expected_symbols(query_terms: set[str]) -> list[str]:
    symbols: list[str] = []
    if query_terms & {"response", "model", "models", "exclude", "unset", "none"}:
        symbols.extend(["response_model_exclude_unset", "response_model_exclude_none", "response_model"])
    if query_terms & {"upload", "uploads", "file", "files", "form", "forms"}:
        symbols.extend(["UploadFile", "File", "Form"])
    if query_terms & {"dependency", "dependencies", "yield", "cleanup", "teardown"}:
        symbols.extend(["Depends", "yield", "finally"])
    if query_terms & {"responsive", "breakpoint", "breakpoints"}:
        symbols.extend(["hideFrom", "hideBelow", "mdToXl", "lgOnly", "smDown"])
    if query_terms & {"dark", "mode", "color"}:
        symbols.extend(["ColorModeButton", "useColorMode", "useColorModeValue"])
    if query_terms & {"theme", "theming", "recipe", "recipes"}:
        symbols.extend(["defineRecipe", "defineSlotRecipe", "defineConfig", "createSystem"])
    if query_terms & {"iconify", "react", "icon", "icons", "component"}:
        symbols.extend(["Icon", "@iconify/react"])
    if query_terms & {"tailwind", "css", "selector", "selectors"}:
        symbols.extend(["addIconSelectors", "addDynamicIconSelectors"])
    if query_terms & {"custom", "json", "collection", "collections", "set", "sets"}:
        symbols.extend(["addCollection", "IconifyJSON"])
    if query_terms & {"composition", "compositions", "render", "video"}:
        symbols.extend(["Composition", "renderMedia"])
    if query_terms & {"sequence", "sequences", "interpolate", "animate", "animation", "animations"}:
        symbols.extend(["Sequence", "interpolate", "useCurrentFrame"])
    if "offthreadvideo" in query_terms or query_terms & {"offthread"}:
        symbols.extend(["OffthreadVideo", "staticFile", "getStaticFiles"])
    return list(dict.fromkeys(symbols))


def shape_result(
    row: sqlite3.Row,
    content: str,
    query_terms: set[str],
    expanded_terms: set[str],
) -> dict[str, str | None]:
    phrases = expected_phrases(query_terms)
    clean_content = clean_result_content(content)
    excerpt = extract_excerpt(clean_content, query_terms | expanded_terms, phrases)
    summary_source = excerpt or clean_content
    summary = extract_summary(summary_source, query_terms | expanded_terms, phrases)
    code = extract_code(clean_content, query_terms | expanded_terms, phrases)
    if not summary:
        section_path = parse_section_path(row["section_path"])
        summary = " / ".join(section_path) if section_path else str(row["title"] or "").strip()
    if not excerpt:
        excerpt = summary
    return {"summary": summary, "content": excerpt, "code": code}


def clean_result_content(content: str) -> str:
    return clean_web_markdown(content)


def extract_excerpt(content: str, terms: set[str], phrases: list[str]) -> str:
    excerpt_source = CODE_BLOCK_RE.sub("", content)
    blocks = [block.strip() for block in re.split(r"\n{2,}", excerpt_source) if block.strip()]
    candidates = []
    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        useful_lines = [line for line in lines if not is_low_value_excerpt_line(line)]
        candidates.extend(matched_line_windows(useful_lines, terms, phrases))
        if useful_lines:
            candidates.append("\n".join(useful_lines))
    ranked = rank_text_candidates(candidates, terms, phrases)
    if not ranked:
        return ""
    return trim_excerpt(normalize_text(ranked[0][1]), max_chars=900)


def matched_line_windows(lines: list[str], terms: set[str], phrases: list[str]) -> list[str]:
    windows: list[str] = []
    for index, line in enumerate(lines):
        normalized = normalize_text(line)
        line_terms = set(tokenize(normalized))
        phrase_hits = any(phrase.lower() in normalized.lower() for phrase in phrases)
        if not phrase_hits and not (terms & line_terms):
            continue
        window = [line]
        for follower in lines[index + 1 : index + 3]:
            if follower.startswith("#") and window:
                break
            window.append(follower)
        windows.append("\n".join(window))
    return windows


def is_low_value_excerpt_line(line: str) -> bool:
    normalized = normalize_text(line).lower()
    if not normalized:
        return True
    if normalized in {"console", "cli", "api", "output", "show output"}:
        return True
    if normalized.startswith("![") or normalized.startswith("was this page helpful"):
        return True
    if re.fullmatch(r"[-*]\s+\[[^\]]+\]\([^)]*\)", line):
        return True
    return False


def trim_excerpt(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    cutoff = text.rfind(". ", 0, max_chars)
    if cutoff < max_chars // 2:
        cutoff = text.rfind(" ", 0, max_chars)
    if cutoff < max_chars // 2:
        cutoff = max_chars
    return text[:cutoff].rstrip(" .") + "."


def extract_summary(content: str, terms: set[str], phrases: list[str]) -> str:
    summary_source = CODE_BLOCK_RE.sub("", content)
    candidates = [part.strip() for part in SENTENCE_RE.split(summary_source) if part.strip()]
    candidates.extend(line.strip("# ").strip() for line in summary_source.splitlines() if line.strip().startswith("#"))
    ranked = rank_text_candidates(candidates, terms, phrases)
    if not ranked:
        return ""
    summary = normalize_text(ranked[0][1]).lstrip("#").strip()
    return summary[:420].rstrip()


def extract_code(content: str, terms: set[str], phrases: list[str]) -> str | None:
    blocks = [match.group("code").strip() for match in CODE_BLOCK_RE.finditer(content) if is_code_like(match.group("code"))]
    ranked_blocks = rank_text_candidates(blocks, terms, phrases)
    if ranked_blocks:
        return ranked_blocks[0][1][:1400].rstrip()

    return None


def rank_text_candidates(candidates: list[str], terms: set[str], phrases: list[str]) -> list[tuple[float, str]]:
    ranked: list[tuple[float, str]] = []
    for candidate in candidates:
        normalized = normalize_text(candidate)
        if not normalized:
            continue
        candidate_terms = set(tokenize(normalized))
        term_hits = len(terms & candidate_terms)
        phrase_hits = sum(1 for phrase in phrases if phrase.lower() in normalized.lower())
        code_bonus = 1 if any(
            marker in normalized
            for marker in (
                "await ",
                "=>",
                ".find(",
                ".init(",
                "orderBy",
                "import ",
                "export ",
                "const ",
                "<",
                "defineConfig",
                "defineRecipe",
                "createSystem",
            )
        ) else 0
        score = term_hits + (phrase_hits * 3) + code_bonus
        if candidate.lstrip().startswith("#"):
            score *= 0.55
        if score:
            ranked.append((score, candidate))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return ranked


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def is_code_like(text: str) -> bool:
    lowered = text.lower()
    code_markers = (
        "await ",
        "const ",
        "let ",
        "import ",
        "export ",
        "function ",
        "return ",
        "=>",
        ".find(",
        ".init(",
        "mikroorm.init",
        "orderby",
        "where:",
        "populate:",
        "populatewhere:",
        "populatehints:",
        "response_model",
        "uploadfile",
        "form(",
        "file(",
        "colormodebutton",
        "usecolormode",
        "defineconfig",
        "definerecipe",
        "defineslotrecipe",
        "createsystem",
        "npx ",
    )
    has_jsx = bool(re.search(r"</?[A-Z][A-Za-z0-9.]*[\s>/]", text))
    return (has_jsx or any(marker in lowered for marker in code_markers)) and any(
        symbol in text for symbol in ("{", "}", "(", ")", ";", ":", "<", ">")
    )


def append_source_filters(where: str, params: list[object], source_ids: list[str] | None, table_name: str) -> str:
    if source_ids is None:
        return where
    placeholders = ",".join("?" for _ in source_ids)
    params.extend(source_ids)
    return f"{where} AND {table_name}.source_id IN ({placeholders})"


def keyword_search(query: str, source_ids: list[str] | None, limit: int) -> dict[int, float]:
    if source_ids == []:
        return {}
    match_query = build_fts_query(query)
    where = "WHERE chunks_fts MATCH ?"
    params: list[object] = [match_query]
    where = append_source_filters(where, params, source_ids, "chunks_fts")
    params.append(limit)

    try:
        with db.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT rowid AS chunk_id, bm25(chunks_fts) AS rank
                FROM chunks_fts
                {where}
                ORDER BY rank
                LIMIT ?
                """,
                params,
            ).fetchall()
    except sqlite3.OperationalError:
        return {}

    if not rows:
        return {}
    worst = max(abs(row["rank"]) for row in rows) or 1.0
    return {int(row["chunk_id"]): 1.0 - (abs(row["rank"]) / (worst + 1.0)) for row in rows}


def vector_search(query: str, source_ids: list[str] | None, limit: int) -> dict[int, float]:
    if source_ids == []:
        return {}
    try:
        query_vector = embed_text(query)
    except EmbeddingError:
        return {}
    sql = "SELECT id, embedding FROM chunks"
    params: list[object] = []
    if source_ids is not None:
        placeholders = ",".join("?" for _ in source_ids)
        sql += f" WHERE source_id IN ({placeholders})"
        params.extend(source_ids)
    with db.connect() as connection:
        rows = connection.execute(sql, params).fetchall()

    scored = []
    for row in rows:
        try:
            vector = json.loads(row["embedding"])
        except json.JSONDecodeError:
            continue
        score = cosine(query_vector, vector)
        if score > 0:
            scored.append((int(row["id"]), score))
    scored.sort(key=lambda item: item[1], reverse=True)
    return {chunk_id: score for chunk_id, score in scored[:limit]}


def fetch_chunks(chunk_ids: set[int]) -> list[sqlite3.Row]:
    placeholders = ",".join("?" for _ in chunk_ids)
    with db.connect() as connection:
        return connection.execute(
            f"""
            SELECT chunks.*, sources.name AS source_name
            FROM chunks
            JOIN sources ON sources.id = chunks.source_id
            WHERE chunks.id IN ({placeholders})
            """,
            list(chunk_ids),
        ).fetchall()


def rank_lookup(scores: dict[int, float]) -> dict[int, int]:
    return {chunk_id: index for index, chunk_id in enumerate(scores, start=1)}


def rrf_score(keyword_rank: int | None, vector_rank: int | None) -> float:
    score = 0.0
    if keyword_rank is not None:
        score += KEYWORD_RRF_WEIGHT / (RRF_K + keyword_rank)
    if vector_rank is not None:
        score += VECTOR_RRF_WEIGHT / (RRF_K + vector_rank)
    return score


def diversify_by_document(ranked: list[tuple[float, float, float, sqlite3.Row]], limit: int) -> list[tuple[float, float, float, sqlite3.Row]]:
    selected: list[tuple[float, float, float, sqlite3.Row]] = []
    deferred: list[tuple[float, float, float, sqlite3.Row]] = []
    seen_documents: set[int] = set()
    seen_topics: set[str] = set()

    for item in ranked:
        document_id = int(item[3]["document_id"])
        topic = result_topic_key(item[3])
        if document_id in seen_documents:
            deferred.append(item)
            continue
        if topic and topic in seen_topics:
            deferred.append(item)
            continue
        selected.append(item)
        seen_documents.add(document_id)
        if topic:
            seen_topics.add(topic)
        if len(selected) == limit:
            return selected

    for item in deferred:
        selected.append(item)
        if len(selected) == limit:
            break
    return selected


def result_topic_key(row: sqlite3.Row) -> str:
    title = normalize_topic_part(str(row["title"] or ""))
    section_path = parse_section_path(row["section_path"])
    section = normalize_topic_part(section_path[0] if section_path else "")
    uri = normalize_topic_part(uri_topic_part(str(row["uri"] or "")))
    if title in {"", "example", "usage", "options", "props", "contents"}:
        return uri or section
    if title in {"render", "sequence", "sequences", "composition", "icon", "selectors"}:
        return title
    return " ".join(part for part in (uri, title, section) if part)[:160]


def uri_topic_part(uri: str) -> str:
    normalized = uri.replace("\\", "/").split("#", 1)[0].split("?", 1)[0].strip("/")
    if not normalized:
        return ""
    parts = [part for part in normalized.split("/") if part]
    if not parts:
        return ""
    if parts[-1] in {"index.md", "index.mdx", "index.html", "index"} and len(parts) > 1:
        return parts[-2]
    return re.sub(r"\.(mdx?|html?|tsx?|jsx?)$", "", parts[-1], flags=re.IGNORECASE)


def normalize_topic_part(value: str) -> str:
    lowered = value.lower()
    lowered = re.sub(r"<[^>]+>", "", lowered)
    lowered = re.sub(r"[^a-z0-9_./:-]+", "-", lowered)
    lowered = re.sub(r"-+", "-", lowered).strip("-")
    return lowered


def assemble_context(row: sqlite3.Row) -> str:
    with db.connect() as connection:
        rows = connection.execute(
            """
            SELECT id, content
            FROM chunks
            WHERE document_id = ?
              AND ordinal BETWEEN ? AND ?
            ORDER BY ordinal
            """,
            (
                row["document_id"],
                max(0, int(row["ordinal"]) - CONTEXT_WINDOW),
                int(row["ordinal"]) + CONTEXT_WINDOW,
            ),
        ).fetchall()

    if len(rows) <= 1:
        return row["content"]

    parts = []
    seen = set()
    for chunk in rows:
        content = str(chunk["content"]).strip()
        if content and content not in seen:
            parts.append(content)
            seen.add(content)
    return "\n\n".join(parts) or row["content"]


def parse_section_path(value: object) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(part) for part in parsed if isinstance(part, str)]


def term_coverage(query_terms: set[str], text: str) -> float:
    if not query_terms:
        return 1.0
    text_terms = set(tokenize(text))
    return len(query_terms & text_terms) / len(query_terms)


def build_fts_query(query: str) -> str:
    terms = list(dict.fromkeys(term.replace('"', "") for term in tokenize(query) if term.strip()))
    if not terms:
        return '""'
    return " OR ".join(f'"{term}"' for term in terms)
