"""Explicit local-demo seeder. Never imported by startup or migrations; dry-run default."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from urllib.parse import urlsplit

from app.scheduling import check_integrity, validate_schedule

REGISTRY = 'demonstration_seed_items'
QUESTION_LABEL = '[Fictional demo] '
NOTE = 'Fictional demonstration agenda, not a record of real community participation.'
MANIFEST = Path(__file__).with_name('demo_gatherings.json')
REQUIRED = {
    'gatherings': {'id', 'title', 'description', 'when_text', 'location', 'agenda', 'gathering_date',
                   'start_time', 'end_time', 'timezone', 'start_fold', 'end_fold'},
    'questions': {'id', 'gathering_id', 'question', 'created_at'},
    'agenda_items': {'id', 'gathering_id', 'position', 'title', 'minutes', 'notes'},
    'resources': {'id', 'gathering_id', 'title', 'url'},
    'rsvps': {'id', 'gathering_id', 'name', 'created_at'},
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def quote(name):
    return '"' + name.replace('"', '""') + '"'


def encoded(value):
    if isinstance(value, bytes):
        return {'sqlite_blob_hex': value.hex()}
    if isinstance(value, (list, tuple)):
        return [encoded(item) for item in value]
    return value


def json_text(value):
    return json.dumps(encoded(value), ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def database_state(db):
    """Logical snapshot includes all table values and schema, including unrelated data."""
    schema = db.execute('SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name').fetchall()
    tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    rows = {table: sorted(json_text(row) for row in db.execute('SELECT * FROM '+quote(table))) for table in tables}
    return {'schema': [json_text(row) for row in schema], 'rows': rows}


def fingerprint(state):
    return hashlib.sha256(json_text(state).encode()).hexdigest()


def read_database(path):
    db = sqlite3.connect(path.resolve().as_uri()+'?mode=ro', uri=True)
    db.execute('PRAGMA query_only=ON')
    return db


def check_schema(db):
    for table, fields in REQUIRED.items():
        actual = {r[1] for r in db.execute('PRAGMA table_info('+quote(table)+')')}
        require(fields <= actual, f'Missing application schema in {table}; run approved migrations separately.')
    require(not db.execute("SELECT name FROM sqlite_master WHERE type='trigger'").fetchall(),
            'Unexpected triggers: review them before seeding.')


def manifest():
    data = json.loads(MANIFEST.read_text())
    seen = set()
    require(len(data['gatherings']) == 5, 'Expected exactly five demo gatherings')
    for g in data['gatherings']:
        require(g['key'] not in seen, 'Duplicate seed key')
        seen.add(g['key'])
        require('Fictional' in g['description'] and 'Fictional' in g['location'], 'Missing demonstration labels')
        require(len(g['title']) <= 120 and len(g['description']) <= 1000 and len(g['location']) <= 120, 'Content exceeds form limits')
        require(len(g['agenda']) == 6 and sum(item[1] for item in g['agenda']) == 90, 'Invalid agenda')
        require(all(0 < item[1] <= 1440 and len(item[0]) <= 200 for item in g['agenda']), 'Invalid agenda item')
        require(len(g['questions']) == len(set(g['questions'])) == 12, 'Expected twelve distinct questions')
        require(all(len(QUESTION_LABEL+q) <= 500 for q in g['questions']), 'Question exceeds form limit')
        require(2 <= len(g['resources']) <= 3, 'Expected two or three verified resources')
        require(all(urlsplit(url).scheme == 'https' and urlsplit(url).hostname and not urlsplit(url).username
                    for _, url in g['resources']), 'Invalid resource URL')
        schedule, (start, end) = validate_schedule(g['date'], g['start'], g['end'], g['timezone'])
        require(g['timezone'] == 'America/New_York' and (end-start).total_seconds() == 5400, 'Invalid demo schedule')
    require(len({q for g in data['gatherings'] for q in g['questions']}) == 60, 'Questions must be distinct across gatherings')
    return data


def gathering_values(g):
    schedule = validate_schedule(g['date'], g['start'], g['end'], g['timezone'])[0]
    return (g['title'], g['description'], '', g['location'], '\n'.join(title for title, _ in g['agenda']), *schedule.values())


def check_seeded(db, g, entry, digest):
    key, gid, stored_digest, identifiers, applied_at = entry
    require(stored_digest == digest, f'Seed definition changed for {key}; refusing to overwrite')
    stored = db.execute('''SELECT title,description,when_text,location,agenda,gathering_date,
        start_time,end_time,timezone,start_fold,end_fold FROM gatherings WHERE id=?''', (gid,)).fetchone()
    require(stored == gathering_values(g), f'Seeded gathering {gid} was edited or removed; no automatic repair')
    ids = json.loads(identifiers)
    require({k:len(v) for k,v in ids.items()} == {'agenda_items':6,'resources':len(g['resources']),'questions':12}, 'Invalid seed registry mapping')
    for position, ((title, minutes), id) in enumerate(zip(g['agenda'], ids['agenda_items'])):
        require(db.execute('SELECT gathering_id,position,title,minutes,notes FROM agenda_items WHERE id=?',(id,)).fetchone()
                == (gid,position,title,minutes,NOTE), f'Seeded agenda {id} changed')
    for (title,url), id in zip(g['resources'], ids['resources']):
        require(db.execute('SELECT gathering_id,title,url FROM resources WHERE id=?',(id,)).fetchone()
                == (gid,title,url), f'Seeded resource {id} changed')
    for text,id in zip(g['questions'], ids['questions']):
        require(db.execute('SELECT gathering_id,question,created_at FROM questions WHERE id=?',(id,)).fetchone()
                == (gid,QUESTION_LABEL+text,applied_at), f'Seeded question {id} changed')
    return ids


def plan(db):
    check_integrity(db); check_schema(db)
    data = manifest()
    state = database_state(db)
    digest = hashlib.sha256(json_text(data).encode()).hexdigest()
    has_registry = REGISTRY in state['rows']
    result = []
    next_ids = {table:db.execute('SELECT COALESCE(MAX(id),0)+1 FROM '+table).fetchone()[0]
                for table in ('gatherings','questions','agenda_items','resources')}
    for g in data['gatherings']:
        key = data['dataset']+':'+g['key']
        entry = db.execute('SELECT seed_key,gathering_id,manifest_sha256,record_ids_json,applied_at FROM '+REGISTRY+' WHERE seed_key=?',(key,)).fetchone() if has_registry else None
        if entry:
            ids = check_seeded(db,g,entry,digest)
            gid = entry[1]; action = 'skip-existing'
        else:
            # Never adopt a real record just because its title resembles this demo.
            require(not db.execute('SELECT id FROM gatherings WHERE title=?',(g['title'],)).fetchone(),
                    f'Unregistered gathering already uses exact title {g["title"]!r}; review manually')
            action = 'create'
            gid = next_ids['gatherings']; next_ids['gatherings'] += 1
            ids = {}
            for table, size in (('questions',12),('agenda_items',6),('resources',len(g['resources']))):
                ids[table] = list(range(next_ids[table],next_ids[table]+size)); next_ids[table] += size
        result.append(dict(seed_key=key,action=action,gathering_id=gid,record_ids=ids,content=g))
    additions = {table:0 for table in ('gatherings','questions','agenda_items','resources',REGISTRY)}
    for row in result:
        if row['action'] == 'create':
            additions['gatherings'] += 1; additions[REGISTRY] += 1
            for table, ids in row['record_ids'].items(): additions[table] += len(ids)
    before = {t:len(rows) for t,rows in state['rows'].items()}
    after = {**before, **{t:before.get(t,0)+n for t,n in additions.items()}}
    return dict(mode='dry-run',dataset=data['dataset'],label=data['label'],resources_verified_on=data['resources_verified_on'],
                database_fingerprint=fingerprint(state),manifest_sha256=digest,ids_are_provisional=True,
                additions=additions,before_counts=before,after_counts=after,gatherings=result)


def verify_backup(backup, expected_sha):
    require(backup.is_file(), 'Separate backup file is required')
    require(hashlib.sha256(backup.read_bytes()).hexdigest() == expected_sha, 'Backup SHA-256 mismatch')
    with read_database(backup) as db:
        db.execute('BEGIN'); check_integrity(db); check_schema(db)
        return database_state(db)


def apply(database, backup, backup_sha256, expected_fingerprint, confirm_local_demo):
    require(confirm_local_demo, 'Writes require --confirm-local-demo (operator assertion, not production autodetection)')
    require(database.is_file() and backup.is_file() and not database.samefile(backup), 'Target and backup must be different existing files')
    require(bool(expected_fingerprint), 'Writes require --expect-database-fingerprint from a reviewed dry-run')
    saved = verify_backup(backup, backup_sha256)
    with sqlite3.connect(database.resolve().as_uri()+'?mode=rw',uri=True) as db:
        db.execute('PRAGMA foreign_keys=ON')
        require(db.execute('PRAGMA foreign_keys').fetchone()[0] == 1, 'Foreign-key enforcement unavailable')
        db.execute('BEGIN IMMEDIATE')
        before = database_state(db)
        require(fingerprint(before) == expected_fingerprint, 'Target fingerprint changed; review a fresh dry-run')
        require(before == saved, 'Backup contents do not exactly match the current target')
        report = plan(db)
        if not report['additions']['gatherings']:
            report.update(mode='applied-no-op', ids_are_provisional=False)
            return report
        db.execute('''CREATE TABLE IF NOT EXISTS demonstration_seed_items (
            seed_key TEXT PRIMARY KEY, gathering_id INTEGER NOT NULL UNIQUE REFERENCES gatherings(id),
            manifest_sha256 TEXT NOT NULL, record_ids_json TEXT NOT NULL, applied_at TEXT NOT NULL)''')
        applied_at = datetime.now(timezone.utc).isoformat()
        for row in report['gatherings']:
            if row['action'] != 'create': continue
            g = row['content']
            gid = db.execute('''INSERT INTO gatherings(title,description,when_text,location,agenda,
                gathering_date,start_time,end_time,timezone,start_fold,end_fold) VALUES (?,?,?,?,?,?,?,?,?,?,?)''', gathering_values(g)).lastrowid
            ids = {'agenda_items':[], 'resources':[], 'questions':[]}
            for pos,(title,minutes) in enumerate(g['agenda']):
                ids['agenda_items'].append(db.execute('INSERT INTO agenda_items(gathering_id,position,title,minutes,notes) VALUES (?,?,?,?,?)', (gid,pos,title,minutes,NOTE)).lastrowid)
            for title,url in g['resources']:
                ids['resources'].append(db.execute('INSERT INTO resources(gathering_id,title,url) VALUES (?,?,?)',(gid,title,url)).lastrowid)
            for text in g['questions']:
                ids['questions'].append(db.execute('INSERT INTO questions(gathering_id,question,created_at) VALUES (?,?,?)',(gid,QUESTION_LABEL+text,applied_at)).lastrowid)
            db.execute('INSERT INTO demonstration_seed_items VALUES (?,?,?,?,?)',(row['seed_key'],gid,report['manifest_sha256'],json.dumps(ids,sort_keys=True),applied_at))
            row.update(gathering_id=gid,record_ids=ids)
        check_integrity(db)
        # Detect triggers/unintended writes and preserve every preexisting value.
        after = database_state(db)
        allowed = ('gatherings','questions','agenda_items','resources',REGISTRY)
        require(set(after['rows']) == set(before['rows']) | {REGISTRY}, 'Unexpected table change')
        for table, rows in before['rows'].items():
            require(not (Counter(rows)-Counter(after['rows'][table])), f'Existing {table} records changed; rolling back')
            if table not in allowed: require(rows == after['rows'][table], f'Unrelated {table} changed')
        for table,n in report['additions'].items():
            require(len(after['rows'].get(table,[])) == len(before['rows'].get(table,[]))+n, f'Unexpected additions to {table}')
        # Re-read registered contents before commit, including all actual allocated IDs.
        plan(db)
        report.update(mode='applied', ids_are_provisional=False,after_counts={t:len(v) for t,v in after['rows'].items()})
        return report  # context manager commits only after every assertion succeeds


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database',type=Path,required=True,help='Explicit local SQLite file; no environment/path default')
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--confirm-local-demo',action='store_true',help='Explicitly assert this is an approved local demo target, never production')
    parser.add_argument('--backup',type=Path)
    parser.add_argument('--backup-sha256')
    parser.add_argument('--expect-database-fingerprint')
    args = parser.parse_args(argv)
    try:
        require(args.database.is_file(), 'Target database must already exist')
        if args.apply:
            require(args.backup is not None and args.backup_sha256 is not None, 'Apply requires a separately verified --backup and --backup-sha256')
            report = apply(args.database,args.backup,args.backup_sha256,args.expect_database_fingerprint,args.confirm_local_demo)
        else:
            with read_database(args.database) as db:
                db.execute('BEGIN'); report=plan(db)
        report['database'] = str(args.database.resolve())
        print(json.dumps(report,ensure_ascii=False,indent=2))
    except (ValueError, sqlite3.Error, OSError) as error:
        parser.exit(1,f'Seeding refused: {error}\n')


if __name__ == '__main__':
    main()
