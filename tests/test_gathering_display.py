"""List presentation uses synthetic records in temporary test databases only."""
from datetime import datetime, timezone
import pytest
from app.gathering_display import description_preview, ordered_gatherings
from tests.test_host_dashboard import client
from tests.form_helpers import post
from app import main


def scheduled(iso, **extra):
    """Explicit structured synthetic fixtures, not legacy inference in the app."""
    row = dict(when_text=iso, **extra)
    try:
        dates = [datetime.fromisoformat(part).astimezone(timezone.utc)
                 for part in iso.split('/') if datetime.fromisoformat(part).tzinfo]
        if not dates:
            return row
        row.update(gathering_date=dates[0].strftime('%Y-%m-%d'),
                   start_time=dates[0].strftime('%H:%M'), timezone='UTC',
                   end_time=dates[1].strftime('%H:%M') if len(dates) == 2 else None)
    except ValueError:
        pass
    return row


def set_schedule(db, id, iso):
    g = scheduled(iso)
    db.execute('UPDATE gatherings SET gathering_date=?,start_time=?,end_time=?,timezone=? WHERE id=?',
               (g['gathering_date'], g['start_time'], g.get('end_time'), g['timezone'], id))


def test_order_explicit_offsets_past_unknown_and_cancelled():
    dates = ['2026-11-01T01:30:00-05:00', '2026-11-01T01:30:00-04:00',
             '2026-10-27T12:00:00Z', 'Tomorrow', '2026-11-02T00:00:00',
             '2026-11-01T01:30:00-04:00', '2026-11-01T00:00:00Z']
    rows = [scheduled(date, id=i, cancelled=i == 6) for i, date in enumerate(dates)]
    original = [dict(row) for row in rows]
    assert [g['id'] for g in ordered_gatherings(rows, datetime(2026, 10, 28, tzinfo=timezone.utc))] == [1, 5, 0, 2, 3, 4, 6]
    assert rows == original


@pytest.mark.parametrize('value, expected', [
    ('# Hello **neighbors** [join](https://example.com) `today`', 'Hello neighbors join today'),
    ('<script>alert(1)</script> _words_', 'alert(1) words'),
    ('short description', 'short description'),
])
def test_plain_preview(value, expected):
    assert description_preview(value) == expected


def test_preview_word_boundary_and_length():
    preview = description_preview('community gathering ' * 30)
    assert 160 <= len(preview) <= 200
    assert preview.endswith('…')
    assert preview[:-1].split()[-1] in ('community', 'gathering')


@pytest.mark.parametrize('invalid, status', [({'title': ' '}, 400), ({'title': 'x' * 121}, 400), ({'agenda': None}, 422)])
def test_create_errors_expand_and_preserve_fields_without_writing(client, invalid, status):
    data = dict(title='Keep <title>', description='Keep **description**', gathering_date='2099-12-01', start_time='14:00', timezone='America/New_York', location='Library', agenda='Welcome')
    data.update(invalid)
    data = {key: value for key, value in data.items() if value is not None}
    with main.connection() as db:
        before = db.execute('SELECT COUNT(*) FROM gatherings').fetchone()[0]
    response = post(client, '/host/gatherings', data=data)
    assert response.status_code == status
    assert '<details class="card create-gathering" open>' in response.text
    assert 'Keep **description**' in response.text
    assert 'role="alert"' in response.text
    with main.connection() as db:
        assert db.execute('SELECT COUNT(*) FROM gatherings').fetchone()[0] == before


def test_twenty_four_cards_full_description_and_preserved_routes(client):
    description = '**Neighbors** ' + 'discuss community priorities together ' * 20
    with main.connection() as db:
        db.executemany('INSERT INTO gatherings(title,description,when_text,location,agenda) VALUES (?,?,?,?,?)',
                       [(f'Event {i}', description, 'Tomorrow at noon', 'Library', 'Welcome') for i in range(23)])
    home = client.get('/').text
    host = client.get('/host').text
    assert home.count('class="gathering-entry"') == 5
    assert host.count('class="gathering-entry"') == 5
    assert '**Neighbors**' not in home
    assert description in client.get('/gatherings/2').text
    assert '0 questions · 0 RSVPs' in host
    assert '<details class="card create-gathering">' in host
    all_home = ''.join(client.get(f'/?unconfirmed_page={page}').text for page in range(1, 6))
    all_host = ''.join(client.get(f'/host?unconfirmed_page={page}').text for page in range(1, 6))
    for i in range(1, 25):
        assert f'href="/gatherings/{i}"' in all_home
        assert f'href="/host/gatherings/{i}"' in all_host
    assert 'Page 5 of 5' in client.get('/?unconfirmed_page=5').text

from app.gathering_display import schedule_bounds, gathering_state, listing_sections
from starlette.requests import Request


def test_lifecycle_end_boundary_and_offset_equivalence():
    row = scheduled('2026-11-01T01:30:00-04:00/2026-11-01T01:30:00-05:00', id=1, cancelled=0)
    assert gathering_state(row, datetime(2026, 11, 1, 6, 29, 59, tzinfo=timezone.utc)) == 'upcoming'
    assert gathering_state(row, datetime(2026, 11, 1, 6, 30, tzinfo=timezone.utc)) == 'past'
    row = scheduled('2026-11-01T01:30:00-05:00', id=1, cancelled=0)
    assert gathering_state(row, datetime(2026, 11, 1, 6, 30, tzinfo=timezone.utc)) == 'past'
    assert gathering_state(dict(row, cancelled=1)) == 'cancelled'


@pytest.mark.parametrize('value', ['Tomorrow', '', '2026-12-05T12:00:00',
    '2026-12-05T12:00:00Z/2026-12-04T12:00:00Z', '2026-12-05',
    '2026-12-05T12:00:00Z/bad', 'a/b/c'])
def test_unknown_schedules_are_not_assigned_timezone_or_year(value):
    assert schedule_bounds({'when_text': value}) == (None, None)
    assert gathering_state(dict(cancelled=0, when_text=value)) == 'unconfirmed'


@pytest.mark.parametrize('value, expected', [('', 1), ('bad', 1), ('0', 1), ('-3', 1), ('999', 3), ('2', 2)])
def test_pagination_safe_and_independent(value, expected):
    rows = [scheduled('2099-12-01T12:00:00Z', id=i, cancelled=0) for i in range(12)]
    request = Request({'type': 'http', 'query_string': f'upcoming_page={value}&past_page=2'.encode()})
    sections = listing_sections(rows, request, host=True)
    section = sections[0]
    assert section['page'] == expected
    assert section['pages'] == 3
    assert [g['id'] for g in section['entries']] == list(range((expected - 1) * 5, min(expected * 5, 12)))
    link = section['next'] or section['previous']
    assert 'past_page=2' in link and link.endswith('#upcoming-gatherings-heading')
    assert sections[2]['page'] == sections[2]['pages'] == 1


def test_past_and_canceled_urls_closed_submissions_and_data_preservation(client):
    with main.connection() as db:
        for title, when in [('Past event', '2000-01-01T12:00:00Z'), ('Future event', '2099-12-01T12:00:00Z'), ('Canceled event', '2099-12-02T12:00:00Z')]:
            db.execute('INSERT INTO gatherings(title,description,when_text,location,agenda) VALUES (?,?,?,?,?)', (title, 'Full description', when, 'Library', 'Welcome'))
        for id, iso in [(2, '2000-01-01T12:00:00Z'), (3, '2099-12-01T12:00:00Z'), (4, '2099-12-02T12:00:00Z')]:
            set_schedule(db, id, iso)
        db.execute('INSERT INTO gathering_status(gathering_id,cancelled) VALUES (4,1)')
        db.execute("INSERT INTO questions(gathering_id,question,created_at) VALUES (2,'Preserved question','now')")
        db.execute("INSERT INTO rsvps(gathering_id,name,created_at) VALUES (2,'Preserved RSVP','now')")
        before = {table: [tuple(r) for r in db.execute(f'SELECT * FROM {table}')] for table in ('gatherings', 'gathering_status', 'questions', 'rsvps')}
    home = client.get('/').text
    assert 'Future event' in home and 'Past event' in home and 'Canceled event' not in home
    host = client.get('/host').text
    assert 'Past gatherings' in host and 'Canceled gatherings' in host
    assert 'Past event' in host and 'Canceled event' in host
    for id in (2, 4):
        page = client.get(f'/gatherings/{id}').text
        assert 'Past Gathering' in page if id == 2 else 'This gathering is cancelled' in page
        assert 'RSVP for gathering' not in page and 'Share my idea' not in page
        workspace = client.get(f'/host/gatherings/{id}')
        assert workspace.status_code == 200
        if id == 2:
            assert 'Past Gathering' in workspace.text
        assert post(client, f'/gatherings/{id}/rsvp', data={'name': 'Blocked'}).status_code == 409
        assert post(client, f'/gatherings/{id}/questions', data={'question': 'Blocked'}).status_code == 409
    with main.connection() as db:
        after = {table: [tuple(r) for r in db.execute(f'SELECT * FROM {table}')] for table in before}
    assert before == after
    assert client.post('/gatherings/2/rsvp', data={'name': 'No token'}).status_code == 403
    post(client, '/host/logout')
    assert client.get('/host/gatherings/2').status_code == 403
    assert client.get('/gatherings/2').status_code == 200


def test_restoring_past_event_does_not_reopen_participation(client):
    with main.connection() as db:
        db.execute("INSERT INTO gatherings(title,description,when_text,location,agenda) VALUES ('Past','Description','2000-01-01T00:00:00Z','Library','Welcome')")
        set_schedule(db, 2, '2000-01-01T00:00:00Z')
        db.execute('INSERT INTO gathering_status(gathering_id,cancelled) VALUES (2,1)')
    assert 'Past Gathering' in client.get('/gatherings/2').text
    post(client, '/host/gatherings/2/status', data={'status': 'active'})
    assert 'Past Gathering' in client.get('/gatherings/2').text
    assert post(client, '/gatherings/2/rsvp', data={'name': 'Blocked'}).status_code == 409
    assert post(client, '/gatherings/2/questions', data={'question': 'Blocked'}).status_code == 409


def test_equal_instants_use_ids_even_with_different_offsets():
    rows = [scheduled('2099-12-01T12:00:00Z', id=2, cancelled=0),
            scheduled('2099-12-01T07:00:00-05:00', id=1, cancelled=0)]
    assert [g['id'] for g in ordered_gatherings(rows)] == [1, 2]


@pytest.mark.parametrize('title,schedule', [
    ('The Future of Our Library', 'Saturday, November 14 · 2:00 PM'),
    ('The Future of Our Neighborhood', 'Saturday, November 21st 2:00 PM - 3:30 PM'),
])
def test_original_november_schedules_remain_unconfirmed_and_unchanged(title, schedule):
    row = dict(id=1, title=title, cancelled=0, when_text=schedule)
    request = Request({'type': 'http', 'query_string': b''})
    sections = listing_sections([row], request)
    assert sections[1]['count'] == 1
    assert sections[1]['entries'][0]['when_text'] == schedule
    assert row['when_text'] == schedule
    assert schedule_bounds({'when_text': schedule}) == (None, None)
    assert gathering_state(row) == 'unconfirmed'


def directory_details(html):
    from tests.test_host_dashboard import Elements
    return [attrs for tag, attrs in Elements(html).elements
            if tag == 'details' and attrs.get('class') == 'gathering-directory']


@pytest.mark.parametrize('route, expected', [('/', 3), ('/host', 4)])
def test_accordion_defaults_counts_empty_states_and_single_page_navigation(client, route, expected):
    html = client.get(route).text
    details = directory_details(html)
    assert len(details) == expected
    assert 'open' in details[0]
    assert all('open' not in attrs for attrs in details[1:])
    assert 'Upcoming gatherings <span class="section-count">(0)</span>' in html
    assert 'Schedule to be confirmed <span class="section-count">(1)</span>' in html
    assert 'Past gatherings <span class="section-count">(0)</span>' in html
    assert 'No upcoming gatherings.' in html
    assert 'No past gatherings.' in html
    assert 'class="gathering-pagination"' not in html
    assert 'Page 1 of 1' not in html
    assert 'Previous' not in html and 'Next →' not in html
    if route == '/':
        assert 'Canceled gatherings' not in html
        assert 'Good things begin when we gather.' in html
    else:
        assert '<details class="card create-gathering">' in html
        assert '<summary>Recent questions and RSVPs</summary>' in html


@pytest.mark.parametrize('route', ['/', '/host'])
def test_accordion_pagination_reopens_target_and_scrolls_to_summary(client, route):
    # Synthetic fixture records live only in the per-test temporary database.
    with main.connection() as db:
        db.executemany('INSERT INTO gatherings(title,description,when_text,location,agenda) VALUES (?,?,?,?,?)',
                       [(f'Past {i}', 'Description', '2000-01-01T12:00:00Z', 'Library', 'Welcome') for i in range(6)])
        for id in range(2, 8):
            set_schedule(db, id, '2000-01-01T12:00:00Z')
    first = client.get(route).text
    assert first.count('class="gathering-pagination"') == 2
    assert first.count('Page 1 of 2') == 2
    import re
    from html import unescape
    link = unescape(re.search(r'href="([^"]+)" rel="next"', first)[1])
    assert link.startswith(route + '?')
    assert 'past_page=2' in link and 'open_section=past' in link
    assert link.endswith('#past-gatherings-heading')
    second = client.get(link).text
    assert second.count('Page 2 of 2') == 2
    assert second.count('Past 5') == 2  # title and accessible link label
    details = directory_details(second)
    assert 'open' in next(attrs for attrs in details if attrs['id'] == 'past-gatherings')
    assert '<summary id="past-gatherings-heading">' in second
    assert 'Past gatherings <span class="section-count">(6)</span>' in second
    invalid = client.get(route + '?past_page=bad').text
    assert 'Page 1 of 2' in invalid
    assert 'open' in next(attrs for attrs in directory_details(invalid) if attrs['id'] == 'past-gatherings')


def test_empty_unconfirmed_section_and_invalid_open_target(client):
    # No database edits: exercise empty sections directly with presentation helpers.
    request = Request({'type': 'http', 'query_string': b'open_section=%3Cscript%3E'})
    sections = listing_sections([], request, host=True)
    assert [s['count'] for s in sections] == [0, 0, 0, 0]
    assert [s['expanded'] for s in sections] == [True, False, False, False]
    html = main.templates.get_template('macros/gathering_lists.html').module.directory(sections, True)
    assert 'No gatherings awaiting schedule confirmation.' in html
    assert 'No canceled gatherings.' in html
    assert 'class="gathering-pagination"' not in html
