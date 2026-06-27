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
from app.retrieval import search as search_module
from app.retrieval.embeddings import clear_embedding_config_cache, embedding_signature


DEFAULT_DATASET = Path(__file__).resolve().parents[3] / "tests" / "evals" / "retrieval" / "neon_fixture.json"


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
        fixture_db = build_fixture_database(dataset, Path(directory) / "ingestor.sqlite")
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


def build_fixture_database(dataset: dict[str, Any], path: Path) -> Database:
    fixture_db = Database(path)
    source_payload = require_mapping(dataset.get("source"), "source")
    documents = dataset.get("documents")
    if not isinstance(documents, list) or not documents:
        raise ValueError("Fixture eval datasets must include documents unless --live is used")

    built_documents = []
    with patched_app_database(fixture_db):
        source = SourceRecord(
            id=str(source_payload.get("id") or "fixture"),
            kind=SourceKind(str(source_payload.get("kind") or SourceKind.LOCAL)),
            name=str(source_payload.get("name") or "fixture"),
            version=str(source_payload.get("version") or "eval"),
            location=str(source_payload.get("location") or "fixture"),
            metadata={"embedding": embedding_signature()},
        )
        fixture_db.upsert_source(source)
        for index, document in enumerate(documents, start=1):
            document_payload = require_mapping(document, f"documents[{index}]")
            built_documents.append(
                build_document(
                    uri=str(document_payload["uri"]),
                    title=str(document_payload["title"]),
                    content=str(document_payload["content"]),
                )
            )

        fixture_db.replace_source_documents(source, built_documents)
    return fixture_db


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
