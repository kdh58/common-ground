"""Receipt recovery is read-only, scoped, and never repeats inference."""
import re
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from fastapi.testclient import TestClient

from app import main
from app.themes import ThemeError
from tests.form_helpers import post
from tests.test_analysis_runs import setup_analysis, runs, run_act, Disclosures
from tests.test_theme_workflow import client, key, login, rows
from tests.test_activity import events


GENERATE = '/host/gatherings/1/themes'
STATUS = GENERATE + '/status'


def form_key(html):
    form = re.search(r'<form[^>]*data-ai-analysis[\s\S]*?</form>', html)[0]
    return re.search(r'name="request_key" value="([^"]+)"', form)[1]


def snapshot():
    with main.connection() as db:
        tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        return {t: [tuple(r) for r in db.execute(f'SELECT * FROM "{t}"')] for t in tables}


def test_completed_replay_and_lost_response_recovery(client, monkeypatch):
    calls = setup_analysis(client, monkeypatch)
    original = key(client, 'generate')
    # The browser loses this response after the transaction has committed.
    committed = post(client, GENERATE, data={'request_key': original}, follow_redirects=False)
    assert committed.status_code == 303
    assert committed.headers['location'].endswith('analysis=1#analysis-1')
    before = snapshot()
    for endpoint in (STATUS, GENERATE, STATUS):
        recovered = post(client, endpoint, data={'request_key': original})
        assert recovered.status_code == 200
        assert 'analysis=1' in str(recovered.url)
        assert Disclosures(recovered.text).details['analysis-1']
        assert 'Analysis #1 is complete' in recovered.text
        assert recovered.headers['cache-control'] == 'no-store'
        assert snapshot() == before
    assert calls == [1] and len(runs()) == 1


def test_recovery_after_redirect_get_failure(client, monkeypatch):
    calls = setup_analysis(client, monkeypatch)
    original = key(client, 'generate')
    get_page = main.host_gathering_page
    fail_get = True

    def page(*args, **kwargs):
        if args[1].method == 'GET' and fail_get:
            raise main.HTTPException(503, 'Temporary workspace outage')
        return get_page(*args, **kwargs)

    monkeypatch.setattr(main, 'host_gathering_page', page)
    failed = post(client, GENERATE, data={'request_key': original})
    assert failed.status_code == 503
    assert runs()[0]['status'] == 'complete'
    fail_get = False
    recovered = post(client, STATUS, data={'request_key': original})
    assert 'Analysis #1 is complete' in recovered.text
    assert calls == [1] and len(rows()) == 1


def test_pending_concurrent_replay_and_status_refresh(client, monkeypatch):
    calls = setup_analysis(client, monkeypatch)
    suggest = main.suggest_themes
    started, finish = Event(), Event()

    def slow(*args):
        started.set()
        assert finish.wait(10)
        return suggest(*args)

    monkeypatch.setattr(main, 'suggest_themes', slow)
    original = key(client, 'generate')
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(post, client, GENERATE, data={'request_key': original})
        try:
            assert started.wait(5)
            before = snapshot()
            for endpoint in (GENERATE, STATUS, STATUS):
                response = post(client, endpoint, data={'request_key': original})
                assert response.status_code == 200
                assert 'in progress or may have been interrupted' in response.text
                assert 'Refresh analysis status</button>' in response.text
                assert f'action="{STATUS}?tab=themes"' in response.text
                assert form_key(response.text) == original
                assert snapshot() == before
            assert len(runs()) == 1 and calls == []
        finally:
            finish.set()
        assert future.result(timeout=10).status_code == 200
    recovered = post(client, STATUS, data={'request_key': original})
    assert 'Analysis #1 is complete' in recovered.text
    assert calls == [1] and len(runs()) == 1


def test_confirmed_failure_requires_explicit_fresh_attempt(client, monkeypatch):
    calls = setup_analysis(client, monkeypatch)
    suggest = main.suggest_themes
    original = key(client, 'generate')

    def fail(*args):
        raise ThemeError('Synthetic failure')

    monkeypatch.setattr(main, 'suggest_themes', fail)
    failed = post(client, GENERATE, data={'request_key': original})
    assert 'Analysis #1 failed' in failed.text
    assert form_key(failed.text) != original
    before = snapshot()
    monkeypatch.setattr(main, 'suggest_themes', suggest)
    for endpoint in (STATUS, GENERATE):
        recovered = post(client, endpoint, data={'request_key': original})
        assert 'Analysis #1 failed' in recovered.text
        assert form_key(recovered.text) != original
        assert calls == [] and snapshot() == before
    retried = post(client, GENERATE, data={'request_key': form_key(recovered.text)})
    assert 'Analysis #2 is complete' in retried.text
    assert [r['status'] for r in runs()] == ['failed', 'complete']
    assert calls == [1]


@pytest.mark.parametrize('state', ['complete', 'pending', 'failed'])
def test_deleted_receipt_never_regenerates(client, monkeypatch, state):
    calls = setup_analysis(client, monkeypatch)
    original = key(client, 'generate')
    post(client, GENERATE, data={'request_key': original})
    with main.connection() as db:
        db.execute('UPDATE theme_requests SET status=? WHERE request_key=?', (state, original))
        db.execute('UPDATE analysis_runs SET status=?', (state,))
    run_act(client, 1, 'delete', confirmation='delete')
    before = snapshot()
    for endpoint in (STATUS, GENERATE):
        response = post(client, endpoint, data={'request_key': original})
        assert response.status_code == 200 and 'This analysis was deleted' in response.text
        assert form_key(response.text) != original
        assert snapshot() == before
    assert calls == [1] and runs() == []


def test_other_tab_completion_is_in_recovered_history(client, monkeypatch):
    calls = setup_analysis(client, monkeypatch)
    original = key(client, 'generate')
    other_tab = key(client, 'generate')
    post(client, GENERATE, data={'request_key': original})
    post(client, GENERATE, data={'request_key': other_tab})
    before = snapshot()
    recovered = post(client, STATUS, data={'request_key': original})
    details = Disclosures(recovered.text).details
    assert details['analysis-1'] and not details['analysis-2']
    assert 'id="analysis-2"' in recovered.text
    assert snapshot() == before and calls == [1, 2]


def test_unrecorded_status_does_not_claim_and_original_resubmit_is_safe(client, monkeypatch):
    calls = setup_analysis(client, monkeypatch)
    original = key(client, 'generate')
    before = snapshot()
    response = post(client, STATUS, data={'request_key': original})
    assert 'No analysis receipt is recorded yet' in response.text
    assert 'Submit original request</button>' in response.text
    assert form_key(response.text) == original
    assert snapshot() == before and calls == []
    # An earlier delayed POST arrives before the explicit resubmission.
    post(client, GENERATE, data={'request_key': original})
    post(client, GENERATE, data={'request_key': form_key(response.text)})
    assert calls == [1] and len(runs()) == 1


@pytest.mark.parametrize('endpoint', [GENERATE, STATUS])
def test_recovery_preserves_csrf_scope_and_session_binding(client, monkeypatch, endpoint):
    calls = setup_analysis(client, monkeypatch)
    original = key(client, 'generate')
    post(client, GENERATE, data={'request_key': original})
    before = snapshot()
    assert client.post(endpoint, data={'request_key': original}).status_code == 403
    assert post(client, endpoint, data={'request_key': original + 'tampered'}).status_code == 400
    assert post(client, endpoint, data={'request_key': key(client, 'manual')}).status_code == 400
    # A valid gathering with the wrong scope cannot inspect the receipt.
    post(client, '/host/gatherings', data=dict(title='Other', description='D', gathering_date='2099-12-01',
         start_time='14:00', timezone='America/New_York', location='L', agenda='A'))
    assert post(client, endpoint.replace('/1/', '/2/'), data={'request_key': original}).status_code == 400
    login(client)  # New session/CSRF token invalidates the old signed form.
    assert post(client, endpoint, data={'request_key': original}).status_code == 400
    with TestClient(main.app) as anonymous:
        assert anonymous.post(endpoint, data={'request_key': original}).status_code == 403
    assert calls == [1] and len(runs()) == 1
    after = snapshot()
    for table in before.keys() - {'gatherings', 'agenda_items'}:
        assert after[table] == before[table]


@pytest.mark.parametrize('endpoint', [GENERATE, STATUS])
@pytest.mark.parametrize('state,event', [
    ('complete', 'AI_ANALYSIS_RECOVERED'),
    ('pending', 'AI_ANALYSIS_PENDING_STATUS'),
    ('failed', 'AI_ANALYSIS_FAILED_RECOVERY'),
    ('deleted', 'AI_ANALYSIS_DELETED_RECOVERY'),
])
def test_recovery_activity_classification(client, monkeypatch, events, endpoint, state, event):
    import json

    calls = setup_analysis(client, monkeypatch)
    original = key(client, 'generate')
    if state == 'pending':
        with main.connection() as db:
            main.workflow.start_analysis(db, 1, original, 2)
    else:
        if state == 'failed':
            def fail(*args):
                raise ThemeError('PRIVATE diagnostic')
            monkeypatch.setattr(main, 'suggest_themes', fail)
        post(client, GENERATE, data={'request_key': original})
        if state == 'deleted':
            run_act(client, 1, 'delete', confirmation='delete')
    before_calls = calls[:]
    before = snapshot()
    events.clear()
    response = post(client, endpoint, data={'request_key': original}, follow_redirects=False)
    final = events[-1]
    assert final['event'] == event and final['status'] == 'succeeded'
    assert final['gathering_id'] == 1 and final['receipt_state'] == state
    assert final['correlation_id'] == response.headers['x-correlation-id']
    if state == 'deleted':
        assert 'analysis_run_id' not in final
    else:
        assert final['analysis_run_id'] == 1
    assert len(events) == 2  # One start and one recovery outcome; no model events.
    assert not any(r['event'] == 'AI_ANALYSIS_COMPLETE' for r in events)
    assert original not in json.dumps(events) and 'PRIVATE' not in json.dumps(events)
    assert snapshot() == before and calls == before_calls


def test_unrecorded_and_unauthorized_status_activity(client, monkeypatch, events):
    setup_analysis(client, monkeypatch)
    original = key(client, 'generate')
    events.clear()
    post(client, STATUS, data={'request_key': original})
    assert events[-1]['event'] == 'AI_ANALYSIS_UNRECORDED_STATUS'
    assert events[-1]['receipt_state'] == 'unrecorded'
    assert 'analysis_run_id' not in events[-1]
    events.clear()
    assert client.post(STATUS, data={'request_key': original}).status_code == 403
    assert events[-1]['event'] == 'AI_ANALYSIS_STATUS_REQUEST'
    assert events[-1]['status'] == 'failed'
    assert 'receipt_state' not in events[-1]


@pytest.mark.parametrize('action,data', [
    ('edit', {'revision': 1, 'title': '', 'description': 'Unsaved interpretation'}),
    ('notes', {'notes_revision': 0, 'shared_concerns': 'Unsaved private notes'}),
    ('manual', {'title': '', 'description': 'Unsaved manual theme'}),
])
def test_rejected_edits_are_marked_unsaved_even_when_rendered_as_field_defaults(client, monkeypatch, action, data):
    setup_analysis(client, monkeypatch)
    post(client, GENERATE)
    if action == 'manual':
        endpoint = GENERATE + '/manual'
        data = {**data, 'request_key': key(client, 'manual')}
    else:
        endpoint = GENERATE + '/1/' + action
    response = post(client, endpoint, data=data)
    assert response.status_code in (400, 409, 422)
    editor = re.search(r'<form action="' + re.escape(endpoint) + r'\?tab=themes"[^>]*>', response.text)[0]
    assert 'data-theme-edit' in editor and 'data-unsaved-edit' in editor
