from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

import httpx
import pytest

from conftest import json_response, make_client
from mtg_toolkits import http
from mtg_toolkits.http import ApiError
from mtg_toolkits.scryfall import ScryfallClient

OK = {"object": "list", "data": []}


@pytest.fixture
def sleeps(monkeypatch):
    slept = []
    monkeypatch.setattr(http.time, "sleep", slept.append)
    return slept


def run(responses):
    """Call an endpoint against a scripted list of responses (or exceptions to raise)."""
    calls = []

    def handler(request):
        calls.append(request)
        item = responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    with make_client(ScryfallClient, handler, slow_interval=0) as sf:
        return sf.sets(), len(calls)


def test_retry_after_seconds_may_be_fractional(sleeps):
    run([httpx.Response(503, headers={"Retry-After": "1.5"}), json_response(OK)])
    assert sleeps == [1.5]


def test_retry_after_http_date(sleeps):
    soon = format_datetime(datetime.now(timezone.utc) + timedelta(seconds=10), usegmt=True)
    past = format_datetime(datetime.now(timezone.utc) - timedelta(days=1), usegmt=True)
    run([httpx.Response(429, headers={"Retry-After": soon}), httpx.Response(429, headers={"Retry-After": past}),
         json_response(OK)])
    assert 8 <= sleeps[0] <= 10 and sleeps[1] == 0


def test_retry_after_is_capped_and_garbage_falls_back(sleeps):
    run([httpx.Response(429, headers={"Retry-After": "99999"}), httpx.Response(429, headers={"Retry-After": "soon"}),
         httpx.Response(503, headers={"Retry-After": "-5"}), json_response(OK)])
    assert sleeps == [http.BaseClient.max_retry_wait, http.BaseClient.rate_limit_backoff, 0] and sleeps[0] == 120


def test_transport_errors_are_retried(sleeps):
    data, calls = run([httpx.ConnectTimeout("t"), httpx.ReadError("r"), json_response(OK)])
    assert (data, calls, sleeps) == ([], 3, [1, 2])


def test_transport_error_that_persists_raises_api_error(sleeps):
    retries = http.BaseClient.max_retries
    with pytest.raises(ApiError, match="ConnectError") as exc:
        run([httpx.ConnectError("refused")] * (retries + 1))
    assert exc.value.status_code == 0 and isinstance(exc.value.__cause__, httpx.ConnectError)
    assert len(sleeps) == retries
