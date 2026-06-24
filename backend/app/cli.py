from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml

from app.db import db
from app.models import LocalSourceRequest, SearchMode, WebSourceRequest
from app.retrieval import get_default_search_mode
from app.search import SourceNotQueryableError, search_chunks
from app.service import index_source, register_local_source, register_web_source


def main() -> int:
    parser = argparse.ArgumentParser(prog="ingestor")
    subparsers = parser.add_subparsers(dest="command", required=True)

    index_local = subparsers.add_parser("index-local", help="Index local documentation files or folders.")
    index_local.add_argument("paths", nargs="+")
    index_local.add_argument("--name", required=True)
    index_local.add_argument("--version", default="latest")

    index_web = subparsers.add_parser("index-web", help="Crawl and index remote documentation.")
    index_web.add_argument("url")
    index_web.add_argument("--name", required=True)
    index_web.add_argument("--version", default="latest")
    index_web.add_argument("--max-depth", type=int, default=3)
    index_web.add_argument("--max-pages", type=int, default=1000)
    index_web.add_argument("--scope", choices=["subpages", "hostname", "domain"], default="hostname")
    index_web.add_argument("--include-pattern", action="append", default=[])
    index_web.add_argument("--exclude-pattern", action="append", default=[])

    search_parser = subparsers.add_parser("search", help="Search indexed documentation.")
    search_parser.add_argument("source", help="Source id/name, or 'all'.")
    search_parser.add_argument("query")
    search_parser.add_argument("--limit", type=int, default=8)
    search_parser.add_argument("--mode", choices=[mode.value for mode in SearchMode])
    search_parser.add_argument("--output", choices=["json", "yaml", "text"], default="text")

    subparsers.add_parser("list", help="List indexed sources.")

    serve = subparsers.add_parser("serve", help="Run the FastAPI server.")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)

    args = parser.parse_args()

    if args.command == "index-local":
        source = register_local_source(
            LocalSourceRequest(paths=[Path(path) for path in args.paths], name=args.name, version=args.version)
        )
        indexed = index_source(source.id)
        print(f"Indexed {indexed.name}: {indexed.document_count} documents, {indexed.chunk_count} chunks")
        return 0
    if args.command == "index-web":
        source = register_web_source(
            WebSourceRequest(
                url=args.url,
                name=args.name,
                version=args.version,
                max_depth=args.max_depth,
                max_pages=args.max_pages,
                scope=args.scope,
                include_patterns=args.include_pattern,
                exclude_patterns=args.exclude_pattern,
            )
        )
        indexed = index_source(source.id)
        print(f"Indexed {indexed.name}: {indexed.document_count} documents, {indexed.chunk_count} chunks")
        return 0
    if args.command == "search":
        source = None if args.source == "all" else args.source
        mode = SearchMode(args.mode) if args.mode else get_default_search_mode()
        try:
            results = search_chunks(
                query=args.query,
                source_name=source,
                limit=args.limit,
                mode=mode,
            )
        except SourceNotQueryableError as error:
            print(str(error))
            return 2
        print(format_results([result.model_dump() for result in results], args.output))
        return 0
    if args.command == "list":
        print(format_results([source.model_dump(mode="json") for source in db.list_sources()], "yaml"))
        return 0
    if args.command == "serve":
        import uvicorn

        uvicorn.run("app.main:app", host=args.host, port=args.port, reload=True)
        return 0
    return 1


def format_results(payload: Any, output: str) -> str:
    if output == "json":
        return json.dumps(payload, indent=2, ensure_ascii=False)
    if output == "yaml":
        return yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)
    lines: list[str] = []
    for index, item in enumerate(payload, start=1):
        title = item.get("title", "Untitled")
        score = item.get("score", 0)
        uri = item.get("uri", "")
        summary = " ".join(str(item.get("summary") or item.get("content") or "").split())[:700]
        lines.append(f"### {index}. {title}")
        lines.append(f"Source: {uri}")
        lines.append(f"Score: {score:.3f}")
        if summary:
            lines.append("")
            lines.append(summary)
        if item.get("code"):
            lines.append("")
            lines.append("```")
            lines.append(str(item["code"]).strip())
            lines.append("```")
        if index < len(payload):
            lines.append("")
            lines.append("---")
            lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
