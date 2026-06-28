from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterator
from contextlib import contextmanager
from time import perf_counter


class IndexingTimings:
    def __init__(self) -> None:
        self._seconds: dict[str, float] = defaultdict(float)

    @contextmanager
    def phase(self, name: str) -> Iterator[None]:
        started_at = perf_counter()
        try:
            yield
        finally:
            self.add(name, perf_counter() - started_at)

    def add(self, name: str, seconds: float) -> None:
        self._seconds[name] += seconds

    def as_dict(self) -> dict[str, float]:
        return {name: round(seconds, 3) for name, seconds in sorted(self._seconds.items())}
