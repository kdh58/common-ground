"""Explicit run provenance, reversible archives, and accessible host history."""
import re
import sqlite3
from html.parser import HTMLParser

import pytest

from app import main, theme_workflow as workflow
from app.themes import ThemeError
from tests.form_helpers import post, generated_notes
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
        return [{'facilitation_notes': generated_notes(), 'title': f'Access and staffing {counter[-1]}',
                 'description': 'Questions explore evening access alongside staff workload.',
                 'question_ids': [q['id'] for q in questions]}]
    monkeypatch.setattr(main, 'suggest_themes', suggest)
    return counter


def generate(client, **data):
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
    generate(client)
    second = rows()[2]
    act(client, 'approve', second)
    generate(client)
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



def run_key(client, run_id, gathering=1):
    html = client.get(f'/host/gatherings/{gathering}?tab=themes').text
    form = re.search(r'<form action="/host/gatherings/' + str(gathering) + '/analyses/' + str(run_id) + r'/[^"]+".*?</form>', html, re.S)
    return re.search(r'name="action_key" value="([^"]+)"', form[0])[1]


def run_act(client, run_id, action, gathering=1, action_key=None, **data):
    return post(client, f'/host/gatherings/{gathering}/analyses/{run_id}/{action}?tab=themes',
        data={'action_key': action_key or run_key(client, run_id, gathering), **data})


@pytest.mark.parametrize('old_choice', ['archive', 'keep', 'delete', 'invalid'])
def test_generation_ignores_obsolete_choices_and_never_changes_previous_data(client, monkeypatch, old_choice):
    setup_analysis(client, monkeypatch)
    create(client, 'Manual draft')
    generate(client)
    generate(client)
    act(client, 'approve', rows()[2])
    generate(client)
    act(client, 'approve', rows()[3])
    act(client, 'publish', rows()[3])
    before = rows()
    runs_before = runs()
    with main.connection() as db:
        before_tables = {t: [tuple(r) for r in db.execute(f'SELECT * FROM {t}')] for t in
                        ('questions', 'rsvps', 'theme_sources', 'theme_facilitation_notes', 'analysis_run_states')}
    response = generate(client, draft_action=old_choice, delete_confirmation='delete')
    assert response.status_code == 200
    assert rows()[:len(before)] == before
    assert runs()[:len(runs_before)] == runs_before
    with main.connection() as db:
        for table in ('questions', 'rsvps', 'analysis_run_states'):
            assert [tuple(r) for r in db.execute(f'SELECT * FROM {table}')] == before_tables[table]
        for table in ('theme_sources', 'theme_facilitation_notes'):
            assert [tuple(r) for r in db.execute(f'SELECT * FROM {table} WHERE theme_id<=?', (before[-1]['id'],))] == before_tables[table]
    html = response.text
    form = re.search(r'<form action="/host/gatherings/1/themes\?tab=themes".*?</form>', html, re.S)[0]
    assert 'Suggest Discussion Themes' in form
    for obsolete in ('draft_action', 'delete_confirmation', 'Previous unapproved', '<fieldset', 'type="checkbox"'):
        assert obsolete not in form
    assert not rows()[-1]['archived'] and not rows()[-1]['inactive_draft']


def test_make_inactive_and_reactivate_preserve_drafts_notes_and_citations(client, monkeypatch):
    setup_analysis(client, monkeypatch)
    generate(client)
    before = rows()[0]
    with main.connection() as db:
        core = tuple(db.execute('SELECT * FROM discussion_themes WHERE id=?', (before['id'],)).fetchone())
        cited = [tuple(r) for r in db.execute('SELECT * FROM theme_sources')]
    old_key = run_key(client, 1)
    assert run_act(client, 1, 'inactive', action_key=old_key).status_code == 200
    inactive = rows()[0]
    assert inactive['inactive_draft'] and inactive['revision'] == before['revision']
    assert inactive['question_ids'] == before['question_ids']
    assert inactive['facilitation_notes'] == before['facilitation_notes']
    assert act(client, 'approve', inactive).status_code == 409
    blocked = act(client, 'edit', inactive, title='Cannot edit inactive')
    assert blocked.status_code == 409 and 'Reactivate this analysis' in blocked.text
    assert 'role="alert"' in blocked.text
    assert run_act(client, 1, 'reactivate', action_key=old_key).status_code == 409
    assert run_act(client, 1, 'reactivate').status_code == 200
    assert rows()[0] == before
    with main.connection() as db:
        assert tuple(db.execute('SELECT * FROM discussion_themes WHERE id=?', (before['id'],)).fetchone()) == core
        assert [tuple(r) for r in db.execute('SELECT * FROM theme_sources')] == cited
    # Generation does not reactivate or otherwise alter older inactive runs.
    run_act(client, 1, 'inactive')
    generate(client)
    assert rows()[0]['inactive_draft'] and not rows()[-1]['inactive_draft']


def test_individual_legacy_archives_remain_explicit_and_survive_run_reactivation(client, monkeypatch):
    setup_analysis(client, monkeypatch)
    generate(client)
    assert act(client, 'archive').status_code == 200
    run_act(client, 1, 'inactive')
    run_act(client, 1, 'reactivate')
    assert rows()[0]['archived']
    assert act(client, 'restore').status_code == 200
    assert not rows()[0]['archived']


def test_run_delete_requires_confirmation_and_retains_request_receipt(client, monkeypatch):
    calls = setup_analysis(client, monkeypatch)
    generate(client)
    with main.connection() as db:
        receipt = db.execute("SELECT request_key FROM theme_requests WHERE kind='generate'").fetchone()[0]
    before = rows()
    response = run_act(client, 1, 'delete')
    assert response.status_code == 400 and 'Confirm deletion' in response.text
    assert Disclosures(response.text).details['analysis-1']
    assert rows() == before
    assert run_act(client, 1, 'delete', confirmation='delete').status_code == 200
    assert rows() == [] and runs() == []
    with main.connection() as db:
        for table in ('theme_facilitation_notes', 'theme_sources', 'theme_analysis_runs', 'analysis_run_questions', 'analysis_run_snapshots', 'analysis_run_states'):
            assert db.execute(f'SELECT count(*) FROM {table}').fetchone()[0] == 0
        assert db.execute('SELECT count(*) FROM questions').fetchone()[0] == 2
        assert db.execute('SELECT count(*) FROM rsvps').fetchone()[0] == 1
        assert db.execute('SELECT count(*) FROM theme_requests').fetchone()[0] == 1
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
    assert generate(client, request_key=receipt).status_code == 409
    assert len(calls) == 1


@pytest.mark.parametrize('state', ['approved', 'published'])
def test_run_delete_protects_current_themes_and_provenance(client, monkeypatch, state):
    setup_analysis(client, monkeypatch)
    generate(client)
    act(client, 'approve')
    if state == 'published':
        act(client, 'publish')
    before = rows()
    assert run_act(client, 1, 'inactive').status_code == 200
    assert rows() == before
    assert run_act(client, 1, 'delete', confirmation='delete').status_code == 409
    assert rows() == before and len(runs()) == 1
    html = client.get('/host/gatherings/1?tab=themes').text
    assert before[0]['title'] in html.split('AI analysis history')[0]
    assert 'cannot be deleted' in html


def test_failed_analysis_preserves_previous_runs_and_drafts(client, monkeypatch):
    setup_analysis(client, monkeypatch)
    generate(client)
    before = rows()
    def fail(*_):
        raise ThemeError('Ollama unavailable. Please try again.')
    monkeypatch.setattr(main, 'suggest_themes', fail)
    assert generate(client).status_code == 200
    assert rows() == before and runs()[-1]['status'] == 'failed'
    assert run_act(client, runs()[-1]['id'], 'delete', confirmation='delete').status_code == 200
    assert rows() == before


def test_edit_and_approve_errors_open_affected_old_run_and_theme(client, monkeypatch):
    setup_analysis(client, monkeypatch)
    generate(client)
    old = rows()[0]
    generate(client)
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
    act(client, 'archive', rows()[0])
    archived = rows()[0]
    with main.connection() as db:
        db.execute('PRAGMA foreign_keys=ON')
        workflow.change_theme(db, 1, archived['id'], archived['revision'], 'delete', confirmation='delete')
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
    assert len(rows()) == 1 and runs()[0]['generated_theme_count'] == 1


@pytest.mark.parametrize('action', ['inactive', 'reactivate', 'delete'])
def test_run_actions_authorization_csrf_signed_scope_and_failures(client, monkeypatch, action):
    path = f'/host/gatherings/1/analyses/1/{action}?tab=themes'
    assert client.post(path, data={'action_key': 'bad'}).status_code == 403
    setup_analysis(client, monkeypatch)
    generate(client)
    key = run_key(client, 1)
    before = rows()
    assert client.post(path, data={'action_key': key}).status_code == 403
    assert client.post(path, data={'action_key': key, 'csrf_token': 'bad'}).status_code == 403
    assert post(client, path, data={'action_key': key + 'tamper', 'confirmation': 'delete'}).status_code == 400
    with main.connection() as db:
        db.execute("INSERT INTO gatherings(id,title,description,when_text,location,agenda) VALUES (2,'Other','D','W','L','A')")
    assert post(client, f'/host/gatherings/2/analyses/1/{action}', data={'action_key': key, 'confirmation': 'delete'}).status_code == 400
    missing = post(client, path)
    assert missing.status_code == 422 and Disclosures(missing.text).details['analysis-1']
    assert rows() == before


@pytest.mark.parametrize('edit', ['edit', 'notes', 'approve'])
def test_stale_run_actions_reject_theme_or_note_changes(client, monkeypatch, edit):
    setup_analysis(client, monkeypatch)
    generate(client)
    key = run_key(client, 1)
    item = rows()[0]
    if edit == 'notes':
        with main.connection() as db:
            workflow.save_notes(db, 1, item['id'], item['facilitation_notes']['revision'], 'New private work.', '', '')
    else:
        act(client, edit, item, title='Revised title', description='Revised public text.')
    before = rows()
    response = run_act(client, 1, 'delete', action_key=key, confirmation='delete')
    assert response.status_code == 409 and 'changed' in response.text
    assert Disclosures(response.text).details['analysis-1']
    assert rows() == before and len(runs()) == 1


def test_deleting_one_run_preserves_other_run_records_and_sources(client, monkeypatch):
    setup_analysis(client, monkeypatch)
    generate(client)
    generate(client)
    first = rows()[0]
    with main.connection() as db:
        before = {table: [tuple(r) for r in db.execute(f'SELECT * FROM {table}')]
                  for table in ('questions', 'rsvps')}
        first_sources = [tuple(r) for r in db.execute('SELECT * FROM theme_sources WHERE theme_id=?', (first['id'],))]
        first_notes = tuple(db.execute('SELECT * FROM theme_facilitation_notes WHERE theme_id=?', (first['id'],)).fetchone())
    with main.connection() as db:
        db.execute('PRAGMA foreign_keys=ON')
        version = workflow.analysis_version(db, 1, 2)
        workflow.change_analysis(db, 1, 2, version, 'delete', 'delete')
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
        assert [tuple(r) for r in db.execute('SELECT * FROM theme_sources WHERE theme_id=?', (first['id'],))] == first_sources
        assert tuple(db.execute('SELECT * FROM theme_facilitation_notes WHERE theme_id=?', (first['id'],)).fetchone()) == first_notes
        assert {table: [tuple(r) for r in db.execute(f'SELECT * FROM {table}')] for table in before} == before
    assert rows() == [first] and [r['id'] for r in runs()] == [1]


def test_manual_theme_association_protects_run_deletion(client, monkeypatch):
    setup_analysis(client, monkeypatch)
    generate(client)
    create(client, 'Protected manual topic')
    with main.connection() as db:
        db.execute('INSERT INTO theme_analysis_runs VALUES (?,1)', (rows()[-1]['id'],))
    before = rows()
    assert run_act(client, 1, 'delete', confirmation='delete').status_code == 409
    assert rows() == before


def test_delete_during_inference_does_not_resurrect_deleted_run(client, monkeypatch):
    setup_analysis(client, monkeypatch)
    def suggest(*_):
        with main.connection() as db:
            run_id = db.execute('SELECT id FROM analysis_runs ORDER BY id DESC').fetchone()[0]
            workflow.change_analysis(db, 1, run_id, workflow.analysis_version(db, 1, run_id), 'delete', 'delete')
        return [{'title': 'Discarded output', 'description': 'Questions explore evening access and staffing.',
                 'question_ids': [1, 2], 'facilitation_notes': generated_notes()}]
    monkeypatch.setattr(main, 'suggest_themes', suggest)
    response = generate(client)
    assert response.status_code == 200 and 'deleted while generation was running' in response.text
    assert rows() == [] and runs() == []
    with main.connection() as db:
        assert db.execute("SELECT status FROM theme_requests WHERE kind='generate'").fetchone()[0] == 'failed'
        assert db.execute('SELECT count(*) FROM questions').fetchone()[0] == 2
        assert db.execute('SELECT count(*) FROM theme_facilitation_notes').fetchone()[0] == 0


def test_make_inactive_during_inference_keeps_result_inactive(client, monkeypatch):
    setup_analysis(client, monkeypatch)
    def suggest(*_):
        with main.connection() as db:
            run_id = db.execute('SELECT id FROM analysis_runs ORDER BY id DESC').fetchone()[0]
            workflow.change_analysis(db, 1, run_id, workflow.analysis_version(db, 1, run_id), 'inactive')
        return [{'title': 'New output', 'description': 'Questions explore evening access and staffing.',
                 'question_ids': [1, 2], 'facilitation_notes': generated_notes()}]
    monkeypatch.setattr(main, 'suggest_themes', suggest)
    assert generate(client).status_code == 200
    assert rows()[0]['inactive_draft'] and runs()[0]['status'] == 'complete'
    assert run_act(client, 1, 'reactivate').status_code == 200
    assert not rows()[0]['inactive_draft']


def test_run_state_migration_does_not_rewrite_legacy_runs_or_theme_archives(client, monkeypatch):
    setup_analysis(client, monkeypatch)
    generate(client)
    act(client, 'archive')
    with main.connection() as db:
        db.execute("UPDATE analysis_runs SET draft_action='archive' WHERE id=1")
        db.execute('DROP TABLE analysis_run_states')
        tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        before = {table: [tuple(r) for r in db.execute(f'SELECT * FROM {table}')] for table in tables}
    main.init_db()
    main.init_db()
    with main.connection() as db:
        assert {table: [tuple(r) for r in db.execute(f'SELECT * FROM {table}')] for table in tables} == before
        assert not db.execute('SELECT * FROM analysis_run_states').fetchall()
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
    assert rows()[0]['archived'] and not rows()[0]['inactive_draft']
    assert 'Previous drafts:' not in client.get('/host/gatherings/1?tab=themes').text
