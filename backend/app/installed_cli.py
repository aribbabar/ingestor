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
FINAL_JOB_STATUSES = {"succeeded", "completed", "failed"}


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    base_url = args.api_url.rstrip("/")

    try:
        args.handler(base_url, args)
    except RuntimeError as error:
        print(error, file=sys.stderr)
        raise SystemExit(1) from error


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ingestor",
        description="Call a running Ingestor desktop API.",
    )
    parser.add_argument(
        "--api-url",
        default=os.environ.get("INGESTOR_API_URL", DEFAULT_BASE_URL),
        help=f"Base URL for the running Ingestor API. Defaults to {DEFAULT_BASE_URL}.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    health = subparsers.add_parser("health", help="Check API health.")
    add_api_url_override(health)
    health.set_defaults(handler=handle_health)

    list_sources = subparsers.add_parser("list", help="List indexed sources.")
    add_api_url_override(list_sources)
    add_output_argument(list_sources)
    list_sources.set_defaults(handler=handle_list)

    search = subparsers.add_parser("search", help="Search indexed sources.")
    add_api_url_override(search)
    search.add_argument("source", help="Source id/name, or 'all'.")
    search.add_argument("query", help="Search query.")
    search.add_argument("--limit", type=int, default=8, help="Maximum number of results.")
    search.add_argument("--mode", choices=["hybrid", "keyword", "vector"], help="Retrieval mode.")
    add_output_argument(search)
    search.set_defaults(handler=handle_search)

    index_local = subparsers.add_parser("index-local", help="Register and index local documentation.")
    add_api_url_override(index_local)
    index_local.add_argument("paths", nargs="+", help="Local documentation files or folders to index.")
    index_local.add_argument("--name", required=True, help="Source name to register.")
    index_local.add_argument("--version", default="latest", help="Source version label.")
    index_local.add_argument("--wait", action="store_true", help="Wait for indexing to finish.")
    index_local.set_defaults(handler=handle_index_local)

    index_web = subparsers.add_parser("index-web", help="Register and index web documentation.")
    add_api_url_override(index_web)
    index_web.add_argument("url", help="Documentation URL to crawl.")
    index_web.add_argument("--name", required=True, help="Source name to register.")
    index_web.add_argument("--version", default="latest", help="Source version label.")
    index_web.add_argument("--max-depth", type=int, default=2, help="Maximum crawl depth.")
    index_web.add_argument("--max-pages", type=int, default=100, help="Maximum pages to crawl.")
    index_web.add_argument(
        "--scope",
        choices=["subpages", "hostname", "domain"],
        default="hostname",
        help="Limit crawl to subpages, host, or domain.",
    )
    index_web.add_argument("--include-pattern", action="append", default=[], help="URL pattern to include.")
    index_web.add_argument("--exclude-pattern", action="append", default=[], help="URL pattern to exclude.")
    index_web.add_argument("--wait", action="store_true", help="Wait for indexing to finish.")
    index_web.set_defaults(handler=handle_index_web)

    reindex = subparsers.add_parser("reindex", help="Reindex an existing source.")
    add_api_url_override(reindex)
    reindex.add_argument("source_id", help="Source id to reindex.")
    reindex.add_argument("--wait", action="store_true", help="Wait for indexing to finish.")
    reindex.set_defaults(handler=handle_reindex)

    delete = subparsers.add_parser("delete", help="Delete a source.")
    add_api_url_override(delete)
    delete.add_argument("source_id", help="Source id to delete.")
    delete.set_defaults(handler=handle_delete)

    return parser


def add_api_url_override(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--api-url", default=argparse.SUPPRESS, help=argparse.SUPPRESS)


def add_output_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--output", choices=["text", "json"], default="text", help="Output format.")


def handle_health(base_url: str, _args: argparse.Namespace) -> None:
    print_json(request(base_url, "/api/health"))


def handle_list(base_url: str, args: argparse.Namespace) -> None:
    print_list(request(base_url, "/api/sources"), args.output)


def handle_search(base_url: str, args: argparse.Namespace) -> None:
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


def handle_index_local(base_url: str, args: argparse.Namespace) -> None:
    created = request(
        base_url,
        "/api/sources/local-folder",
        method="POST",
        body={"paths": args.paths, "name": args.name, "version": args.version},
    )
    job = request(base_url, f"/api/sources/{created['source']['id']}/index", method="POST")
    print_job(base_url, job, args.wait)


def handle_index_web(base_url: str, args: argparse.Namespace) -> None:
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


def handle_reindex(base_url: str, args: argparse.Namespace) -> None:
    job = request(base_url, f"/api/sources/{args.source_id}/index", method="POST")
    print_job(base_url, job, args.wait)


def handle_delete(base_url: str, args: argparse.Namespace) -> None:
    print_json(request(base_url, f"/api/sources/{args.source_id}", method="DELETE"))


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
        logs = job_log_lines(status.get("logs", []))
        for line in logs[last_log_count:]:
            print(line)
        last_log_count = len(logs)
        if status["job"]["status"] in FINAL_JOB_STATUSES:
            print_json(status)
            return
        time.sleep(1)


def job_log_lines(logs: Any) -> list[str]:
    if isinstance(logs, str):
        return logs.splitlines()
    return list(logs)


if __name__ == "__main__":
    main()
