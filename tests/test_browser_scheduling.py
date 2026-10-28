"""Server independently validates hidden browser timezone fields; SQLite is temporary."""
import pytest
from app import main
from tests.test_host_dashboard import client
from tests.form_helpers import post
from tests.test_schedule_persistence import EditForm


def fields(**changes):
    data = dict(title='Synthetic test event', description='Description', location='Here', agenda='Welcome',
                gathering_date='2099-12-05', start_time='14:00', end_time='15:30', timezone='Europe/London')
    data.update(changes)
    return data


def test_scheduling_ui_has_only_three_visible_inputs(client):
    for path in ('/host', '/host/gatherings/1'):
        html = client.get(path).text
        assert 'type="hidden" name="timezone"' in html
        assert 'name="start_fold"' not in html and 'name="end_fold"' not in html
        assert 'Start time occurrence' not in html and 'IANA timezone</label>' not in html
        assert 'Change timezone</button>' in html
        assert '/static/scheduling.js' in html
    assert 'data-saved-timezone=""' in client.get('/host').text


@pytest.mark.parametrize('zone', [None, '', 'Invalid/Zone'])
def test_schedule_with_missing_or_invalid_hidden_timezone_rejected(client, zone):
    data = fields(timezone=zone)
    if zone is None:
        data.pop('timezone')
    for path in ('/host/gatherings', '/host/gatherings/1/edit'):
        response = post(client, path, data=data)
        assert response.status_code in (400, 422)
        assert 'role="alert"' in response.text
    assert main.get_gathering(1)['gathering_date'] is None
    with main.connection() as db:
        assert db.execute('SELECT COUNT(*) FROM gatherings').fetchone()[0] == 1


def test_hidden_timezone_persists_and_explicit_change_never_shifts_wall_clock(client):
    assert post(client, '/host/gatherings', data=fields()).status_code == 200
    form = EditForm(client.get('/host/gatherings/2').text)
    assert form.fields['timezone'] == 'Europe/London'
    assert 'data-saved-timezone="Europe/London"' in client.get('/host/gatherings/2').text
    assert post(client, '/host/gatherings/2/edit', data={**form.fields, 'timezone': 'America/New_York'}).status_code == 200
    for path in ('/host', '/host/gatherings/2', '/host/gatherings/2'):
        assert client.get(path).status_code == 200
    reloaded = EditForm(client.get('/host/gatherings/2').text)
    assert reloaded.fields['timezone'] == 'America/New_York'
    assert reloaded.fields['start_time'] == '14:00' and reloaded.fields['end_time'] == '15:30'
    assert reloaded.fields['gathering_date'] == '2099-12-05'


@pytest.mark.parametrize('day,start,end', [('2026-03-08', '02:30', '04:00'),
    ('2026-11-01', '01:30', '03:00'), ('2026-11-01', '00:30', '01:30')])
def test_new_or_changed_dst_times_rejected_even_with_forged_occurrence(client, day, start, end):
    bad = fields(gathering_date=day, start_time=start, end_time=end, timezone='America/New_York', start_fold='0', end_fold='1')
    response = post(client, '/host/gatherings', data=bad)
    assert response.status_code == 400 and 'Choose a different time' in response.text
    assert post(client, '/host/gatherings', data=fields()).status_code == 200
    before = main.get_gathering(2)
    response = post(client, '/host/gatherings/2/edit', data=bad)
    assert response.status_code == 400 and 'Choose a different time' in response.text
    after = main.get_gathering(2)
    assert after['gathering_date'] == before['gathering_date']
    assert after['timezone'] == before['timezone']


def test_preexisting_ambiguous_schedule_preserves_saved_instant_on_details_edit(client):
    # Existing stored DST resolutions remain readable and cannot be changed via hidden folds.
    with main.connection() as db:
        db.execute("UPDATE gatherings SET gathering_date='2026-11-01',start_time='01:30',end_time='01:30',timezone='America/New_York',start_fold=0,end_fold=1 WHERE id=1")
    form = EditForm(client.get('/host/gatherings/1').text, id=1)
    assert 'start_fold' not in form.fields
    response = post(client, '/host/gatherings/1/edit', data={**form.fields, 'title': 'Updated title', 'start_fold': '1', 'end_fold': '0'})
    assert response.status_code == 200
    g = main.get_gathering(1)
    assert g['start_fold'] == 0 and g['end_fold'] == 1
    assert g['when_text'] == 'Saturday, November 14 · 2:00 PM'


def test_auto_initialized_zone_alone_does_not_confirm_or_break_legacy_details_edit(client):
    assert post(client, '/host/gatherings/1/edit', data=dict(title='Title', description='D', location='Here', timezone='Europe/London')).status_code == 200
    g = main.get_gathering(1)
    assert g['timezone'] is None and g['gathering_date'] is None
    assert g['when_text'] == 'Saturday, November 14 · 2:00 PM'
