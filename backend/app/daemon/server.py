from __future__ import annotations

from typing import Annotated

import typer
import uvicorn

from app.daemon.app import app

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765

cli = typer.Typer(help="Run the Ingestor daemon.")


def serve(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, reload: bool = False) -> None:
    if reload:
        uvicorn.run("app.daemon.app:app", host=host, port=port, reload=True)
        return
    uvicorn.run(app, host=host, port=port)


@cli.callback(invoke_without_command=True)
def run(
    host: Annotated[str, typer.Option(help="Host interface to bind.")] = DEFAULT_HOST,
    port: Annotated[int, typer.Option(help="Port to bind.")] = DEFAULT_PORT,
    reload: Annotated[bool, typer.Option(help="Reload on source changes.")] = False,
) -> None:
    serve(host=host, port=port, reload=reload)


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
