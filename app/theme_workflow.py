"""Transactional persistence for host-curated discussion themes.

No participant records are written here. Callers own transaction boundaries.
"""
from datetime import datetime, timezone
import json
import hashlib

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
    db.execute("""CREATE TABLE IF NOT EXISTS analysis_run_states (
        run_id INTEGER PRIMARY KEY REFERENCES analysis_runs(id),
        state TEXT NOT NULL CHECK(state IN ('active','inactive')),
        revision INTEGER NOT NULL CHECK(revision > 0)
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS analysis_run_models (
        run_id INTEGER PRIMARY KEY REFERENCES analysis_runs(id),
        model TEXT NOT NULL
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS theme_facilitation_notes (
        theme_id INTEGER PRIMARY KEY REFERENCES discussion_themes(id),
        shared_concerns TEXT NOT NULL CHECK(length(shared_concerns) <= 2000),
        different_perspectives TEXT NOT NULL CHECK(length(different_perspectives) <= 2000),
        discussion_questions TEXT NOT NULL CHECK(length(discussion_questions) <= 4000),
        original_ai_notes TEXT,
        revision INTEGER NOT NULL CHECK(revision > 0),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS analysis_run_snapshots (
        run_id INTEGER PRIMARY KEY REFERENCES analysis_runs(id),
        question_count INTEGER NOT NULL CHECK(question_count >= 0)
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS analysis_run_questions (
        run_id INTEGER NOT NULL REFERENCES analysis_run_snapshots(run_id),
        question_id INTEGER NOT NULL REFERENCES questions(id),
        question_number INTEGER NOT NULL CHECK(question_number > 0),
        PRIMARY KEY(run_id,question_id), UNIQUE(run_id,question_number)
    )""")




def plain_text(value, maximum, required=True, multiline=False):
    """Accept plain text only; markup is displayed literally by autoescaping."""
    allowed_controls = '\n\t\r' if multiline else ''
    if not isinstance(value, str) or any((ord(c) < 32 and c not in allowed_controls) or ord(c) == 127 for c in value):
        raise HTTPException(400, "Theme text contains unsupported control characters")
    value = value.strip()
    if len(value) > maximum or (required and not value):
        raise HTTPException(400, f"Theme text must have {'1' if required else '0'}–{maximum} characters")
    return value


def load_themes(db, gathering_id, public=False, run_id=None):
    if public:
        # Deliberately do not select provenance, sources, drafts or host metadata.
        return [dict(r) for r in db.execute(
            "SELECT title,description,origin FROM discussion_themes WHERE gathering_id=? AND status='published' ORDER BY position,id",
            (gathering_id,))]
    run_filter = ' AND a.run_id=?' if run_id is not None else ''
    parameters = (gathering_id, run_id) if run_id is not None else (gathering_id,)
    themes = [dict(r) for r in db.execute(
        f"""SELECT t.*, a.run_id, CASE WHEN x.theme_id IS NOT NULL AND t.origin='ai'
        AND t.status='draft' THEN 1 ELSE 0 END AS archived,
        CASE WHEN r.state='inactive' AND t.origin='ai' AND t.status='draft'
        THEN 1 ELSE 0 END AS inactive_draft
        FROM discussion_themes t LEFT JOIN theme_analysis_runs a ON a.theme_id=t.id
        LEFT JOIN analysis_run_states r ON r.run_id=a.run_id
        LEFT JOIN archived_themes x ON x.theme_id=t.id
        WHERE t.gathering_id=?{run_filter} ORDER BY t.position,t.id""", parameters)]
    for theme in themes:
        theme['facilitation_notes'] = load_notes(db, theme['id'])
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
    inactive = db.execute("""SELECT 1 FROM theme_analysis_runs a
        JOIN analysis_run_states r ON r.run_id=a.run_id WHERE a.theme_id=? AND r.state='inactive'""", (theme_id,)).fetchone()
    if inactive and theme['origin'] == 'ai' and theme['status'] == 'draft' and action != 'delete':
        raise HTTPException(409, 'Reactivate this analysis before editing or approving its drafts.')
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
    for table in ('theme_facilitation_notes', 'theme_sources', 'theme_analysis_runs', 'archived_themes'):
        db.execute(f"DELETE FROM {table} WHERE theme_id=?", (theme_id,))
    db.execute("DELETE FROM discussion_themes WHERE id=? AND gathering_id=?", (theme_id, gathering_id))


def start_analysis(db, gathering_id, request_key, question_count, model=None):
    claim_request(db, request_key, gathering_id, 'generate')
    # draft_action is retained solely for existing SQLite compatibility/history.
    cursor = db.execute("""INSERT INTO analysis_runs
        (gathering_id,request_key,question_count,draft_action,status,created_at)
        VALUES (?,?,?,'keep','pending',?)""",
        (gathering_id, request_key, question_count, timestamp()))
    if model is not None:
        db.execute('INSERT INTO analysis_run_models VALUES (?,?)', (cursor.lastrowid, model))
    return cursor.lastrowid


def finish_analysis(db, run_id, status):
    db.execute("""UPDATE analysis_runs SET status=?,completed_at=?,
        generated_theme_count=CASE WHEN ?='complete' THEN
        (SELECT count(*) FROM theme_analysis_runs WHERE run_id=?) ELSE NULL END WHERE id=?""",
        (status, timestamp(), status, run_id, run_id))


def analysis_workspace(db, gathering_id, themes):
    runs = [dict(row) for row in db.execute(
        "SELECT * FROM analysis_runs WHERE gathering_id=? ORDER BY id DESC", (gathering_id,))]
    for run in runs:
        state = db.execute('SELECT state FROM analysis_run_states WHERE run_id=?', (run['id'],)).fetchone()
        run['inactive'] = bool(state and state['state'] == 'inactive')
        run['action_version'] = analysis_version(db, gathering_id, run['id'])
        run['protected'] = bool(db.execute("""SELECT 1 FROM theme_analysis_runs a
            JOIN discussion_themes t ON t.id=a.theme_id WHERE a.run_id=?
            AND (t.status!='draft' OR t.origin!='ai' OR t.gathering_id!=?)""", (run['id'], gathering_id)).fetchone())
        run['coverage'], run['coverage_unavailable'] = run_coverage(db, run)
        run['themes'] = [t for t in themes if t['origin'] == 'ai' and t['run_id'] == run['id']]
        counts = {status: sum(t['status'] == status and not t['archived'] for t in run['themes'])
                  for status in ('draft', 'approved', 'published')}
        archived = sum(t['archived'] for t in run['themes'])
        run['status_label'] = ({'pending': 'In progress or interrupted', 'failed': 'Failed'}[run['status']]
            if run['status'] != 'complete' else
            f"{counts['draft']} {'inactive' if run['inactive'] else 'active'} drafts · {archived} archived · {counts['approved']} approved · {counts['published']} published")
        if run['inactive']:
            run['status_label'] = 'Inactive · ' + run['status_label']
    # Stable grouping retains the existing newest-first order inside each state.
    runs.sort(key=lambda run: run['inactive'])
    by_id = {run['id']: run for run in runs}
    current_themes = [t for t in themes if t['origin'] == 'manual' or t['status'] in ('approved', 'published')]
    for theme in current_themes:
        source = by_id.get(theme['run_id']) if theme['origin'] == 'ai' else None
        theme['origin_analysis'] = ({'id': source['id'], 'created_at': source['created_at'],
                                     'inactive': source['inactive']} if source else None)
    return {
        'analysis_runs': runs,
        # Keep host position/id order; analysis recency must not reorder themes.
        'current_themes': current_themes,
        'legacy_themes': [t for t in themes if t['origin'] == 'ai' and t['run_id'] is None],
    }


def load_notes(db, theme_id):
    row = db.execute("""SELECT shared_concerns,different_perspectives,discussion_questions,
        revision,updated_at,original_ai_notes IS NOT NULL AS ai_suggested
        FROM theme_facilitation_notes WHERE theme_id=?""", (theme_id,)).fetchone()
    if row is None:
        return {'shared_concerns': '', 'different_perspectives': '', 'discussion_questions': [],
                'revision': 0, 'updated_at': None, 'ai_suggested': False}
    notes = dict(row)
    notes['discussion_questions'] = json.loads(notes['discussion_questions'])
    return notes


def insert_generated_notes(db, theme_id, notes):
    now = timestamp()
    db.execute("INSERT INTO theme_facilitation_notes VALUES (?,?,?,?,?,1,?,?)",
        (theme_id, notes['shared_concerns'], notes['different_perspectives'],
         json.dumps(notes['discussion_questions'], ensure_ascii=False),
         json.dumps(notes, ensure_ascii=False), now, now))


def save_notes(db, gathering_id, theme_id, revision, shared_concerns, different_perspectives, discussion_questions):
    # Independent revision stream: never change public text/status/the theme revision.
    db.execute('BEGIN IMMEDIATE')
    if not db.execute('SELECT 1 FROM discussion_themes WHERE id=? AND gathering_id=?', (theme_id, gathering_id)).fetchone():
        raise HTTPException(404, 'Theme not found')
    if load_notes(db, theme_id)['revision'] != revision:
        raise HTTPException(409, 'These facilitation notes changed since you opened the form. Review the current notes before saving again.')
    shared = plain_text(shared_concerns, 2000, required=False, multiline=True)
    perspectives = plain_text(different_perspectives, 2000, required=False, multiline=True)
    prompts = plain_text(discussion_questions, 1502, required=False, multiline=True)
    prompts = [plain_text(line, 500) for line in prompts.splitlines() if line.strip()]
    if len(prompts) > 3:
        raise HTTPException(400, 'Use at most 3 discussion questions, one per line')
    now = timestamp()
    db.execute("""INSERT INTO theme_facilitation_notes
        (theme_id,shared_concerns,different_perspectives,discussion_questions,revision,created_at,updated_at)
        VALUES (?,?,?,?,1,?,?) ON CONFLICT(theme_id) DO UPDATE SET
        shared_concerns=excluded.shared_concerns,different_perspectives=excluded.different_perspectives,
        discussion_questions=excluded.discussion_questions,revision=theme_facilitation_notes.revision+1,
        updated_at=excluded.updated_at""", (theme_id, shared, perspectives, json.dumps(prompts, ensure_ascii=False), now, now))


def record_question_snapshot(db, gathering_id, run_id, questions):
    run = db.execute('SELECT question_count FROM analysis_runs WHERE id=? AND gathering_id=?', (run_id, gathering_id)).fetchone()
    if run is None or run['question_count'] != len(questions):
        raise HTTPException(400, 'Invalid analysis snapshot')
    db.execute('INSERT INTO analysis_run_snapshots VALUES (?,?)', (run_id, len(questions)))
    for question in questions:
        if not db.execute('SELECT 1 FROM questions WHERE id=? AND gathering_id=?', (question['id'], gathering_id)).fetchone():
            raise HTTPException(400, 'Snapshot question does not belong to this gathering')
        db.execute('INSERT INTO analysis_run_questions VALUES (?,?,?)', (run_id, question['id'], question['question_number']))


def run_coverage(db, run):
    if run['status'] != 'complete':
        return None, 'analysis did not complete'
    snapshot = db.execute('SELECT question_count FROM analysis_run_snapshots WHERE run_id=?', (run['id'],)).fetchone()
    if snapshot is None:
        return None, 'input question snapshot not recorded for this historical run'
    questions = [dict(r) for r in db.execute("""SELECT q.id,q.question,s.question_number
        FROM analysis_run_questions s JOIN questions q ON q.id=s.question_id
        WHERE s.run_id=? AND q.gathering_id=? ORDER BY s.question_number""", (run['id'], run['gathering_id']))]
    if len(questions) != snapshot['question_count'] or len(questions) != run['question_count']:
        return None, 'input question snapshot is incomplete'
    cited = {r[0] for r in db.execute("""SELECT DISTINCT s.question_id FROM theme_sources s
        JOIN theme_analysis_runs a ON a.theme_id=s.theme_id
        JOIN discussion_themes t ON t.id=s.theme_id
        WHERE a.run_id=? AND t.gathering_id=?""", (run['id'], run['gathering_id']))}
    if not cited <= {q['id'] for q in questions}:
        return None, 'source associations do not match the recorded snapshot'
    uncited = [q for q in questions if q['id'] not in cited]
    return {'analyzed': len(questions), 'cited': len(cited), 'uncited_count': len(uncited), 'uncited': uncited}, ''


def analysis_version(db, gathering_id, run_id):
    run = db.execute('SELECT status FROM analysis_runs WHERE id=? AND gathering_id=?', (run_id, gathering_id)).fetchone()
    if run is None:
        raise HTTPException(404, 'Analysis run not found')
    state = db.execute('SELECT state,revision FROM analysis_run_states WHERE run_id=?', (run_id,)).fetchone()
    members = [tuple(r) for r in db.execute("""SELECT t.id,t.revision,t.status,t.origin,t.gathering_id,
        COALESCE(n.revision,0),x.theme_id IS NOT NULL
        FROM theme_analysis_runs a JOIN discussion_themes t ON t.id=a.theme_id
        LEFT JOIN theme_facilitation_notes n ON n.theme_id=t.id
        LEFT JOIN archived_themes x ON x.theme_id=t.id WHERE a.run_id=? ORDER BY t.id""", (run_id,))]
    snapshot = [run['status'], tuple(state) if state else ('active', 0), members]
    return hashlib.sha256(json.dumps(snapshot).encode()).hexdigest()


def change_analysis(db, gathering_id, run_id, expected_version, action, confirmation=''):
    db.execute('BEGIN IMMEDIATE')
    if analysis_version(db, gathering_id, run_id) != expected_version:
        raise HTTPException(409, 'This analysis or one of its themes changed. Review the current run before trying again.')
    if action in ('inactive', 'reactivate'):
        target = 'inactive' if action == 'inactive' else 'active'
        current = db.execute('SELECT state FROM analysis_run_states WHERE run_id=?', (run_id,)).fetchone()
        if (current['state'] if current else 'active') == target:
            raise HTTPException(409, 'This analysis is already in that state')
        db.execute("""INSERT INTO analysis_run_states VALUES (?,?,1) ON CONFLICT(run_id)
            DO UPDATE SET state=excluded.state,revision=analysis_run_states.revision+1""", (run_id, target))
    elif action == 'delete':
        if confirmation != 'delete':
            raise HTTPException(400, 'Confirm deletion of this analysis run and its unapproved drafts')
        members = list(db.execute("""SELECT t.id,t.gathering_id,t.status,t.origin FROM theme_analysis_runs a
            JOIN discussion_themes t ON t.id=a.theme_id WHERE a.run_id=?""", (run_id,)))
        if any(t['gathering_id'] != gathering_id or t['status'] != 'draft' or t['origin'] != 'ai' for t in members):
            raise HTTPException(409, 'This run contains approved, published or manual themes and cannot be deleted. Make it inactive instead.')
        for theme in members:
            delete_draft(db, theme['id'], gathering_id)
        for table in ('analysis_run_models', 'analysis_run_questions', 'analysis_run_snapshots', 'analysis_run_states'):
            db.execute(f'DELETE FROM {table} WHERE run_id=?', (run_id,))
        db.execute('DELETE FROM analysis_runs WHERE id=? AND gathering_id=?', (run_id, gathering_id))
        # Retain the single-use request receipt: deletion must never allow replay.
    else:
        raise HTTPException(404, 'Unknown analysis action')
