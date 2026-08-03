"""Smoke tests for the india_news MCP server.

Offline: news_fetch.news_search is monkeypatched so these never touch the
network. `server` is loaded via importlib under a unique module name, same
fix as test_india_filings.py (every mcp/<name>/ dir has its own server.py).
"""

import importlib.util
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "mcp" / "common"))

import news_fetch  # noqa: E402


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


server = _load("india_news_server", Path(__file__).parent.parent / "mcp" / "india_news" / "server.py")


def test_get_news_shape(monkeypatch):
    calls = {}

    def fake_search(query, limit=10):
        calls["query"] = query
        calls["limit"] = limit
        return [{"title": "Cupid falls 11%", "link": "https://example.com/a", "published": "Wed, 08 Jul 2026 16:08:49 GMT", "publisher": "tennews.in"}]

    monkeypatch.setattr(news_fetch, "news_search", fake_search)
    out = server.get_news("Cupid Limited", limit=5)
    assert out["source"] == "Google News RSS"
    assert calls["query"] == "Cupid Limited"
    assert calls["limit"] == 5
    assert out["data"][0]["title"] == "Cupid falls 11%"


def test_get_news_surfaces_failure_honestly(monkeypatch):
    def fake_search(query, limit=10):
        raise RuntimeError("News search failed for query 'X': timeout")

    monkeypatch.setattr(news_fetch, "news_search", fake_search)
    out = server.get_news("X")
    assert "error" in out["data"]
    assert "timeout" in out["data"]["error"]


def test_get_news_circuit_open_also_surfaces_as_data_error(monkeypatch):
    def fake_search(query, limit=10):
        raise news_fetch.NewsCircuitOpenError("circuit open")

    monkeypatch.setattr(news_fetch, "news_search", fake_search)
    out = server.get_news("X")
    assert "circuit open" in out["data"]["error"]


@pytest.mark.network
def test_live_news_reliance():
    out = server.get_news("Reliance Industries", limit=5)
    assert len(out["data"]) > 0
    assert out["data"][0]["title"]
    assert out["data"][0]["link"].startswith("https://")
