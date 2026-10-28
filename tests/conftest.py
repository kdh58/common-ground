"""Keep model readiness checks local and deterministic in inference tests."""
import httpx
import pytest

from app import main, themes


@pytest.fixture(autouse=True)
def ollama_model_inventory(monkeypatch):
    themes._readiness_cache.clear()
    original = httpx.Client.get

    def get(client, url, **kwargs):
        if str(url) == main.OLLAMA_BASE_URL.rstrip('/') + '/api/tags':
            return httpx.Response(200, json={'models': [{'name': main.OLLAMA_MODEL}]},
                                  request=httpx.Request('GET', url))
        return original(client, url, **kwargs)

    monkeypatch.setattr(httpx.Client, 'get', get)
    yield
    themes._readiness_cache.clear()
