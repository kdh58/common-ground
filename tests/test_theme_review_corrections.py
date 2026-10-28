"""Single description editors and gathering-local model/source identifiers."""
import json
from html.parser import HTMLParser

import httpx
import pytest

from app import main, theme_workflow as workflow
from tests.form_helpers import post, generated_notes
from tests.test_theme_workflow import client, login, create, act, rows


class ThemeMarkup(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.elements = []
        self.feed(html)

    def handle_starttag(self, tag, attributes):
        self.elements.append((tag, dict(attributes)))


def test_expanded_description_only_has_one_editor(client):
    login(client)
    description = 'The questions explore evening access alongside staff workload.'
    create(client, description=description)
    for state in ('draft', 'approved', 'published'):
        if state == 'approved':
            act(client, 'approve', rows()[0])
        elif state == 'published':
            act(client, 'publish', rows()[0])
        html = client.get('/host/gatherings/1?theme=1').text
        elements = ThemeMarkup(html).elements
        assert ('details', {'class': 'theme-item', 'id': 'theme-1', 'open': None}) in elements
        assert sum(tag == 'textarea' and attrs.get('id') == 'theme-description-1' for tag, attrs in elements) == 1
        assert not any(tag == 'p' and attrs.get('class') == 'theme-description' for tag, attrs in elements)
        assert 'class="theme-preview"' in html
        assert f'>{description}</textarea>' in html
        assert f'theme-status-{state}' in html
    css = client.get('/static/style.css').text
    assert '.theme-item[open] > summary > .theme-preview { display: none; }' in css
    # Public published descriptions still have their usual static display.
    assert f'<p class="theme-description">{description}</p>' in client.get('/gatherings/1').text


def test_archived_description_remains_readable_without_enabling_editing(client):
    login(client)
    with main.connection() as db:
        theme_id = workflow.insert_theme(db, 1, 'Archived theme', 'Archived interpretation.', 'ai')
    assert act(client, 'archive', rows()[0]).status_code == 200
    html = client.get(f'/host/gatherings/1?theme={theme_id}').text
    descriptions = [attrs for tag, attrs in ThemeMarkup(html).elements
                    if tag == 'textarea' and attrs.get('id') == f'theme-description-{theme_id}']
    assert len(descriptions) == 1 and 'readonly' in descriptions[0]
    assert f'/themes/{theme_id}/edit' not in html
    assert 'class="theme-description"' not in html
    assert 'Restore draft' in html


def seed_nonconsecutive_sources(client):
    login(client)
    with main.connection() as db:
        db.execute("INSERT INTO gatherings(id,title,description,when_text,location,agenda) VALUES (2,'Other','D','W','L','A')")
        db.executemany('INSERT INTO questions VALUES (?,?,?,?)', [
            (40, 1, 'Could evening workshops help access?', '2026-01-01'),
            (10, 1, 'How would evening hours affect staff workload?', '2026-01-02'),
            (70, 1, 'What about workshop costs?', '2026-01-02'),
            (1, 2, 'Could weekend workshops help?', '2026-01-01'),
            (90, 2, 'What would weekend staffing require?', '2026-01-02'),
        ])
        db.execute("INSERT INTO rsvps VALUES (7,1,'Preserved attendee','2026-01-01')")
        for title, status in [('Existing approved', 'approved'), ('Existing published', 'published')]:
            theme_id = workflow.insert_theme(db, 1, title, 'Historical reference to question #70.', 'ai', [70])
            db.execute('UPDATE discussion_themes SET status=? WHERE id=?', (status, theme_id))
        return {table: [tuple(r) for r in db.execute(f'SELECT * FROM {table}')]
                for table in ('questions', 'rsvps', 'discussion_themes', 'theme_sources')}


def test_model_local_numbers_map_to_database_sources_in_each_gathering(client, monkeypatch):
    before = seed_nonconsecutive_sources(client)
    calls = []
    original = httpx.Client.post
    def ollama(self, url, **kwargs):
        if not str(url).endswith('/api/chat'):
            return original(self, url, **kwargs)
        payload = kwargs['json']
        questions = json.loads(payload['messages'][1]['content'])['untrusted_questions']
        calls.append(questions)
        assert [q['id'] for q in questions] == list(range(1, len(questions) + 1))
        assert all(set(q) == {'id', 'question'} for q in questions)
        prompt = payload['messages'][0]['content']
        assert 'gathering-local question number' in prompt
        assert 'do not insert question numbers or identifiers' in prompt
        return httpx.Response(200, json={'done': True, 'message': {'content': json.dumps({'themes': [{'facilitation_notes': generated_notes(),
            'title': 'Workshop access and staffing',
            'description': 'The questions explore workshop access alongside staffing requirements.',
            'question_ids': [1, len(questions)],
        }]})}}, request=httpx.Request('POST', url))
    monkeypatch.setattr(httpx.Client, 'post', ollama)
    for gathering, expected in [(1, [40, 70]), (2, [1, 90])]:
        response = post(client, f'/host/gatherings/{gathering}/themes')
        assert response.status_code == 200
        generated = rows(gathering)[-1]
        assert set(generated['question_ids']) == set(expected)
        assert 'Historical reference to question #70.' in client.get('/host/gatherings/1?tab=themes').text
        page = client.get(f'/host/gatherings/{gathering}?tab=themes').text
        assert 'Original question #1:' in page
        assert f'Original question #{3 if gathering == 1 else 2}:' in page
    assert len(calls[0]) == 3 and len(calls[1]) == 2
    assert 'weekend' not in str(calls[0]) and 'evening' not in str(calls[1])
    with main.connection() as db:
        for table in ('questions', 'rsvps'):
            assert [tuple(r) for r in db.execute(f'SELECT * FROM {table}')] == before[table]
        assert [tuple(r) for r in db.execute('SELECT * FROM discussion_themes WHERE id<=2')] == before['discussion_themes']
        assert [tuple(r) for r in db.execute('SELECT * FROM theme_sources WHERE theme_id<=2')] == before['theme_sources']
        assert not db.execute('PRAGMA foreign_key_check').fetchall()


@pytest.mark.parametrize('bad_sources', [[40], [90], [4], [0], [-1], [True], ['1'], [], None, [1, 90]])
def test_route_rejects_unmapped_model_sources_without_partial_storage(client, monkeypatch, bad_sources):
    before = seed_nonconsecutive_sources(client)
    monkeypatch.setattr(main, 'suggest_themes', lambda *_: [
        {'facilitation_notes': generated_notes(), 'title': 'Valid first', 'description': 'Questions explore access to evening workshops.', 'question_ids': [1]},
        {'facilitation_notes': generated_notes(), 'title': 'Invalid second', 'description': 'Questions explore staffing for workshops.', 'question_ids': bad_sources},
    ])
    response = post(client, '/host/gatherings/1/themes')
    assert response.status_code == 200 and "AI analysis couldn't be completed" in response.text
    with main.connection() as db:
        for table in before:
            assert [tuple(r) for r in db.execute(f'SELECT * FROM {table}')] == before[table]
        assert db.execute("SELECT status FROM analysis_runs").fetchone()[0] == 'failed'
        assert db.execute('SELECT count(*) FROM theme_analysis_runs').fetchone()[0] == 0
