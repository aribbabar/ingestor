from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from enum import StrEnum
from typing import Annotated, Any, Callable

import typer

from app.domain.models import SearchMode

DEFAULT_BASE_URL = "http://127.0.0.1:8765"
FINAL_JOB_STATUSES = {"succeeded", "completed", "failed"}


class TextOutputFormat(StrEnum):
    TEXT = "text"
    JSON = "json"


class CrawlScope(StrEnum):
    SUBPAGES = "subpages"
    HOSTNAME = "hostname"
    DOMAIN = "domain"


app = typer.Typer(help="Call a running Ingestor backend API.")


@app.callback()
def configure(
    ctx: typer.Context,
    api_url: Annotated[
        str,
        typer.Option(
            envvar="INGESTOR_API_URL",
            help="Base URL for the running Ingestor API.",
        ),
    ] = os.environ.get("INGESTOR_API_URL", DEFAULT_BASE_URL),
) -> None:
    ctx.obj = {"base_url": api_url.rstrip("/")}


def base_url_from(ctx: typer.Context) -> str:
    return str(ctx.obj["base_url"])


@app.command()
def health(ctx: typer.Context) -> None:
    """Check API health."""
    run_api_command(lambda base_url: print_json(request(base_url, "/api/health")), base_url_from(ctx))


@app.command("list")
def list_sources(
    ctx: typer.Context,
    output: Annotated[TextOutputFormat, typer.Option(help="Output format.")] = TextOutputFormat.TEXT,
) -> None:
    """List indexed sources."""
    run_api_command(lambda base_url: print_list(request(base_url, "/api/sources"), output.value), base_url_from(ctx))


@app.command()
def search(
    ctx: typer.Context,
    source: Annotated[str, typer.Argument(help="Source id/name, or 'all'.")],
    query: Annotated[str, typer.Argument(help="Search query.")],
    limit: Annotated[int, typer.Option(help="Maximum number of results.")] = 8,
    mode: Annotated[SearchMode | None, typer.Option(help="Retrieval mode.")] = None,
    output: Annotated[TextOutputFormat, typer.Option(help="Output format.")] = TextOutputFormat.TEXT,
) -> None:
    """Search through the running API."""

    def command(base_url: str) -> None:
        payload = request(
            base_url,
            "/api/sources/search",
            method="POST",
            body={
                "source": None if source == "all" else source,
                "query": query,
                "limit": limit,
                "mode": mode.value if mode else None,
            },
        )
        print_search(payload, output.value)

    run_api_command(command, base_url_from(ctx))


@app.command()
def index_local(
    ctx: typer.Context,
    paths: Annotated[list[str], typer.Argument(help="Local documentation files or folders to index.")],
    name: Annotated[str, typer.Option(help="Source name to register.")],
    version: Annotated[str, typer.Option(help="Source version label.")] = "latest",
    wait: Annotated[bool, typer.Option(help="Wait for indexing to finish.")] = False,
) -> None:
    """Register and index local documentation through the API."""

    def command(base_url: str) -> None:
        created = request(
            base_url,
            "/api/sources/local-folder",
            method="POST",
            body={"paths": paths, "name": name, "version": version},
        )
        job = request(base_url, f"/api/sources/{created['source']['id']}/index", method="POST")
        print_job(base_url, job, wait)

    run_api_command(command, base_url_from(ctx))


@app.command()
def index_web(
    ctx: typer.Context,
    url: Annotated[str, typer.Argument(help="Documentation URL to crawl.")],
    name: Annotated[str, typer.Option(help="Source name to register.")],
    version: Annotated[str, typer.Option(help="Source version label.")] = "latest",
    max_depth: Annotated[int, typer.Option(help="Maximum crawl depth.")] = 2,
    max_pages: Annotated[int, typer.Option(help="Maximum pages to crawl.")] = 100,
    scope: Annotated[CrawlScope, typer.Option(help="Limit crawl to subpages, host, or domain.")] = CrawlScope.HOSTNAME,
    include_pattern: Annotated[
        list[str] | None, typer.Option(help="URL pattern to include. Can be passed multiple times.")
    ] = None,
    exclude_pattern: Annotated[
        list[str] | None, typer.Option(help="URL pattern to exclude. Can be passed multiple times.")
    ] = None,
    wait: Annotated[bool, typer.Option(help="Wait for indexing to finish.")] = False,
) -> None:
    """Register and index web documentation through the API."""

    def command(base_url: str) -> None:
        created = request(
            base_url,
            "/api/sources/web",
            method="POST",
            body={
                "url": url,
                "name": name,
                "version": version,
                "max_depth": max_depth,
                "max_pages": max_pages,
                "scope": scope.value,
                "include_patterns": include_pattern or [],
                "exclude_patterns": exclude_pattern or [],
            },
        )
        job = request(base_url, f"/api/sources/{created['source']['id']}/index", method="POST")
        print_job(base_url, job, wait)

    run_api_command(command, base_url_from(ctx))


@app.command()
def reindex(
    ctx: typer.Context,
    source_id: Annotated[str, typer.Argument(help="Source id to reindex.")],
    wait: Annotated[bool, typer.Option(help="Wait for indexing to finish.")] = False,
) -> None:
    """Reindex an existing source."""

    def command(base_url: str) -> None:
        job = request(base_url, f"/api/sources/{source_id}/index", method="POST")
        print_job(base_url, job, wait)

    run_api_command(command, base_url_from(ctx))


@app.command()
def delete(
    ctx: typer.Context,
    source_id: Annotated[str, typer.Argument(help="Source id to delete.")],
) -> None:
    """Delete a source."""
    run_api_command(
        lambda base_url: print_json(request(base_url, f"/api/sources/{source_id}", method="DELETE")),
        base_url_from(ctx),
    )


def run_api_command(command: Callable[[str], None], base_url: str) -> None:
    try:
        command(base_url)
    except RuntimeError as error:
        print(error, file=sys.stderr)
        raise typer.Exit(code=1) from error


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


def main() -> None:
    app()


if __name__ == "__main__":
    main()

