"""Readable server fallback, safe templates, and unchanged UTC/event storage."""
import re

import pytest

from app import main
from app.timestamps import timestamp_display
from tests.test_theme_workflow import client, login, create, rows


@pytest.mark.parametrize('value,expected', [
    ('2026-10-27T17:22:00.123456+00:00', 'Oct 27, 2026 · 1:22 PM EDT'),
    ('2026-01-27T17:22:00Z', 'Jan 27, 2026 · 12:22 PM EST'),
    ('2026-03-08T06:59:00Z', 'Mar 8, 2026 · 1:59 AM EST'),
    ('2026-03-08T07:00:00Z', 'Mar 8, 2026 · 3:00 AM EDT'),
    ('2026-11-01T05:30:00Z', 'Nov 1, 2026 · 1:30 AM EDT'),
    ('2026-11-01T06:30:00Z', 'Nov 1, 2026 · 1:30 AM EST'),
    ('2026-10-28T01:22:00Z', 'Oct 27, 2026 · 9:22 PM EDT'),
])
def test_readable_labeled_server_fallback(value, expected, monkeypatch):
    monkeypatch.setenv('TZ', 'Asia/Tokyo')
    display = timestamp_display(value)
    assert display['label'] == expected + ' (America/New_York; fallback)'
    assert display['iso'].endswith('+00:00') and '.' not in display['iso']


@pytest.mark.parametrize('value', [None, '', 'invalid', 42, '2026-10-27',
                                  '2026-10-27T17:22:00', '2026-02-30T17:22:00Z',
                                  '<script>alert(1)</script>'])
def test_invalid_timestamps_do_not_echo_raw_input(value):
    assert timestamp_display(value) is None
    html = main.templates.get_template('macros/timestamps.html').module.timestamp(value)
    assert 'Time unavailable' in html
    assert '<time' not in html and '<script>' not in html


def test_host_dates_are_safe_and_do_not_change_storage_or_event_text(client):
    login(client)
    create(client)
    stamp = '2026-10-27T17:22:00.123456+00:00'
    event = 'Saturday, November 14 · 2:00 PM'
    with main.connection() as db:
        db.execute('UPDATE discussion_themes SET created_at=?,updated_at=?', (stamp, stamp))
        db.execute('UPDATE gatherings SET when_text=? WHERE id=1', (event,))
    before = rows()
    html = client.get('/host/gatherings/1').text
    assert html.count('Oct 27, 2026 · 1:22 PM EDT (America/New_York; fallback)') == 2
    assert '123456' not in html and 'T17:22' not in re.sub(r'datetime="[^"]*"', '', html)
    assert 'datetime="2026-10-27T17:22:00+00:00"' in html
    assert '/static/timestamps.js' in html
    assert event in html and event in client.get('/gatherings/1').text
    assert rows() == before
    with main.connection() as db:
        assert db.execute('SELECT when_text FROM gatherings WHERE id=1').fetchone()[0] == event
        db.execute("UPDATE discussion_themes SET created_at=?,updated_at=?", ('<script>alert(1)</script>', ''))
    html = client.get('/host/gatherings/1').text
    assert html.count('Time unavailable') == 2
    assert '<script>alert(1)</script>' not in html


def test_analysis_and_theme_dates_use_the_same_formatter(client, monkeypatch):
    from app import theme_workflow
    from tests.test_analysis_runs import setup_analysis, generate, runs

    setup_analysis(client, monkeypatch)
    stamp = '2026-10-27T17:22:00.123456+00:00'
    monkeypatch.setattr(theme_workflow, 'timestamp', lambda: stamp)
    create(client)
    assert generate(client).status_code == 200
    before_themes, before_runs = rows(), runs()
    html = client.get('/host/gatherings/1').text
    # Two theme Created/Updated pairs, analysis start, and analysis completion.
    assert html.count('Oct 27, 2026 · 1:22 PM EDT (America/New_York; fallback)') == 6
    assert '123456' not in html
    assert rows() == before_themes and runs() == before_runs
