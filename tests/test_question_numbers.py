"""Display numbering is gathering-scoped and independent of theme membership."""
import csv
import io

import pytest
from fastapi.testclient import TestClient

from app import main, theme_workflow
from app.questions import load_questions
from tests.form_helpers import post, generated_notes


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, 'DB', str(tmp_path / 'numbers.db'))
    monkeypatch.setattr(main, 'ADMIN_PASSWORD', 'password')
    with TestClient(main.app) as client:
        yield client


def test_local_numbers_everywhere_preserve_identifiers(client, monkeypatch):
    with main.connection() as db:
        db.execute("INSERT INTO gatherings VALUES (2,'Other','D','W','L','A')")
        db.executemany('INSERT INTO questions VALUES (?,?,?,?)', [
            (40, 1, 'First concern', '2026-01-01'),
            (10, 1, 'Second concern', '2026-01-02'),
            (70, 1, 'Third concern', '2026-01-02'),
            (25, 2, 'Other first concern', '2026-01-01'),
            (90, 2, 'Other second concern', '2026-01-02'),
        ])
        db.execute("INSERT INTO rsvps VALUES (9,1,'Attendee','2026-01-01')")
        first = theme_workflow.insert_theme(db, 1, 'Subset', 'Third concern', 'ai', [70])
        theme_workflow.insert_theme(db, 1, 'Overlap', 'Second and third concerns', 'ai', [10, 70])
        original = [tuple(r) for r in db.execute('SELECT * FROM questions ORDER BY id')]
        assert [(q['id'], q['question_number']) for q in load_questions(db, 1)] == [(40, 1), (10, 2), (70, 3)]
        assert [(q['id'], q['question_number']) for q in load_questions(db, 2)] == [(25, 1), (90, 2)]
    post(client, '/host/login', data={'password': 'password'})
    page = client.get('/host/gatherings/1?tab=themes').text
    participants = client.get('/host/gatherings/1?tab=participants').text
    for number, text in enumerate(['First concern', 'Second concern', 'Third concern'], 1):
        assert f'#{number}: {text}' in participants
    assert page.count('Original question #3: Third concern') == 2
    assert 'Original question #1: Third concern' not in page
    assert 'Other first concern' not in page
    dashboard = client.get('/host').text
    assert 'Question #1: Other first concern' in dashboard
    assert 'Question #3: Third concern' in dashboard
    for gathering, ids in [(1, [40, 10, 70]), (2, [25, 90])]:
        response = client.get(f'/host/gatherings/{gathering}/export/questions.csv')
        exported = list(csv.DictReader(io.StringIO(response.text)))
        assert [int(r['id']) for r in exported] == ids
        assert [int(r['question_number']) for r in exported] == list(range(1, len(ids) + 1))
        assert all(int(r['gathering_id']) == gathering for r in exported)
    captured = []
    def suggest(questions, *_):
        captured.extend(questions)
        return [{'facilitation_notes': generated_notes(), 'title': 'Generated', 'description': 'The questions raise a third concern.', 'question_ids': [3]}]
    monkeypatch.setattr(main, 'suggest_themes', suggest)
    assert post(client, '/host/gatherings/1/themes').status_code == 200
    assert [q['id'] for q in captured] == [1, 2, 3]
    with main.connection() as db:
        generated = theme_workflow.load_themes(db, 1)[-1]
        assert generated['question_ids'] == [70]
    assert post(client, '/gatherings/1/questions', data={'question': 'New concern'}).status_code == 200
    with main.connection() as db:
        numbered = load_questions(db, 1)
        assert [(q['id'], q['question_number']) for q in numbered[:3]] == [(40, 1), (10, 2), (70, 3)]
        assert numbered[-1]['question_number'] == 4
        assert [tuple(r) for r in db.execute('SELECT * FROM questions WHERE id<=90 ORDER BY id')] == original
        assert db.execute('SELECT question_id FROM theme_sources WHERE theme_id=?', (first,)).fetchone()[0] == 70
        assert db.execute('SELECT name FROM rsvps WHERE id=9').fetchone()[0] == 'Attendee'
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
    main.init_db()
    assert 'Original question #3: Third concern' in client.get('/host/gatherings/1?tab=themes').text


def test_recent_limit_does_not_restart_numbers(client):
    with main.connection() as db:
        db.executemany('INSERT INTO questions VALUES (?,1,?,?)', [
            (i * 3, f'Concern {i}', '2026-01-01') for i in range(1, 56)
        ])
    post(client, '/host/login', data={'password': 'password'})
    page = client.get('/host').text
    assert 'Question #55: Concern 55' in page
    assert 'Question #6: Concern 6' in page
    assert 'Question #5: Concern 5<' not in page
    assert 'Question #1: Concern 55' not in page
