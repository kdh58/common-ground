from tests.form_helpers import post
import importlib
import os
import tempfile

from fastapi.testclient import TestClient


def test_flow():
    with tempfile.TemporaryDirectory() as d:
        os.environ['DATABASE_PATH'] = os.path.join(d, 'test.db')
        os.environ['ADMIN_PASSWORD'] = 'test-only-password'
        os.environ['SESSION_SECRET'] = 'test-only-secret-is-long-enough-123'
        import app.main as module
        module = importlib.reload(module)
        with TestClient(module.app) as client:
            assert client.get('/health').json() == {'status': 'ok'}
            assert 'The Future of Our Library' in client.get('/').text
            r = client.get('/gatherings/1')
            assert r.status_code == 200
            assert 'role="status"' not in r.text
            r = post(client, '/gatherings/1/rsvp', data={'name': 'Casey'}, follow_redirects=True)
            assert '1 RSVP(s)' in r.text
            assert ('<button type="submit">RSVP for gathering</button>'
                    '<div class="notice" role="status">Thanks! Your RSVP was recorded.</div>'
                    '</form>') in r.text
            assert 'Your question was shared' not in r.text
            r = post(client, '/gatherings/1/questions', data={'question': 'Can we host workshops?'}, follow_redirects=True)
            assert ('<button type="submit">Share my idea</button>'
                    '<div class="notice" role="status">Thank you. Your question was shared with the host.</div>'
                    '</form>') in r.text
            assert 'Your RSVP was recorded' not in r.text
            assert post(client, '/host/gatherings', data={}).status_code == 403
            assert post(client, '/host/login', data={'password': 'wrong'}).status_code == 200
            assert post(client, '/host/login', data={'password': 'test-only-password'}, follow_redirects=False).status_code == 303
            assert 'Can we host workshops?' in client.get('/host').text
            r = post(client, '/host/gatherings', follow_redirects=False, data={'title':'Neighborhood Forum','description':'Ideas', 'when_text':'Tomorrow', 'location':'Library', 'agenda':'Introductions\nDiscussion'})
            assert r.status_code == 303
            assert 'Neighborhood Forum' in client.get('/').text
