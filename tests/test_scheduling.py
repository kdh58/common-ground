"""Structured scheduling never guesses from legacy prose; databases are temporary."""
from datetime import datetime, timezone
import sqlite3

import pytest

from app import main
from app.scheduling import (migrate_schedule, check_integrity, validate_schedule,
                            schedule_bounds, schedule_label, SCHEDULE_COLUMNS)
from app.gathering_display import gathering_state, ordered_gatherings
from tests.test_host_dashboard import client
from tests.form_helpers import post


def data(**changes):
    fields = dict(title='Structured event', description='Full description', agenda='Welcome',
                  location='Library', gathering_date='2099-12-01', start_time='14:00',
                  end_time='15:00', timezone='America/New_York')
    fields.update(changes)
    return fields


def schedule(**changes):
    fields = dict(gathering_date='2026-12-05', start_time='14:00', end_time='15:00', timezone_name='America/New_York')
    fields.update(changes)
    return validate_schedule(**fields)


def test_migration_twice_backs_up_and_preserves_every_original_value(tmp_path):
    path = tmp_path / 'legacy.db'
    with sqlite3.connect(path) as db:
        db.executescript("""
        CREATE TABLE gatherings(id INTEGER PRIMARY KEY,title TEXT,when_text TEXT);
        CREATE TABLE questions(id INTEGER PRIMARY KEY,gathering_id INTEGER REFERENCES gatherings(id),question TEXT);
        CREATE TABLE analyses(id INTEGER PRIMARY KEY,notes TEXT);
        INSERT INTO gatherings VALUES(1,'Library','Saturday, November 14 · 2:00 PM');
        INSERT INTO gatherings VALUES(2,'Neighborhood','Saturday, November 21st 2:00 PM - 3:30 PM');
        INSERT INTO questions VALUES(1,1,'Keep question');
        INSERT INTO analyses VALUES(1,'Keep private notes and citations');
        """)
        before = db.execute('SELECT * FROM gatherings').fetchall()
        backup = migrate_schedule(db)
        assert backup and backup.exists()
        with sqlite3.connect(f'{backup.as_uri()}?mode=ro', uri=True) as saved:
            check_integrity(saved)
            assert saved.execute('SELECT * FROM gatherings').fetchall() == before
            assert len(saved.execute('PRAGMA table_info(gatherings)').fetchall()) == 3
        schema = db.execute("SELECT sql FROM sqlite_master WHERE name='gatherings'").fetchone()
        assert migrate_schedule(db) is None
        assert db.execute("SELECT sql FROM sqlite_master WHERE name='gatherings'").fetchone() == schema
        assert db.execute('SELECT id,title,when_text FROM gatherings').fetchall() == before
        assert db.execute('SELECT * FROM questions').fetchall() == [(1, 1, 'Keep question')]
        assert db.execute('SELECT * FROM analyses').fetchall() == [(1, 'Keep private notes and citations')]
        assert all(all(v is None for v in row) for row in db.execute('SELECT '+','.join(SCHEDULE_COLUMNS)+' FROM gatherings'))
        check_integrity(db)


@pytest.mark.parametrize('changes', [
    {'gathering_date': '2026-02-29'}, {'gathering_date': '2026-13-01'},
    {'gathering_date': '2026-2-01'}, {'start_time': '24:00'}, {'start_time': '12:60'},
    {'start_time': '12:00:15'}, {'timezone_name': 'Invalid/Zone'}, {'timezone_name': ''},
    {'timezone_name': 'localtime'}, {'end_time': '14:00'}, {'end_time': '13:00'},
    {'start_fold': 'bad'}, {'start_fold': '1'},
])
def test_validation_rejects_invalid_dates_times_zones_and_end(changes):
    with pytest.raises(ValueError):
        schedule(**changes)


def test_leap_day_optional_end_and_timezone_local_display():
    g, (start, end) = schedule(gathering_date='2028-02-29', end_time='')
    assert start == end == datetime(2028, 2, 29, 19, tzinfo=timezone.utc)
    assert g['end_time'] is None and g['start_fold'] is None
    assert '02:00 PM EST' in schedule_label(g)
    assert 'America/New_York' in schedule_label(g)
    assert schedule_bounds(g) == (start, end)


@pytest.mark.parametrize('changes,label', [
    ({'gathering_date': '2026-03-08', 'start_time': '02:30', 'end_time': ''}, 'does not exist'),
    ({'gathering_date': '2026-03-08', 'start_time': '01:30', 'end_time': '02:30'}, 'does not exist'),
    ({'gathering_date': '2026-11-01', 'start_time': '01:30', 'end_time': ''}, 'occurs twice'),
    ({'gathering_date': '2026-11-01', 'start_time': '00:30', 'end_time': '01:30'}, 'occurs twice'),
    ({'gathering_date': '2026-10-04', 'start_time': '02:15', 'end_time': '', 'timezone_name': 'Australia/Lord_Howe'}, 'does not exist'),
])
def test_dst_gap_and_repeat_require_safe_choices(changes, label):
    with pytest.raises(ValueError, match=label):
        schedule(**changes)


def test_repeat_occurrences_and_instant_end_constraint():
    g, (start, end) = schedule(gathering_date='2026-11-01', start_time='01:30', end_time='01:30', start_fold='0', end_fold='1')
    assert (end - start).total_seconds() == 3600
    assert g['start_fold'] == 0 and g['end_fold'] == 1
    assert 'EDT' in schedule_label(g) and 'EST' in schedule_label(g)
    assert schedule_bounds(g) == (start, end)
    assert gathering_state(g, end) == 'past'
    assert gathering_state(g, start) == 'upcoming'
    with pytest.raises(ValueError, match='after start'):
        schedule(gathering_date='2026-11-01', start_time='01:30', end_time='01:45', start_fold='1', end_fold='0')


def test_legacy_even_iso_text_stays_unconfirmed():
    for text in ['Saturday, November 14 · 2:00 PM', 'Saturday, November 21st 2:00 PM - 3:30 PM', '2000-01-01T00:00:00Z']:
        g = dict(when_text=text)
        assert schedule_bounds(g) == (None, None)
        assert gathering_state(g) == 'unconfirmed'
        assert schedule_label(g) == text


def test_new_create_and_edit_preserve_timezone_and_legacy_text(client):
    html = client.get('/host').text
    assert 'type="date"' in html and 'type="time"' in html
    assert 'type="hidden" name="timezone" value=""' in html
    assert '/static/scheduling.js' in html
    assert 'name="when_text"' not in html
    assert post(client, '/host/gatherings', data=data()).status_code == 200
    g = main.get_gathering(2)
    assert g['when_text'] == '' and g['gathering_date'] == '2099-12-01'
    for path in ('/', '/host', '/gatherings/2', '/host/gatherings/2'):
        page = client.get(path).text
        assert 'America/New_York' in page and '02:00 PM' in page
    assert post(client, '/host/gatherings/2/edit', data=data(timezone='Europe/London', start_time='10:00', end_time='11:00')).status_code == 200
    g = main.get_gathering(2)
    assert g['timezone'] == 'Europe/London' and g['start_time'] == '10:00'
    with main.connection() as db:
        before_text = db.execute('SELECT when_text FROM gatherings WHERE id=1').fetchone()[0]
    page = client.get('/host/gatherings/1').text
    assert 'Schedule to be confirmed. Original schedule:' in page
    assert 'type="hidden" name="timezone" value=""' in page
    assert post(client, '/host/gatherings/1/edit', data=data()).status_code == 200
    assert main.get_gathering(1)['when_text'] == before_text
    assert main.get_gathering(1)['gathering_date'] == '2099-12-01'


@pytest.mark.parametrize('changes', [dict(gathering_date='2026-02-29'), dict(end_time='13:00'), dict(timezone='Invalid/Zone'), dict(gathering_date='2026-03-08', start_time='02:30')])
def test_invalid_create_and_edit_retain_fields_without_writes(client, changes):
    with main.connection() as db:
        before = [tuple(r) for r in db.execute('SELECT * FROM gatherings')]
    for route in ('/host/gatherings', '/host/gatherings/1/edit'):
        response = post(client, route, data=data(**changes))
        assert response.status_code == 400
        assert 'Structured event' in response.text
        assert 'role="alert"' in response.text
        for field, value in changes.items():
            assert f'value="{value}"' in response.text
        with main.connection() as db:
            assert [tuple(r) for r in db.execute('SELECT * FROM gatherings')] == before


def test_new_legacy_only_post_rejected_and_empty_legacy_edit_preserved(client):
    assert post(client, '/host/gatherings', data=dict(title='Legacy', description='D', when_text='Tomorrow', location='Here', agenda='Welcome')).status_code == 422
    before = main.get_gathering(1)
    assert post(client, '/host/gatherings/1/edit', data=dict(title='Updated', description='D', location='Here')).status_code == 200
    after = main.get_gathering(1)
    assert after['when_text'] == before['when_text']
    assert after['gathering_date'] is None and after['timezone'] is None
    assert post(client, '/host/gatherings/1/edit', data=data(gathering_date='', start_time='')).status_code == 400


def test_expired_schedule_blocks_posts_preserves_records_and_direct_urls(client):
    assert post(client, '/host/gatherings', data=data()).status_code == 200
    post(client, '/gatherings/2/rsvp', data={'name': 'Preserved'})
    post(client, '/gatherings/2/questions', data={'question': 'Preserved idea'})
    assert post(client, '/host/gatherings/2/edit', data=data(gathering_date='2000-01-01', end_time='')).status_code == 200
    with main.connection() as db:
        before = {t: [tuple(r) for r in db.execute(f'SELECT * FROM {t}')] for t in ('gatherings', 'questions', 'rsvps')}
    assert 'Past Gathering' in client.get('/gatherings/2').text
    assert client.get('/host/gatherings/2').status_code == 200
    assert post(client, '/gatherings/2/rsvp', data={'name': 'Blocked'}).status_code == 409
    assert post(client, '/gatherings/2/questions', data={'question': 'Blocked'}).status_code == 409
    assert client.post('/gatherings/2/rsvp', data={'name': 'Missing CSRF'}).status_code == 403
    with main.connection() as db:
        assert {t: [tuple(r) for r in db.execute(f'SELECT * FROM {t}')] for t in before} == before


def test_aware_sorting_and_expiration_across_zones():
    a, _ = schedule(gathering_date='2026-12-05', start_time='10:00', end_time='', timezone_name='America/New_York')
    b, _ = schedule(gathering_date='2026-12-05', start_time='14:00', end_time='', timezone_name='Europe/London')
    a.update(id=1); b.update(id=2)
    now = datetime(2026, 12, 5, 13, tzinfo=timezone.utc)
    assert [g['id'] for g in ordered_gatherings([a, b], now)] == [2, 1]
    assert gathering_state(b, datetime(2026, 12, 5, 14, tzinfo=timezone.utc)) == 'past'
    assert gathering_state(a, datetime(2026, 12, 5, 14, tzinfo=timezone.utc)) == 'upcoming'
    assert gathering_state(dict(a, cancelled=True), now) == 'cancelled'


def test_partial_migration_rolls_back_schema_on_failure(tmp_path):
    path = tmp_path / 'rollback.db'
    with sqlite3.connect(path) as db:
        db.executescript("CREATE TABLE gatherings(id INTEGER PRIMARY KEY,when_text TEXT); INSERT INTO gatherings VALUES(1,'Keep original');")
        alterations = []
        def authorize(action, *args):
            if action == sqlite3.SQLITE_ALTER_TABLE:
                alterations.append(action)
                if len(alterations) == 2:
                    return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK
        db.set_authorizer(authorize)
        with pytest.raises(sqlite3.DatabaseError):
            migrate_schedule(db)
        db.set_authorizer(None)
        assert [r[1] for r in db.execute('PRAGMA table_info(gatherings)')] == ['id', 'when_text']
        assert db.execute('SELECT * FROM gatherings').fetchall() == [(1, 'Keep original')]
        assert len(list(tmp_path.glob('pre-scheduling-*.db'))) == 1
        check_integrity(db)


def test_dst_choices_are_not_accepted_through_create_or_changed_edit(client):
    repeated = data(gathering_date='2026-11-01', start_time='01:30', end_time='01:30')
    response = post(client, '/host/gatherings', data=repeated)
    assert response.status_code == 400 and 'Choose a different time' in response.text
    assert '<details class="card create-gathering" open>' in response.text
    # Old or forged occurrence fields cannot resolve a new ambiguous time.
    assert post(client, '/host/gatherings', data={**repeated, 'start_fold': '0', 'end_fold': '1'}).status_code == 400
    assert post(client, '/host/gatherings', data=data()).status_code == 200
    assert post(client, '/host/gatherings/2/edit', data={**repeated, 'start_fold': '0', 'end_fold': '1'}).status_code == 400
    assert main.get_gathering(2)['gathering_date'] == '2099-12-01'


def test_confirmed_schedule_cannot_be_cleared_and_security_is_preserved(client):
    assert post(client, '/host/gatherings', data=data()).status_code == 200
    before = main.get_gathering(2)
    assert post(client, '/host/gatherings/2/edit', data=dict(title='Updated', description='D', location='Here')).status_code == 400
    assert main.get_gathering(2)['gathering_date'] == before['gathering_date']
    assert post(client, '/host/gatherings', data=data(timezone='')).status_code == 422
    assert client.post('/host/gatherings', data=data()).status_code == 403
    post(client, '/host/logout')
    assert client.post('/host/gatherings', data=data()).status_code == 403
    assert client.post('/host/gatherings/2/edit', data=data()).status_code == 403
