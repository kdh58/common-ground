import httpx
import pytest

from app import main, themes
from tests.test_themes import client, login, mock_ollama
from tests.form_helpers import post, generated_notes


@pytest.mark.parametrize('inventory,error,unavailable', [
    (['qwen3:8b'], None, False),
    ([], None, True),
    (None, httpx.ConnectError('private address'), True),
    (None, httpx.ConnectTimeout('private address'), True),
    (None, httpx.ReadTimeout('private address'), True),
])
def test_readiness_is_bounded_cached_and_never_generates(monkeypatch, inventory, error, unavailable):
    calls = []
    def get(client, url, **kwargs):
        calls.append(url)
        assert client.timeout.connect == 1
        assert client.timeout.read == 3
        if error:
            raise error
        return httpx.Response(200, json={'models': [{'name': n} for n in inventory]},
                              request=httpx.Request('GET', url))
    def forbidden(*args, **kwargs):
        pytest.fail('Readiness must never generate text')
    monkeypatch.setattr(httpx.Client, 'get', get)
    monkeypatch.setattr(httpx.Client, 'post', forbidden)
    for _ in range(2):
        if unavailable:
            with pytest.raises(themes.OllamaUnavailable):
                themes.require_ollama_ready(main.OLLAMA_BASE_URL, main.OLLAMA_MODEL)
        else:
            themes.require_ollama_ready(main.OLLAMA_BASE_URL, main.OLLAMA_MODEL)
    assert len(calls) == 1


def test_readiness_recovers_after_cache_expiry(monkeypatch):
    now = [100]
    inventory = []
    monkeypatch.setattr(themes.time, 'monotonic', lambda: now[0])
    monkeypatch.setattr(httpx.Client, 'get', lambda self, url: httpx.Response(
        200, json={'models': inventory}, request=httpx.Request('GET', url)))
    with pytest.raises(themes.OllamaUnavailable):
        themes.require_ollama_ready(main.OLLAMA_BASE_URL, main.OLLAMA_MODEL)
    inventory.append({'name': main.OLLAMA_MODEL})
    now[0] += 6
    themes.require_ollama_ready(main.OLLAMA_BASE_URL, main.OLLAMA_MODEL)


@pytest.mark.parametrize('error,status,kind', [
    (httpx.ConnectError('private'), 200, 'standby'),
    (httpx.ConnectTimeout('private'), 200, 'standby'),
    (httpx.ReadTimeout('private'), 200, 'timeout'),
    (httpx.WriteTimeout('private'), 200, 'timeout'),
    (None, 404, 'standby'),
    (None, 500, 'processing'),
    (None, 200, 'processing'),
])
def test_analysis_error_categories(monkeypatch, error, status, kind):
    mock_ollama(monkeypatch, {}, error, status)
    with pytest.raises(themes.ThemeError) as caught:
        themes.suggest_themes([{'id': 1, 'question': 'Access?'}], main.OLLAMA_BASE_URL, main.OLLAMA_MODEL)
    assert caught.value.kind == kind


@pytest.mark.parametrize('exception,heading', [
    (themes.OllamaUnavailable('PRIVATE'), 'AI assistance is currently on standby'),
    (themes.AnalysisTimeout('PRIVATE'), "AI analysis couldn't be completed"),
    (themes.ThemeError('PRIVATE'), "AI analysis couldn't be completed"),
])
def test_error_page_and_retry(client, monkeypatch, exception, heading):
    login(client)
    post(client, '/gatherings/1/questions', data={'question': 'Access?'})
    def fail(*args):
        raise exception
    monkeypatch.setattr(main, 'suggest_themes', fail)
    response = post(client, '/host/gatherings/1/themes')
    assert heading in response.text
    assert '>Retry</button>' in response.text
    assert 'PRIVATE' not in response.text
    assert 'data-ai-loading role="status" aria-live="polite" hidden' in response.text
    assert 'Ollama is analyzing your discussion ideas…' in response.text
    assert 'Identifying common themes and preparing suggestions. This may take a little while.' in response.text
    assert 'class="ai-spinner" aria-hidden="true"' in response.text
    if exception.kind == 'standby':
        assert 'href="tel:+15717584756"' in response.text
        assert '(571) 758-4756' in response.text
        assert 'href="mailto:kevin@itresidentexpert.com"' in response.text
    else:
        assert 'intentionally offline' not in response.text
    monkeypatch.setattr(main, 'suggest_themes', lambda *_: [{
        'title': 'Access', 'description': 'A question asks about access.',
        'question_ids': [1], 'facilitation_notes': generated_notes()}])
    recovered = post(client, '/host/gatherings/1/themes')
    assert 'Suggest Discussion Themes</button>' in recovered.text
    with main.connection() as db:
        assert [r[0] for r in db.execute('SELECT status FROM analysis_runs ORDER BY id')] == ['failed', 'complete']
    assert client.get('/gatherings/1').status_code == 200


def test_custom_contact(client, monkeypatch):
    login(client)
    post(client, '/gatherings/1/questions', data={'question': 'Access?'})
    monkeypatch.setattr(main, 'DEMO_CONTACT_NAME', 'Demo Host')
    monkeypatch.setattr(main, 'DEMO_CONTACT_PHONE', '+12025550123')
    monkeypatch.setattr(main, 'DEMO_CONTACT_EMAIL', 'host@example.org')
    def fail(*_):
        raise themes.OllamaUnavailable('private')
    monkeypatch.setattr(main, 'suggest_themes', fail)
    html = post(client, '/host/gatherings/1/themes').text
    assert 'contact Demo Host.' in html
    assert 'href="tel:+12025550123"' in html
    assert 'href="mailto:host@example.org"' in html


@pytest.mark.parametrize('inventory', [[], None])
def test_unavailable_inventory_stops_generation(client, monkeypatch, inventory):
    login(client)
    post(client, '/gatherings/1/questions', data={'question': 'Access?'})
    original_get = httpx.Client.get
    def get(self, url, **kwargs):
        if str(url).endswith('/api/tags'):
            if inventory is None:
                raise httpx.ConnectError('PRIVATE infrastructure')
            return httpx.Response(200, json={'models': inventory}, request=httpx.Request('GET', url))
        return original_get(self, url, **kwargs)
    original_post = httpx.Client.post
    def no_inference(self, url, **kwargs):
        assert not str(url).endswith('/api/chat')
        return original_post(self, url, **kwargs)
    monkeypatch.setattr(httpx.Client, 'get', get)
    monkeypatch.setattr(httpx.Client, 'post', no_inference)
    html = post(client, '/host/gatherings/1/themes').text
    assert 'AI assistance is currently on standby' in html
    assert 'PRIVATE' not in html
    assert client.get('/gatherings/1').status_code == 200
