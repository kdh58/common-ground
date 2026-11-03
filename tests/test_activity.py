import json
import logging

import httpx
import pytest

from app import activity, main, themes
from tests.test_themes import client, login, mock_ollama
from tests.form_helpers import post


@pytest.fixture
def events():
    records = []
    class Capture(logging.Handler):
        def emit(self, record):
            records.append(json.loads(record.getMessage()))
    handler = Capture()
    activity.logger.addHandler(handler)
    yield records
    activity.logger.removeHandler(handler)


def test_actions_correlation_and_privacy(client, events):
    login(client)
    response = post(client, '/gatherings/1/questions', data={'question': 'PRIVATE QUESTION'})
    records = [r for r in events if r['event'] == 'QUESTION_SUBMIT']
    assert [r['status'] for r in records] == ['started', 'succeeded']
    assert len({r['correlation_id'] for r in records}) == 1
    assert records[0]['role'] == 'host'
    assert records[0]['gathering_id'] == 1
    assert records[0]['timestamp'].endswith('Z')
    serialized = json.dumps(events)
    assert 'PRIVATE QUESTION' not in serialized
    assert 'test-password' not in serialized
    assert 'csrf' not in serialized


def test_login_failure_with_http_200(client, events):
    post(client, '/host/login', data={'password': 'SECRET'})
    assert events[-1]['event'] == 'HOST_LOGIN'
    assert events[-1]['status'] == 'failed'
    assert 'SECRET' not in json.dumps(events)


@pytest.mark.parametrize('status,error,received', [
    (200, None, True), (500, None, True),
    (200, httpx.ConnectError('PRIVATE'), False),
    (200, httpx.ReadTimeout('PRIVATE'), False),
])
def test_ollama_transport(events, monkeypatch, status, error, received):
    mock_ollama(monkeypatch, {'done': True, 'eval_count': 12, 'prompt_eval_count': 7,
                              'message': {'content': 'PRIVATE'}}, error, status)
    token = activity.context.set({'correlation_id': 'test-correlation', 'gathering_id': 1,
                                  'analysis_run_id': 2, 'role': 'host'})
    try:
        with httpx.Client(timeout=httpx.Timeout(90.0, connect=5.0)) as client:
            try:
                activity.ollama_request(client, 'post', main.OLLAMA_BASE_URL + '/api/chat',
                                        model=main.OLLAMA_MODEL, json={'secret': 'PRIVATE'})
            except httpx.HTTPError:
                pass
    finally:
        activity.context.reset(token)
    assert any(r['event'] == 'OLLAMA_HTTP_RESPONSE' for r in events) == received
    assert events[-1]['status'] == ('succeeded' if received and status == 200 else 'failed')
    assert all(r['correlation_id'] == 'test-correlation' and r['analysis_run_id'] == 2 for r in events)
    assert 'PRIVATE' not in json.dumps(events)
    if status == 200 and received:
        assert events[-1]['eval_count'] == 12


def test_analysis_correlation_and_failure(client, monkeypatch, events):
    login(client)
    post(client, '/gatherings/1/questions', data={'question': 'PRIVATE'})
    original = httpx.Client.send
    def send(self, request, **kwargs):
        if str(request.url).endswith('/api/chat'):
            raise httpx.ConnectError('SECRET')
        return original(self, request, **kwargs)
    monkeypatch.setattr(httpx.Client, 'send', send)
    post(client, '/host/gatherings/1/themes')
    final = events[-1]
    assert final['event'] == 'AI_ANALYSIS_FAILED'
    linked = [r for r in events if r['correlation_id'] == final['correlation_id']]
    assert linked[0]['event'] == 'AI_ANALYSIS_REQUEST'
    assert any(r['event'] == 'OLLAMA_REQUEST_FAILED' for r in linked)
    assert final['analysis_run_id'] > 0


def test_logging_failure_is_nonfatal(client, monkeypatch):
    def broken(*args, **kwargs):
        raise OSError('disk full')
    monkeypatch.setattr(activity.logger, 'info', broken)
    login(client)
    assert post(client, '/gatherings/1/questions', data={'question': 'Still works'}).status_code == 200
    with main.connection() as db:
        assert db.execute('SELECT count(*) FROM questions').fetchone()[0] == 1


def test_file_permissions_rotation_and_json(tmp_path, monkeypatch):
    path = tmp_path / 'logs/activity.jsonl'
    monkeypatch.setenv('ACTIVITY_LOG_PATH', str(path))
    old = activity.logger.handlers[:]
    activity.logger.handlers = []
    try:
        activity.configure()
        handler = activity.logger.handlers[0]
        handler.maxBytes = 220
        for _ in range(8):
            activity.emit('HOST_LOGIN', 'started')
        handler.flush()
        assert path.stat().st_mode & 0o777 == 0o600
        assert path.parent.stat().st_mode & 0o777 == 0o700
        assert list(path.parent.glob('activity.jsonl.*'))
        assert json.loads(path.read_text().splitlines()[0])['event'] == 'HOST_LOGIN'
    finally:
        for handler in activity.logger.handlers:
            handler.close()
        activity.logger.handlers = old


def test_public_action_response_correlation(client, events):
    response = post(client, '/gatherings/1/rsvp', data={'name': 'PRIVATE NAME'}, follow_redirects=False)
    assert response.status_code == 303
    assert events[-1]['correlation_id'] == response.headers['x-correlation-id']
    assert events[-1]['role'] == 'participant'
    assert 'PRIVATE NAME' not in json.dumps(events)


def test_ollama_incomplete_response(events, monkeypatch):
    mock_ollama(monkeypatch, {'done': False, 'message': {'content': 'SECRET'}})
    with httpx.Client(timeout=httpx.Timeout(90.0, connect=5.0)) as client:
        with pytest.raises(ValueError):
            activity.ollama_request(client, 'post', main.OLLAMA_BASE_URL + '/api/chat', model=main.OLLAMA_MODEL)
    assert [r['event'] for r in events] == ['OLLAMA_REQUEST_SUBMITTED', 'OLLAMA_HTTP_RESPONSE', 'OLLAMA_REQUEST_FAILED']


def test_configure_storage_failure_is_nonfatal(monkeypatch):
    old = activity.logger.handlers[:]
    activity.logger.handlers = []
    def broken(*args, **kwargs):
        raise OSError('read only')
    monkeypatch.setattr(activity.os, 'open', broken)
    try:
        activity.configure()
        activity.emit('HOST_LOGIN', 'started')
    finally:
        activity.logger.handlers = old


def test_analysis_success_and_print_click(client, monkeypatch, events):
    from tests.form_helpers import generated_notes
    login(client)
    post(client, '/gatherings/1/questions', data={'question': 'PRIVATE'})
    original = httpx.Client.send
    body = {'done': True, 'eval_count': 10, 'message': {'content': json.dumps({'themes': [
        {'title': 'Access', 'description': 'A question asks about access.', 'question_ids': [1],
         'facilitation_notes': generated_notes()}]})}}
    def send(self, request, **kwargs):
        if str(request.url).endswith('/api/chat'):
            return httpx.Response(200, json=body, request=request)
        return original(self, request, **kwargs)
    monkeypatch.setattr(httpx.Client, 'send', send)
    response = post(client, '/host/gatherings/1/themes', follow_redirects=False)
    assert response.status_code == 303
    final = events[-1]
    assert final['event'] == 'AI_ANALYSIS_COMPLETE'
    model = next(r for r in events if r['event'] == 'OLLAMA_MODEL_RESPONSE')
    assert model['correlation_id'] == final['correlation_id']
    assert model['analysis_run_id'] == final['analysis_run_id']
    url = f"/host/gatherings/1/analyses/{final['analysis_run_id']}/print-click"
    assert post(client, url).status_code == 204
    assert events[-1]['event'] == 'ANALYSIS_PRINT_REQUEST'
    assert events[-1]['status'] == 'succeeded'
    assert client.post(url).status_code == 403
    assert events[-1]['status'] == 'failed'
    assert 'PRIVATE' not in json.dumps(events)
