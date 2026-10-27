"""Transactional persistence for host-curated discussion themes.

No participant records are written here. Callers own transaction boundaries.
"""
from datetime import datetime, timezone

from fastapi import HTTPException


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def init_schema(db):
    # These statements run inside init_db's migration transaction.
    db.execute("""CREATE TABLE IF NOT EXISTS discussion_themes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        gathering_id INTEGER NOT NULL REFERENCES gatherings(id),
        title TEXT NOT NULL CHECK(length(title) BETWEEN 1 AND 120),
        description TEXT NOT NULL DEFAULT '' CHECK(length(description) <= 2000),
        origin TEXT NOT NULL CHECK(origin IN ('ai', 'manual')),
        ai_original_title TEXT,
        status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','approved','published')),
        position INTEGER NOT NULL,
        revision INTEGER NOT NULL DEFAULT 1 CHECK(revision > 0),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS theme_sources (
        theme_id INTEGER NOT NULL REFERENCES discussion_themes(id),
        question_id INTEGER NOT NULL REFERENCES questions(id),
        PRIMARY KEY(theme_id, question_id)
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS theme_requests (
        request_key TEXT PRIMARY KEY,
        gathering_id INTEGER NOT NULL REFERENCES gatherings(id),
        kind TEXT NOT NULL CHECK(kind IN ('generate','manual')),
        status TEXT NOT NULL CHECK(status IN ('pending','complete','failed')),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""")
    db.execute("CREATE INDEX IF NOT EXISTS themes_gathering_order ON discussion_themes(gathering_id,position,id)")
    # Additive provenance and archive metadata: never rewrite legacy theme rows.
    db.execute("""CREATE TABLE IF NOT EXISTS analysis_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        gathering_id INTEGER NOT NULL REFERENCES gatherings(id),
        request_key TEXT NOT NULL UNIQUE REFERENCES theme_requests(request_key),
        question_count INTEGER NOT NULL CHECK(question_count >= 0),
        generated_theme_count INTEGER CHECK(generated_theme_count >= 0),
        draft_action TEXT NOT NULL CHECK(draft_action IN ('archive','keep','delete')),
        status TEXT NOT NULL CHECK(status IN ('pending','complete','failed')),
        created_at TEXT NOT NULL,
        completed_at TEXT
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS theme_analysis_runs (
        theme_id INTEGER PRIMARY KEY REFERENCES discussion_themes(id),
        run_id INTEGER NOT NULL REFERENCES analysis_runs(id)
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS archived_themes (
        theme_id INTEGER PRIMARY KEY REFERENCES discussion_themes(id),
        archived_at TEXT NOT NULL
    )""")
    db.execute("CREATE INDEX IF NOT EXISTS analysis_gathering_order ON analysis_runs(gathering_id,id)")



def plain_text(value, maximum, required=True, multiline=False):
    """Accept plain text only; markup is displayed literally by autoescaping."""
    allowed_controls = '\n\t\r' if multiline else ''
    if not isinstance(value, str) or any((ord(c) < 32 and c not in allowed_controls) or ord(c) == 127 for c in value):
        raise HTTPException(400, "Theme text contains unsupported control characters")
    value = value.strip()
    if len(value) > maximum or (required and not value):
        raise HTTPException(400, f"Theme text must have {'1' if required else '0'}–{maximum} characters")
    return value


def load_themes(db, gathering_id, public=False):
    if public:
        # Deliberately do not select provenance, sources, drafts or host metadata.
        return [dict(r) for r in db.execute(
            "SELECT title,description,origin FROM discussion_themes WHERE gathering_id=? AND status='published' ORDER BY position,id",
            (gathering_id,))]
    themes = [dict(r) for r in db.execute(
        """SELECT t.*, a.run_id, CASE WHEN x.theme_id IS NOT NULL AND t.origin='ai'
        AND t.status='draft' THEN 1 ELSE 0 END AS archived
        FROM discussion_themes t LEFT JOIN theme_analysis_runs a ON a.theme_id=t.id
        LEFT JOIN archived_themes x ON x.theme_id=t.id
        WHERE t.gathering_id=? ORDER BY t.position,t.id""", (gathering_id,))]
    for theme in themes:
        theme['question_ids'] = [r[0] for r in db.execute(
            "SELECT s.question_id FROM theme_sources s JOIN questions q ON q.id=s.question_id WHERE s.theme_id=? AND q.gathering_id=? ORDER BY s.question_id",
            (theme['id'], gathering_id))]
    return themes


def claim_request(db, key, gathering_id, kind):
    now = timestamp()
    result = db.execute(
        "INSERT INTO theme_requests VALUES (?,?,?,'pending',?,?) ON CONFLICT(request_key) DO NOTHING",
        (key, gathering_id, kind, now, now))
    if result.rowcount != 1:
        raise HTTPException(409, "This form was already submitted. Reload Manage gathering before trying again.")


def finish_request(db, key, status):
    db.execute("UPDATE theme_requests SET status=?,updated_at=? WHERE request_key=?", (status, timestamp(), key))


def insert_theme(db, gathering_id, title, description, origin, question_ids=()):
    now = timestamp()
    position = db.execute("SELECT COALESCE(MAX(position),0)+1 FROM discussion_themes WHERE gathering_id=?", (gathering_id,)).fetchone()[0]
    cursor = db.execute(
        "INSERT INTO discussion_themes(gathering_id,title,description,origin,ai_original_title,position,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)",
        (gathering_id, title, description, origin, title if origin == 'ai' else None, position, now, now))
    for question_id in set(question_ids):
        # Enforce gathering isolation even though legacy connections do not enable foreign keys.
        if not db.execute("SELECT 1 FROM questions WHERE id=? AND gathering_id=?", (question_id, gathering_id)).fetchone():
            raise HTTPException(400, "Theme source does not belong to this gathering")
        db.execute("INSERT INTO theme_sources VALUES (?,?)", (cursor.lastrowid, question_id))
    return cursor.lastrowid


def current_theme(db, gathering_id, theme_id, revision):
    row = db.execute("SELECT * FROM discussion_themes WHERE id=? AND gathering_id=?", (theme_id, gathering_id)).fetchone()
    if row is None:
        raise HTTPException(404, "Theme not found")
    if row['revision'] != revision:
        raise HTTPException(409, "This theme changed since you opened the form. Reload Manage gathering and review the current version.")
    return row


def change_theme(db, gathering_id, theme_id, revision, action, title='', description='', confirmation=''):
    # Serialize read/modify/write and ordering swaps; revision checks reject stale forms.
    db.execute('BEGIN IMMEDIATE')
    theme = current_theme(db, gathering_id, theme_id, revision)
    now = timestamp()
    archived = db.execute("SELECT 1 FROM archived_themes WHERE theme_id=?", (theme_id,)).fetchone()
    if archived and action not in ('restore', 'delete'):
        raise HTTPException(409, "Restore this archived draft before editing or approving it.")
    if action in ('archive', 'restore'):
        if theme['origin'] != 'ai' or theme['status'] != 'draft':
            raise HTTPException(409, "Only unapproved AI drafts can be archived or restored")
        if action == 'archive':
            db.execute("INSERT INTO archived_themes VALUES (?,?)", (theme_id, now))
        elif not archived:
            raise HTTPException(409, "This draft is already active")
        else:
            db.execute("DELETE FROM archived_themes WHERE theme_id=?", (theme_id,))
        db.execute("UPDATE discussion_themes SET revision=revision+1,updated_at=? WHERE id=?", (now, theme_id))
    elif action == 'edit':
        title = plain_text(title, 120)
        description = plain_text(description, 2000, required=False, multiline=True)
        db.execute("UPDATE discussion_themes SET title=?,description=?,status='draft',revision=revision+1,updated_at=? WHERE id=? AND gathering_id=?",
                   (title, description, now, theme_id, gathering_id))
    elif action in ('approve', 'publish', 'unpublish'):
        source, target = {'approve': ('draft', 'approved'), 'publish': ('approved', 'published'), 'unpublish': ('published', 'approved')}[action]
        if theme['status'] != source:
            raise HTTPException(409, f"Cannot {action} a {theme['status']} theme")
        db.execute("UPDATE discussion_themes SET status=?,revision=revision+1,updated_at=? WHERE id=? AND gathering_id=?", (target, now, theme_id, gathering_id))
    elif action == 'delete':
        if theme['status'] != 'draft':
            raise HTTPException(409, "Only unapproved drafts can be deleted")
        if confirmation != 'delete':
            raise HTTPException(400, "Confirm deletion of this draft")
        delete_draft(db, theme_id, gathering_id)
    elif action in ('up', 'down'):
        rows = db.execute("SELECT id,position FROM discussion_themes WHERE gathering_id=? ORDER BY position,id", (gathering_id,)).fetchall()
        index = next(i for i, row in enumerate(rows) if row['id'] == theme_id)
        adjacent = index + (-1 if action == 'up' else 1)
        if not 0 <= adjacent < len(rows):
            raise HTTPException(409, "This theme is already at the edge of the list")
        other = rows[adjacent]
        for row_id, position in ((theme_id, other['position']), (other['id'], theme['position'])):
            db.execute("UPDATE discussion_themes SET position=?,revision=revision+1,updated_at=? WHERE id=? AND gathering_id=?", (position, now, row_id, gathering_id))
    else:
        raise HTTPException(404, "Theme action not found")


def delete_draft(db, theme_id, gathering_id):
    """Caller has checked state/revision inside the write transaction."""
    for table in ('theme_sources', 'theme_analysis_runs', 'archived_themes'):
        db.execute(f"DELETE FROM {table} WHERE theme_id=?", (theme_id,))
    db.execute("DELETE FROM discussion_themes WHERE id=? AND gathering_id=?", (theme_id, gathering_id))


def start_analysis(db, gathering_id, request_key, question_count, draft_action):
    claim_request(db, request_key, gathering_id, 'generate')
    cursor = db.execute("""INSERT INTO analysis_runs
        (gathering_id,request_key,question_count,draft_action,status,created_at)
        VALUES (?,?,?,?,'pending',?)""",
        (gathering_id, request_key, question_count, draft_action, timestamp()))
    # Snapshot revisions now. A host edit/approval during inference must win.
    previous = [(r['id'], r['revision']) for r in db.execute(
        "SELECT id,revision FROM discussion_themes WHERE gathering_id=? AND origin='ai' AND status='draft'",
        (gathering_id,))]
    return cursor.lastrowid, previous


def finish_analysis(db, run_id, status):
    db.execute("""UPDATE analysis_runs SET status=?,completed_at=?,
        generated_theme_count=CASE WHEN ?='complete' THEN
        (SELECT count(*) FROM theme_analysis_runs WHERE run_id=?) ELSE NULL END WHERE id=?""",
        (status, timestamp(), status, run_id, run_id))


def apply_draft_action(db, gathering_id, action, previous):
    if action == 'keep':
        return
    for theme_id, revision in previous:
        theme = db.execute("""SELECT * FROM discussion_themes
            WHERE id=? AND gathering_id=? AND revision=? AND origin='ai' AND status='draft'""",
            (theme_id, gathering_id, revision)).fetchone()
        if theme is None:
            continue
        if action == 'delete':
            delete_draft(db, theme_id, gathering_id)
        elif not db.execute("SELECT 1 FROM archived_themes WHERE theme_id=?", (theme_id,)).fetchone():
            db.execute("INSERT INTO archived_themes VALUES (?,?)", (theme_id, timestamp()))
            db.execute("UPDATE discussion_themes SET revision=revision+1,updated_at=? WHERE id=?",
                       (timestamp(), theme_id))


def analysis_workspace(db, gathering_id, themes):
    runs = [dict(row) for row in db.execute(
        "SELECT * FROM analysis_runs WHERE gathering_id=? ORDER BY id DESC", (gathering_id,))]
    for run in runs:
        run['themes'] = [t for t in themes if t['origin'] == 'ai' and t['run_id'] == run['id']]
        counts = {status: sum(t['status'] == status and not t['archived'] for t in run['themes'])
                  for status in ('draft', 'approved', 'published')}
        archived = sum(t['archived'] for t in run['themes'])
        run['status_label'] = ({'pending': 'In progress or interrupted', 'failed': 'Failed'}[run['status']]
            if run['status'] != 'complete' else
            f"{counts['draft']} active drafts · {archived} archived · {counts['approved']} approved · {counts['published']} published")
    return {
        'analysis_runs': runs,
        'current_themes': [t for t in themes if t['origin'] == 'manual' or t['status'] in ('approved', 'published')],
        'legacy_themes': [t for t in themes if t['origin'] == 'ai' and t['run_id'] is None],
    }
