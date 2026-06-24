from __future__ import annotations

import argparse

import uvicorn

from app.main import app


def main() -> int:
    parser = argparse.ArgumentParser(prog="ingestor-backend")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    uvicorn.run(app, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
