"""Smoke tests for mcp/common/nse_fetch.py — cookie warm-up, retry, circuit breaker.

Offline: httpx.Client.get is monkeypatched, no network. Each test resets the
module's process-global throttle/circuit state first since nse_get() shares
that state across calls by design (one client, one rate limit, per process).
"""

import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "mcp" / "common"))

import nse_fetch  # noqa: E402


@pytest.fixture(autouse=True)
def reset_state(tmp_path, monkeypatch):
    nse_fetch._last_request_at = 0.0
    nse_fetch._consecutive_failures = 0
    nse_fetch._circuit_open_until = 0.0
    monkeypatch.setattr(nse_fetch, "DOC_CACHE_DIR", tmp_path / "filing_doc_cache")
    yield
    nse_fetch._last_request_at = 0.0
    nse_fetch._consecutive_failures = 0
    nse_fetch._circuit_open_until = 0.0


class FakeResponse:
    def __init__(self, json_data, status_ok=True):
        self._json = json_data
        self._status_ok = status_ok

    def raise_for_status(self):
        if not self._status_ok:
            raise httpx.HTTPStatusError("bad status", request=None, response=None)

    def json(self):
        return self._json


def test_nse_get_success(monkeypatch):
    calls = []

    def fake_get(url, params=None, headers=None):
        calls.append(url)
        return FakeResponse([{"ok": True}])

    client = nse_fetch._get_client()
    monkeypatch.setattr(client, "get", fake_get)
    monkeypatch.setattr(nse_fetch.time, "sleep", lambda s: None)
    result = nse_fetch.nse_get("/api/test", params={"symbol": "X"}, referer="https://www.nseindia.com/x")
    assert result == [{"ok": True}]
    # one warm-up GET (referer) + one API GET
    assert len(calls) == 2


def test_nse_get_retries_once_then_raises(monkeypatch):
    def always_fail(url, params=None, headers=None):
        return FakeResponse(None, status_ok=False)

    client = nse_fetch._get_client()
    monkeypatch.setattr(client, "get", always_fail)
    monkeypatch.setattr(nse_fetch.time, "sleep", lambda s: None)
    with pytest.raises(RuntimeError, match="NSE fetch failed"):
        nse_fetch.nse_get("/api/test")
    assert nse_fetch._consecutive_failures == 1


def test_circuit_opens_after_max_failures(monkeypatch):
    def always_fail(url, params=None, headers=None):
        return FakeResponse(None, status_ok=False)

    client = nse_fetch._get_client()
    monkeypatch.setattr(client, "get", always_fail)
    monkeypatch.setattr(nse_fetch.time, "sleep", lambda s: None)

    for _ in range(nse_fetch.MAX_CONSECUTIVE_FAILURES):
        with pytest.raises(RuntimeError):
            nse_fetch.nse_get("/api/test")

    with pytest.raises(nse_fetch.NSECircuitOpenError):
        nse_fetch.nse_get("/api/test")


def test_success_resets_failure_count(monkeypatch):
    client = nse_fetch._get_client()
    monkeypatch.setattr(nse_fetch.time, "sleep", lambda s: None)

    monkeypatch.setattr(client, "get", lambda url, params=None, headers=None: FakeResponse(None, status_ok=False))
    with pytest.raises(RuntimeError):
        nse_fetch.nse_get("/api/test")
    assert nse_fetch._consecutive_failures == 1

    monkeypatch.setattr(client, "get", lambda url, params=None, headers=None: FakeResponse({"ok": True}))
    nse_fetch.nse_get("/api/test")
    assert nse_fetch._consecutive_failures == 0


class FakeBinaryResponse:
    def __init__(self, content: bytes, status_ok: bool = True):
        self.content = content
        self._status_ok = status_ok

    def raise_for_status(self):
        if not self._status_ok:
            raise httpx.HTTPStatusError("bad status", request=None, response=None)


def test_nse_get_binary_rejects_non_nse_host():
    with pytest.raises(nse_fetch.NSEUntrustedHostError):
        nse_fetch.nse_get_binary("https://evil.example.com/steal.pdf")


def test_nse_get_binary_accepts_nse_archive_subdomain(monkeypatch):
    calls = []

    def fake_get(url, headers=None):
        calls.append(url)
        return FakeBinaryResponse(b"%PDF-fake-content")

    client = nse_fetch._get_client()
    monkeypatch.setattr(client, "get", fake_get)
    monkeypatch.setattr(nse_fetch.time, "sleep", lambda s: None)
    content = nse_fetch.nse_get_binary("https://nsearchives.nseindia.com/corporate/FOO.pdf")
    assert content == b"%PDF-fake-content"
    assert calls == ["https://nsearchives.nseindia.com/corporate/FOO.pdf"]


def test_nse_get_binary_caches_byte_exact_and_skips_refetch(monkeypatch):
    calls = []

    def fake_get(url, headers=None):
        calls.append(url)
        return FakeBinaryResponse(b"%PDF-fake-content")

    client = nse_fetch._get_client()
    monkeypatch.setattr(client, "get", fake_get)
    monkeypatch.setattr(nse_fetch.time, "sleep", lambda s: None)
    url = "https://nsearchives.nseindia.com/corporate/FOO.pdf"
    first = nse_fetch.nse_get_binary(url)
    second = nse_fetch.nse_get_binary(url)
    assert first == second == b"%PDF-fake-content"
    assert len(calls) == 1  # second call served from cache, no re-fetch


def test_nse_get_binary_retries_once_then_raises(monkeypatch):
    def always_fail(url, headers=None):
        return FakeBinaryResponse(b"", status_ok=False)

    client = nse_fetch._get_client()
    monkeypatch.setattr(client, "get", always_fail)
    monkeypatch.setattr(nse_fetch.time, "sleep", lambda s: None)
    with pytest.raises(RuntimeError, match="NSE document fetch failed"):
        nse_fetch.nse_get_binary("https://nsearchives.nseindia.com/corporate/FOO.pdf")
    assert nse_fetch._consecutive_failures == 1
