"""SQLite backup stream and offline restore, used by scripts/database.sh."""

import argparse
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone


def validate(path):
    with sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True) as db:
        if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise ValueError("Database integrity check failed")
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"gatherings", "rsvps", "questions"} <= tables:
            raise ValueError("Not a Common Ground database")


def snapshot(source, destination):
    with sqlite3.connect(f"{source.as_uri()}?mode=ro", uri=True) as src:
        with sqlite3.connect(destination) as dst:
            src.backup(dst)
    validate(destination)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["backup", "restore"])
    args = parser.parse_args()
    database = Path(os.environ.get("DATABASE_PATH", "/data/common-ground.db")).resolve()
    if args.action == "backup":
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "backup.db"
            snapshot(database, target)
            with target.open("rb") as stream:
                shutil.copyfileobj(stream, sys.stdout.buffer)
    else:
        # The wrapper stops the web service before invoking this operation.
        fd, name = tempfile.mkstemp(prefix=".restore-", dir=database.parent)
        target = Path(name)
        try:
            with os.fdopen(fd, "wb") as stream:
                shutil.copyfileobj(sys.stdin.buffer, stream)
            validate(target)
            if database.exists():
                stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
                recovery = database.with_name(f"pre-restore-{stamp}.db")
                snapshot(database, recovery)
                os.chmod(recovery, 0o600)
                print(f"Previous database saved to {recovery}", file=sys.stderr)
            for suffix in ("-wal", "-shm", "-journal"):
                Path(str(database) + suffix).unlink(missing_ok=True)
            os.replace(target, database)
            print("Database restored.", file=sys.stderr)
        finally:
            target.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
