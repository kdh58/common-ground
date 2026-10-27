"""Host-private facilitation notes and deterministic per-run question coverage."""
import json

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import main, theme_workflow as workflow
from app.themes import suggest_themes, ThemeError
from tests.form_helpers import post, generated_notes
from tests.test_theme_workflow import client, login, create, act, rows, public


def theme(title='Access and staffing', sources=None, notes=None):
    return {'title': title, 'description': 'Questions explore access alongside staffing requirements.',
            'question_ids': [1] if sources is None else sources,
            'facilitation_notes': generated_notes() if notes is None else notes}


def mock_model(monkeypatch, themes):
    original = httpx.Client.post
    def response(self, url, **kwargs):
        if not str(url).endswith('/api/chat'):
            return original(self, url, **kwargs)
        return httpx.Response(200, json={'done': True, 'done_reason': 'stop',
            'message': {'content': json.dumps({'themes': themes})}}, request=httpx.Request('POST', url))
    monkeypatch.setattr(httpx.Client, 'post', response)


def prepare(client):
    login(client)
    post(client, '/gatherings/1/questions', data={'question': 'Could evening workshops improve access?'})
    post(client, '/gatherings/1/questions', data={'question': 'How would evening workshops affect staffing?'})


def save(client, item=None, revision=None, **values):
    item = item or rows()[0]
    data = {'notes_revision': item['facilitation_notes']['revision'] if revision is None else revision,
            'shared_concerns': 'Private working concern.',
            'different_perspectives': 'Evidence of disagreement is insufficient.',
            'discussion_questions': 'What could we explore together?\nWhat tradeoffs need attention?'}
    data.update(values)
    return post(client, f'/host/gatherings/1/themes/{item["id"]}/notes?tab=themes', data=data)


def coverage(gathering=1):
    with main.connection() as db:
        return workflow.analysis_workspace(db, gathering, workflow.load_themes(db, gathering))['analysis_runs']


def test_complete_contract_and_grounded_private_notes(monkeypatch):
    expected = theme(sources=[1, 2])
    questions = [{'id': 1, 'question': 'Could evening hours help access?'},
                 {'id': 2, 'question': 'What staffing tradeoffs arise?'}]
    def response(self, url, **kwargs):
        payload = kwargs['json']
        item = payload['format']['properties']['themes']['items']
        assert 'facilitation_notes' in item['required']
        assert item['properties']['facilitation_notes']['required'] == ['shared_concerns', 'different_perspectives', 'discussion_questions']
        prompt = payload['messages'][0]['content']
        for phrase in ('grounded ONLY in that theme', 'insufficient evidence', 'recurrence does not imply consensus',
                       'open-ended, neutral', 'not findings or community decisions', 'untrusted data'):
            assert phrase in prompt
        assert json.loads(payload['messages'][1]['content'])['untrusted_questions'] == questions
        assert payload['options']['num_predict'] == 4800 and payload['think'] is False
        assert self.timeout.read == 90 and self.timeout.connect == 5
        return httpx.Response(200, json={'done': True, 'message': {'content': json.dumps({'themes': [expected]})}}, request=httpx.Request('POST', url))
    monkeypatch.setattr(httpx.Client, 'post', response)
    assert suggest_themes(questions, main.OLLAMA_BASE_URL, main.OLLAMA_MODEL) == [expected]


BAD_NOTES = [None, {}, {'shared_concerns': 'Only one field.'}]
for field, value in [
    ('shared_concerns', ''), ('shared_concerns', ' '), ('shared_concerns', 'One. Two. Three. Four.'),
    ('shared_concerns', 'x' * 1001), ('shared_concerns', 'Bad\x00text'),
    ('different_perspectives', None), ('different_perspectives', []), ('different_perspectives', 'Bad\x7ftext'),
    ('discussion_questions', []), ('discussion_questions', ['Just one?']),
    ('discussion_questions', ['One?', 'Two?', 'Three?', 'Four?']),
    ('discussion_questions', 'Not a list'), ('discussion_questions', ['First?', 42]),
    ('discussion_questions', ['First?', ' ']), ('discussion_questions', ['First?', 'FIRST!']),
    ('discussion_questions', ['x' * 301, 'Another?']), ('discussion_questions', ['Line\nbreak?', 'Other?']),
]:
    bad = generated_notes()
    bad[field] = value
    BAD_NOTES.append(bad)
extra = generated_notes()
extra['invented_sources'] = [999]
BAD_NOTES.append(extra)


@pytest.mark.parametrize('notes', BAD_NOTES)
def test_invalid_generated_notes_reject_entire_response(monkeypatch, notes):
    invalid = theme()
    invalid['facilitation_notes'] = notes
    mock_model(monkeypatch, [invalid])
    with pytest.raises(ThemeError, match='incomplete or invalid'):
        suggest_themes([{'id': 1, 'question': 'Synthetic concern?'}], main.OLLAMA_BASE_URL, main.OLLAMA_MODEL)


def test_missing_notes_are_not_accepted_as_legacy_generation(monkeypatch):
    invalid = theme()
    del invalid['facilitation_notes']
    mock_model(monkeypatch, [invalid])
    with pytest.raises(ThemeError):
        suggest_themes([{'id': 1, 'question': 'Synthetic concern?'}], main.OLLAMA_BASE_URL, main.OLLAMA_MODEL)


def test_generated_notes_persist_restart_and_never_appear_publicly(client, monkeypatch):
    prepare(client)
    notes = generated_notes()
    notes['shared_concerns'] = 'PRIVATE NOTES <script>alert(1)</script>.'
    mock_model(monkeypatch, [theme(sources=[1, 2], notes=notes)])
    assert post(client, '/host/gatherings/1/themes').status_code == 200
    item = rows()[0]
    assert item['facilitation_notes']['shared_concerns'] == notes['shared_concerns']
    assert item['facilitation_notes']['revision'] == 1 and item['facilitation_notes']['ai_suggested']
    assert item['question_ids'] == [1, 2] and item['run_id'] is not None
    html = client.get('/host/gatherings/1?tab=themes').text
    assert 'AI Facilitation Notes' in html and 'not findings or community decisions' in html
    assert '&lt;script&gt;' in html and '<script>alert(1)</script>' not in html
    assert 'Save private notes' in html and 'data-local-time' in html
    with main.connection() as db:
        original = json.loads(db.execute('SELECT original_ai_notes FROM theme_facilitation_notes').fetchone()[0])
        assert original == notes
    main.init_db()
    with TestClient(main.app):
        pass
    assert rows()[0]['facilitation_notes'] == item['facilitation_notes']
    for action in ('approve', 'publish', 'unpublish'):
        assert act(client, action).status_code == 200
        page = public(client)
        assert 'PRIVATE NOTES' not in page and 'different_perspectives' not in page
        assert 'insufficient evidence' not in page
        assert rows()[0]['facilitation_notes'] == item['facilitation_notes']
    assert act(client, 'edit', title=item['title'], description=item['description']).status_code == 200
    assert rows()[0]['status'] == 'draft'
    assert act(client, 'archive').status_code == 200
    assert rows()[0]['facilitation_notes'] == item['facilitation_notes']
    assert save(client, shared_concerns='Archived private edit.').status_code == 200
    assert rows()[0]['archived']
    assert act(client, 'restore').status_code == 200
    assert rows()[0]['facilitation_notes']['shared_concerns'] == 'Archived private edit.'
    with main.connection() as db:
        assert json.loads(db.execute('SELECT original_ai_notes FROM theme_facilitation_notes').fetchone()[0]) == original


def test_private_edits_do_not_invalidate_public_approval_and_have_independent_revisions(client):
    login(client)
    create(client)
    act(client, 'approve')
    act(client, 'publish')
    original = rows()[0]
    public_before = public(client)
    with main.connection() as db:
        theme_before = tuple(db.execute('SELECT * FROM discussion_themes').fetchone())
    first = save(client, shared_concerns='PRIVATE HOST ONLY <img src=x onerror=alert(1)>')
    assert first.status_code == 200
    after = rows()[0]
    assert after['status'] == 'published' and after['revision'] == original['revision']
    assert after['facilitation_notes']['revision'] == 1
    assert public(client) == public_before and 'PRIVATE HOST ONLY' not in public(client)
    assert '&lt;img' in first.text and '<img src=x' not in first.text
    with main.connection() as db:
        assert tuple(db.execute('SELECT * FROM discussion_themes').fetchone()) == theme_before
    stale = save(client, revision=0, shared_concerns='Unsaved stale note')
    assert stale.status_code == 409 and 'Unsaved stale note</textarea>' in stale.text
    assert 'id="notes-feedback-1"' in stale.text and 'id="theme-1" open>' in stale.text
    assert rows()[0]['facilitation_notes'] == after['facilitation_notes']
    assert save(client, shared_concerns='Revised private concern.').status_code == 200
    assert rows()[0]['status'] == 'published' and rows()[0]['facilitation_notes']['revision'] == 2
    # A public edit form opened before a private edit is still valid, then reapproval is required.
    assert act(client, 'edit', original, title='Changed public topic', description='Changed public context.').status_code == 200
    assert rows()[0]['status'] == 'draft' and rows()[0]['facilitation_notes']['revision'] == 2


@pytest.mark.parametrize('values', [
    {'shared_concerns': 'x' * 2001}, {'different_perspectives': 'x' * 2001},
    {'shared_concerns': 'Bad\x00control'}, {'discussion_questions': 'One?\nTwo?\nThree?\nFour?'},
    {'discussion_questions': 'x' * 501},
])
def test_host_note_limits_do_not_change_theme_or_notes(client, values):
    login(client)
    create(client)
    before = rows()
    response = save(client, **values)
    assert response.status_code == 400 and 'role="alert"' in response.text
    assert rows() == before


def test_note_auth_csrf_scope_and_manual_blank_working_content(client):
    path = '/host/gatherings/1/themes/1/notes?tab=themes'
    assert client.post(path, data={'notes_revision': 0}).status_code == 403
    login(client)
    create(client)
    assert rows()[0]['facilitation_notes']['revision'] == 0
    assert client.post(path, data={'notes_revision': 0}).status_code == 403
    assert client.post(path, data={'notes_revision': 0, 'csrf_token': 'bad'}).status_code == 403
    missing = post(client, path)
    assert missing.status_code == 422 and 'AI Facilitation Notes' not in missing.text
    with main.connection() as db:
        db.execute("INSERT INTO gatherings VALUES (2,'Other','D','W','L','A')")
    assert post(client, '/host/gatherings/2/themes/1/notes', data={'notes_revision': 0}).status_code == 404
    assert rows()[0]['facilitation_notes']['revision'] == 0
    assert save(client, shared_concerns='', different_perspectives='', discussion_questions='').status_code == 200
    assert rows()[0]['facilitation_notes']['discussion_questions'] == []
    assert not rows()[0]['facilitation_notes']['ai_suggested']
    assert 'PRIVATE' not in client.get('/host/gatherings/2?tab=themes').text


def test_route_revalidates_notes_and_rolls_back_new_themes_sources_and_notes(client, monkeypatch):
    prepare(client)
    monkeypatch.setattr(main, 'suggest_themes', lambda *_: [theme()])
    post(client, '/host/gatherings/1/themes')
    before = rows()
    invalid = theme('Incomplete second theme')
    del invalid['facilitation_notes']
    monkeypatch.setattr(main, 'suggest_themes', lambda *_: [theme('Valid first theme'), invalid])
    response = post(client, '/host/gatherings/1/themes')
    assert response.status_code == 200 and 'invalid facilitation notes' in response.text
    assert rows() == before
    with main.connection() as db:
        assert db.execute('SELECT count(*) FROM theme_facilitation_notes').fetchone()[0] == 1
        assert db.execute("SELECT status FROM analysis_runs ORDER BY id DESC LIMIT 1").fetchone()[0] == 'failed'
        assert db.execute('SELECT count(*) FROM analysis_run_snapshots').fetchone()[0] == 2
        assert not db.execute('PRAGMA foreign_key_check').fetchall()


def test_snapshot_coverage_is_per_run_distinct_and_excludes_later_questions(client, monkeypatch):
    login(client)
    with main.connection() as db:
        db.execute("INSERT INTO gatherings VALUES (2,'Other','D','W','L','A')")
        db.executemany('INSERT INTO questions VALUES (?,?,?,?)', [
            (40, 1, 'Access?', '2026-01-01'), (70, 1, 'Staffing?', '2026-01-02'),
            (90, 1, 'Cost?', '2026-01-03'), (1, 2, 'Other gathering?', '2026-01-01'),
        ])
        workflow.insert_theme(db, 1, 'Historical citation', 'Keep historical content.', 'ai', [70])
    calls = []
    def generate(questions, *_):
        if not calls:
            with main.connection() as db:
                db.execute("INSERT INTO questions VALUES (120,1,'Later contribution?','2026-01-04')")
        calls.append(questions)
        return [theme('Access', [1]), theme('Access and costs', [1, 3])]
    monkeypatch.setattr(main, 'suggest_themes', generate)
    assert post(client, '/host/gatherings/1/themes').status_code == 200
    first = coverage()[0]
    assert first['coverage']['analyzed'] == 3 and first['coverage']['cited'] == 2
    assert [(q['id'], q['question_number']) for q in first['coverage']['uncited']] == [(70, 2)]
    page = client.get('/host/gatherings/1?tab=themes').text
    assert '3 questions analyzed · 2 distinct questions cited · 1 question not cited' in page
    assert 'Uncited question #2: Staffing?' in page
    assert 'Citation coverage is not evidence of representativeness' in page
    with main.connection() as db:
        assert [r[0] for r in db.execute('SELECT question_id FROM analysis_run_questions WHERE run_id=1 ORDER BY question_number')] == [40, 70, 90]
    post(client, '/host/gatherings/1/themes')
    runs = coverage()
    assert runs[0]['coverage']['analyzed'] == 4 and runs[0]['coverage']['uncited_count'] == 2
    assert runs[1]['coverage'] == first['coverage']
    old = next(t for t in rows() if t['run_id'] == first['id'] and len(t['question_ids']) == 2)
    assert not old['archived']
    assert act(client, 'delete', old, confirmation='delete').status_code == 200
    assert coverage()[1]['coverage']['cited'] == 1
    assert coverage()[0]['coverage']['cited'] == 2
    monkeypatch.setattr(main, 'suggest_themes', lambda *_: [theme('Other topic', [1])])
    post(client, '/host/gatherings/2/themes')
    assert coverage(2)[0]['coverage']['analyzed'] == 1 and coverage(2)[0]['coverage']['cited'] == 1
    assert 'Staffing?' not in client.get('/host/gatherings/2?tab=themes').text


def test_private_note_edits_during_generation_are_preserved(client, monkeypatch):
    prepare(client)
    monkeypatch.setattr(main, 'suggest_themes', lambda *_: [theme()])
    post(client, '/host/gatherings/1/themes')
    old = rows()[0]
    def generate(*_):
        with main.connection() as db:
            workflow.save_notes(db, 1, old['id'], old['facilitation_notes']['revision'], 'Host revised during inference.', '', '')
        return [theme('New theme')]
    monkeypatch.setattr(main, 'suggest_themes', generate)
    assert post(client, '/host/gatherings/1/themes').status_code == 200
    old_after = next(t for t in rows() if t['id'] == old['id'])
    assert not old_after['archived'] and old_after['facilitation_notes']['shared_concerns'] == 'Host revised during inference.'


def test_migration_preserves_legacy_content_and_does_not_invent_snapshots(client):
    prepare(client)
    create(client, 'Published legacy', 'Preserved public description')
    act(client, 'approve')
    act(client, 'publish')
    with main.connection() as db:
        legacy = workflow.insert_theme(db, 1, 'AI legacy', 'Original AI description.', 'ai', [1])
        run_id = workflow.start_analysis(db, 1, 'historical-key', 2)
        db.execute('INSERT INTO theme_analysis_runs VALUES (?,?)', (legacy, run_id))
        workflow.finish_analysis(db, run_id, 'complete')
        workflow.finish_request(db, 'historical-key', 'complete')
        for table in ('analysis_run_questions', 'analysis_run_snapshots', 'theme_facilitation_notes'):
            db.execute(f'DROP TABLE {table}')
        tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        before = {t: [tuple(r) for r in db.execute(f'SELECT * FROM {t}')] for t in tables}
    main.init_db()
    main.init_db()
    with main.connection() as db:
        assert {t: [tuple(r) for r in db.execute(f'SELECT * FROM {t}')] for t in tables} == before
        assert db.execute('SELECT count(*) FROM theme_facilitation_notes').fetchone()[0] == 0
        assert db.execute('SELECT count(*) FROM analysis_run_snapshots').fetchone()[0] == 0
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
    assert all(t['facilitation_notes']['revision'] == 0 for t in rows())
    run = coverage()[0]
    assert run['coverage'] is None and 'historical run' in run['coverage_unavailable']
    html = client.get('/host/gatherings/1?tab=themes').text
    assert 'Coverage unavailable' in html and 'Not generated for this theme' in html
    assert 'Preserved public description' in public(client)


def test_delete_with_foreign_keys_on_removes_only_notes_and_theme_metadata(client, monkeypatch):
    prepare(client)
    monkeypatch.setattr(main, 'suggest_themes', lambda *_: [theme()])
    post(client, '/host/gatherings/1/themes')
    old = rows()[0]
    with main.connection() as db:
        db.execute('PRAGMA foreign_keys=ON')
        workflow.change_theme(db, 1, old['id'], old['revision'], 'delete', confirmation='delete')
        assert db.execute('SELECT count(*) FROM theme_facilitation_notes').fetchone()[0] == 0
        assert db.execute('SELECT count(*) FROM analysis_run_questions').fetchone()[0] == 2
        assert db.execute('SELECT count(*) FROM questions').fetchone()[0] == 2
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
    assert coverage()[0]['coverage']['cited'] == 0


@pytest.mark.parametrize('field', ['shared_concerns', 'different_perspectives', 'discussion_questions'])
def test_each_generated_note_field_is_required(monkeypatch, field):
    invalid = theme()
    del invalid['facilitation_notes'][field]
    mock_model(monkeypatch, [invalid])
    with pytest.raises(ThemeError):
        suggest_themes([{'id': 1, 'question': 'Synthetic access question?'}], main.OLLAMA_BASE_URL, main.OLLAMA_MODEL)


def test_invalid_notes_diagnostics_do_not_log_text(monkeypatch, caplog):
    monkeypatch.setenv('CG_DEV_THEME_DIAGNOSTICS', '1')
    invalid = theme()
    invalid['facilitation_notes']['different_perspectives'] = 'PRIVATE MODEL TEXT ' + 'x' * 1001
    mock_model(monkeypatch, [invalid])
    with pytest.raises(ThemeError):
        suggest_themes([{'id': 1, 'question': 'PRIVATE PARTICIPANT TEXT'}], main.OLLAMA_BASE_URL, main.OLLAMA_MODEL)
    assert 'reason=schema_mismatch' in caplog.text
    assert 'PRIVATE' not in caplog.text


def test_complete_notes_still_reject_truncation_timeout_and_fabricated_sources(monkeypatch):
    from tests.test_themes import mock_ollama
    complete = {'done': True, 'done_reason': 'length', 'message': {'content': json.dumps({'themes': [theme()]})}}
    mock_ollama(monkeypatch, complete)
    with pytest.raises(ThemeError, match='incomplete or invalid'):
        suggest_themes([{'id': 1, 'question': 'Access?'}], main.OLLAMA_BASE_URL, main.OLLAMA_MODEL)
    mock_ollama(monkeypatch, error=httpx.ReadTimeout('PRIVATE timeout'))
    with pytest.raises(ThemeError, match='took too long'):
        suggest_themes([{'id': 1, 'question': 'Access?'}], main.OLLAMA_BASE_URL, main.OLLAMA_MODEL)
    mock_model(monkeypatch, [theme(sources=[999])])
    with pytest.raises(ThemeError, match='incomplete or invalid'):
        suggest_themes([{'id': 1, 'question': 'Access?'}], main.OLLAMA_BASE_URL, main.OLLAMA_MODEL)


def test_snapshot_scope_guard_and_incomplete_snapshot_not_reported_as_coverage(client, monkeypatch):
    prepare(client)
    with main.connection() as db:
        db.execute("INSERT INTO gatherings VALUES (2,'Other','D','W','L','A')")
        db.execute("INSERT INTO questions VALUES (90,2,'Other private question','2026-01-01')")
    with pytest.raises(HTTPException):
        with main.connection() as db:
            run_id = workflow.start_analysis(db, 1, 'invalid-snapshot', 1)
            workflow.record_question_snapshot(db, 1, run_id, [{'id': 90, 'question_number': 1}])
    with main.connection() as db:
        assert not db.execute("SELECT 1 FROM theme_requests WHERE request_key='invalid-snapshot'").fetchone()
    monkeypatch.setattr(main, 'suggest_themes', lambda *_: [theme()])
    post(client, '/host/gatherings/1/themes')
    with main.connection() as db:
        db.execute('DELETE FROM analysis_run_questions WHERE question_id=2')
    run = coverage()[0]
    assert run['coverage'] is None and 'incomplete' in run['coverage_unavailable']
    html = client.get('/host/gatherings/1?tab=themes').text
    assert 'Coverage unavailable' in html and 'questions analyzed' not in html
