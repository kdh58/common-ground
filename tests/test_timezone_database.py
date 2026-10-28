"""Run in the built Docker image too; never mount host source over /project/app."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from app import scheduling, main
from app.scheduling import validate_schedule, verify_timezone_database, TimezoneDataError
from tests.test_host_dashboard import client
from tests.form_helpers import post


@pytest.mark.parametrize('zone,winter,summer', [('America/New_York', -5, -4), ('Europe/London', 0, 1)])
def test_actual_iana_data_has_winter_and_summer_rules(zone, winter, summer):
    tz = ZoneInfo(zone)
    assert datetime(2026, 1, 15, 12, tzinfo=tz).utcoffset().total_seconds() == winter * 3600
    assert datetime(2026, 7, 15, 12, tzinfo=tz).utcoffset().total_seconds() == summer * 3600
    verify_timezone_database()


@pytest.mark.parametrize('name,expected', [('America/New_York', 'America/New_York'),
    (' Europe/London ', 'Europe/London'), ('\tAmerica/New_York\r\n', 'America/New_York'),
    ('\u00a0America/New_York\u00a0', 'America/New_York')])
def test_timezone_whitespace_normalization(name, expected):
    g, (start, end) = validate_schedule('2026-12-05', '14:00', '15:30', name)
    assert g['timezone'] == expected
    assert start.tzinfo == timezone.utc
    assert (end-start).total_seconds() == 5400


@pytest.mark.parametrize('name', ['', '  ', '\u00a0', 'Invalid/Zone', 'America/New York',
    'america/new_york', 'localtime', 'posixrules', '/usr/share/zoneinfo/Europe/London',
    '../Europe/London', 'posix/Europe/London', 'right/Europe/London'])
def test_invalid_names_are_rejected_not_replaced_with_utc(name):
    with pytest.raises(ValueError, match='valid IANA timezone'):
        validate_schedule('2026-12-05', '14:00', '', name)


def test_resolver_uses_zoneinfo_not_global_enumeration(monkeypatch):
    import zoneinfo
    monkeypatch.setattr(zoneinfo, 'available_timezones', lambda: set())
    assert validate_schedule('2026-12-05', '14:00', '', 'America/New_York')[0]['timezone'] == 'America/New_York'


def no_timezone_data(name):
    from zoneinfo import ZoneInfoNotFoundError
    raise ZoneInfoNotFoundError(name)


def test_missing_database_is_an_explicit_configuration_failure(monkeypatch):
    monkeypatch.setattr(scheduling, 'ZoneInfo', no_timezone_data)
    with pytest.raises(TimezoneDataError, match='unavailable on the server'):
        verify_timezone_database()
    with pytest.raises(TimezoneDataError, match='restore tzdata'):
        validate_schedule('2026-12-05', '14:00', '', 'America/New_York')
    called = []
    monkeypatch.setattr(main, 'init_db', lambda: called.append('database touched'))
    with pytest.raises(TimezoneDataError):
        main.on_startup()
    assert called == []


@pytest.mark.parametrize('zone', [' America/New_York ', '\u00a0Europe/London\u00a0'])
def test_create_and_edit_normalize_pasted_zone_names(client, zone):
    fields = dict(title='Synthetic test event', description='D', location='Here', agenda='Welcome',
                  gathering_date='2099-12-05', start_time='14:00', end_time='15:30', timezone=zone)
    assert post(client, '/host/gatherings', data=fields).status_code == 200
    assert main.get_gathering(2)['timezone'] == zone.strip()
    fields['timezone'] = ' Europe/London '
    assert post(client, '/host/gatherings/2/edit', data=fields).status_code == 200
    assert main.get_gathering(2)['timezone'] == 'Europe/London'
    assert 'value="Europe/London"' in client.get('/host/gatherings/2').text


@pytest.mark.parametrize('route', ['/host/gatherings', '/host/gatherings/1/edit'])
def test_missing_server_data_retains_input_with_503_and_no_writes(client, monkeypatch, route):
    with main.connection() as db:
        before = [tuple(r) for r in db.execute('SELECT * FROM gatherings')]
    monkeypatch.setattr(scheduling, 'ZoneInfo', no_timezone_data)
    response = post(client, route, data=dict(title='Keep title', description='Keep description',
        location='Here', agenda='Welcome', gathering_date='2099-12-05', start_time='14:00',
        end_time='15:30', timezone='America/New_York'))
    assert response.status_code == 503
    assert 'Timezone data is unavailable on the server' in response.text
    assert 'role="alert"' in response.text
    assert 'value="America/New_York"' in response.text
    assert 'value="2099-12-05"' in response.text
    with main.connection() as db:
        assert [tuple(r) for r in db.execute('SELECT * FROM gatherings')] == before
