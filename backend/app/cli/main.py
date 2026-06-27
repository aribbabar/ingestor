from __future__ import annotations

import os
import sys
import time
from enum import StrEnum
from typing import Annotated, Any, Callable

import typer

from app.cli.client import ApiConnectionError, ApiError, DEFAULT_BASE_URL, ensure_daemon, request
from app.cli.output import print_json, print_list, print_search
from app.domain.models import SearchMode

FINAL_JOB_STATUSES = {"succeeded", "completed", "failed", "cancelled"}


class TextOutputFormat(StrEnum):
    TEXT = "text"
    JSON = "json"


class CrawlScope(StrEnum):
    SUBPAGES = "subpages"
    HOSTNAME = "hostname"
    DOMAIN = "domain"


class CliConfig:
    def __init__(self, base_url: str, start_daemon: bool) -> None:
        self.base_url = base_url
        self.start_daemon = start_daemon


app = typer.Typer(help="Call a running Ingestor daemon API.")


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
    start_daemon: Annotated[
        bool,
        typer.Option(
            envvar="INGESTOR_AUTO_START",
            help="Start the local daemon if the API is not reachable.",
        ),
    ] = False,
) -> None:
    ctx.obj = CliConfig(base_url=api_url.rstrip("/"), start_daemon=start_daemon)


@app.command()
def health(ctx: typer.Context) -> None:
    """Check daemon health."""
    run_api_command(lambda base_url: print_json(request(base_url, "/api/health")), config_from(ctx))


@app.command("list")
def list_sources(
    ctx: typer.Context,
    output: Annotated[TextOutputFormat, typer.Option(help="Output format.")] = TextOutputFormat.TEXT,
) -> None:
    """List indexed sources."""
    run_api_command(lambda base_url: print_list(request(base_url, "/api/sources"), output.value), config_from(ctx))


@app.command()
def search(
    ctx: typer.Context,
    source: Annotated[str, typer.Argument(help="Source id/name, or 'all'.")],
    query: Annotated[str, typer.Argument(help="Search query.")],
    limit: Annotated[int, typer.Option(help="Maximum number of results.")] = 8,
    mode: Annotated[SearchMode | None, typer.Option(help="Retrieval mode.")] = None,
    output: Annotated[TextOutputFormat, typer.Option(help="Output format.")] = TextOutputFormat.TEXT,
) -> None:
    """Search indexed documentation through the daemon."""

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

    run_api_command(command, config_from(ctx))


@app.command()
def index_local(
    ctx: typer.Context,
    paths: Annotated[list[str], typer.Argument(help="Local documentation files or folders to index.")],
    name: Annotated[str, typer.Option(help="Source name to register.")],
    version: Annotated[str, typer.Option(help="Source version label.")] = "latest",
    wait: Annotated[bool, typer.Option(help="Wait for indexing to finish.")] = False,
) -> None:
    """Register and index local documentation through the daemon."""

    def command(base_url: str) -> None:
        created = request(
            base_url,
            "/api/sources/local-folder",
            method="POST",
            body={"paths": paths, "name": name, "version": version},
        )
        job = request(base_url, f"/api/sources/{created['source']['id']}/index", method="POST")
        print_job(base_url, job, wait)

    run_api_command(command, config_from(ctx))


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
    """Register and index web documentation through the daemon."""

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

    run_api_command(command, config_from(ctx))


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

    run_api_command(command, config_from(ctx))


@app.command()
def delete(
    ctx: typer.Context,
    source_id: Annotated[str, typer.Argument(help="Source id to delete.")],
) -> None:
    """Delete a source."""
    run_api_command(
        lambda base_url: print_json(request(base_url, f"/api/sources/{source_id}", method="DELETE")),
        config_from(ctx),
    )


@app.command()
def daemon(
    host: Annotated[str, typer.Option(help="Host interface to bind.")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="Port to bind.")] = 8765,
    reload: Annotated[bool, typer.Option(help="Reload on source changes.")] = False,
) -> None:
    """Run the local Ingestor daemon."""
    from app.daemon.server import serve

    serve(host=host, port=port, reload=reload)


def config_from(ctx: typer.Context) -> CliConfig:
    return ctx.obj


def run_api_command(command: Callable[[str], None], config: CliConfig) -> None:
    try:
        command(config.base_url)
    except ApiConnectionError as error:
        if not config.start_daemon:
            print(f"{error} Start the Ingestor desktop app, run `ingestor daemon`, or pass --start-daemon.", file=sys.stderr)
            raise typer.Exit(code=1) from error
        try:
            ensure_daemon(config.base_url)
            command(config.base_url)
        except ApiError as retry_error:
            print(str(retry_error), file=sys.stderr)
            raise typer.Exit(code=1) from retry_error
    except ApiError as error:
        print(str(error), file=sys.stderr)
        raise typer.Exit(code=1) from error


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
