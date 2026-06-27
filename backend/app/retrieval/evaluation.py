from __future__ import annotations

import argparse
import json
import sys
import tempfile
from collections.abc import Iterable
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app import db as db_package
from app.db import Database
from app.domain.models import SearchMode, SourceKind, SourceRecord
from app.indexing.chunking import build_document
from app.indexing.discovery import document_from_file
from app.retrieval import search as search_module
from app.retrieval.embeddings import clear_embedding_config_cache, embedding_signature


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATASET = REPO_ROOT / "tests" / "evals" / "retrieval" / "local_docs_fixture.json"


@dataclass(frozen=True)
class EvalOptions:
    dataset_path: Path = DEFAULT_DATASET
    live: bool = False
    mode: SearchMode | None = None
    limit: int | None = None


def run_retrieval_eval(options: EvalOptions) -> dict[str, Any]:
    dataset = load_dataset(options.dataset_path)
    if options.live:
        return evaluate_dataset(dataset, options)

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
        fixture_db = build_fixture_database(dataset, Path(directory) / "ingestor.sqlite", options.dataset_path)
        try:
            with patched_app_database(fixture_db), patched_search_database(fixture_db):
                return evaluate_dataset(dataset, options)
        finally:
            fixture_db.engine.dispose()


def load_dataset(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ValueError(f"Eval dataset does not exist: {path}") from error
    except json.JSONDecodeError as error:
        raise ValueError(f"Eval dataset is not valid JSON: {path}") from error

    if not isinstance(payload, dict):
        raise ValueError("Eval dataset must be a JSON object")
    if not isinstance(payload.get("cases"), list) or not payload["cases"]:
        raise ValueError("Eval dataset must include at least one case")
    return payload


def build_fixture_database(dataset: dict[str, Any], path: Path, dataset_path: Path) -> Database:
    fixture_db = Database(path)
    source_payloads = fixture_sources(dataset)
    documents_by_source = fixture_documents_by_source(dataset, source_payloads)
    if not any(documents_by_source.values()):
        raise ValueError("Fixture eval datasets must include documents unless --live is used")

    with patched_app_database(fixture_db):
        for source_index, source_payload in enumerate(source_payloads, start=1):
            source = build_fixture_source(source_payload, source_index)
            fixture_db.upsert_source(source)
            built_documents = [
                build_fixture_document(document_payload, label, dataset_path, source_payload)
                for document_payload, label in documents_by_source[fixture_source_key(source_payload)]
            ]
            if not built_documents:
                raise ValueError(
                    f"Fixture source {source.name!r} must include documents unless --live is used"
                )
            fixture_db.replace_source_documents(source, built_documents)
    return fixture_db


def fixture_sources(dataset: dict[str, Any]) -> list[dict[str, Any]]:
    sources = dataset.get("sources")
    if sources is None:
        return [require_mapping(dataset.get("source"), "source")]
    if not isinstance(sources, list) or not sources:
        raise ValueError("sources must be a non-empty list")
    return [require_mapping(source, f"sources[{index}]") for index, source in enumerate(sources, start=1)]


def build_fixture_source(source_payload: dict[str, Any], index: int) -> SourceRecord:
    metadata = dict(source_payload["metadata"]) if isinstance(source_payload.get("metadata"), dict) else {}
    metadata.setdefault("embedding", embedding_signature())
    return SourceRecord(
        id=str(source_payload.get("id") or f"fixture-{index}"),
        kind=SourceKind(str(source_payload.get("kind") or SourceKind.LOCAL)),
        name=str(source_payload.get("name") or source_payload.get("id") or f"fixture-{index}"),
        version=str(source_payload.get("version") or "eval"),
        location=str(source_payload.get("location") or source_payload.get("root") or "fixture"),
        metadata=metadata,
    )


def fixture_documents_by_source(
    dataset: dict[str, Any],
    source_payloads: list[dict[str, Any]],
) -> dict[str, list[tuple[dict[str, Any], str]]]:
    source_lookup: dict[str, str] = {}
    documents_by_source: dict[str, list[tuple[dict[str, Any], str]]] = {}
    for index, source_payload in enumerate(source_payloads, start=1):
        primary_key = fixture_source_key(source_payload)
        documents_by_source[primary_key] = []
        for alias in fixture_source_aliases(source_payload):
            if alias in source_lookup and source_lookup[alias] != primary_key:
                raise ValueError(f"Duplicate fixture source alias: {alias}")
            source_lookup[alias] = primary_key

        source_documents = source_payload.get("documents", [])
        if source_documents is None:
            source_documents = []
        if not isinstance(source_documents, list):
            raise ValueError(f"sources[{index}].documents must be a list")
        for document_index, document in enumerate(source_documents, start=1):
            documents_by_source[primary_key].append(
                (
                    require_mapping(document, f"sources[{index}].documents[{document_index}]"),
                    f"sources[{index}].documents[{document_index}]",
                )
            )

    top_level_documents = dataset.get("documents", [])
    if top_level_documents is None:
        top_level_documents = []
    if not isinstance(top_level_documents, list):
        raise ValueError("documents must be a list")
    for document_index, document in enumerate(top_level_documents, start=1):
        document_payload = require_mapping(document, f"documents[{document_index}]")
        source_reference = optional_string(document_payload.get("source_id")) or optional_string(document_payload.get("source"))
        if source_reference is None:
            if len(source_payloads) != 1:
                raise ValueError(f"documents[{document_index}] must specify source or source_id")
            source_key = fixture_source_key(source_payloads[0])
        else:
            source_key = source_lookup.get(source_reference)
            if source_key is None:
                raise ValueError(f"documents[{document_index}] references unknown source: {source_reference}")
        documents_by_source[source_key].append((document_payload, f"documents[{document_index}]"))

    return documents_by_source


def fixture_source_key(source_payload: dict[str, Any]) -> str:
    return str(source_payload.get("id") or source_payload.get("name") or "fixture")


def fixture_source_aliases(source_payload: dict[str, Any]) -> list[str]:
    aliases = []
    for value in (source_payload.get("id"), source_payload.get("name")):
        text = optional_string(value)
        if text and text not in aliases:
            aliases.append(text)
    return aliases or ["fixture"]


def build_fixture_document(
    document_payload: dict[str, Any],
    label: str,
    dataset_path: Path,
    source_payload: dict[str, Any],
) -> dict[str, Any]:
    if "path" in document_payload:
        path = resolve_fixture_path(document_payload["path"], dataset_path, label)
        root_value = document_payload.get("root") or source_payload.get("root") or source_payload.get("location")
        root = resolve_fixture_path(root_value, dataset_path, f"{label}.root") if root_value else path.parent
        uri_root_value = document_payload.get("uri_root") or source_payload.get("uri_root") or source_payload.get("location")
        uri_root = Path(str(uri_root_value)) if uri_root_value else None
        document = document_from_file(path, root, uri_path=uri_root, embed=True)
        if document is None:
            raise ValueError(f"{label} is not a supported fixture document: {path}")
        return document

    for field in ("uri", "title", "content"):
        if field not in document_payload:
            raise ValueError(f"{label} must include {field!r} or use a path-backed document")
    return build_document(
        uri=str(document_payload["uri"]),
        title=str(document_payload["title"]),
        content=str(document_payload["content"]),
    )


def resolve_fixture_path(value: object, dataset_path: Path, label: str) -> Path:
    raw = Path(str(value)).expanduser()
    if raw.is_absolute():
        return raw.resolve()

    dataset_relative = (dataset_path.parent / raw).resolve()
    if dataset_relative.exists():
        return dataset_relative

    repo_relative = (REPO_ROOT / raw).resolve()
    if repo_relative.exists():
        return repo_relative

    raise ValueError(f"{label} does not exist: {value}")


def evaluate_dataset(dataset: dict[str, Any], options: EvalOptions) -> dict[str, Any]:
    case_results = [evaluate_case(case, options) for case in dataset["cases"]]
    evaluated = [case for case in case_results if case["status"] == "evaluated"]
    passed = [case for case in evaluated if case["passed"]]
    reciprocal_ranks = [1 / case["rank"] for case in evaluated if case["rank"] is not None]
    summary = {
        "cases": len(case_results),
        "evaluated": len(evaluated),
        "passed": len(passed),
        "failed": len(evaluated) - len(passed),
        "skipped": len(case_results) - len(evaluated),
        "pass_rate": round(len(passed) / len(evaluated), 4) if evaluated else 0.0,
        "mrr": round(sum(reciprocal_ranks) / len(evaluated), 4) if evaluated else 0.0,
    }
    return {
        "dataset": {
            "name": dataset.get("name", options.dataset_path.stem),
            "path": str(options.dataset_path),
            "live": options.live,
        },
        "summary": summary,
        "cases": case_results,
    }


def evaluate_case(case: object, options: EvalOptions) -> dict[str, Any]:
    payload = require_mapping(case, "case")
    case_id = str(payload.get("id") or payload.get("query") or "unnamed")
    mode = options.mode or SearchMode(str(payload.get("mode") or SearchMode.HYBRID))
    limit = options.limit or int(payload.get("limit") or 8)
    source_id = optional_string(payload.get("source_id"))
    source_name = optional_string(payload.get("source"))
    query = str(payload.get("query") or "").strip()
    if not query:
        return skipped_case(case_id, "query is empty")

    results = search_module.search_chunks(
        query=query,
        source_id=source_id,
        source_name=source_name,
        limit=limit,
        mode=mode,
    )
    expected = require_mapping(payload.get("expected"), f"{case_id}.expected")
    max_rank = int(payload.get("max_rank") or limit)
    rank = first_matching_rank(results[:max_rank], expected)
    return {
        "id": case_id,
        "status": "evaluated",
        "query": query,
        "source": source_name or source_id or "all",
        "mode": mode.value,
        "limit": limit,
        "max_rank": max_rank,
        "passed": rank is not None,
        "rank": rank,
        "top_results": [
            {
                "rank": index,
                "title": result.title,
                "uri": result.uri,
                "score": result.score,
                "summary": result.summary,
            }
            for index, result in enumerate(results, start=1)
        ],
    }


def first_matching_rank(results: Iterable[Any], expected: dict[str, Any]) -> int | None:
    for rank, result in enumerate(results, start=1):
        if result_matches(result, expected):
            return rank
    return None


def result_matches(result: Any, expected: dict[str, Any]) -> bool:
    haystack = "\n".join(
        [
            result.title,
            result.uri,
            result.content,
            result.summary,
            result.code or "",
            " ".join(result.section_path),
        ]
    ).lower()

    for key in ("uri_contains", "title_contains", "content_contains"):
        values = expected.get(key)
        if values is None:
            continue
        if not any(str(value).lower() in haystack for value in require_list(values, key)):
            return False

    required_terms = expected.get("terms")
    if required_terms is not None:
        if not all(str(value).lower() in haystack for value in require_list(required_terms, "terms")):
            return False

    return True


def skipped_case(case_id: str, reason: str) -> dict[str, Any]:
    return {
        "id": case_id,
        "status": "skipped",
        "passed": False,
        "rank": None,
        "reason": reason,
        "top_results": [],
    }


@contextmanager
def patched_search_database(database: Database):
    original_search_db = search_module.db
    try:
        search_module.db = database
        yield
    finally:
        search_module.db = original_search_db


@contextmanager
def patched_app_database(database: Database):
    original_db = db_package.db
    clear_embedding_config_cache()
    try:
        db_package.db = database
        yield
    finally:
        db_package.db = original_db
        clear_embedding_config_cache()


def require_mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def require_list(value: object, label: str) -> list[object]:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        return [value]
    raise ValueError(f"{label} must be a string or list")


def optional_string(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def print_text_report(report: dict[str, Any]) -> None:
    summary = report["summary"]
    dataset = report["dataset"]
    print(f"Retrieval eval: {dataset['name']}")
    print(
        f"Passed {summary['passed']}/{summary['evaluated']} "
        f"(pass_rate={summary['pass_rate']:.2f}, mrr={summary['mrr']:.2f}, skipped={summary['skipped']})"
    )
    for case in report["cases"]:
        if case["status"] != "evaluated":
            print(f"- SKIP {case['id']}: {case.get('reason', 'skipped')}")
            continue
        marker = "PASS" if case["passed"] else "FAIL"
        rank = case["rank"] if case["rank"] is not None else "-"
        top = case["top_results"][0]["uri"] if case["top_results"] else "no results"
        print(f"- {marker} {case['id']} rank={rank} top={top}")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run retrieval quality evals against Ingestor search.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET, help="Path to a retrieval eval dataset JSON file.")
    parser.add_argument("--live", action="store_true", help="Run cases against the configured database instead of fixture docs.")
    parser.add_argument("--mode", choices=[mode.value for mode in SearchMode], help="Override retrieval mode for all cases.")
    parser.add_argument("--limit", type=int, help="Override result limit for all cases.")
    parser.add_argument("--output", choices=["text", "json"], default="text", help="Report format.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        report = run_retrieval_eval(
            EvalOptions(
                dataset_path=args.dataset,
                live=args.live,
                mode=SearchMode(args.mode) if args.mode else None,
                limit=args.limit,
            )
        )
    except Exception as error:
        print(str(error), file=sys.stderr)
        return 2

    if args.output == "json":
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print_text_report(report)
    return 0 if report["summary"]["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
