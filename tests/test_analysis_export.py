"""Private standalone exports use only saved, gathering/run-scoped records."""
import re
from html.parser import HTMLParser

import pytest

from app import main, theme_workflow as workflow
from tests.form_helpers import post, generated_notes
from tests.test_theme_workflow import client, login, create, act, rows
from tests.test_analysis_runs import run_act
from tests.test_facilitation import save


class Document(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.elements = []
        self.text = []
        self.styles = []
        self.in_style = False
        self.feed(html)

    def handle_starttag(self, tag, attributes):
        self.elements.append((tag, dict(attributes)))
        if tag == 'style':
            self.in_style = True

    def handle_endtag(self, tag):
        if tag == 'style':
            self.in_style = False

    def handle_data(self, data):
        self.text.append(data)
        if self.in_style:
            self.styles.append(data)


def snapshot():
    with main.connection() as db:
        tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        return {table: [tuple(r) for r in db.execute(f'SELECT * FROM {table}')] for table in tables}


def setup_export(client, monkeypatch):
    login(client)
    monkeypatch.setattr(main, 'OLLAMA_MODEL', 'qwen3:export-test')
    post(client, '/gatherings/1/rsvp', data={'name': 'CONFIDENTIAL RSVP NAME'})
    with main.connection() as db:
        db.execute("INSERT INTO gatherings VALUES (2,'OTHER GATHERING','D','W','L','A')")
        db.executemany('INSERT INTO questions VALUES (?,?,?,?)', [
            (40, 1, 'FIRST SOURCE', '2026-01-01'),
            (10, 1, 'SECOND SOURCE', '2026-01-02'),
            (70, 1, 'THIRD SOURCE', '2026-01-03'),
            (90, 1, 'UNCITED INPUT', '2026-01-04'),
            (1, 2, 'OTHER PRIVATE SOURCE', '2026-01-01'),
        ])
    items = []
    for title, sources in [('DRAFT TOPIC', [1]), ('ARCHIVED TOPIC', [2]),
                           ('APPROVED TOPIC', [1, 3]), ('PUBLISHED TOPIC', [3])]:
        notes = generated_notes()
        notes['shared_concerns'] = f'Saved concerns for {title}.'
        items.append({'title': title, 'description': f'Saved description for {title}.',
                      'question_ids': sources, 'facilitation_notes': notes})
    monkeypatch.setattr(main, 'suggest_themes', lambda *_: items)
    assert post(client, '/host/gatherings/1/themes').status_code == 200
    act(client, 'archive', rows()[1])
    act(client, 'approve', rows()[2])
    act(client, 'approve', rows()[3])
    act(client, 'publish', rows()[3])
    assert run_act(client, 1, 'inactive').status_code == 200
    monkeypatch.setattr(main, 'suggest_themes', lambda *_: [{
        'title': 'UNRELATED SAME GATHERING RUN', 'description': 'Unrelated saved description.',
        'question_ids': [4], 'facilitation_notes': generated_notes(),
    }])
    post(client, '/host/gatherings/1/themes')
    monkeypatch.setattr(main, 'suggest_themes', lambda *_: [{
        'title': 'OTHER GATHERING TOPIC', 'description': 'Other gathering description.',
        'question_ids': [1], 'facilitation_notes': generated_notes(),
    }])
    post(client, '/host/gatherings/2/themes')
    create(client, 'UNASSOCIATED MANUAL TOPIC', 'Do not export unrelated manual content')
    with main.connection() as db:
        db.execute("UPDATE analysis_runs SET created_at='2026-10-27T17:22:00.123456+00:00' WHERE id=1")


def url(run=1, gathering=1):
    return f'/host/gatherings/{gathering}/analyses/{run}/export.html'


def test_complete_export_all_statuses_archive_and_run_isolation(client, monkeypatch):
    setup_export(client, monkeypatch)
    before = snapshot()
    response = client.get(url())
    assert response.status_code == 200
    assert response.headers['content-type'].startswith('text/html')
    assert response.headers['content-disposition'] == 'attachment; filename="gathering-1-analysis-1.html"'
    assert response.headers['cache-control'] == 'private, no-store'
    assert response.headers['x-content-type-options'] == 'nosniff'
    assert "default-src 'none'" in response.headers['content-security-policy']
    assert "script-src 'none'" in response.headers['content-security-policy']
    assert response.headers['referrer-policy'] == 'no-referrer'
    html = response.text
    for value in ('The Future of Our Library', 'Saturday, November 14 · 2:00 PM',
                  'Community Library · Meeting Room', 'AI Analysis #1', 'qwen3:export-test',
                  'DRAFT TOPIC', 'ARCHIVED TOPIC', 'APPROVED TOPIC', 'PUBLISHED TOPIC',
                  'Shared concerns', 'Different perspectives and potential tradeoffs',
                  'Suggested discussion questions', 'Cited original questions', 'UNCITED INPUT'):
        assert value in html
    assert 'Draft' in html and 'Approved' in html and 'Published' in html and 'Archived draft' in html
    assert 'Inactive · Complete' in html
    assert 'Questions supplied to analysis</dt><dd>4</dd>' in html
    assert 'Questions analyzed</dt><dd>4</dd>' in html
    assert 'Distinct questions cited</dt><dd>3</dd>' in html
    assert 'Questions not cited</dt><dd>1</dd>' in html
    for number, text in enumerate(['FIRST SOURCE', 'SECOND SOURCE', 'THIRD SOURCE', 'UNCITED INPUT'], 1):
        assert f'Question #{number}:</strong> {text}' in html
    assert 'Question #40:' not in html and 'Question #70:' not in html
    for excluded in ('CONFIDENTIAL RSVP NAME', 'UNRELATED SAME GATHERING RUN', 'OTHER GATHERING TOPIC',
                     'OTHER PRIVATE SOURCE', 'UNASSOCIATED MANUAL TOPIC', 'csrf_token', 'request_key',
                     'action_version', 'host.docker.internal', 'CG_DEV_THEME_DIAGNOSTICS'):
        assert excluded not in html
    assert 'not findings, community decisions or evidence of community consensus' in html
    assert snapshot() == before


def test_export_is_standalone_printable_and_contains_no_active_resources(client, monkeypatch):
    setup_export(client, monkeypatch)
    document = Document(client.get(url()).text)
    tags = {tag for tag, _ in document.elements}
    assert 'style' in tags
    assert not tags & {'script', 'link', 'img', 'iframe', 'form', 'input', 'textarea', 'object', 'embed', 'details'}
    assert '@media print' in ''.join(document.styles) and '@page' in ''.join(document.styles)
    assert '@media (max-width: 500px)' in ''.join(document.styles)
    assert 'url(' not in ''.join(document.styles) and '@import' not in ''.join(document.styles)
    assert not any('src' in attrs or 'srcset' in attrs for _, attrs in document.elements)
    assert all(attrs.get('href', '#').startswith('#') for _, attrs in document.elements)
    workspace = client.get('/host/gatherings/1?tab=themes').text
    assert workspace.count('>View / Print Analysis</a>') == 2  # selected inactive + other active run
    assert 'data-analysis-export' in workspace
    assert 'Save theme edits and private notes before exporting' in workspace


def test_save_private_notes_is_separate_and_export_reads_current_saved_values(client, monkeypatch):
    setup_export(client, monkeypatch)
    published = next(t for t in rows() if t['title'] == 'PUBLISHED TOPIC')
    before = (published['revision'], published['status'], published['description'], published['question_ids'])
    saved = post(client, f'/host/gatherings/1/themes/{published["id"]}/notes?tab=themes', data={
        'notes_revision': published['facilitation_notes']['revision'],
        'shared_concerns': 'CURRENT SAVED PRIVATE CONCERN',
        'different_perspectives': 'CURRENT SAVED PRIVATE TRADEOFF',
        'discussion_questions': 'CURRENT SAVED PROMPT ONE?\nCURRENT SAVED PROMPT TWO?',
    }, follow_redirects=False)
    assert saved.status_code == 303 and '?tab=themes' in saved.headers['location']
    assert 'content-disposition' not in saved.headers
    current = next(t for t in rows() if t['id'] == published['id'])
    assert (current['revision'], current['status'], current['description'], current['question_ids']) == before
    before_export = snapshot()
    response = client.get(url() + '?shared_concerns=UNSAVED_FORM_VALUE&title=UNSAVED_TITLE&description=UNSAVED_DESCRIPTION')
    for text in ('CURRENT SAVED PRIVATE CONCERN', 'CURRENT SAVED PRIVATE TRADEOFF',
                 'CURRENT SAVED PROMPT ONE?', 'CURRENT SAVED PROMPT TWO?'):
        assert text in response.text
    assert 'UNSAVED_' not in response.text
    assert snapshot() == before_export
    public = client.get('/gatherings/1').text
    assert 'CURRENT SAVED PRIVATE' not in public and 'CURRENT SAVED PROMPT' not in public
    assert 'PUBLISHED TOPIC' in public


def test_requested_model_is_recorded_per_run_not_inferred_from_current_configuration(client, monkeypatch):
    setup_export(client, monkeypatch)
    monkeypatch.setattr(main, 'OLLAMA_MODEL', 'different-current-model:latest')
    monkeypatch.setattr(main, 'OLLAMA_BASE_URL', 'http://private-user:PRIVATE-ENDPOINT-CREDENTIAL@localhost:11434')
    monkeypatch.setattr(main, 'ADMIN_PASSWORD', 'PRIVATE-HOST-PASSWORD')
    def forbidden(*_):
        pytest.fail('Export must never invoke Ollama')
    monkeypatch.setattr(main, 'suggest_themes', forbidden)
    html = client.get(url()).text
    assert 'qwen3:export-test' in html
    assert 'different-current-model' not in html and 'PRIVATE-ENDPOINT-CREDENTIAL' not in html
    assert 'PRIVATE-HOST-PASSWORD' not in html and 'private-user' not in html
    main.init_db()
    assert 'qwen3:export-test' in client.get(url()).text


@pytest.mark.parametrize('endpoint', ['export.html', 'view.html'])
def test_untrusted_export_fields_are_escaped_without_creating_active_markup(client, monkeypatch, endpoint):
    setup_export(client, monkeypatch)
    with main.connection() as db:
        db.execute('UPDATE gatherings SET title=?,location=?,when_text=? WHERE id=1',
                   ('<script>GATHERING</script>', '<img src=x onerror=alert(1)>', '<iframe src=https://tracker.example>'))
        db.execute('UPDATE discussion_themes SET title=?,description=? WHERE id=1',
                   ('<script>THEME</script>', '<img src=x onerror=alert(1)>'))
        db.execute('UPDATE questions SET question=? WHERE id=40', ('<svg onload=alert(1)>SOURCE</svg>',))
        db.execute('UPDATE analysis_run_models SET model=? WHERE run_id=1', ('<script>MODEL</script>',))
    item = rows()[0]
    assert save(client, item, shared_concerns='<script>NOTES</script>',
                different_perspectives='<img src=x onerror=alert(1)>',
                discussion_questions='<svg onload=alert(1)>PROMPT</svg>').status_code == 200
    html = client.get(url().replace("export.html", endpoint)).text
    document = Document(html)
    assert not {tag for tag, _ in document.elements} & {'img', 'svg', 'iframe'}
    assert '<script>NOTES</script>' not in html and '&lt;script&gt;NOTES&lt;/script&gt;' in html
    decoded = ''.join(document.text)
    assert '<script>MODEL</script>' in decoded and '<svg onload=alert(1)>SOURCE</svg>' in decoded
    assert '<script>NOTES</script>' in decoded

    scripts = re.findall(r"<script>(.*?)</script>", html)
    assert scripts == ([main.PRINT_ANALYSIS_SCRIPT] if endpoint == "view.html" else [])


def test_legacy_blank_notes_unknown_model_and_unavailable_coverage(client):
    login(client)
    with main.connection() as db:
        db.execute("INSERT INTO questions VALUES (50,1,'Legacy original source','')")
        theme_id = workflow.insert_theme(db, 1, 'Legacy AI', '', 'ai', [50])
        run_id = workflow.start_analysis(db, 1, 'legacy-export-receipt', 1)
        db.execute('INSERT INTO theme_analysis_runs VALUES (?,?)', (theme_id, run_id))
        workflow.finish_analysis(db, run_id, 'complete')
        workflow.finish_request(db, 'legacy-export-receipt', 'complete')
    before = snapshot()
    html = client.get(url(run_id)).text
    assert html.count('Not generated or entered.') == 3
    assert 'No saved description.' in html
    assert 'Not recorded for this historical run' in html
    assert 'Coverage unavailable' in html and 'input question snapshot not recorded' in html
    assert 'Question #1:</strong> Legacy original source' in html
    assert snapshot() == before


@pytest.mark.parametrize('endpoint', ['export.html', 'view.html'])
def test_export_authentication_and_run_gathering_ownership(client, monkeypatch, endpoint):
    assert client.get(url().replace("export.html", endpoint)).status_code == 403
    assert client.get(url(999, 999).replace("export.html", endpoint)).status_code == 403
    setup_export(client, monkeypatch)
    assert client.get(url(1, 2).replace("export.html", endpoint)).status_code == 404
    assert client.get(url(3, 1).replace("export.html", endpoint)).status_code == 404
    assert client.get(url(999).replace("export.html", endpoint)).status_code == 404
    assert client.get(url(1, 999).replace("export.html", endpoint)).status_code == 404
    assert client.get('/gatherings/1/analyses/1/export.html').status_code == 404
    post(client, '/host/logout')
    assert client.get(url().replace("export.html", endpoint)).status_code == 403


@pytest.mark.parametrize('zone,stamp,expected', [
    ('America/New_York', '2026-10-27T17:22:00.123456+00:00', 'Oct 27, 2026 · 1:22 PM EDT'),
    ('America/Los_Angeles', '2026-10-27T17:22:00Z', 'Oct 27, 2026 · 10:22 AM PDT'),
    ('America/Los_Angeles', '2026-01-27T17:22:00Z', 'Jan 27, 2026 · 9:22 AM PST'),
    ('America/New_York', '2026-03-08T06:59:00Z', 'Mar 8, 2026 · 1:59 AM EST'),
    ('America/New_York', '2026-03-08T07:00:00Z', 'Mar 8, 2026 · 3:00 AM EDT'),
    ('Asia/Tokyo', '2026-10-27T17:22:00Z', 'Oct 28, 2026 · 2:22 AM JST'),
])
def test_script_free_export_uses_requested_browser_timezone_and_dst(client, monkeypatch, zone, stamp, expected):
    setup_export(client, monkeypatch)
    with main.connection() as db:
        db.execute('UPDATE analysis_runs SET created_at=? WHERE id=1', (stamp,))
    html = client.get(url(), params={'timezone': zone}).text
    assert expected in html and 'prototype fallback;' not in html
    assert f'System timestamp timezone</dt><dd>{zone}' in html
    assert '123456' not in html and '<script' not in html
    assert 'Saturday, November 14 · 2:00 PM' in html


@pytest.mark.parametrize('requested', [None, '', 'Invalid/Zone', '../../etc/passwd', '<script>alert(1)</script>'])
def test_missing_invalid_timezone_is_labeled_fallback_not_container_time(client, monkeypatch, requested):
    setup_export(client, monkeypatch)
    monkeypatch.setenv('TZ', 'Asia/Tokyo')
    response = client.get(url(), params={} if requested is None else {'timezone': requested})
    assert response.status_code == 200
    assert 'Oct 27, 2026 · 1:22 PM EDT (America/New_York; fallback)' in response.text
    assert 'prototype fallback; browser timezone unavailable or unsupported' in response.text
    assert '<script>alert(1)</script>' not in response.text


def test_new_model_metadata_migration_preserves_existing_tables(client, monkeypatch):
    setup_export(client, monkeypatch)
    with main.connection() as db:
        db.execute('DROP TABLE analysis_run_models')
    before = snapshot()
    main.init_db()
    main.init_db()
    after = snapshot()
    assert {table: after[table] for table in before} == before
    assert after['analysis_run_models'] == []
    assert 'Not recorded for this historical run' in client.get(url()).text


def test_inline_report_toolbar_security_and_download(client, monkeypatch):
    import base64
    import hashlib
    setup_export(client, monkeypatch)
    response = client.get(url().replace('export.html', 'view.html'), params={'timezone': 'Asia/Tokyo'})
    assert response.status_code == 200
    assert response.headers['content-type'] == 'text/html; charset=utf-8'
    assert response.headers['content-disposition'] == 'inline; filename="gathering-1-analysis-1.html"'
    assert response.headers['cache-control'] == 'private, no-store'
    assert response.headers['x-content-type-options'] == 'nosniff'
    assert response.headers['x-frame-options'] == 'DENY'
    assert response.headers['referrer-policy'] == 'no-referrer'
    script, = re.findall(r'<script>(.*?)</script>', response.text)
    digest = base64.b64encode(hashlib.sha256(script.encode()).digest()).decode()
    csp = response.headers['content-security-policy']
    assert f"script-src 'sha256-{digest}'" in csp
    for directive in ("default-src 'none'", "base-uri 'none'", "form-action 'none'", "frame-ancestors 'none'"):
        assert directive in csp
    assert "script-src 'unsafe-inline'" not in csp
    document = Document(response.text)
    meta = next(attrs['content'] for tag, attrs in document.elements if tag == 'meta' and attrs.get('http-equiv') == 'Content-Security-Policy')
    assert f"script-src 'sha256-{digest}'" in meta
    assert ('button', {'type': 'button', 'id': 'print-analysis'}) in document.elements
    toolbar = next(attrs for tag, attrs in document.elements if tag == 'nav')
    assert 'screen-only' in toolbar['class'].split()
    assert re.search(r'@media print.*?\.screen-only\s*{\s*display: none;', ''.join(document.styles), re.S)
    download = next(attrs for tag, attrs in document.elements if tag == 'a' and 'download' in attrs)
    assert download['href'] == url() + '?timezone=Asia%2FTokyo'
    attachment = client.get(download['href'])
    assert attachment.headers['content-disposition'].startswith('attachment;')
    assert '<script' not in attachment.text
    assert 'DRAFT TOPIC' in response.text and 'UNCITED INPUT' in response.text
    workspace = Document(client.get('/host/gatherings/1?tab=themes').text)
    links = [attrs for tag, attrs in workspace.elements if tag == 'a' and 'data-analysis-export' in attrs]
    assert len(links) == 2
    for link in links:
        assert link['href'].endswith('/view.html')
        assert link['target'] == '_blank'
        assert set(link['rel'].split()) == {'noopener', 'noreferrer'}
        assert 'download' not in link and 'onclick' not in link
