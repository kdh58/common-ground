"""Server-rendered workspace navigation preserves every existing host operation."""
import re
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlsplit

import pytest

from app import main, theme_workflow
from tests.form_helpers import post, generated_notes
from tests.test_theme_workflow import client, login, create, rows, key


TABS = ('gathering', 'participants', 'themes')


class Markup(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.elements = []
        self.feed(html)

    def handle_starttag(self, tag, attributes):
        self.elements.append((tag, dict(attributes)))


def active_tab(response, expected):
    assert response.headers['cache-control'] == 'no-store'
    current = [attrs for tag, attrs in Markup(response.text).elements if tag == 'a' and attrs.get('aria-current') == 'page']
    assert len(current) == 1
    assert parse_qs(urlsplit(current[0]['href']).query)['tab'] == [expected]


def redirect_tab(response, expected):
    assert response.status_code == 303
    assert parse_qs(urlsplit(response.headers['location']).query)['tab'] == [expected]


def seed(client, monkeypatch):
    login(client)
    post(client, '/gatherings/1/rsvp', data={'name': 'PRIVATE RSVP NAME'})
    with main.connection() as db:
        db.execute("INSERT INTO gatherings VALUES (2,'Other','D','W','L','A')")
        db.execute("INSERT INTO rsvps VALUES (8,2,'OTHER PRIVATE NAME','2026-01-01T00:00:00+00:00')")
        db.executemany('INSERT INTO questions VALUES (?,?,?,?)', [
            (5, 2, 'OTHER PRIVATE QUESTION', '2026-01-01'),
            (40, 1, 'PRIVATE EVENING QUESTION', '2026-01-01T00:00:00+00:00'),
            (70, 1, 'PRIVATE STAFFING QUESTION', '2026-01-02T00:00:00+00:00'),
        ])
    assert create(client, 'MANUAL PRIVATE TOPIC').status_code == 200
    post(client, '/host/gatherings/1/resources', data={'title': 'Reading resource', 'url': 'https://example.org/reading'})
    monkeypatch.setattr(main, 'suggest_themes', lambda *_: [{'facilitation_notes': generated_notes(),
        'title': 'AI PRIVATE TOPIC', 'description': 'Questions explore evening access and staff workload.', 'question_ids': [1, 2],
    }])
    assert post(client, '/host/gatherings/1/themes').status_code == 200


def snapshot():
    with main.connection() as db:
        tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        return {table: [tuple(r) for r in db.execute(f'SELECT * FROM {table}')] for table in tables}


def test_all_three_tabs_navigation_contents_and_readonly_gets(client, monkeypatch):
    seed(client, monkeypatch)
    before = snapshot()
    pages = {}
    for tab in TABS:
        response = client.get(f'/host/gatherings/1?tab={tab}')
        assert response.status_code == 200
        active_tab(response, tab)
        pages[tab] = response.text
        assert '<h1>The Future of Our Library</h1>' in response.text
        assert '>Active</strong>' in response.text
        assert 'Saturday, November 14 · 2:00 PM' in response.text
        assert 'Community Library · Meeting Room' in response.text
        assert 'href="/host"' in response.text
        assert 'aria-label="Gathering workspace"' in response.text
        for target in TABS:
            assert f'href="/host/gatherings/1?tab={target}"' in response.text
        assert 'OTHER PRIVATE NAME' not in response.text and 'OTHER PRIVATE QUESTION' not in response.text
    assert 'Save details' in pages['gathering'] and 'Save agenda' in pages['gathering']
    assert 'Add resource' in pages['gathering'] and 'Save resource' in pages['gathering']
    assert '1 RSVP(s) · 2 question(s)' in pages['participants']
    assert 'PRIVATE RSVP NAME' in pages['participants']
    assert '#1: PRIVATE EVENING QUESTION' in pages['participants']
    assert '#2: PRIVATE STAFFING QUESTION' in pages['participants']
    assert 'Export RSVPs' in pages['participants'] and 'Export questions' in pages['participants']
    assert 'data-local-time' in pages['participants']
    assert 'Suggest Discussion Themes' in pages['themes'] and 'AI PRIVATE TOPIC' in pages['themes']
    assert 'Original question #1: PRIVATE EVENING QUESTION' in pages['themes']
    assert 'Make inactive' in pages['themes'] and 'id="analysis-1"' in pages['themes']
    assert 'Previous unapproved AI drafts' not in pages['themes']
    assert 'Cancel gathering' in pages['gathering'] and 'Remove resource' in pages['gathering']
    for tab in ('gathering', 'themes'):
        assert 'PRIVATE RSVP NAME' not in pages[tab]
    for tab in ('gathering', 'participants'):
        assert 'AI PRIVATE TOPIC' not in pages[tab]
        assert 'name="request_key"' not in pages[tab]
    assert '?tab=administration' not in pages['gathering']
    assert 'Administration' not in pages['gathering']
    assert pages['gathering'].index('id="gathering-status-heading"') > pages['gathering'].index('id="resources"')
    assert '/resources/1/remove?tab=gathering' in pages['gathering']
    assert snapshot() == before
    active_tab(client.get('/host/gatherings/1'), 'gathering')
    # Ordinary GET links support bookmarking and browser Back/Forward, with no shared tab state.
    for tab in ('themes', 'participants', 'gathering', 'participants', 'themes'):
        active_tab(client.get(f'/host/gatherings/1?tab={tab}'), tab)
    assert client.get('/host/gatherings/1?tab=invalid').status_code == 400
    public = client.get('/gatherings/1').text
    assert 'PRIVATE RSVP NAME' not in public and 'PRIVATE EVENING QUESTION' not in public
    assert 'AI PRIVATE TOPIC' not in public and 'Gathering workspace' not in public


@pytest.mark.parametrize('suffix,data,expected', [
    ('edit', dict(title='Revised', description='New description', when_text='Tomorrow at noon', location='Here'), 'gathering'),
    ('agenda', {'item_title': ['Revised agenda'], 'minutes': ['10'], 'notes': ['Notes']}, 'gathering'),
    ('resources', {'title': 'Another resource', 'url': 'https://example.org/another'}, 'gathering'),
    ('resources/1/edit', {'title': 'Changed resource', 'url': 'https://example.org/changed'}, 'gathering'),
    ('resources/1/remove', {}, 'gathering'),
    ('status', {'status': 'cancelled'}, 'gathering'),
])
def test_mutation_redirects_return_to_the_owner_tab(client, monkeypatch, suffix, data, expected):
    seed(client, monkeypatch)
    response = post(client, f'/host/gatherings/1/{suffix}?tab={expected}', data=data, follow_redirects=False)
    redirect_tab(response, expected)
    landing = client.get(response.headers['location'])
    assert landing.status_code == 200
    active_tab(landing, expected)
    if suffix == 'status':
        assert '>Cancelled</strong>' in landing.text and 'Restore gathering' in landing.text
        restored = post(client, '/host/gatherings/1/status?tab=gathering', data={'status': 'active'})
        active_tab(restored, 'gathering')
        assert '>Active</strong>' in restored.text
    if suffix == 'agenda':
        assert '<details class="card workspace-secondary" id="agenda" open>' in landing.text


@pytest.mark.parametrize('suffix,data,expected,status', [
    ('edit', dict(title=' ', description='Keep this text', when_text='Tomorrow', location='Here'), 'gathering', 400),
    ('edit', {'title': 'Unsaved title'}, 'gathering', 422),
    ('agenda', {'item_title': ['Unsaved agenda'], 'minutes': ['0'], 'notes': ['Keep this note']}, 'gathering', 400),
    ('resources', {'title': 'Unsaved resource', 'url': 'javascript:alert(1)'}, 'gathering', 400),
    ('resources/1/edit', {'title': 'Unsaved resource', 'url': 'invalid'}, 'gathering', 400),
    ('resources', {'title': 'Unsaved resource'}, 'gathering', 422),
    ('status', {'status': 'invalid'}, 'gathering', 400),
    ('status', {}, 'gathering', 422),
    ('themes', {'request_key': 'invalid-key'}, 'themes', 400),
    ('themes', {'request_key': ''}, 'themes', 422),
])
def test_validation_stays_on_tab_preserves_data_and_records(client, monkeypatch, suffix, data, expected, status):
    seed(client, monkeypatch)
    before = snapshot()
    response = post(client, f'/host/gatherings/1/{suffix}?tab={expected}', data=data)
    assert response.status_code == status
    active_tab(response, expected)
    assert 'role="alert"' in response.text
    if 'Unsaved' in str(data):
        assert 'Unsaved' in response.text
    if suffix == 'agenda':
        assert 'Keep this note' in response.text
        assert '<details class="card workspace-secondary" id="agenda" open>' in response.text
    assert snapshot() == before


def test_manual_and_theme_errors_stay_on_themes_and_preserve_edit_text(client, monkeypatch):
    seed(client, monkeypatch)
    response = post(client, '/host/gatherings/1/themes/manual?tab=themes', data={
        'request_key': key(client), 'title': ' ', 'description': 'Keep my manual description',
    })
    assert response.status_code == 400
    active_tab(response, 'themes')
    assert 'Keep my manual description</textarea>' in response.text
    missing = post(client, '/host/gatherings/1/themes/manual?tab=themes', data={'request_key': key(client)})
    assert missing.status_code == 422
    active_tab(missing, 'themes')
    theme = rows()[1]
    response = post(client, f'/host/gatherings/1/themes/{theme["id"]}/edit?tab=themes', data={
        'revision': theme['revision'], 'title': ' ', 'description': 'Keep my interpretation',
    })
    assert response.status_code == 400
    active_tab(response, 'themes')
    assert 'Keep my interpretation</textarea>' in response.text
    assert f'id="theme-{theme["id"]}" open>' in response.text
    missing = post(client, f'/host/gatherings/1/themes/{theme["id"]}/approve?tab=themes')
    assert missing.status_code == 422
    active_tab(missing, 'themes')
    assert f'id="theme-{theme["id"]}" open>' in missing.text


def test_generation_approval_publication_archive_and_exports(client, monkeypatch):
    seed(client, monkeypatch)
    generated = post(client, '/host/gatherings/1/themes?tab=themes', follow_redirects=False)
    redirect_tab(generated, 'themes')
    theme = rows()[-1]
    for action in ('archive', 'restore', 'approve', 'publish', 'unpublish'):
        with main.connection() as db:
            current = next(t for t in theme_workflow.load_themes(db, 1) if t['id'] == theme['id'])
        response = post(client, f'/host/gatherings/1/themes/{theme["id"]}/{action}?tab=themes',
                        data={'revision': current['revision']}, follow_redirects=False)
        redirect_tab(response, 'themes')
        landing = client.get(response.headers['location'])
        active_tab(landing, 'themes')
        assert f'id="theme-{theme["id"]}" open>' in landing.text
        public = client.get('/gatherings/1').text
        assert ('AI PRIVATE TOPIC' in public) == (action == 'publish')
    for kind in ('rsvps', 'questions'):
        response = client.get(f'/host/gatherings/1/export/{kind}.csv?tab=participants')
        assert response.status_code == 200 and 'attachment;' in response.headers['content-disposition']
        assert response.headers['cache-control'] == 'no-store'
        assert 'OTHER PRIVATE' not in response.text
    assert 'PRIVATE RSVP NAME' in client.get('/host/gatherings/1/export/rsvps.csv').text
    exported = client.get('/host/gatherings/1/export/questions.csv').text
    assert 'question_number' in exported and '40,1,' in exported and '70,1,' in exported


@pytest.mark.parametrize('tab', TABS)
def test_workspace_authentication_and_scoping(client, tab):
    assert client.get(f'/host/gatherings/1?tab={tab}').status_code == 403
    login(client)
    assert client.get(f'/host/gatherings/999?tab={tab}').status_code == 404
    assert client.post('/host/gatherings/1/edit?tab=gathering', data={'title': 'No CSRF'}).status_code == 403
    assert post(client, '/host/gatherings/999/edit?tab=gathering').status_code == 404


def test_escaped_error_state_and_responsive_accessibility(client):
    login(client)
    response = post(client, '/host/gatherings/1/edit?tab=gathering', data={
        'title': '<img src=x onerror=alert(1)>', 'description': ' ', 'when_text': 'Tomorrow', 'location': 'Here',
    })
    assert response.status_code == 400
    assert '<img src=x' not in response.text and '&lt;img' in response.text
    css = client.get('/static/style.css').text
    assert '.workspace-tabs' in css and 'flex-wrap: wrap' in css and 'min-height: 44px' in css
    assert ':focus-visible' in css and 'aria-current="page"' in css


def test_manual_creation_save_and_confirmed_theme_deletion_stay_on_themes(client):
    login(client)
    response = post(client, '/host/gatherings/1/themes/manual?tab=themes', data={
        'request_key': key(client), 'title': 'Manual review', 'description': 'Original context.',
    }, follow_redirects=False)
    redirect_tab(response, 'themes')
    theme = rows()[0]
    saved = post(client, f'/host/gatherings/1/themes/{theme["id"]}/edit?tab=themes', data={
        'revision': theme['revision'], 'title': 'Revised manual review', 'description': 'Revised context.',
    }, follow_redirects=False)
    redirect_tab(saved, 'themes')
    assert f'&theme={theme["id"]}#theme-{theme["id"]}' in saved.headers['location']
    deleted = post(client, f'/host/gatherings/1/themes/{theme["id"]}/delete?tab=themes', data={
        'revision': rows()[0]['revision'], 'confirmation': 'delete',
    }, follow_redirects=False)
    redirect_tab(deleted, 'themes')
    assert rows() == []


@pytest.mark.parametrize('suffix,section', [
    ('', ''), ('&section=status', 'status'), ('&section=resource-removal', 'resources'),
    ('&section=https://example.org', ''),
])
def test_old_administration_urls_redirect_without_mutating_data(client, monkeypatch, suffix, section):
    url = '/host/gatherings/1?tab=administration' + suffix
    assert client.get(url, follow_redirects=False).status_code == 403
    seed(client, monkeypatch)
    before = snapshot()
    response = client.get(url, follow_redirects=False)
    redirect_tab(response, 'gathering')
    expected = '/host/gatherings/1?tab=gathering'
    if section:
        expected += f'&section={section}#{section}'
    assert response.headers['location'] == expected
    assert response.headers['cache-control'] == 'no-store'
    active_tab(client.get(response.headers['location']), 'gathering')
    assert snapshot() == before
    assert client.get('/host/gatherings/999?tab=administration', follow_redirects=False).status_code == 404


def test_legacy_administration_forms_return_to_gathering_and_keep_protections(client, monkeypatch):
    seed(client, monkeypatch)
    before = snapshot()
    for endpoint, data in [('status', {'status': 'cancelled'}), ('resources/1/remove', {})]:
        assert client.post(f'/host/gatherings/1/{endpoint}?tab=administration', data=data).status_code == 403
    assert snapshot() == before
    invalid = post(client, '/host/gatherings/1/status?tab=administration', data={'status': 'invalid'})
    assert invalid.status_code == 400
    active_tab(invalid, 'gathering')
    assert 'id="status-feedback"' in invalid.text
    assert snapshot() == before
    cancelled = post(client, '/host/gatherings/1/status?tab=administration', data={'status': 'cancelled'}, follow_redirects=False)
    redirect_tab(cancelled, 'gathering')
    assert cancelled.headers['location'].endswith('&section=status#status')
    removed = post(client, '/host/gatherings/1/resources/1/remove?tab=administration', follow_redirects=False)
    redirect_tab(removed, 'gathering')
    assert removed.headers['location'].endswith('&section=resources#resources')
    with main.connection() as db:
        assert not db.execute('SELECT * FROM resources WHERE id=1').fetchall()
        assert [tuple(r) for r in db.execute('SELECT * FROM questions')] == before['questions']
        assert [tuple(r) for r in db.execute('SELECT * FROM rsvps')] == before['rsvps']
        assert [tuple(r) for r in db.execute('SELECT * FROM discussion_themes')] == before['discussion_themes']
        assert [tuple(r) for r in db.execute('SELECT * FROM theme_sources')] == before['theme_sources']
