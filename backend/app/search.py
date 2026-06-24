from __future__ import annotations

import json
import re
import sqlite3

from app import vector_index
from app.db import db
from app.embedding import EmbeddingError, cosine, embed_text, embedding_signature, tokenize
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
    keyword = keyword_search(query, source_filters, limit * 6) if mode != SearchMode.VECTOR else {}
    vector = vector_search(query, source_filters, limit * 6) if mode != SearchMode.KEYWORD else {}

    chunk_ids = set(keyword) | set(vector)
    if not chunk_ids:
        return []

    rows = fetch_chunks(chunk_ids)
    keyword_ranks = rank_lookup(keyword)
    vector_ranks = rank_lookup(vector)
    query_terms = meaningful_terms(query)
    ranked = []
    for row in rows:
        keyword_score = keyword.get(row["id"], 0.0)
        vector_score = vector.get(row["id"], 0.0)
        if mode == SearchMode.KEYWORD:
            score = keyword_score
        elif mode == SearchMode.VECTOR:
            score = vector_score
        else:
            score = rrf_score(keyword_ranks.get(row["id"]), vector_ranks.get(row["id"]))
        ranked.append((score, keyword_score, vector_score, row["id"], row))

    ranked.sort(key=lambda item: (item[0], item[1], item[2], -item[3]), reverse=True)
    selected = diversify_by_document(ranked, limit)
    results: list[SearchResult] = []
    for score, keyword_score, vector_score, _chunk_id, row in selected:
        result_context = assemble_context(row)
        shaped = shape_result(row, result_context, query_terms)
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


def meaningful_terms(text: str) -> set[str]:
    return {term for term in tokenize(text) if term not in STOP_TERMS}


def shape_result(
    row: sqlite3.Row,
    content: str,
    query_terms: set[str],
) -> dict[str, str | None]:
    clean_content = content.replace("\r\n", "\n").replace("\r", "\n").strip()
    excerpt = extract_excerpt(clean_content, query_terms)
    summary_source = excerpt or clean_content
    summary = extract_summary(summary_source, query_terms)
    code = extract_code(clean_content, query_terms)
    if not summary:
        section_path = parse_section_path(row["section_path"])
        summary = " / ".join(section_path) if section_path else str(row["title"] or "").strip()
    if not excerpt:
        excerpt = summary
    return {"summary": summary, "content": excerpt, "code": code}


def extract_excerpt(content: str, terms: set[str]) -> str:
    excerpt_source = CODE_BLOCK_RE.sub("", content)
    blocks = [block.strip() for block in re.split(r"\n{2,}", excerpt_source) if block.strip()]
    candidates = []
    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        useful_lines = [line for line in lines if not is_low_value_excerpt_line(line)]
        candidates.extend(matched_line_windows(useful_lines, terms))
        if useful_lines:
            candidates.append("\n".join(useful_lines))
    ranked = rank_text_candidates(candidates, terms)
    if not ranked:
        return ""
    return trim_excerpt(normalize_text(ranked[0][1]), max_chars=900)


def matched_line_windows(lines: list[str], terms: set[str]) -> list[str]:
    windows: list[str] = []
    for index, line in enumerate(lines):
        normalized = normalize_text(line)
        line_terms = set(tokenize(normalized))
        if not (terms & line_terms):
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


def extract_summary(content: str, terms: set[str]) -> str:
    summary_source = CODE_BLOCK_RE.sub("", content)
    candidates = [part.strip() for part in SENTENCE_RE.split(summary_source) if part.strip()]
    candidates.extend(line.strip("# ").strip() for line in summary_source.splitlines() if line.strip().startswith("#"))
    ranked = rank_text_candidates(candidates, terms)
    if not ranked:
        return ""
    summary = normalize_text(ranked[0][1]).lstrip("#").strip()
    return summary[:420].rstrip()


def extract_code(content: str, terms: set[str]) -> str | None:
    blocks = [match.group("code").strip() for match in CODE_BLOCK_RE.finditer(content) if is_code_like(match.group("code"))]
    ranked_blocks = rank_text_candidates(blocks, terms)
    if ranked_blocks:
        return ranked_blocks[0][1][:1400].rstrip()

    return None


def rank_text_candidates(candidates: list[str], terms: set[str]) -> list[tuple[float, str]]:
    ranked: list[tuple[float, str]] = []
    for candidate in candidates:
        normalized = normalize_text(candidate)
        if not normalized:
            continue
        candidate_terms = set(tokenize(normalized))
        term_hits = len(terms & candidate_terms)
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
        score = term_hits + code_bonus
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
    indexed = sqlite_vec_search(query_vector, source_ids, limit)
    if indexed:
        return indexed
    return python_vector_search(query_vector, source_ids, limit)


def sqlite_vec_search(query_vector: list[float], source_ids: list[str] | None, limit: int) -> dict[int, float]:
    if not vector_index.is_available():
        return {}
    try:
        with db.connect() as connection:
            if source_ids is None:
                rows = vector_index.query(connection, query_vector, limit=limit)
            else:
                rows = []
                for source_id in source_ids:
                    rows.extend(vector_index.query(connection, query_vector, source_id=source_id, limit=limit))
    except sqlite3.Error:
        return {}

    if not rows:
        return {}
    rows.sort(key=lambda item: item[1])
    selected = rows[:limit]
    return {chunk_id: distance_to_score(distance) for chunk_id, distance in selected}


def distance_to_score(distance: float) -> float:
    if distance < 0:
        return 0.0
    return 1.0 / (1.0 + distance)


def python_vector_search(query_vector: list[float], source_ids: list[str] | None, limit: int) -> dict[int, float]:
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
    sorted_scores = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    return {chunk_id: index for index, (chunk_id, _score) in enumerate(sorted_scores, start=1)}


def rrf_score(keyword_rank: int | None, vector_rank: int | None) -> float:
    score = 0.0
    if keyword_rank is not None:
        score += KEYWORD_RRF_WEIGHT / (RRF_K + keyword_rank)
    if vector_rank is not None:
        score += VECTOR_RRF_WEIGHT / (RRF_K + vector_rank)
    return score


def diversify_by_document(
    ranked: list[tuple[float, float, float, int, sqlite3.Row]],
    limit: int,
) -> list[tuple[float, float, float, int, sqlite3.Row]]:
    selected: list[tuple[float, float, float, int, sqlite3.Row]] = []
    deferred: list[tuple[float, float, float, int, sqlite3.Row]] = []
    seen_documents: set[int] = set()

    for item in ranked:
        document_id = int(item[4]["document_id"])
        if document_id in seen_documents:
            deferred.append(item)
            continue
        selected.append(item)
        seen_documents.add(document_id)
        if len(selected) == limit:
            return selected

    for item in deferred:
        selected.append(item)
        if len(selected) == limit:
            break
    return selected


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


def build_fts_query(query: str) -> str:
    terms = list(dict.fromkeys(term.replace('"', "") for term in tokenize(query) if term.strip()))
    if not terms:
        return '""'
    return " OR ".join(f'"{term}"' for term in terms)
