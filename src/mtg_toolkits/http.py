"""Shared HTTP plumbing: polite User-Agent, throttling and retries."""

from __future__ import annotations

import threading
import time
from typing import Any

import httpx

from . import __version__

DEFAULT_USER_AGENT = f"mtg-toolkits/{__version__} (+https://github.com/colombod-personal/mtg-toolkits)"


class ApiError(RuntimeError):
    """Raised when a remote API returns an error response."""

    def __init__(self, status_code: int, message: str, payload: Any = None):
        super().__init__(f"HTTP {status_code}: {message}")
        self.status_code = status_code
        self.payload = payload


class Throttle:
    """Enforces a minimum interval between calls (thread-safe)."""

    def __init__(self, min_interval: float):
        self.min_interval = min_interval
        self._last = 0.0
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:
            delay = self._last + self.min_interval - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            self._last = time.monotonic()


class BaseClient:
    """Small wrapper around :class:`httpx.Client` with throttling and 429/5xx retry."""

    base_url: str = ""
    min_interval: float = 0.1
    max_retries: int = 3
    # Seconds to wait after a 429 without Retry-After (Scryfall locks you out for 30 s).
    rate_limit_backoff: float = 30.0

    def __init__(
        self,
        *,
        user_agent: str = DEFAULT_USER_AGENT,
        client: httpx.Client | None = None,
        min_interval: float | None = None,
        timeout: float = 30.0,
    ):
        self._client = client or httpx.Client(timeout=timeout, follow_redirects=True)
        self._client.headers.update({"User-Agent": user_agent, "Accept": "application/json"})
        self._throttle = Throttle(self.min_interval if min_interval is None else min_interval)

    def close(self) -> None:
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _url(self, path: str) -> str:
        return path if path.startswith("http") else self.base_url.rstrip("/") + "/" + path.lstrip("/")

    def _request(self, method: str, path: str, *, throttle: Throttle | None = None, **kwargs) -> httpx.Response:
        url = self._url(path)
        for attempt in range(self.max_retries + 1):
            (throttle or self._throttle).wait()
            resp = self._client.request(method, url, **kwargs)
            if resp.status_code == 429 or resp.status_code >= 500:
                if attempt < self.max_retries:
                    retry_after = resp.headers.get("Retry-After")
                    if retry_after and retry_after.isdigit():
                        delay = float(retry_after)
                    elif resp.status_code == 429:
                        delay = self.rate_limit_backoff
                    else:
                        delay = 2**attempt
                    time.sleep(delay)
                    continue
            return resp
        return resp  # pragma: no cover
