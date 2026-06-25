from __future__ import annotations

from typing import Annotated

import typer
import uvicorn

from app.main import app


cli = typer.Typer(help="Run the packaged Ingestor backend server.")


@cli.callback(invoke_without_command=True)
def serve(
    host: Annotated[str, typer.Option(help="Host interface to bind.")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="Port to bind.")] = 8765,
) -> None:
    uvicorn.run(app, host=host, port=port)


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
