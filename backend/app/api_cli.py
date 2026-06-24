from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any

DEFAULT_BASE_URL = "http://127.0.0.1:8765"


def main() -> int:
    parser = argparse.ArgumentParser(prog="ingestor")
    parser.add_argument("--api-url", default=os.environ.get("INGESTOR_API_URL", DEFAULT_BASE_URL))
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("health")

    list_parser = subparsers.add_parser("list")
    list_parser.add_argument("--output", choices=["text", "json"], default="text")

    search = subparsers.add_parser("search")
    search.add_argument("source")
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=8)
    search.add_argument("--mode", choices=["hybrid", "keyword", "vector"])
    search.add_argument("--output", choices=["text", "json"], default="text")

    index_local = subparsers.add_parser("index-local")
    index_local.add_argument("paths", nargs="+")
    index_local.add_argument("--name", required=True)
    index_local.add_argument("--version", default="latest")
    index_local.add_argument("--wait", action="store_true")

    index_web = subparsers.add_parser("index-web")
    index_web.add_argument("url")
    index_web.add_argument("--name", required=True)
    index_web.add_argument("--version", default="latest")
    index_web.add_argument("--max-depth", type=int, default=2)
    index_web.add_argument("--max-pages", type=int, default=100)
    index_web.add_argument("--scope", choices=["subpages", "hostname", "domain"], default="hostname")
    index_web.add_argument("--include-pattern", action="append", default=[])
    index_web.add_argument("--exclude-pattern", action="append", default=[])
    index_web.add_argument("--wait", action="store_true")

    reindex = subparsers.add_parser("reindex")
    reindex.add_argument("source_id")
    reindex.add_argument("--wait", action="store_true")

    delete = subparsers.add_parser("delete")
    delete.add_argument("source_id")

    args = parser.parse_args()
    base_url = args.api_url.rstrip("/")

    try:
        if args.command == "health":
            print_json(request(base_url, "/api/health"))
        elif args.command == "list":
            print_list(request(base_url, "/api/sources"), args.output)
        elif args.command == "search":
            payload = request(
                base_url,
                "/api/sources/search",
                method="POST",
                body={
                    "source": None if args.source == "all" else args.source,
                    "query": args.query,
                    "limit": args.limit,
                    "mode": args.mode,
                },
            )
            print_search(payload, args.output)
        elif args.command == "index-local":
            created = request(
                base_url,
                "/api/sources/local-folder",
                method="POST",
                body={"paths": args.paths, "name": args.name, "version": args.version},
            )
            job = request(base_url, f"/api/sources/{created['source']['id']}/index", method="POST")
            print_job(base_url, job, args.wait)
        elif args.command == "index-web":
            created = request(
                base_url,
                "/api/sources/web",
                method="POST",
                body={
                    "url": args.url,
                    "name": args.name,
                    "version": args.version,
                    "max_depth": args.max_depth,
                    "max_pages": args.max_pages,
                    "scope": args.scope,
                    "include_patterns": args.include_pattern,
                    "exclude_patterns": args.exclude_pattern,
                },
            )
            job = request(base_url, f"/api/sources/{created['source']['id']}/index", method="POST")
            print_job(base_url, job, args.wait)
        elif args.command == "reindex":
            job = request(base_url, f"/api/sources/{args.source_id}/index", method="POST")
            print_job(base_url, job, args.wait)
        elif args.command == "delete":
            print_json(request(base_url, f"/api/sources/{args.source_id}", method="DELETE"))
        return 0
    except RuntimeError as error:
        print(error, file=sys.stderr)
        return 1


def request(base_url: str, path: str, method: str = "GET", body: dict[str, Any] | None = None) -> Any:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request_object = urllib.request.Request(
        f"{base_url}{path}",
        data=data,
        method=method,
        headers={"content-type": "application/json"} if body is not None else {},
    )
    try:
        with urllib.request.urlopen(request_object, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8")
        try:
            detail = json.loads(detail).get("detail", detail)
        except json.JSONDecodeError:
            pass
        raise RuntimeError(f"Ingestor API error {error.code}: {detail}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"Could not reach Ingestor at {base_url}. Start the Ingestor desktop app and try again.") from error


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


def print_job(base_url: str, payload: dict[str, Any], wait: bool) -> None:
    if not wait:
        print_json(payload)
        return
    last_log_count = 0
    while True:
        status = request(base_url, f"/api/sources/jobs/{payload['job']['id']}")
        logs = status.get("logs", [])
        for line in logs[last_log_count:]:
            print(line)
        last_log_count = len(logs)
        if status["job"]["status"] in {"completed", "failed"}:
            print_json(status)
            return
        time.sleep(1)


if __name__ == "__main__":
    raise SystemExit(main())
