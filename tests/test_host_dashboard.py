"""Presentation regressions for the host dashboard; no browser scripting required."""
import re
from html.parser import HTMLParser

import pytest
from fastapi.testclient import TestClient

from app import main
from tests.form_helpers import post


class Elements(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.elements = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, 'DB', str(tmp_path / 'dashboard.db'))
    monkeypatch.setattr(main, 'ADMIN_PASSWORD', 'dashboard-password')
    with TestClient(main.app) as client:
        post(client, '/host/login', data={'password': 'dashboard-password'})
        yield client


def test_gathering_cards_show_status_time_and_manage_link(client):
    post(client, '/host/gatherings', data={
        'title': 'Cancelled <meeting>', 'description': 'Description',
        'gathering_date': '2099-12-01', 'start_time': '14:00', 'timezone': 'America/New_York', 'location': 'Library', 'agenda': 'Welcome',
    })
    post(client, '/host/gatherings/2/status', data={'status': 'cancelled'})
    page = client.get('/host').text
    cards = re.findall(r'<li class="gathering-entry">(.*?)</li>', page, re.S)
    assert len(cards) == 2
    assert 'Cancelled &lt;meeting&gt;' in cards[1]
    assert 'Dec 01, 2099' in cards[1] and 'America/New_York' in cards[1]
    assert 'Status: <strong>Cancelled</strong>' in cards[1]
    assert 'Saturday, November 14' in cards[0]
    assert 'Status: <strong>Active</strong>' in cards[0]
    for id, card in zip((1, 2), cards):
        anchors = [attrs for tag, attrs in Elements(card).elements if tag == 'a']
        assert any(a['href'] == f'/gatherings/{id}' for a in anchors)
        manage = next(a for a in anchors if a['href'] == f'/host/gatherings/{id}')
        assert 'button' in manage['class'].split()
        assert manage['aria-label'].startswith('Manage gathering: ')
        assert '>Manage gathering</a>' in card
    assert '>Host review</a>' not in page
    post(client, '/host/gatherings/2/status', data={'status': 'active'})
    assert 'Status: <strong>Cancelled</strong>' not in client.get('/host').text


def test_recent_questions_native_disclosure_and_existing_limit(client):
    page = client.get('/host').text
    assert '<h2>Recent questions (0)</h2>' in page
    assert 'No questions yet.' in page
    with main.connection() as db:
        db.executemany('INSERT INTO questions(gathering_id,question,created_at) VALUES (1,?,?)',
                       [(f'Question {i} <tag>', 'timestamp') for i in range(51)])
    page = client.get('/host').text
    details = re.search(r'<details class="recent-questions"[^>]*>.*?</details>', page, re.S)[0]
    tag, attrs = Elements(details).elements[0]
    assert tag == 'details' and 'open' not in attrs
    assert '<h2>Recent questions (50)</h2>' in details
    assert details.count('<li>') == 50
    assert 'Question 50 &lt;tag&gt;' in details
    assert 'Question 0 &lt;tag&gt;' not in details
    assert details.index('Question 50') < details.index('Question 1 ')
    assert '<h2>Recent RSVPs</h2>' in page


def test_management_heading_and_dashboard_navigation(client):
    page = client.get('/host/gatherings/1').text
    assert '<h1>The Future of Our Library</h1>' in page
    assert '<a class="back-to-dashboard" href="/host">← Back to Host dashboard</a>' in page
    assert 'Discussion Themes</a>' in page
    assert 'Suggest Discussion Themes' in client.get('/host/gatherings/1?tab=themes').text
    assert 'name="csrf_token"' in page
