import csv
import io
import sqlite3

import pytest
from fastapi.testclient import TestClient
from app import main
from tests.form_helpers import post


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, 'DB', str(tmp_path / 'test.db'))
    monkeypatch.setattr(main, 'ADMIN_PASSWORD', 'host-password')
    with TestClient(main.app) as client:
        yield client


def auth(client):
    assert post(client, '/host/login', data={'password': 'host-password'}).status_code == 200


def test_operations(client):
    post(client, '/gatherings/1/rsvp', data={'name': '=PRIVATE, "name"'})
    post(client, '/gatherings/1/questions', data={'question': 'Private question\nsecond line'})
    auth(client)
    assert post(client, '/host/gatherings/1/edit', data=dict(title='New title', description='Description', when_text='Tomorrow', location='Here')).status_code == 200
    assert 'New title' in client.get('/gatherings/1').text
    assert post(client, '/host/gatherings/1/agenda', data={'item_title': ['First', 'Second'], 'minutes': ['10', ''], 'notes': ['Public notes', '']}).status_code == 200
    page = client.get('/gatherings/1').text
    assert '10 minutes' in page and 'Public notes' in page
    assert post(client, '/host/gatherings/1/agenda', data={'item_title': ['Revised'], 'minutes': ['20'], 'notes': ['Updated']}).status_code == 200
    assert '<li>First' not in client.get('/gatherings/1').text
    assert post(client, '/host/gatherings/1/resources', data={'title': 'Reading', 'url': 'https://example.org/doc'}).status_code == 200
    assert 'https://example.org/doc' in client.get('/gatherings/1').text
    assert post(client, '/host/gatherings/1/resources/1/edit', data={'title': 'Updated resource', 'url': 'https://example.org/new'}).status_code == 200
    assert 'Updated resource' in client.get('/gatherings/1').text
    assert post(client, '/host/gatherings/1/resources/1/remove').status_code == 200
    assert 'Updated resource' not in client.get('/gatherings/1').text
    assert post(client, '/host/gatherings/1/status', data={'status': 'cancelled'}).status_code == 200
    assert 'This gathering is cancelled' in client.get('/gatherings/1').text
    assert post(client, '/gatherings/1/rsvp', data={'name': 'Blocked'}).status_code == 409
    assert post(client, '/gatherings/1/questions', data={'question': 'Blocked'}).status_code == 409
    for kind, expected in [('rsvps', "'=PRIVATE, \"name\""), ('questions', 'Private question\nsecond line')]:
        response = client.get(f'/host/gatherings/1/export/{kind}.csv')
        rows = list(csv.reader(io.StringIO(response.text)))
        assert len(rows) == 2 and rows[1][2] == expected
        assert response.headers['cache-control'] == 'no-store'
    assert post(client, '/host/gatherings/1/status', data={'status': 'active'}).status_code == 200
    assert post(client, '/gatherings/1/rsvp', data={'name': 'Restored'}).status_code == 200
    page = client.get('/gatherings/1').text
    assert 'PRIVATE' not in page and 'Private question' not in page


@pytest.mark.parametrize('suffix,data', [
    ('edit', dict(title=' ', description='D', when_text='W', location='L')),
    ('status', {'status': 'deleted'}),
    ('agenda', {'item_title': ['Valid'], 'minutes': ['0'], 'notes': ['']}),
    ('agenda', {'item_title': ['Valid'], 'minutes': [], 'notes': ['']}),
    ('resources', {'title': 'Unsafe', 'url': 'javascript:alert(1)'}),
    ('resources', {'title': 'Unsafe', 'url': 'https://user:pass@example.org'}),
])
def test_validation(client, suffix, data):
    auth(client)
    assert post(client, '/host/gatherings/1/' + suffix, data=data).status_code == 400
    assert 'Welcome and introductions' in client.get('/gatherings/1').text


@pytest.mark.parametrize('suffix', ['edit', 'status', 'agenda', 'resources', 'resources/1/edit', 'resources/1/remove', 'themes'])
def test_protection(client, suffix):
    path = '/host/gatherings/1/' + suffix
    assert client.post(path).status_code == 403
    auth(client)
    assert client.post(path).status_code == 403
    assert client.post(path, data={'csrf_token': 'bad'}).status_code == 403


def test_export_scope_and_missing(client):
    assert client.get('/host/gatherings/1/export/rsvps.csv').status_code == 403
    auth(client)
    post(client, '/host/gatherings', data=dict(title='Other', description='D', gathering_date='2099-12-01', start_time='14:00', timezone='America/New_York', location='L', agenda='A'))
    post(client, '/gatherings/2/rsvp', data={'name': 'Other private name'})
    assert 'Other private name' not in client.get('/host/gatherings/1/export/rsvps.csv').text
    assert post(client, '/host/gatherings/2/resources/1/remove').status_code == 404
    assert client.get('/host/gatherings/999/export/rsvps.csv').status_code == 404
    assert post(client, '/host/gatherings/999/agenda').status_code == 404
    assert client.get('/host/gatherings/1/export/invalid.csv').status_code == 404
    assert client.post('/host/logout').status_code == 403
    assert post(client, '/host/logout').status_code == 200
    assert client.get('/host/gatherings/1/export/questions.csv').status_code == 403


def test_legacy_migration(tmp_path, monkeypatch):
    database = tmp_path / 'legacy.db'
    with sqlite3.connect(database) as db:
        db.executescript("CREATE TABLE gatherings (id INTEGER PRIMARY KEY,title TEXT,description TEXT,when_text TEXT,location TEXT,agenda TEXT); CREATE TABLE rsvps(id INTEGER PRIMARY KEY,gathering_id INTEGER,name TEXT,created_at TEXT); CREATE TABLE questions(id INTEGER PRIMARY KEY,gathering_id INTEGER,question TEXT,created_at TEXT); INSERT INTO gatherings VALUES(7,'Legacy','D','W','L','Welcome'||char(10)||'Discussion'); INSERT INTO rsvps VALUES(3,7,'Private','timestamp'); INSERT INTO questions VALUES(4,7,'Question','timestamp');")
    monkeypatch.setattr(main, 'DB', str(database))
    main.init_db()
    main.init_db()
    with main.connection() as db:
        assert db.execute('SELECT count(*) FROM agenda_items').fetchone()[0] == 2
        assert tuple(db.execute('SELECT * FROM rsvps').fetchone()) == (3, 7, 'Private', 'timestamp')
        assert tuple(db.execute('SELECT * FROM questions').fetchone()) == (4, 7, 'Question', 'timestamp')
        assert db.execute('SELECT agenda FROM gatherings').fetchone()[0] == 'Welcome\nDiscussion'


def test_agenda_limit_and_clear(client):
    auth(client)
    data = {'item_title': ['Topic'] * 50 + [''], 'minutes': [''] * 51, 'notes': [''] * 51}
    assert post(client, '/host/gatherings/1/agenda', data=data).status_code == 200
    data['item_title'][-1] = 'Too many'
    assert post(client, '/host/gatherings/1/agenda', data=data).status_code == 400
    assert post(client, '/host/gatherings/1/agenda', data={'item_title': [''], 'minutes': [''], 'notes': ['']}).status_code == 200
    main.init_db()
    assert main.get_gathering(1)['items'] == []


def test_csrf_session_binding(client):
    import re
    token = re.search(r'name="csrf_token" value="([^"]+)"', client.get('/host').text)[1]
    with TestClient(main.app) as other:
        other.get('/host')
        assert other.post('/host/login', data={'password': 'host-password', 'csrf_token': token}).status_code == 403
    auth(client)
    assert client.post('/host/logout', data={'csrf_token': token}).status_code == 403
    assert client.post('/gatherings/1/questions', data={'question': 'Blocked'}).status_code == 403
