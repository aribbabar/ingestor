from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any

import typer
import yaml

from app.db import db
from app.domain.models import LocalSourceRequest, SearchMode, WebSourceRequest
from app.retrieval.search import SourceNotQueryableError, search_chunks
from app.retrieval.settings import get_default_search_mode
from app.sources.service import index_source, register_local_source, register_web_source


class OutputFormat(StrEnum):
    JSON = "json"
    YAML = "yaml"
    TEXT = "text"


class CrawlScope(StrEnum):
    SUBPAGES = "subpages"
    HOSTNAME = "hostname"
    DOMAIN = "domain"


app = typer.Typer(help="Index and search documentation sources.")


@app.command()
def index_local(
    paths: Annotated[list[Path], typer.Argument(help="Local documentation files or folders to index.")],
    name: Annotated[str, typer.Option(help="Source name to register.")],
    version: Annotated[str, typer.Option(help="Source version label.")] = "latest",
) -> None:
    """Index local documentation files or folders."""
    source = register_local_source(LocalSourceRequest(paths=paths, name=name, version=version))
    indexed = index_source(source.id)
    print(f"Indexed {indexed.name}: {indexed.document_count} documents, {indexed.chunk_count} chunks")


@app.command()
def index_web(
    url: Annotated[str, typer.Argument(help="Documentation URL to crawl.")],
    name: Annotated[str, typer.Option(help="Source name to register.")],
    version: Annotated[str, typer.Option(help="Source version label.")] = "latest",
    max_depth: Annotated[int, typer.Option(help="Maximum crawl depth.")] = 3,
    max_pages: Annotated[int, typer.Option(help="Maximum pages to crawl.")] = 1000,
    scope: Annotated[CrawlScope, typer.Option(help="Limit crawl to subpages, host, or domain.")] = CrawlScope.HOSTNAME,
    include_pattern: Annotated[
        list[str] | None, typer.Option(help="URL pattern to include. Can be passed multiple times.")
    ] = None,
    exclude_pattern: Annotated[
        list[str] | None, typer.Option(help="URL pattern to exclude. Can be passed multiple times.")
    ] = None,
) -> None:
    """Crawl and index remote documentation."""
    source = register_web_source(
        WebSourceRequest(
            url=url,
            name=name,
            version=version,
            max_depth=max_depth,
            max_pages=max_pages,
            scope=scope.value,
            include_patterns=include_pattern or [],
            exclude_patterns=exclude_pattern or [],
        )
    )
    indexed = index_source(source.id)
    print(f"Indexed {indexed.name}: {indexed.document_count} documents, {indexed.chunk_count} chunks")


@app.command()
def search(
    source: Annotated[str, typer.Argument(help="Source id/name, or 'all'.")],
    query: Annotated[str, typer.Argument(help="Search query.")],
    limit: Annotated[int, typer.Option(help="Maximum number of results.")] = 8,
    mode: Annotated[SearchMode | None, typer.Option(help="Retrieval mode.")] = None,
    output: Annotated[OutputFormat, typer.Option(help="Output format.")] = OutputFormat.TEXT,
) -> None:
    """Search indexed documentation."""
    source_name = None if source == "all" else source
    search_mode = mode or get_default_search_mode()
    try:
        results = search_chunks(
            query=query,
            source_name=source_name,
            limit=limit,
            mode=search_mode,
        )
    except SourceNotQueryableError as error:
        print(str(error))
        raise typer.Exit(code=2) from error
    print(format_results([result.model_dump() for result in results], output.value))


@app.command("list")
def list_sources() -> None:
    """List indexed sources."""
    print(format_results([source.model_dump(mode="json") for source in db.list_sources()], "yaml"))


@app.command()
def serve(
    host: Annotated[str, typer.Option(help="Host interface to bind.")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="Port to bind.")] = 8765,
) -> None:
    """Run the FastAPI server."""
    import uvicorn

    uvicorn.run("app.main:app", host=host, port=port, reload=True)


def main() -> None:
    app()


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
    main()

