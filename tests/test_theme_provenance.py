"""Analysis provenance is display-only; host theme ordering remains authoritative."""
import re

import pytest

from app import main, theme_workflow as workflow
from tests.form_helpers import post
from tests.test_theme_workflow import client, create, act, rows, public
from tests.test_analysis_runs import setup_analysis, generate, run_act, Disclosures


def current_html(client):
    html = client.get('/host/gatherings/1?tab=themes').text
    return html.split('<h3 id="current-themes-heading">Current Themes</h3>')[1].split('<h3>Create a theme without AI</h3>')[0]


def raw_records():
    with main.connection() as db:
        return {table: [tuple(r) for r in db.execute(f'SELECT * FROM {table}')]
                for table in ('discussion_themes', 'theme_sources', 'theme_facilitation_notes',
                              'theme_analysis_runs', 'analysis_runs', 'questions', 'rsvps')}


def test_active_history_first_and_host_current_order_preserved(client, monkeypatch):
    setup_analysis(client, monkeypatch)
    for _ in range(5):
        generate(client)
        act(client, 'approve', rows()[-1])
    act(client, 'publish', rows()[0])
    create(client, 'Manual working topic')
    # Move the oldest AI theme after newer themes using explicit host controls.
    act(client, 'down', rows()[0])
    act(client, 'down', next(t for t in rows() if t['run_id'] == 1))
    expected_order = [t['id'] for t in rows()]
    before = raw_records()
    public_before = public(client)
    run_act(client, 2, 'inactive')
    run_act(client, 5, 'inactive')
    assert raw_records() == before
    assert public(client) == public_before
    with main.connection() as db:
        workspace = workflow.analysis_workspace(db, 1, workflow.load_themes(db, 1))
    assert [r['id'] for r in workspace['analysis_runs']] == [4, 3, 1, 5, 2]
    assert [t['id'] for t in workspace['current_themes']] == expected_order
    html = client.get('/host/gatherings/1?tab=themes').text
    assert re.findall(r'<details class="analysis-run" id="analysis-(\d+)"', html) == ['4', '3', '1', '5', '2']
    disclosure = Disclosures(html).details
    assert disclosure['analysis-4'] and not disclosure['analysis-5'] and not disclosure['analysis-2']
    assert [int(value) for value in re.findall(r'<details class="theme-item" id="theme-(\d+)"', current_html(client))] == expected_order
    assert 'Manually created' in current_html(client)
    run_act(client, 5, 'reactivate')
    with main.connection() as db:
        workspace = workflow.analysis_workspace(db, 1, workflow.load_themes(db, 1))
    assert [r['id'] for r in workspace['analysis_runs']] == [5, 4, 3, 1, 2]
    assert [t['id'] for t in workspace['current_themes']] == expected_order
    assert raw_records() == before


def test_ai_provenance_in_current_summary_uses_original_analysis_time(client, monkeypatch):
    setup_analysis(client, monkeypatch)
    generate(client)
    act(client, 'approve')
    act(client, 'publish')
    with main.connection() as db:
        db.execute("UPDATE analysis_runs SET created_at='2026-10-27T17:22:00.123456+00:00' WHERE id=1")
        db.execute("UPDATE discussion_themes SET created_at='2026-10-28T17:22:00+00:00' WHERE id=1")
    before = raw_records()
    for inactive in (False, True):
        if inactive:
            assert run_act(client, 1, 'inactive').status_code == 200
        current = current_html(client)
        summary = re.search(r'<summary>.*?</summary>', current, re.S)[0]
        assert 'Published</strong>' in summary
        assert 'From Analysis #1' in summary
        assert 'href="#analysis-1" data-open-analysis="analysis-1"' in summary
        assert 'Analysis created' in summary
        assert 'Oct 27, 2026 · 1:22 PM EDT' in summary and 'data-local-time' in summary
        assert '123456' not in summary
        assert ('Analysis inactive' in summary) == inactive
        assert raw_records() == before
    # The existing enhancement opens linked native disclosures; no new navigation script.
    script = client.get('/static/theme-workflow.js').text
    assert '[data-open-analysis]' in script and 'node.open = true' in script
    assert rows()[0]['status'] == 'published'
    assert 'From Analysis' not in public(client) and 'Analysis inactive' not in public(client)


def test_manual_and_unknown_legacy_provenance_is_honest_and_private(client, monkeypatch):
    setup_analysis(client, monkeypatch)
    create(client, 'Manual topic')
    with main.connection() as db:
        legacy_id = workflow.insert_theme(db, 1, 'Legacy AI topic', 'Preserved content.', 'ai', [1])
    act(client, 'approve', next(t for t in rows() if t['id'] == legacy_id))
    before = raw_records()
    current = current_html(client)
    assert 'Manually created' in current and 'Analysis provenance unavailable' in current
    assert 'From Analysis #' not in current
    assert 'Theme created' in current
    assert raw_records() == before
    assert client.get('/host/gatherings/2?tab=themes').status_code == 404
    with main.connection() as db:
        db.execute("INSERT INTO gatherings(id,title,description,when_text,location,agenda) VALUES (2,'Other','D','W','L','A')")
    other = client.get('/host/gatherings/2?tab=themes').text
    assert 'Legacy AI topic' not in other and 'Manual topic' not in other
    post(client, '/host/logout')
    assert client.get('/host/gatherings/1?tab=themes').status_code == 403
