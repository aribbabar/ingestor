from __future__ import annotations

import json
from typing import Any


def print_json(payload: Any) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def print_list(payload: dict[str, Any], output: str) -> None:
    if output == "json":
        print_json(payload)
        return

    sources = payload.get("sources", [])
    if not sources:
        print("No indexed sources.")
        return

    for source in sources:
        print(f"{source['name']} ({source['id']})")
        print(f"  {source['kind']} {source['status']} docs={source['document_count']} chunks={source['chunk_count']}")
        print(f"  {source['location']}")


def print_search(payload: dict[str, Any], output: str) -> None:
    if output == "json":
        print_json(payload)
        return

    results = payload.get("results", [])
    if not results:
        print("No results.")
        return

    for index, result in enumerate(results, start=1):
        summary = normalize_text(result.get("summary") or result.get("content") or "")[:700]
        print(f"### {index}. {result.get('title') or 'Untitled'}")
        print(f"Source: {result.get('uri') or result.get('source_name') or result.get('source_id')}")
        print(f"Score: {float(result.get('score') or 0):.3f}")
        if summary:
            print()
            print(summary)
        if result.get("code"):
            print()
            print("```")
            print(str(result["code"]).strip())
            print("```")
        if index < len(results):
            print()
            print("---")
            print()


def normalize_text(value: Any) -> str:
    return " ".join(str(value or "").split())
