"""Persistent curation, isolation, request replay and concurrency regressions."""
import json
import re
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import httpx
import pytest
from fastapi.testclient import TestClient

from app import main, theme_workflow
from tests.form_helpers import post


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, 'DB', str(tmp_path / 'workflow.db'))
    monkeypatch.setattr(main, 'ADMIN_PASSWORD', 'workflow-password')
    with TestClient(main.app) as client:
        yield client


def login(client):
    assert post(client, '/host/login', data={'password': 'workflow-password'}).status_code == 200


def key(client, kind='manual', gathering=1):
    page = client.get(f'/host/gatherings/{gathering}').text
    action = f'/host/gatherings/{gathering}/themes' + ('/manual' if kind == 'manual' else '')
    form = re.search(r'<form action="' + re.escape(action) + r'".*?</form>', page, re.S)[0]
    return re.search(r'name="request_key" value="([^\"]+)"', form)[1]


def rows(gathering=1):
    with main.connection() as db:
        return theme_workflow.load_themes(db, gathering)


def create(client, title='Manual topic', description='A curated description', gathering=1, request_key=None):
    return post(client, f'/host/gatherings/{gathering}/themes/manual', data={
        'title': title, 'description': description, 'request_key': request_key or key(client, gathering=gathering)})


def act(client, action, theme=None, gathering=1, **data):
    theme = theme or rows(gathering)[0]
    return post(client, f'/host/gatherings/{gathering}/themes/{theme["id"]}/{action}', data={
        'revision': theme['revision'], **data})


def public(client, gathering=1):
    return client.get(f'/gatherings/{gathering}').text


def test_manual_lifecycle_reapproval_and_preserved_submissions(client):
    post(client, '/gatherings/1/questions', data={'question': 'Anonymous PRIVATE SOURCE'})
    post(client, '/gatherings/1/rsvp', data={'name': 'PRIVATE ATTENDEE'})
    with main.connection() as db:
        questions = [tuple(r) for r in db.execute('SELECT * FROM questions')]
        rsvps = [tuple(r) for r in db.execute('SELECT * FROM rsvps')]
    login(client)
    assert create(client).status_code == 200
    first = rows()[0]
    assert first['status'] == 'draft' and first['origin'] == 'manual'
    assert first['created_at'] == first['updated_at']
    assert 'Manual topic' not in public(client)
    assert act(client, 'publish').status_code == 409
    assert act(client, 'approve').status_code == 200
    assert rows()[0]['status'] == 'approved'
    assert 'Manual topic' not in public(client)
    assert act(client, 'delete', confirmation='delete').status_code == 409
    assert act(client, 'publish').status_code == 200
    page = public(client)
    assert 'Curated discussion topics' in page and 'Manual topic' in page
    assert 'A curated description' in page and 'Created and curated by host' in page
    assert 'PRIVATE' not in page and 'Original question #' not in page and 'revision' not in page
    assert act(client, 'delete', confirmation='delete').status_code == 409
    assert act(client, 'edit', title='Revised topic', description='Revised description').status_code == 200
    revised = rows()[0]
    assert revised['status'] == 'draft'
    assert revised['created_at'] == first['created_at'] and revised['updated_at'] > first['updated_at']
    assert 'Manual topic' not in public(client) and 'Revised topic' not in public(client)
    assert act(client, 'publish').status_code == 409
    assert act(client, 'approve').status_code == 200
    assert act(client, 'publish').status_code == 200
    assert 'Revised topic' in public(client)
    assert act(client, 'unpublish').status_code == 200
    assert rows()[0]['status'] == 'approved'
    assert 'Revised topic' not in public(client)
    # Editing approved text also invalidates approval.
    assert act(client, 'edit', title='Final draft', description='').status_code == 200
    assert rows()[0]['status'] == 'draft'
    with main.connection() as db:
        assert [tuple(r) for r in db.execute('SELECT * FROM questions')] == questions
        assert [tuple(r) for r in db.execute('SELECT * FROM rsvps')] == rsvps


def test_ai_generation_scoped_persistent_append_only(client, monkeypatch):
    login(client)
    post(client, '/gatherings/1/questions', data={'question': 'PRIVATE question'})
    post(client, '/host/gatherings', data=dict(title='Other', description='D', when_text='W', location='L', agenda='A'))
    post(client, '/gatherings/2/questions', data={'question': 'OTHER private question'})
    create(client, title='Keep published')
    act(client, 'approve')
    act(client, 'publish')
    create(client, title='Keep approved')
    act(client, 'approve', rows()[1])
    before = rows()
    seen = []
    def suggest(questions, base, model):
        seen.append(questions)
        return [{'title': 'AI suggestion', 'description': 'Questions raise concerns about access and opportunities for discussion.', 'question_ids': [questions[0]['id']]}]
    monkeypatch.setattr(main, 'suggest_themes', suggest)
    request_key = key(client, 'generate')
    assert post(client, '/host/gatherings/1/themes', data={'request_key': request_key}).status_code == 200
    assert rows()[:2] == before
    ai = rows()[2]
    assert ai['status'] == 'draft' and ai['origin'] == 'ai' and ai['ai_original_title'] == 'AI suggestion'
    assert seen == [[{'id': 1, 'question': 'PRIVATE question'}]]
    assert ai['question_ids'] == [1]
    assert 'AI suggestion' in client.get('/host/gatherings/1').text
    assert 'AI suggestion' not in public(client)
    assert post(client, '/host/gatherings/1/themes', data={'request_key': request_key}).status_code == 409
    assert len(seen) == 1 and len(rows()) == 3
    assert post(client, '/host/gatherings/1/themes', data={'draft_action': 'keep'}).status_code == 200
    assert len(rows()) == 4 and rows()[:2] == before
    assert act(client, 'edit', ai, title='Host interpretation', description='Human correction').status_code == 200
    assert rows()[2]['ai_original_title'] == 'AI suggestion'
    assert rows()[2]['question_ids'] == [1]
    act(client, 'approve', rows()[2])
    act(client, 'publish', rows()[2])
    page = public(client)
    assert 'Host interpretation' in page and 'AI-assisted suggestion, curated by host' in page
    assert 'PRIVATE question' not in page and 'AI suggestion' not in page
    assert 'OTHER private question' not in client.get('/host/gatherings/1').text


@pytest.mark.parametrize('case', ['timeout', 'unavailable', 'truncated', 'malformed', 'invalid-reference', 'unsafe-control'])
def test_ai_failures_save_nothing_preserve_existing(client, monkeypatch, case):
    login(client)
    create(client)
    post(client, '/gatherings/1/questions', data={'question': 'A question'})
    before = rows()
    original = httpx.Client.post
    def ollama(self, url, **kwargs):
        if not str(url).endswith('/api/chat'):
            return original(self, url, **kwargs)
        if case == 'timeout':
            raise httpx.ReadTimeout('PRIVATE error')
        if case == 'unavailable':
            raise httpx.ConnectError('PRIVATE error')
        title = 'Bad\x00control' if case == 'unsafe-control' else 'Topic'
        content = json.dumps({'themes': [{'title': title, 'description': 'Questions raise concerns about access and opportunities for discussion.', 'question_ids': [999 if case == 'invalid-reference' else 1]}]})
        body = {'done': True, 'message': {'content': 'invalid json' if case == 'malformed' else content}}
        if case == 'truncated':
            body['done_reason'] = 'length'
        return httpx.Response(200, json=body, request=httpx.Request('POST', url))
    monkeypatch.setattr(httpx.Client, 'post', ollama)
    response = post(client, '/host/gatherings/1/themes')
    assert response.status_code == 200
    assert 'Ollama' in response.text and ('try again' in response.text or 'Please try again' in response.text)
    assert rows() == before
    assert 'PRIVATE error' not in response.text
    with main.connection() as db:
        assert db.execute('SELECT status FROM theme_requests WHERE kind="generate"').fetchone()[0] == 'failed'
        assert db.execute('SELECT question FROM questions').fetchone()[0] == 'A question'


def test_optimistic_concurrency_and_duplicate_manual(client):
    login(client)
    request_key = key(client)
    assert create(client, request_key=request_key).status_code == 200
    assert create(client, title='Accidental resubmit', request_key=request_key).status_code == 409
    assert len(rows()) == 1
    stale = rows()[0]
    assert act(client, 'edit', stale, title='First edit').status_code == 200
    for action in ('edit', 'approve', 'publish', 'unpublish', 'delete', 'up', 'down'):
        assert act(client, action, stale, title='Stale edit', confirmation='delete').status_code == 409
    assert rows()[0]['title'] == 'First edit'


def test_confirmed_delete_and_no_id_reuse(client):
    login(client)
    create(client)
    theme = rows()[0]
    assert act(client, 'delete').status_code == 400
    assert len(rows()) == 1
    assert act(client, 'delete', confirmation='delete').status_code == 200
    assert rows() == []
    create(client, title='Replacement')
    assert rows()[0]['id'] != theme['id']
    assert act(client, 'delete', theme, confirmation='delete').status_code == 404


def test_keyboard_ordering_and_public_order(client):
    login(client)
    create(client, 'First topic')
    create(client, 'Second topic')
    create(client, 'Third topic')
    assert act(client, 'up').status_code == 409
    assert act(client, 'up', rows()[1]).status_code == 200
    assert [r['title'] for r in rows()] == ['Second topic', 'First topic', 'Third topic']
    assert act(client, 'down', rows()[1]).status_code == 200
    assert [r['title'] for r in rows()] == ['Second topic', 'Third topic', 'First topic']
    for theme in rows():
        act(client, 'approve', theme)
    for theme in rows():
        act(client, 'publish', theme)
    assert act(client, 'up', rows()[2]).status_code == 200
    assert [r['status'] for r in rows()] == ['published'] * 3
    page = public(client)
    assert page.index('Second topic') < page.index('First topic') < page.index('Third topic')
    host = client.get('/host/gatherings/1').text
    assert 'Move up' in host and 'Move down' in host
    assert 'theme-status-published' in host and '>Published</strong>' in host


@pytest.mark.parametrize('action', ['edit', 'approve', 'publish', 'unpublish', 'delete', 'up', 'down'])
def test_authorization_csrf_and_cross_gathering(client, action):
    path = f'/host/gatherings/1/themes/1/{action}'
    assert client.post(path, data={'revision': 1}).status_code == 403
    assert client.post('/host/gatherings/1/themes/manual', data={}).status_code == 403
    login(client)
    create(client)
    assert client.post(path, data={'revision': 1}).status_code == 403
    assert client.post(path, data={'revision': 1, 'csrf_token': 'wrong'}).status_code == 403
    post(client, '/host/gatherings', data=dict(title='Other', description='D', when_text='W', location='L', agenda='A'))
    assert act(client, action, gathering=2, theme=rows()[0], title='Attack', confirmation='delete').status_code == 404
    assert rows()[0]['title'] == 'Manual topic' and len(rows()) == 1
    assert 'Manual topic' not in client.get('/host/gatherings/2').text


@pytest.mark.parametrize('title,description', [(' ', ''), ('x'*121, ''), ('Good', 'x'*2001), ('Null\x00', ''), ('Good', 'Bad\x7f')])
def test_text_validation(client, title, description):
    login(client)
    assert create(client, title, description).status_code == 400
    assert rows() == []
    create(client)
    before = rows()
    assert act(client, 'edit', title=title, description=description).status_code == 400
    assert rows() == before


def test_xss_is_literal_and_private_metadata_not_published(client):
    login(client)
    title = '<script>alert("title")</script>'
    description = '<img src=x onerror=alert(1)>\nSecond line & text'
    create(client, title, description)
    host = client.get('/host/gatherings/1').text
    assert '<script>' not in host and '&lt;script&gt;' in host
    act(client, 'approve')
    act(client, 'publish')
    page = public(client)
    assert '<script>' not in page and '<img src=x' not in page
    assert '&lt;script&gt;' in page and '&lt;img' in page
    assert 'created_at' not in page and 'Original AI suggestion:' not in page
    assert 'request_key' not in page and 'revision' not in page


def test_restart_migrations_and_cancelled_visibility(client):
    login(client)
    create(client)
    act(client, 'approve')
    act(client, 'publish')
    before = rows()
    main.init_db()
    main.init_db()
    assert rows() == before
    # A new app lifespan does not erase saved or published themes.
    with TestClient(main.app) as restarted:
        assert 'Manual topic' in public(restarted)
    post(client, '/host/gatherings/1/status', data={'status': 'cancelled'})
    page = public(client)
    assert 'This gathering is cancelled' in page and 'Manual topic' in page
    assert 'RSVP for gathering' not in page
    assert act(client, 'unpublish').status_code == 200
    assert 'Manual topic' not in public(client)


def test_phase_one_migration_is_additive_and_preserves_all_tables(tmp_path, monkeypatch):
    monkeypatch.setattr(main, 'DB', str(tmp_path / 'phase1.db'))
    initialize = theme_workflow.init_schema
    monkeypatch.setattr(theme_workflow, 'init_schema', lambda db: None)
    main.init_db()
    with main.connection() as db:
        db.execute("INSERT INTO rsvps VALUES(1,1,'Name','Time')")
        db.execute("INSERT INTO questions VALUES(1,1,'Question','Time')")
        db.execute("INSERT INTO gathering_status VALUES(1,1)")
        db.execute("INSERT INTO resources VALUES(1,1,'Link','https://example.org')")
        tables = ['gatherings', 'rsvps', 'questions', 'gathering_status', 'resources', 'agenda_items']
        before = {table: [tuple(r) for r in db.execute(f'SELECT * FROM {table}')] for table in tables}
    monkeypatch.setattr(theme_workflow, 'init_schema', initialize)
    main.init_db()
    main.init_db()
    with main.connection() as db:
        assert {table: [tuple(r) for r in db.execute(f'SELECT * FROM {table}')] for table in tables} == before
        assert db.execute('SELECT count(*) FROM discussion_themes').fetchone()[0] == 0


def test_generation_claim_prevents_concurrent_duplicate(client, monkeypatch):
    login(client)
    post(client, '/gatherings/1/questions', data={'question': 'A question'})
    request_key = key(client, 'generate')
    started, finish = Event(), Event()
    calls = []
    def suggest(*args):
        calls.append(1)
        started.set()
        assert finish.wait(10)
        return [{'title': 'Only once', 'description': 'Questions raise concerns about access and opportunities for discussion.', 'question_ids': [1]}]
    monkeypatch.setattr(main, 'suggest_themes', suggest)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(post, client, '/host/gatherings/1/themes', data={'request_key': request_key})
        try:
            assert started.wait(5)
            assert post(client, '/host/gatherings/1/themes', data={'request_key': request_key}).status_code == 409
            # Other edits remain usable while inference is in progress.
            assert create(client, 'Concurrent manual').status_code == 200
        finally:
            finish.set()
        assert future.result(timeout=10).status_code == 200
    assert calls == [1] and len(rows()) == 2


@pytest.mark.parametrize('endpoint', ['https://external.example', 'https://8.8.8.8', 'http://user:password@localhost:11434', 'ftp://localhost', 'http://localhost:99999'])
def test_external_ai_endpoint_rejected_before_network(monkeypatch, endpoint):
    def forbidden(*args, **kwargs):
        pytest.fail('No network call is allowed for an external endpoint')
    monkeypatch.setattr(httpx.Client, 'post', forbidden)
    with pytest.raises(main.ThemeError, match='local endpoint'):
        main.suggest_themes([{'id': 1, 'question': 'Private'}], endpoint, main.OLLAMA_MODEL)


def test_form_keys_are_signed_scoped_and_csrf_protected(client):
    login(client)
    manual_key = key(client)
    generation_key = key(client, 'generate')
    assert create(client, request_key=generation_key).status_code == 400
    assert create(client, request_key=manual_key + 'tamper').status_code == 400
    assert client.post('/host/gatherings/1/themes/manual', data={'title': 'No CSRF', 'request_key': manual_key}).status_code == 403
    assert post(client, '/host/gatherings/1/themes', data={'request_key': manual_key}).status_code == 400
    post(client, '/host/gatherings', data=dict(title='Other', description='D', when_text='W', location='L', agenda='A'))
    assert create(client, gathering=2, request_key=manual_key).status_code == 400
    assert rows() == [] and rows(2) == []


def test_generation_batch_is_atomic_and_sources_are_scoped(client, monkeypatch):
    login(client)
    post(client, '/gatherings/1/questions', data={'question': 'Here'})
    post(client, '/host/gatherings', data=dict(title='Other', description='D', when_text='W', location='L', agenda='A'))
    post(client, '/gatherings/2/questions', data={'question': 'Elsewhere'})
    create(client)
    before = rows()
    monkeypatch.setattr(main, 'suggest_themes', lambda *args: [
        {'title': 'Valid first', 'description': 'Questions raise concerns about access and opportunities for discussion.', 'question_ids': [1]},
        {'title': 'Invalid second', 'description': 'Questions raise concerns about access and opportunities for discussion.', 'question_ids': [2]},
    ])
    assert post(client, '/host/gatherings/1/themes').status_code == 200
    assert rows() == before
    with main.connection() as db:
        assert db.execute('SELECT count(*) FROM theme_sources').fetchone()[0] == 0


def test_migration_failure_rolls_back_new_tables(tmp_path, monkeypatch):
    monkeypatch.setattr(main, 'DB', str(tmp_path / 'migration.db'))
    initialize = theme_workflow.init_schema
    monkeypatch.setattr(theme_workflow, 'init_schema', lambda db: None)
    main.init_db()
    def failing(db):
        initialize(db)
        raise RuntimeError('Simulated migration failure')
    monkeypatch.setattr(theme_workflow, 'init_schema', failing)
    with pytest.raises(RuntimeError, match='migration failure'):
        main.init_db()
    with main.connection() as db:
        assert db.execute("SELECT name FROM sqlite_master WHERE name='discussion_themes'").fetchone() is None
        assert db.execute('SELECT count(*) FROM gatherings').fetchone()[0] == 1
    monkeypatch.setattr(theme_workflow, 'init_schema', initialize)
    main.init_db()
    with main.connection() as db:
        assert db.execute('SELECT count(*) FROM discussion_themes').fetchone()[0] == 0


def test_backup_contains_saved_workflow(client, tmp_path):
    from pathlib import Path
    from app.database_tools import snapshot, validate
    login(client)
    create(client)
    act(client, 'approve')
    act(client, 'publish')
    before = rows()
    target = tmp_path / 'backup.db'
    snapshot(Path(main.DB).resolve(), target)
    validate(target)
    with sqlite3.connect(target) as db:
        db.row_factory = sqlite3.Row
        assert theme_workflow.load_themes(db, 1) == before
        assert db.execute('SELECT count(*) FROM theme_requests').fetchone()[0] == 1


def test_generated_description_round_trip_and_publication_rules(client, monkeypatch):
    login(client)
    post(client, '/gatherings/1/questions', data={'question': 'Could evening workshops improve access?'})
    post(client, '/gatherings/1/questions', data={'question': 'How would evening hours affect staff workload?'})
    create(client, 'Existing draft', 'Keep draft description')
    create(client, 'Existing published', 'Keep published description')
    act(client, 'approve', rows()[1])
    act(client, 'publish', rows()[1])
    before = rows()
    with main.connection() as db:
        questions_before = [tuple(r) for r in db.execute('SELECT * FROM questions')]
    description = ('Questions explore evening access alongside staffing workload. '
                   'One question includes <script>alert("not executable")</script> as untrusted text.')
    original = httpx.Client.post
    def ollama(self, url, **kwargs):
        if not str(url).endswith('/api/chat'):
            return original(self, url, **kwargs)
        sent = json.loads(kwargs['json']['messages'][1]['content'])['untrusted_questions']
        assert [q['id'] for q in sent] == [1, 2]
        return httpx.Response(200, json={'done': True, 'message': {'content': json.dumps({'themes': [{
            'title': 'Evening access and staffing', 'description': description, 'question_ids': [1, 2],
        }]})}}, request=httpx.Request('POST', url))
    monkeypatch.setattr(httpx.Client, 'post', ollama)
    assert post(client, '/host/gatherings/1/themes').status_code == 200
    assert rows()[:2] == before
    generated = rows()[2]
    assert generated['description'] == description and generated['status'] == 'draft'
    assert generated['question_ids'] == [1, 2]
    assert 'Evening access and staffing' not in public(client)
    host = client.get('/host/gatherings/1').text
    assert 'Questions explore evening access' in host
    assert '&lt;script&gt;' in host and '<script>' not in host
    assert re.search(r'<textarea[^>]*name="description"[^>]*>Questions explore evening access', host)
    with TestClient(main.app) as restarted:
        assert 'Evening access and staffing' not in public(restarted)
    assert rows()[2]['description'] == description
    assert act(client, 'approve', generated).status_code == 200
    assert 'Evening access and staffing' not in public(client)
    assert act(client, 'publish', rows()[2]).status_code == 200
    page = public(client)
    assert 'Questions explore evening access' in page and '&lt;script&gt;' in page and '<script>' not in page
    assert act(client, 'edit', rows()[2], title=generated['title'], description='Host revised context.').status_code == 200
    assert rows()[2]['status'] == 'draft'
    assert 'Questions explore evening access' not in public(client) and 'Host revised context.' not in public(client)
    assert act(client, 'publish', rows()[2]).status_code == 409
    assert rows()[:2] == before
    with main.connection() as db:
        assert [tuple(r) for r in db.execute('SELECT * FROM questions')] == questions_before


@pytest.mark.parametrize('bad_description', [None, '', 'x' * 1001])
def test_invalid_description_batch_preserves_saved_topics(client, monkeypatch, bad_description):
    login(client)
    create(client)
    before = rows()
    post(client, '/gatherings/1/questions', data={'question': 'A question'})
    original = httpx.Client.post
    def ollama(self, url, **kwargs):
        if not str(url).endswith('/api/chat'):
            return original(self, url, **kwargs)
        return httpx.Response(200, json={'done': True, 'message': {'content': json.dumps({'themes': [
            {'title': 'Valid topic', 'description': 'A valid description.', 'question_ids': [1]},
            {'title': 'Invalid topic', 'description': bad_description, 'question_ids': [1]},
        ]})}}, request=httpx.Request('POST', url))
    monkeypatch.setattr(httpx.Client, 'post', ollama)
    assert post(client, '/host/gatherings/1/themes').status_code == 200
    assert rows() == before


@pytest.mark.parametrize('description', [None, '', 'Title only', 'One. Two. Three. Four.'])
def test_generation_route_rejects_invalid_descriptions_before_storage(client, monkeypatch, description):
    login(client)
    post(client, '/gatherings/1/questions', data={'question': 'Could evening hours help access?'})
    create(client)
    before = rows()
    suggestion = {'title': 'Title only', 'question_ids': [1]}
    if description is not None:
        suggestion['description'] = description
    monkeypatch.setattr(main, 'suggest_themes', lambda *_: [suggestion])
    response = post(client, '/host/gatherings/1/themes')
    assert response.status_code == 200
    assert rows() == before
    assert 'Please try again' in response.text
    with main.connection() as db:
        assert db.execute("SELECT status FROM theme_requests WHERE kind='generate'").fetchone()[0] == 'failed'
