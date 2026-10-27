import os
import sqlite3
import subprocess
import sys


def run_tool(database, action, data=None):
    return subprocess.run(
        [sys.executable, "-m", "app.database_tools", action],
        input=data, capture_output=True,
        env={**os.environ, "DATABASE_PATH": str(database)},
    )


def create_database(path):
    with sqlite3.connect(path) as db:
        db.executescript("""
            CREATE TABLE gatherings (id INTEGER PRIMARY KEY, title TEXT);
            CREATE TABLE rsvps (name TEXT);
            CREATE TABLE questions (question TEXT);
            INSERT INTO gatherings VALUES (1, 'Original gathering');
            INSERT INTO rsvps VALUES ('Casey');
            INSERT INTO questions VALUES ('More workshops?');
        """)


def test_backup_restore_and_recovery(tmp_path):
    database = tmp_path / "live.db"
    create_database(database)
    # Include committed WAL data in an online backup.
    with sqlite3.connect(database) as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("UPDATE gatherings SET title='Backed up'")
        db.commit()
        backup = run_tool(database, "backup")
    assert backup.returncode == 0, backup.stderr
    with sqlite3.connect(database) as db:
        db.execute("UPDATE gatherings SET title='Later change'")
    restored = run_tool(database, "restore", backup.stdout)
    assert restored.returncode == 0, restored.stderr
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT title FROM gatherings").fetchone() == ("Backed up",)
        assert db.execute("SELECT name FROM rsvps").fetchone() == ("Casey",)
        assert db.execute("SELECT question FROM questions").fetchone() == ("More workshops?",)
    recovery, = tmp_path.glob("pre-restore-*.db")
    with sqlite3.connect(recovery) as db:
        assert db.execute("SELECT title FROM gatherings").fetchone() == ("Later change",)


def test_invalid_restore_preserves_database(tmp_path):
    database = tmp_path / "live.db"
    create_database(database)
    original = database.read_bytes()
    for invalid in (b"not sqlite", b""):
        result = run_tool(database, "restore", invalid)
        assert result.returncode != 0
        assert database.read_bytes() == original
    assert not list(tmp_path.glob(".restore-*"))


def test_restore_to_new_database_and_missing_backup_source(tmp_path):
    source = tmp_path / "source.db"
    create_database(source)
    backup = run_tool(source, "backup")
    destination = tmp_path / "new.db"
    assert run_tool(destination, "backup").returncode != 0
    assert not destination.exists()
    result = run_tool(destination, "restore", backup.stdout)
    assert result.returncode == 0, result.stderr
    assert not list(tmp_path.glob("pre-restore-*.db"))
