"""Explicit run provenance, reversible archives, and accessible host history."""
import re
import sqlite3
from html.parser import HTMLParser

import pytest

from app import main, theme_workflow as workflow
from app.themes import ThemeError
from tests.form_helpers import post
from tests.test_theme_workflow import client, login, create, act, rows


class Disclosures(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.details = {}
        self.ids = []
        self.feed(html)

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if 'id' in attrs:
            self.ids.append(attrs['id'])
        if tag == 'details' and 'id' in attrs:
            self.details[attrs['id']] = 'open' in attrs


def setup_analysis(client, monkeypatch):
    login(client)
    post(client, '/gatherings/1/questions', data={'question': 'Could evening workshops help access?'})
    post(client, '/gatherings/1/questions', data={'question': 'How would evening hours affect staff workload?'})
    post(client, '/gatherings/1/rsvp', data={'name': 'Preserved attendee'})
    counter = []
    def suggest(questions, *_):
        counter.append(len(counter) + 1)
        return [{'title': f'Access and staffing {counter[-1]}',
                 'description': 'Questions explore evening access alongside staff workload.',
                 'question_ids': [q['id'] for q in questions]}]
    monkeypatch.setattr(main, 'suggest_themes', suggest)
    return counter


def generate(client, action=None, **data):
    if action is not None:
        data['draft_action'] = action
    return post(client, '/host/gatherings/1/themes', data=data)


def runs():
    with main.connection() as db:
        return [dict(r) for r in db.execute('SELECT * FROM analysis_runs ORDER BY id')]


def test_grouping_disclosures_and_current_visibility(client, monkeypatch):
    setup_analysis(client, monkeypatch)
    create(client, 'Manual visible')
    generate(client)
    ai = rows()[1]
    act(client, 'approve', ai)
    act(client, 'publish', rows()[1])
    generate(client, 'keep')
    second = rows()[2]
    act(client, 'approve', second)
    generate(client, 'keep')
    html = client.get('/host/gatherings/1?tab=themes').text
    parsed = Disclosures(html)
    assert len(parsed.ids) == len(set(parsed.ids))
    assert parsed.details['analysis-3']
    assert not parsed.details['analysis-1'] and not parsed.details['analysis-2']
    assert all(not opened for identifier, opened in parsed.details.items() if identifier.startswith('theme-'))
    assert html.index('id="analysis-3"') < html.index('id="analysis-2"') < html.index('id="analysis-1"')
    current = html.split('<h3 id="current-themes-heading">Current Themes</h3>')[1].split('<h3>Create a theme without AI</h3>')[0]
    assert 'Manual visible' in current and ai['title'] in current and second['title'] in current
    assert 'Access and staffing 3' not in current
    assert 'Original analysis #1' in current
    assert '2 questions · 1 themes generated' in html
    assert 'data-local-time' in html and 'America/New_York; fallback)</time>' in html
    assert 'Published</strong>' in current and 'Approved</strong>' in current
    assert 'in Current Themes' in html.split('id="analysis-1"')[1]
    for theme in rows()[1:]:
        assert theme['question_ids'] == [1, 2]
        assert theme['run_id'] is not None
    assert len(runs()) == 3 and all(r['status'] == 'complete' for r in runs())


@pytest.mark.parametrize('choice', ['archive', 'keep', 'delete'])
def test_all_generation_choices_protect_current_and_submissions(client, monkeypatch, choice):
    setup_analysis(client, monkeypatch)
    create(client, 'Manual draft')
    generate(client)
    draft = rows()[1]
    generate(client, 'keep')
    act(client, 'approve', rows()[2])
    generate(client, 'keep')
    act(client, 'approve', rows()[3])
    act(client, 'publish', rows()[3])
    protected = [rows()[i] for i in (0, 2, 3)]
    with main.connection() as db:
        db.execute("INSERT INTO gatherings VALUES (2,'Other','D','W','L','A')")
        other_id = workflow.insert_theme(db, 2, 'Other AI draft', 'Do not alter.', 'ai')
        before = {t: [tuple(r) for r in db.execute(f'SELECT * FROM {t}')] for t in ('questions', 'rsvps')}
    response = generate(client, choice, delete_confirmation='delete' if choice == 'delete' else '')
    assert response.status_code == 200
    remaining = {t['id']: t for t in rows()}
    assert all(remaining[t['id']] == t for t in protected)
    assert rows(2)[0]['id'] == other_id and not rows(2)[0]['archived']
    if choice == 'delete':
        assert draft['id'] not in remaining
        assert runs()[0]['generated_theme_count'] == 1
        with main.connection() as db:
            assert db.execute('SELECT 1 FROM theme_sources WHERE theme_id=?', (draft['id'],)).fetchone() is None
            assert db.execute('SELECT 1 FROM theme_analysis_runs WHERE theme_id=?', (draft['id'],)).fetchone() is None
    else:
        assert remaining[draft['id']]['archived'] == (choice == 'archive')
        assert remaining[draft['id']]['question_ids'] == draft['question_ids']
        assert remaining[draft['id']]['run_id'] == draft['run_id']
    assert not rows()[-1]['archived']
    with main.connection() as db:
        assert {t: [tuple(r) for r in db.execute(f'SELECT * FROM {t}')] for t in before} == before
        assert not db.execute('PRAGMA foreign_key_check').fetchall()


def test_default_archive_restore_revision_and_original_sources(client, monkeypatch):
    setup_analysis(client, monkeypatch)
    generate(client)
    original = rows()[0]
    generate(client)  # Default choice must archive.
    archived = rows()[0]
    assert archived['archived'] and archived['revision'] == original['revision'] + 1
    assert act(client, 'restore', original).status_code == 409
    assert act(client, 'approve', archived).status_code == 409
    assert act(client, 'edit', archived, title='Cannot edit').status_code == 409
    page = client.get('/host/gatherings/1?tab=themes').text
    assert 'Restore draft' in page
    assert act(client, 'restore', archived).status_code == 200
    restored = rows()[0]
    assert not restored['archived'] and restored['revision'] == archived['revision'] + 1
    for field in ('id', 'title', 'description', 'question_ids', 'run_id', 'ai_original_title', 'status'):
        assert restored[field] == original[field]
    assert act(client, 'approve', restored).status_code == 200
    assert rows()[0]['status'] == 'approved'
    assert act(client, 'archive', rows()[0]).status_code == 409
    create(client)
    assert act(client, 'archive', rows()[-1]).status_code == 409


def test_delete_requires_confirmation_before_inference_or_receipt(client, monkeypatch):
    calls = setup_analysis(client, monkeypatch)
    generate(client)
    before = rows()
    response = generate(client, 'delete')
    assert response.status_code == 400 and 'Confirm deletion' in response.text
    assert rows() == before and len(calls) == 1 and len(runs()) == 1
    assert generate(client, 'anything').status_code == 400
    assert len(calls) == 1


@pytest.mark.parametrize('choice', ['archive', 'keep', 'delete'])
def test_failed_analysis_preserves_previous_drafts(client, monkeypatch, choice):
    setup_analysis(client, monkeypatch)
    generate(client)
    before = rows()
    def fail(*_):
        raise ThemeError('Ollama unavailable. Please try again.')
    monkeypatch.setattr(main, 'suggest_themes', fail)
    assert generate(client, choice, delete_confirmation='delete').status_code == 200
    assert rows() == before
    assert runs()[-1]['status'] == 'failed'
    page = client.get('/host/gatherings/1?tab=themes').text
    assert Disclosures(page).details['analysis-2'] and 'Failed' in page


@pytest.mark.parametrize('choice', ['archive', 'delete'])
@pytest.mark.parametrize('change', ['edit', 'approve'])
def test_host_changes_during_inference_are_preserved(client, monkeypatch, choice, change):
    setup_analysis(client, monkeypatch)
    generate(client)
    draft = rows()[0]
    def suggest(questions, *_):
        with main.connection() as db:
            workflow.change_theme(db, 1, draft['id'], draft['revision'], change, 'Host changed', 'Host interpretation')
        return [{'title': 'New analysis', 'description': 'Questions explore evening access alongside staff workload.', 'question_ids': [1, 2]}]
    monkeypatch.setattr(main, 'suggest_themes', suggest)
    assert generate(client, choice, delete_confirmation='delete').status_code == 200
    assert not rows()[0]['archived']
    assert rows()[0]['status'] == ('approved' if change == 'approve' else 'draft')
    if change == 'edit':
        assert rows()[0]['title'] == 'Host changed'


def test_edit_and_approve_errors_open_affected_old_run_and_theme(client, monkeypatch):
    setup_analysis(client, monkeypatch)
    generate(client)
    old = rows()[0]
    generate(client, 'keep')
    response = act(client, 'edit', old, title=' ', description='Unsaved explanation')
    assert response.status_code == 400
    disclosures = Disclosures(response.text).details
    assert disclosures['analysis-1'] and disclosures[f'theme-{old["id"]}']
    assert not disclosures['analysis-2']
    assert 'id="theme-feedback-1"' in response.text and 'Unsaved explanation</textarea>' in response.text
    assert act(client, 'edit', old, title='Revised title').status_code == 200
    response = act(client, 'approve', old)  # stale revision
    assert response.status_code == 409
    assert 'changed since you opened' in response.text
    assert Disclosures(response.text).details['analysis-1']
    assert 'role="alert"' in response.text
    assert rows()[0]['status'] == 'draft'


@pytest.mark.parametrize('action', ['archive', 'restore'])
def test_archive_authorization_csrf_and_scope(client, monkeypatch, action):
    path = f'/host/gatherings/1/themes/1/{action}'
    assert client.post(path, data={'revision': 1}).status_code == 403
    setup_analysis(client, monkeypatch)
    generate(client)
    assert client.post(path, data={'revision': 1}).status_code == 403
    assert client.post(path, data={'revision': 1, 'csrf_token': 'wrong'}).status_code == 403
    post(client, '/host/gatherings', data=dict(title='Other', description='D', when_text='W', location='L', agenda='A'))
    assert act(client, action, rows()[0], gathering=2).status_code == 404
    assert not rows()[0]['archived']


def test_legacy_migration_is_additive_repeatable_and_honest(client):
    login(client)
    post(client, '/gatherings/1/questions', data={'question': 'Preserve source'})
    create(client, 'Manual existing')
    with main.connection() as db:
        workflow.insert_theme(db, 1, 'Legacy one', '', 'ai', [1])
        workflow.insert_theme(db, 1, 'Legacy two', '', 'ai', [1])
        for table in ('archived_themes', 'theme_analysis_runs', 'analysis_runs'):
            db.execute(f'DROP TABLE {table}')
        tables = ['discussion_themes', 'theme_sources', 'theme_requests', 'questions', 'rsvps', 'gatherings']
        before = {t: [tuple(r) for r in db.execute(f'SELECT * FROM {t}')] for t in tables}
    main.init_db()
    main.init_db()
    with main.connection() as db:
        assert {t: [tuple(r) for r in db.execute(f'SELECT * FROM {t}')] for t in tables} == before
        assert db.execute('SELECT count(*) FROM analysis_runs').fetchone()[0] == 0
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
    html = client.get('/host/gatherings/1?tab=themes').text
    assert 'Legacy suggestions — analysis run unknown' in html
    assert 'Question count unknown' in html
    assert not Disclosures(html).details['analysis-legacy']
    assert 'Manual existing' in html.split('id="analysis-legacy"')[0]


def test_delete_archived_draft_cleans_metadata_with_foreign_keys_enabled(client, monkeypatch):
    setup_analysis(client, monkeypatch)
    generate(client)
    generate(client)
    archived = rows()[0]
    with main.connection() as db:
        db.execute('PRAGMA foreign_keys=ON')
        workflow.change_theme(db, 1, archived['id'], archived['revision'], 'delete', confirmation='delete')
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
    assert len(rows()) == 1 and runs()[0]['generated_theme_count'] == 1
