"""Structured local schedules, explicit DST disambiguation, and additive migration."""
import argparse
from datetime import date, datetime, time, timezone
import os
from pathlib import Path
import re
import sqlite3
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_TIMEZONE = 'America/New_York'
SCHEDULE_COLUMNS = {
    'gathering_date': 'TEXT', 'start_time': 'TEXT', 'end_time': 'TEXT',
    'timezone': 'TEXT', 'start_fold': 'INTEGER', 'end_fold': 'INTEGER',
}


def check_integrity(db):
    if [tuple(r) for r in db.execute('PRAGMA integrity_check')] != [('ok',)]:
        raise ValueError('Database integrity check failed')
    if db.execute('PRAGMA foreign_key_check').fetchall():
        raise ValueError('Database foreign-key check failed')


def migrate_schedule(db):
    """Back up populated databases before atomic, repeatable nullable additions.

    No UPDATE/backfill: all legacy text and associated records remain untouched.
    Caller must not have an open transaction. Returns the backup path, if any.
    """
    if db.in_transaction:
        raise ValueError('Scheduling migration requires a committed connection')
    existing = {r[1] for r in db.execute('PRAGMA table_info(gatherings)')}
    if not existing:
        raise ValueError('Missing gatherings table')
    if set(SCHEDULE_COLUMNS) <= existing:
        return None
    check_integrity(db)
    backup = None
    if db.execute('SELECT COUNT(*) FROM gatherings').fetchone()[0]:
        filename = db.execute('PRAGMA database_list').fetchone()[2]
        if not filename:
            raise ValueError('A populated database must have a backup location')
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        backup = Path(filename).with_name(f'pre-scheduling-{stamp}.db')
        fd = os.open(backup, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        with sqlite3.connect(backup) as target:
            db.backup(target)
            check_integrity(target)
    try:
        db.execute('BEGIN IMMEDIATE')
        existing = {r[1] for r in db.execute('PRAGMA table_info(gatherings)')}
        for name, kind in SCHEDULE_COLUMNS.items():
            if name not in existing:
                db.execute(f'ALTER TABLE gatherings ADD COLUMN {name} {kind}')
        check_integrity(db)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return backup


def normalize_clock(value, label):
    """HTML time controls may serialize minute-aligned times with zero seconds."""
    if not re.fullmatch(r'\d{2}:\d{2}(?::00(?:\.0{1,3})?)?', value):
        raise ValueError(f'{label}: enter a valid time at minute precision (HH:MM or HH:MM:00).')
    return value[:5]


def local_instant(day, clock, zone, fold, label):
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', day):
        raise ValueError(f'{label}: enter a real date and a time in HH:MM format.')
    try:
        naive = datetime.combine(date.fromisoformat(day), time.fromisoformat(clock))
    except ValueError:
        raise ValueError(f'{label}: enter a real calendar date and valid time.') from None
    candidates = {}
    for choice in (0, 1):
        local = naive.replace(tzinfo=zone, fold=choice)
        try:
            instant = local.astimezone(timezone.utc)
            roundtrip = instant.astimezone(zone)
        except (OverflowError, ValueError):
            raise ValueError(f'{label}: this date is outside the supported timezone range.') from None
        if roundtrip.replace(tzinfo=None) == naive and roundtrip.fold == choice:
            candidates[choice] = instant
    if not candidates:
        raise ValueError(f'{label} does not exist in this timezone because of daylight saving. Choose another time.')
    if fold not in ('', '0', '1'):
        raise ValueError(f'{label}: choose a valid occurrence.')
    if len(candidates) == 2 and fold == '':
        raise ValueError(f'{label} occurs twice because of daylight saving. Choose the first or second occurrence explicitly.')
    selected = int(fold) if fold else 0
    if selected not in candidates:
        raise ValueError(f'{label}: the selected occurrence is not valid for this time.')
    return candidates[selected], selected if len(candidates) == 2 else None


class TimezoneDataError(ValueError):
    """Server configuration failure, not an invalid host-entered timezone."""


def verify_timezone_database():
    """Required reference zones fail startup if the server cannot load IANA data."""
    try:
        for name in ('America/New_York', 'Europe/London'):
            ZoneInfo(name)
    except ZoneInfoNotFoundError:
        raise TimezoneDataError('Timezone data is unavailable on the server. Ask the administrator to restore tzdata; the gathering was not saved.') from None


def resolve_timezone(value):
    # HTML text inputs preserve pasted whitespace, including nonbreaking spaces.
    name = value.strip() if isinstance(value, str) else ''
    if (not name or len(name) > 100 or name in ('localtime', 'posixrules')
            or name.startswith(('posix/', 'right/'))):
        raise ValueError('Enter a valid IANA timezone, such as America/New_York.')
    try:
        return name, ZoneInfo(name)
    except ZoneInfoNotFoundError:
        # Do not describe a missing server database as a bad user-entered name.
        verify_timezone_database()
        raise ValueError('Enter a valid IANA timezone, such as America/New_York.') from None
    except ValueError:
        raise ValueError('Enter a valid IANA timezone, such as America/New_York.') from None


def validate_schedule(gathering_date, start_time, end_time, timezone_name, start_fold='', end_fold=''):
    """Return normalized storage values and aware UTC bounds; never parse legacy text."""
    timezone_name, zone = resolve_timezone(timezone_name)
    start_time = normalize_clock(start_time, 'Start time')
    end_time = normalize_clock(end_time, 'End time') if end_time else ''
    start, first = local_instant(gathering_date, start_time, zone, start_fold, 'Start time')
    end, last = (local_instant(gathering_date, end_time, zone, end_fold, 'End time')
                 if end_time else (start, None))
    if end_time and end <= start:
        raise ValueError('End time must be after start time on the same date.')
    return dict(gathering_date=gathering_date, start_time=start_time, end_time=end_time or None,
                timezone=timezone_name, start_fold=first, end_fold=last), (start, end)


def schedule_bounds(g):
    try:
        if not all(g.get(k) for k in ('gathering_date', 'start_time', 'timezone')):
            return None, None
        return validate_schedule(g['gathering_date'], g['start_time'], g.get('end_time') or '',
                                 g['timezone'], str(g['start_fold']) if g.get('start_fold') is not None else '',
                                 str(g['end_fold']) if g.get('end_fold') is not None else '')[1]
    except (ValueError, TypeError, OverflowError):
        return None, None


def schedule_label(g):
    start, end = schedule_bounds(g)
    if start is None:
        return g.get('when_text') or 'Schedule to be confirmed'
    zone = ZoneInfo(g['timezone'])
    first = start.astimezone(zone)
    label = first.strftime('%b %d, %Y · %I:%M %p %Z (UTC%z)')
    if g.get('end_time'):
        label += end.astimezone(zone).strftime(' – %I:%M %p %Z (UTC%z)')
    return f'{label} · {g["timezone"]}'


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Back up and add nullable scheduling columns; never backfill schedules.')
    parser.add_argument('database', type=Path)
    args = parser.parse_args()
    # mode=rw forbids accidentally creating a new database at a mistyped path.
    with sqlite3.connect(f'{args.database.resolve().as_uri()}?mode=rw', uri=True) as connection:
        print(f'Backup: {migrate_schedule(connection)}')
        check_integrity(connection)
        print('Scheduling schema ready; integrity and foreign keys verified.')
