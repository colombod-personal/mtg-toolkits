"""Shared HTTP plumbing: polite User-Agent, throttling and retries."""

from __future__ import annotations

import math
import threading
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
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


def retry_after_seconds(value: str | None, now: datetime | None = None) -> float | None:
    """Seconds a ``Retry-After`` header asks for: a (possibly fractional) delay or an
    HTTP-date. Never negative; None if absent or unreadable."""
    value = (value or "").strip()
    try:
        seconds = float(value)
    except ValueError:
        try:
            when = parsedate_to_datetime(value)
        except (TypeError, ValueError, IndexError):
            return None
        when = when if when.tzinfo else when.replace(tzinfo=timezone.utc)
        now = now or datetime.now(timezone.utc)
        now = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
        seconds = (when - now).total_seconds()
    return max(0.0, seconds) if math.isfinite(seconds) else None


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
    """Small wrapper around :class:`httpx.Client` with throttling and retries.

    429 and 5xx responses are retried after the server's ``Retry-After`` (capped at
    :attr:`max_retry_wait`), else :attr:`rate_limit_backoff` for 429 and ``2**attempt``
    seconds for 5xx. Network errors (:class:`httpx.TransportError`) are retried the same
    number of times; if the last attempt fails too, :class:`ApiError` (status 0) is raised.
    """

    base_url: str = ""
    min_interval: float = 0.1
    max_retries: int = 3
    # Seconds to wait after a 429 without Retry-After (Scryfall locks you out for 30 s).
    rate_limit_backoff: float = 30.0
    max_retry_wait: float = 120.0  # never sleep longer than this, whatever Retry-After says

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
            try:
                resp = self._client.request(method, url, **kwargs)
            except httpx.TransportError as exc:
                if attempt == self.max_retries:
                    raise ApiError(0, f"{type(exc).__name__}: {exc}") from exc
                time.sleep(min(2**attempt, self.max_retry_wait))
                continue
            if (resp.status_code == 429 or resp.status_code >= 500) and attempt < self.max_retries:
                delay = retry_after_seconds(resp.headers.get("Retry-After"))
                if delay is None:
                    delay = self.rate_limit_backoff if resp.status_code == 429 else 2**attempt
                time.sleep(min(delay, self.max_retry_wait))
                continue
            return resp
        raise AssertionError("unreachable")  # pragma: no cover
