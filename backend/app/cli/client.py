from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

DEFAULT_BASE_URL = "http://127.0.0.1:8765"
DEFAULT_DAEMON_HOST = "127.0.0.1"
DEFAULT_DAEMON_PORT = 8765


class ApiError(RuntimeError):
    pass


class ApiConnectionError(ApiError):
    pass


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
        raise ApiError(f"Ingestor API error {error.code}: {detail}") from error
    except urllib.error.URLError as error:
        raise ApiConnectionError(f"Could not reach Ingestor at {base_url}.") from error


def ensure_daemon(base_url: str, timeout_seconds: float = 15) -> None:
    if api_is_ready(base_url):
        return

    endpoint = daemon_endpoint_from(base_url)
    start_daemon_process(endpoint.host, endpoint.port)
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if api_is_ready(base_url):
            return
        time.sleep(0.25)
    raise ApiConnectionError(f"Started the Ingestor daemon, but it did not become ready at {base_url}.")


def api_is_ready(base_url: str) -> bool:
    try:
        request(base_url, "/api/health")
    except ApiError:
        return False
    return True


class DaemonEndpoint:
    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port


def daemon_endpoint_from(base_url: str) -> DaemonEndpoint:
    parsed = urlparse(base_url)
    return DaemonEndpoint(
        host=parsed.hostname or DEFAULT_DAEMON_HOST,
        port=parsed.port or DEFAULT_DAEMON_PORT,
    )


def start_daemon_process(host: str, port: int) -> None:
    executable = resolve_daemon_executable()
    if executable is not None:
        command = [str(executable), "--host", host, "--port", str(port)]
    else:
        command = [sys.executable, "-m", "app.daemon", "--host", host, "--port", str(port)]

    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=os.name != "nt",
        creationflags=creationflags,
    )


def resolve_daemon_executable() -> Path | None:
    configured = os.environ.get("INGESTOR_DAEMON")
    if configured:
        return Path(configured)

    name = "ingestor-daemon.exe" if os.name == "nt" else "ingestor-daemon"
    candidates = [
        Path(sys.executable).with_name(name),
        Path.cwd() / name,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None
