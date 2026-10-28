"""Opt-in fictional data seeding runs only on per-test temporary SQLite databases."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from app import main, gathering_display
from app import seed_demo as seed
from app.database_tools import snapshot
from app.scheduling import check_integrity
from tests.form_helpers import post


@pytest.fixture
def database(tmp_path, monkeypatch):
    path = tmp_path/'disposable.db'
    monkeypatch.setattr(main, 'DB', str(path))
    main.init_db()  # Existing legacy seed is retained; demo seeder never calls startup.
    return path


def read_state(path):
    with seed.read_database(path) as db:
        db.execute('BEGIN')
        return seed.database_state(db)


def backup_for(path, tmp_path, name='backup.db'):
    backup=tmp_path/name
    snapshot(path.resolve(), backup)
    with seed.read_database(backup) as db:
        check_integrity(db)
    return backup, hashlib.sha256(backup.read_bytes()).hexdigest()


def apply(path, tmp_path, name='backup.db'):
    backup, sha = backup_for(path,tmp_path,name)
    return seed.apply(path,backup,sha,seed.fingerprint(read_state(path)),True)


def test_dry_run_detailed_and_strictly_read_only(database):
    before=database.read_bytes()
    result=subprocess.run([sys.executable,'-m','app.seed_demo','--database',str(database)],capture_output=True,text=True)
    assert result.returncode == 0,result.stderr
    report=json.loads(result.stdout)
    assert report['mode'] == 'dry-run'
    assert report['additions'] == dict(gatherings=5,questions=60,agenda_items=30,resources=10,demonstration_seed_items=5)
    assert len(report['gatherings'][0]['content']['questions']) == 12
    assert 'Fictional' in report['label']
    assert report['ids_are_provisional'] is True
    assert database.read_bytes() == before
    assert seed.REGISTRY not in read_state(database)['rows']


def test_apply_twice_is_noop_and_preserves_all_preexisting_rows(database,tmp_path):
    before=read_state(database)
    report=apply(database,tmp_path)
    after=read_state(database)
    assert report['mode'] == 'applied'
    assert report['after_counts']['questions'] == 60
    assert report['after_counts']['gatherings'] == 6
    for table,rows in before['rows'].items():
        assert set(rows) <= set(after['rows'][table])
        if table not in ('gatherings','questions','agenda_items','resources'):
            assert rows == after['rows'][table]
    again=apply(database,tmp_path,'second-backup.db')
    assert again['mode'] == 'applied-no-op'
    assert all(g['action']=='skip-existing' for g in again['gatherings'])
    assert read_state(database) == after
    with seed.read_database(database) as db:
        check_integrity(db)
        assert db.execute('SELECT COUNT(*) FROM rsvps').fetchone()[0] == 0
        assert db.execute('SELECT COUNT(*) FROM analysis_runs').fetchone()[0] == 0
        assert db.execute('SELECT COUNT(*) FROM discussion_themes').fetchone()[0] == 0


@pytest.mark.parametrize('problem', ['no-confirmation','wrong-sha','wrong-target','stale-backup','same-file'])
def test_apply_guards_refuse_without_mutations(database,tmp_path,problem):
    backup,sha=backup_for(database,tmp_path)
    if problem=='stale-backup':
        with sqlite3.connect(database) as db: db.execute("UPDATE gatherings SET title='Changed since backup' WHERE id=1")
    before=read_state(database)
    target_fp=seed.fingerprint(before)
    if problem=='same-file': backup=database; sha=hashlib.sha256(database.read_bytes()).hexdigest()
    with pytest.raises(ValueError):
        seed.apply(database,backup,'bad' if problem=='wrong-sha' else sha,
                   'bad' if problem=='wrong-target' else target_fp,problem!='no-confirmation')
    assert read_state(database) == before


def test_apply_flag_requires_backup_and_explicit_target(database):
    before=read_state(database)
    result=subprocess.run([sys.executable,'-m','app.seed_demo','--database',str(database),'--apply'],capture_output=True,text=True)
    assert result.returncode != 0 and 'backup' in result.stderr
    assert read_state(database)==before
    missing=database.with_name('missing.db')
    result=subprocess.run([sys.executable,'-m','app.seed_demo','--database',str(missing)],capture_output=True,text=True)
    assert result.returncode != 0 and not missing.exists()


def test_same_title_real_record_is_not_adopted_or_overwritten(database,tmp_path):
    with sqlite3.connect(database) as db:
        db.execute('INSERT INTO gatherings(title,description,when_text,location,agenda) VALUES (?,?,?,?,?)',
                   (seed.manifest()['gatherings'][0]['title'],'Keep real data','Legacy time','Real place','Agenda'))
    before=read_state(database)
    with pytest.raises(ValueError,match='Unregistered'):
        apply(database,tmp_path)
    assert read_state(database)==before


def test_idempotence_uses_registry_not_approximate_title_and_preserves_edits(database,tmp_path):
    report=apply(database,tmp_path)
    gid=report['gatherings'][0]['gathering_id']
    with sqlite3.connect(database) as db: db.execute('UPDATE gatherings SET title=? WHERE id=?',('Host edited demo',gid))
    before=read_state(database)
    with pytest.raises(ValueError,match='edited or removed'):
        apply(database,tmp_path,'changed-backup.db')
    assert read_state(database)==before


def test_tampered_question_not_repaired(database,tmp_path):
    report=apply(database,tmp_path)
    id=report['gatherings'][0]['record_ids']['questions'][0]
    with sqlite3.connect(database) as db: db.execute('UPDATE questions SET question=? WHERE id=?',('Host edited question',id))
    before=read_state(database)
    with pytest.raises(ValueError,match='question.*changed'):
        apply(database,tmp_path,'changed-backup.db')
    assert read_state(database)==before


def test_allocated_ids_do_not_assume_empty_or_sequential_existing_records(database,tmp_path):
    with sqlite3.connect(database) as db:
        db.execute("INSERT INTO gatherings(id,title,description,when_text,location,agenda) VALUES (88,'Other','Keep','Legacy','Here','Welcome')")
        db.execute("INSERT INTO questions(id,gathering_id,question,created_at) VALUES (900,88,'Keep question','timestamp')")
    report=apply(database,tmp_path)
    assert report['gatherings'][0]['gathering_id']==89
    assert report['gatherings'][0]['record_ids']['questions'][0]==901
    with seed.read_database(database) as db:
        assert db.execute('SELECT question FROM questions WHERE id=900').fetchone()[0]=='Keep question'


def test_failure_rolls_back_all_rows_and_registry(database,tmp_path,monkeypatch):
    backup,sha=backup_for(database,tmp_path)
    before=read_state(database)
    real=seed.plan
    calls=[]
    def failing(db):
        calls.append(1)
        if len(calls)==2: raise ValueError('Forced final verification failure')
        return real(db)
    monkeypatch.setattr(seed,'plan',failing)
    with pytest.raises(ValueError,match='Forced'):
        seed.apply(database,backup,sha,seed.fingerprint(before),True)
    assert read_state(database)==before


def test_content_schedules_agendas_labels_and_resources(database,tmp_path):
    report=apply(database,tmp_path)
    with seed.read_database(database) as db:
        for row in report['gatherings']:
            gid=row['gathering_id']
            agenda=db.execute('SELECT minutes FROM agenda_items WHERE gathering_id=?',(gid,)).fetchall()
            assert len(agenda)==6 and sum(r[0] for r in agenda)==90
            g=db.execute('SELECT description,location,timezone,start_fold,end_fold FROM gatherings WHERE id=?',(gid,)).fetchone()
            assert 'Fictional' in g[0] and 'Fictional' in g[1]
            assert g[2:] == ('America/New_York',None,None)
            questions=[r[0] for r in db.execute('SELECT question FROM questions WHERE gathering_id=?',(gid,))]
            assert len(questions)==len(set(questions))==12
            assert all(q.startswith('[Fictional demo] ') for q in questions)
            assert db.execute('SELECT COUNT(*) FROM resources WHERE gathering_id=?',(gid,)).fetchone()[0]==2


def test_upcoming_order_in_public_and_host_directories(database,tmp_path,monkeypatch):
    report=apply(database,tmp_path)
    class Clock(datetime):
        @classmethod
        def now(cls,tz=None): return datetime(2026,11,1,tzinfo=timezone.utc).astimezone(tz)
    monkeypatch.setattr(gathering_display,'datetime',Clock)
    monkeypatch.setattr(main,'ADMIN_PASSWORD','test-only')
    with TestClient(main.app) as client:
        post(client,'/host/login',data={'password':'test-only'})
        for route in ('/','/host'):
            html=client.get(route).text
            upcoming=html.split('id="upcoming-gatherings"',1)[1].split('</details>',1)[0]
            titles=[row['content']['title'] for row in report['gatherings']]
            # Apostrophe is escaped by the templates.
            from html import unescape
            upcoming=unescape(upcoming)
            positions=[upcoming.index(title) for title in titles]
            assert positions == sorted(positions)
            assert upcoming.count('class="gathering-entry"')==5
            assert 'America/New_York' in upcoming
        for row in report['gatherings']:
            page=client.get('/gatherings/'+str(row['gathering_id'])).text
            assert 'Fictional demonstration' in page
            assert page.count('<li>')>=6
            assert 'Past Gathering' not in page
