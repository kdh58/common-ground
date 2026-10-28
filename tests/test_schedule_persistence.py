"""Rendered-form regressions use temporary SQLite files, never the live volume."""
from datetime import datetime, timezone
from html.parser import HTMLParser
import sqlite3
from urllib.parse import urlsplit

import pytest

from app import main, gathering_display
from app.scheduling import validate_schedule
from tests.test_host_dashboard import client


class EditForm(HTMLParser):
    """Collect the actual controls and selected values, including Automatic=''."""
    def __init__(self, html, id=2):
        super().__init__()
        self.fields = {}
        self.active = False
        self.textarea = None
        self.select = None
        self.path = f'/host/gatherings/{id}/edit'
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'form':
            self.active = urlsplit(attrs.get('action', '')).path == self.path
            if self.active:
                self.action = attrs['action']
        if not self.active:
            return
        if tag == 'input' and 'name' in attrs:
            self.fields[attrs['name']] = attrs.get('value', '')
        if tag == 'textarea':
            self.textarea = attrs['name']
            self.fields[self.textarea] = ''
        if tag == 'select':
            self.select = attrs['name']
        if tag == 'option' and self.select:
            if self.select not in self.fields or 'selected' in attrs:
                self.fields[self.select] = attrs.get('value', '')

    def handle_data(self, value):
        if self.active and self.textarea:
            self.fields[self.textarea] += value

    def handle_endtag(self, tag):
        if tag == 'textarea':
            self.textarea = None
        if tag == 'select':
            self.select = None
        if tag == 'form':
            self.active = False


@pytest.fixture
def neighborhood(client, monkeypatch):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 10, 28, 12, tzinfo=timezone.utc).astimezone(tz)
    monkeypatch.setattr(gathering_display, 'datetime', Clock)
    with main.connection() as db:
        db.execute('''INSERT INTO gatherings(id,title,description,when_text,location,agenda)
            VALUES (2,'The Future of Our Neighborhood','Preserved description',
            'Saturday, November 21st 2:00 PM - 3:30 PM','Recreation Center','Welcome')''')
        db.execute("INSERT INTO questions(gathering_id,question,created_at) VALUES (2,'Keep question','timestamp')")
        db.execute("INSERT INTO rsvps(gathering_id,name,created_at) VALUES (2,'Keep RSVP','timestamp')")
    return EditForm(client.get('/host/gatherings/2').text)


def records():
    with main.connection() as db:
        tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        return {table: [tuple(r) for r in db.execute(f'SELECT * FROM "{table}"')] for table in tables}


def submission(form, start='14:00', end='15:30'):
    return {**form.fields, 'gathering_date': '2026-12-05', 'start_time': start,
            'end_time': end, 'timezone': 'America/New_York'}


@pytest.mark.parametrize('start,end', [('14:00', '15:30'), ('14:00:00', '15:30:00'),
                                       ('14:00:00.000', '15:30:00.0')])
def test_reported_edit_commits_and_repopulates_on_new_gets(client, neighborhood, start, end):
    before = records()
    assert 'start_fold' not in neighborhood.fields and 'end_fold' not in neighborhood.fields
    response = client.post(neighborhood.action, data=submission(neighborhood, start, end), follow_redirects=False)
    assert response.status_code == 303
    assert response.headers['location'].endswith('#details-feedback')
    # A separate SQLite connection verifies a commit, independently of GET rendering.
    with sqlite3.connect(main.DB) as db:
        assert db.execute('SELECT gathering_date,start_time,end_time,timezone,start_fold,end_fold FROM gatherings WHERE id=2').fetchone() == ('2026-12-05', '14:00', '15:30', 'America/New_York', None, None)
    landing = client.get(response.headers['location'])
    assert 'role="status"' in landing.text and 'Gathering details saved.' in landing.text
    for path in ('/host', '/host/gatherings/2?tab=participants', '/host/gatherings/2', '/host/gatherings/2'):
        page = client.get(path)
        assert page.status_code == 200
        if urlsplit(path).path == '/host/gatherings/2' and 'participants' not in path:
            form = EditForm(page.text)
            for key, value in dict(gathering_date='2026-12-05', start_time='14:00', end_time='15:30', timezone='America/New_York').items():
                assert form.fields[key] == value
            assert 'start_fold' not in form.fields and 'end_fold' not in form.fields
    home = client.get('/host').text
    upcoming = home.split('id="upcoming-gatherings"', 1)[1].split('</details>', 1)[0]
    assert 'The Future of Our Neighborhood' in upcoming
    assert 'Dec 05, 2026' in upcoming and '02:00 PM' in upcoming and '03:30 PM' in upcoming
    assert 'America/New_York' in upcoming
    after = records()
    assert all(after[t] == rows for t, rows in before.items() if t != 'gatherings')
    assert after['gatherings'][0] == before['gatherings'][0]
    assert after['gatherings'][1][:6] == before['gatherings'][1][:6]


@pytest.mark.parametrize('changes,status', [({'end_time': '13:30:00'}, 400),
    ({'start_time': '14:00:30'}, 400), ({'timezone': 'Invalid/Zone'}, 400),
    ({'description': None}, 422), ({'gathering_date': '2026-02-30'}, 400)])
def test_failed_edit_prominent_feedback_retains_entries_and_writes_nothing(client, neighborhood, changes, status):
    fields = submission(neighborhood, '14:00:00', '15:30:00')
    fields.update(changes)
    fields = {key: value for key, value in fields.items() if value is not None}
    before = records()
    response = client.post(neighborhood.action, data=fields)
    assert response.status_code == status
    assert 'Details were not saved.' in response.text
    assert 'id="details-feedback" role="alert" tabindex="-1"' in response.text
    assert 'aria-describedby="details-feedback"' in response.text
    assert 'Review the validation error above' in response.text
    assert 'Gathering details saved.' not in response.text
    rendered = EditForm(response.text)
    for key in ('gathering_date', 'start_time', 'end_time', 'timezone'):
        assert rendered.fields[key] == fields[key]
    assert records() == before


def test_success_flash_cannot_be_triggered_by_query_and_is_consumed_once(client, neighborhood):
    assert 'Gathering details saved.' not in client.get('/host/gatherings/2?saved=details').text
    response = client.post(neighborhood.action, data=submission(neighborhood), follow_redirects=False)
    assert response.status_code == 303
    assert 'Gathering details saved.' in client.get(response.headers['location']).text
    assert 'Gathering details saved.' not in client.get(response.headers['location']).text


@pytest.mark.parametrize('precision', ['', ':00', ':00.000'])
def test_zero_seconds_normalize_in_create_workflow(client, precision):
    from tests.form_helpers import post
    response = post(client, '/host/gatherings', data=dict(title='Synthetic test event', description='D',
        agenda='Welcome', location='Here', gathering_date='2099-12-05', start_time='14:00'+precision,
        end_time='15:30'+precision, timezone='America/New_York', start_fold='', end_fold=''))
    assert response.status_code == 200
    assert main.get_gathering(2)['start_time'] == '14:00'
    assert main.get_gathering(2)['end_time'] == '15:30'
    assert EditForm(client.get('/host/gatherings/2').text).fields['start_time'] == '14:00'


@pytest.mark.parametrize('clock', ['14:00:01', '14:00:00.001', '14:00:60', '24:00:00'])
def test_non_minute_or_invalid_times_are_not_silently_rounded(clock):
    with pytest.raises(ValueError):
        validate_schedule('2026-12-05', clock, '', 'America/New_York')
