"""Offline tests for mcp/common/screener_fetch.py.

Rollout plan step 1 (docs/screener-integration-design.md §12): fixture
coverage for `_is_blocked_response()` — it should fire on the synthesized
blocked-response fixture and stay quiet on the three real, live-captured
fixtures (Apollo consolidated, Gillette consolidated with its blank
financial tables, Gillette standalone). Cache-path derivation and the
throttle/retry/circuit-breaker behavior (mirroring test_nse_fetch.py) round
out the module's own contract, independent of any real fixture content.
"""

import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "mcp" / "common"))

import screener_fetch

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def reset_state():
    screener_fetch._last_request_at = 0.0
    screener_fetch._consecutive_failures = 0
    screener_fetch._circuit_open_until = 0.0
    yield
    screener_fetch._last_request_at = 0.0
    screener_fetch._consecutive_failures = 0
    screener_fetch._circuit_open_until = 0.0


class TestIsBlockedResponse:
    def test_blocked_captcha_fixture_is_blocked(self):
        html = (FIXTURES / "screener_blocked_captcha.html").read_text()
        assert screener_fetch._is_blocked_response(200, html) is True

    def test_403_status_is_blocked_regardless_of_body(self):
        assert screener_fetch._is_blocked_response(403, "<html>anything</html>") is True

    def test_429_status_is_blocked_regardless_of_body(self):
        assert screener_fetch._is_blocked_response(429, "<html>anything</html>") is True

    def test_apollo_consolidated_fixture_not_blocked(self):
        html = (FIXTURES / "screener_apollotyre_consolidated.html").read_text()
        assert screener_fetch._is_blocked_response(200, html) is False

    def test_gillette_consolidated_fixture_not_blocked(self):
        # The blank-financial-tables case (§11) — genuinely different from a
        # block, and must not be misreported as one.
        html = (FIXTURES / "screener_gillette_consolidated.html").read_text()
        assert screener_fetch._is_blocked_response(200, html) is False

    def test_gillette_standalone_fixture_not_blocked(self):
        html = (FIXTURES / "screener_gillette_standalone.html").read_text()
        assert screener_fetch._is_blocked_response(200, html) is False


class TestCachePathFor:
    def test_consolidated_path(self):
        p = screener_fetch._cache_path_for("/company/APOLLOTYRE/consolidated/")
        assert p.name == "APOLLOTYRE_consolidated.html"

    def test_standalone_path(self):
        p = screener_fetch._cache_path_for("/company/GILLETTE/")
        assert p.name == "GILLETTE_standalone.html"

    def test_unrecognized_path_raises(self):
        with pytest.raises(ValueError):
            screener_fetch._cache_path_for("/screens/some-screen/")


class FakeResponse:
    def __init__(self, text: str, status_code: int = 200):
        self.text = text
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("bad status", request=None, response=None)


class TestScreenerGet:
    def test_success_writes_cache_and_returns_html(self, monkeypatch, tmp_path):
        monkeypatch.setattr(screener_fetch, "CACHE_DIR", tmp_path)
        client = screener_fetch._get_client()
        monkeypatch.setattr(client, "get", lambda url: FakeResponse("<html>real data</html>"))
        monkeypatch.setattr(screener_fetch.time, "sleep", lambda s: None)

        html = screener_fetch.screener_get("/company/APOLLOTYRE/consolidated/", use_cache=False)
        assert html == "<html>real data</html>"
        assert (tmp_path / "APOLLOTYRE_consolidated.html").read_text() == "<html>real data</html>"

    def test_cache_hit_skips_network(self, monkeypatch, tmp_path):
        monkeypatch.setattr(screener_fetch, "CACHE_DIR", tmp_path)
        cache_path = tmp_path / "APOLLOTYRE_consolidated.html"
        tmp_path.mkdir(parents=True, exist_ok=True)
        cache_path.write_text("<html>cached</html>")

        client = screener_fetch._get_client()

        def fail_if_called(url):
            raise AssertionError("should not hit network on a warm cache")

        monkeypatch.setattr(client, "get", fail_if_called)
        html = screener_fetch.screener_get("/company/APOLLOTYRE/consolidated/", use_cache=True, cache_ttl_hours=24.0)
        assert html == "<html>cached</html>"

    def test_blocked_response_raises_without_retry(self, monkeypatch, tmp_path):
        monkeypatch.setattr(screener_fetch, "CACHE_DIR", tmp_path)
        calls = []
        client = screener_fetch._get_client()

        def fake_get(url):
            calls.append(url)
            return FakeResponse("captcha challenge", status_code=403)

        monkeypatch.setattr(client, "get", fake_get)
        monkeypatch.setattr(screener_fetch.time, "sleep", lambda s: None)

        with pytest.raises(screener_fetch.ScreenerBlockedError):
            screener_fetch.screener_get("/company/APOLLOTYRE/consolidated/", use_cache=False)
        assert len(calls) == 1  # not retried

    def test_other_failure_retries_once_then_raises(self, monkeypatch, tmp_path):
        monkeypatch.setattr(screener_fetch, "CACHE_DIR", tmp_path)
        client = screener_fetch._get_client()
        monkeypatch.setattr(client, "get", lambda url: FakeResponse("", status_code=500))
        monkeypatch.setattr(screener_fetch.time, "sleep", lambda s: None)

        with pytest.raises(RuntimeError, match="Screener fetch failed"):
            screener_fetch.screener_get("/company/APOLLOTYRE/consolidated/", use_cache=False)
        assert screener_fetch._consecutive_failures == 1

    def test_circuit_opens_after_max_failures(self, monkeypatch, tmp_path):
        monkeypatch.setattr(screener_fetch, "CACHE_DIR", tmp_path)
        client = screener_fetch._get_client()
        monkeypatch.setattr(client, "get", lambda url: FakeResponse("", status_code=500))
        monkeypatch.setattr(screener_fetch.time, "sleep", lambda s: None)

        for _ in range(screener_fetch.MAX_CONSECUTIVE_FAILURES):
            with pytest.raises(RuntimeError):
                screener_fetch.screener_get("/company/APOLLOTYRE/consolidated/", use_cache=False)

        with pytest.raises(screener_fetch.ScreenerCircuitOpenError):
            screener_fetch.screener_get("/company/APOLLOTYRE/consolidated/", use_cache=False)
