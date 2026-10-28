"""Common Ground: small community gathering prototype.

Development demo only; review security/privacy before public deployment.
"""
import base64
import hashlib
import csv
import io
from urllib.parse import urlencode, urlsplit

import hmac
import os
import re
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import http_exception_handler, request_validation_exception_handler
from fastapi.staticfiles import StaticFiles
from itsdangerous import BadSignature, URLSafeSerializer
from jinja2 import Environment, FileSystemLoader, select_autoescape
from starlette.middleware.sessions import SessionMiddleware

from app.analysis_export import load_analysis_export, export_timezone
from app.facilitation import validate_generated_notes
from app.timestamps import timestamp_display
from app.scheduling import migrate_schedule, validate_schedule, schedule_label, verify_timezone_database, TimezoneDataError, resolve_timezone, normalize_clock
from app.gathering_display import ordered_gatherings, description_preview, gathering_state, listing_sections
from app.questions import NUMBERED_QUESTIONS, load_questions
from app.themes import ThemeError, suggest_themes, validate_generated_description
from app import theme_workflow as workflow

ROOT = Path(__file__).parent
DB = os.environ.get("DATABASE_PATH", "/tmp/common-ground.db")
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://host.docker.internal:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen3:8b")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
SESSION_SECRET = os.environ.get("SESSION_SECRET", "")
if len(SESSION_SECRET) < 24:
    # Local test convenience; Docker Compose requires an explicit value.
    SESSION_SECRET = secrets.token_urlsafe(32)

async def protect_request(request: Request):
    if request.method == "POST":
        if request.url.path.startswith("/host/") and request.url.path != "/host/login":
            require_admin(request)
        form = await request.form()
        token = form.get("csrf_token", "")
        expected = request.session.get("csrf_token", "")
        if not isinstance(token, str) or not expected or not hmac.compare_digest(token.encode(), expected.encode()):
            raise HTTPException(403, "Invalid form token. Reload the page and try again.")
        if request.url.path.startswith("/host/gatherings/"):
            request.state.workspace_form = form


app = FastAPI(dependencies=[Depends(protect_request)], title="Common Ground", docs_url=None, redoc_url=None)
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET, same_site="lax", https_only=False)
app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")
templates = Environment(loader=FileSystemLoader(str(ROOT / "templates")), autoescape=select_autoescape())
templates.filters["timestamp_display"] = timestamp_display
templates.filters["description_preview"] = description_preview
templates.filters["schedule_label"] = schedule_label

@contextmanager
def connection():
    Path(DB).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    try:
        yield db
        db.commit()
    finally:
        db.close()

def init_db():
    with connection() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS gatherings (
            id INTEGER PRIMARY KEY, title TEXT NOT NULL, description TEXT NOT NULL,
            when_text TEXT NOT NULL, location TEXT NOT NULL, agenda TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS rsvps (
            id INTEGER PRIMARY KEY, gathering_id INTEGER NOT NULL REFERENCES gatherings(id),
            name TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS questions (
            id INTEGER PRIMARY KEY, gathering_id INTEGER NOT NULL REFERENCES gatherings(id),
            question TEXT NOT NULL, created_at TEXT NOT NULL
        );
        """)
        migrate_schedule(db)
        db.execute("BEGIN")
        db.execute("CREATE TABLE IF NOT EXISTS gathering_status (gathering_id INTEGER PRIMARY KEY REFERENCES gatherings(id), cancelled INTEGER NOT NULL DEFAULT 0 CHECK(cancelled IN (0,1)))")
        db.execute("CREATE TABLE IF NOT EXISTS resources (id INTEGER PRIMARY KEY, gathering_id INTEGER NOT NULL REFERENCES gatherings(id), title TEXT NOT NULL, url TEXT NOT NULL)")
        # Table creation and legacy conversion share a transaction, so startup is repeatable.
        migrated = db.execute("SELECT 1 FROM sqlite_master WHERE name='agenda_items'").fetchone()
        db.execute("CREATE TABLE IF NOT EXISTS agenda_items (id INTEGER PRIMARY KEY, gathering_id INTEGER NOT NULL REFERENCES gatherings(id), position INTEGER NOT NULL, title TEXT NOT NULL, minutes INTEGER, notes TEXT NOT NULL DEFAULT '')")
        if not migrated:
            for row in db.execute("SELECT id, agenda FROM gatherings").fetchall():
                for position, title in enumerate(row['agenda'].splitlines()):
                    if title.strip():
                        db.execute("INSERT INTO agenda_items(gathering_id,position,title) VALUES (?,?,?)", (row['id'], position, title.strip()))
        workflow.init_schema(db)
        existing = db.execute("SELECT COUNT(*) FROM gatherings").fetchone()[0]
        if existing == 0:
            db.execute("INSERT INTO gatherings (title, description, when_text, location, agenda) VALUES (?, ?, ?, ?, ?)", (
                "The Future of Our Library", "A fictional community gathering to plan new library services.",
                "Saturday, November 14 · 2:00 PM", "Community Library · Meeting Room",
                "Welcome and introductions\nWhat does our community need?\nIdeas and next steps"))
            seed = db.execute("SELECT id,agenda FROM gatherings").fetchone()
            for position, title in enumerate(seed['agenda'].splitlines()):
                db.execute("INSERT INTO agenda_items(gathering_id,position,title) VALUES (?,?,?)", (seed['id'], position, title))

@app.on_event("startup")
def on_startup():
    verify_timezone_database()
    init_db()

def render(name, request, **kwargs):
    if "csrf_token" not in request.session:
        request.session["csrf_token"] = secrets.token_urlsafe(32)
    return HTMLResponse(templates.get_template(name).render(request=request, **kwargs),
                        headers={"Cache-Control": "no-store"})

def get_gathering(id):
    with connection() as db:
        row = db.execute("SELECT * FROM gatherings WHERE id=?", (id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Gathering not found")
    result = dict(row)
    with connection() as db:
        status = db.execute("SELECT cancelled FROM gathering_status WHERE gathering_id=?", (id,)).fetchone()
        result['cancelled'] = bool(status and status[0])
        result['items'] = [dict(r) for r in db.execute("SELECT * FROM agenda_items WHERE gathering_id=? ORDER BY position,id", (id,))]
        result['resources'] = [dict(r) for r in db.execute("SELECT * FROM resources WHERE gathering_id=? ORDER BY id", (id,))]
    result['past'] = gathering_state(dict(result, cancelled=False)) == 'past'
    return result

def validate_text(value, max_chars):
    value = value.strip()
    if not value or len(value) > max_chars:
        raise HTTPException(400, f"Must have 1–{max_chars} characters")
    return value

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    with connection() as db:
        gatherings = dashboard_gatherings(db)
    return render("home.html", request, sections=listing_sections(gatherings, request))

@app.get("/gatherings/{id}", response_class=HTMLResponse)
def gathering_page(id: int, request: Request, thanks: str = ""):
    g = get_gathering(id)
    with connection() as db:
        count = db.execute("SELECT COUNT(*) FROM rsvps WHERE gathering_id=?", (id,)).fetchone()[0]
        published_themes = workflow.load_themes(db, id, public=True)
    return render("gathering.html", request, gathering=g, count=count, thanks=thanks, published_themes=published_themes)

@app.post("/gatherings/{id}/rsvp")
def rsvp(id: int, name: str = Form(...)):
    state = gathering_state(get_gathering(id))
    if state in ("cancelled", "past"):
        raise HTTPException(409, "This gathering is cancelled" if state == "cancelled" else "This gathering has ended")
    name = validate_text(name, 100)
    with connection() as db:
        db.execute("INSERT INTO rsvps(gathering_id,name,created_at) VALUES (?,?,?)", (id, name, datetime.now(timezone.utc).isoformat()))
    return RedirectResponse(f"/gatherings/{id}?thanks=rsvp", status_code=303)

@app.post("/gatherings/{id}/questions")
def question(id: int, question: str = Form(...)):
    state = gathering_state(get_gathering(id))
    if state in ("cancelled", "past"):
        raise HTTPException(409, "This gathering is cancelled" if state == "cancelled" else "This gathering has ended")
    question = validate_text(question, 500)
    with connection() as db:
        db.execute("INSERT INTO questions(gathering_id,question,created_at) VALUES (?,?,?)", (id, question, datetime.now(timezone.utc).isoformat()))
    return RedirectResponse(f"/gatherings/{id}?thanks=question", status_code=303)

def is_admin(request):
    return bool(request.session.get("admin"))

def require_admin(request):
    if not is_admin(request):
        raise HTTPException(403, "Host login required")

def dashboard_gatherings(db):
    return ordered_gatherings([dict(r) for r in db.execute("""
        SELECT g.*, COALESCE(s.cancelled, 0) AS cancelled,
        (SELECT COUNT(*) FROM questions q WHERE q.gathering_id=g.id) AS question_count,
        (SELECT COUNT(*) FROM rsvps r WHERE r.gathering_id=g.id) AS rsvp_count
        FROM gatherings g LEFT JOIN gathering_status s ON s.gathering_id=g.id
    """)])


@app.get("/host", response_class=HTMLResponse)
def host(request: Request):
    if not is_admin(request):
        return render("login.html", request, error="")
    return dashboard_page(request)


def dashboard_page(request, error="", submitted=None, status_code=200):
    with connection() as db:
        gatherings = dashboard_gatherings(db)
        questions = [dict(r) for r in db.execute(f"SELECT q.*, g.title FROM ({NUMBERED_QUESTIONS}) q JOIN gatherings g ON g.id=q.gathering_id ORDER BY q.created_at DESC,q.id DESC LIMIT 50")]
        rsvps = [dict(r) for r in db.execute("SELECT r.name, g.title FROM rsvps r JOIN gatherings g ON g.id=r.gathering_id ORDER BY r.id DESC LIMIT 50")]
    response = render("host.html", request, sections=listing_sections(gatherings, request, host=True), questions=questions, rsvps=rsvps, error=error, submitted=submitted or {})
    response.status_code = status_code
    return response

@app.post("/host/login")
def login(request: Request, password: str = Form(...)):
    if not ADMIN_PASSWORD or not hmac.compare_digest(password.encode(), ADMIN_PASSWORD.encode()):
        return render("login.html", request, error="Incorrect password")
    request.session.clear()
    request.session["admin"] = True
    request.session["csrf_token"] = secrets.token_urlsafe(32)
    return RedirectResponse("/host", status_code=303)

@app.post("/host/logout")
def logout(request: Request):
    require_admin(request)
    request.session.clear()
    return RedirectResponse("/", status_code=303)

def checked_schedule(day, start, end, zone, existing=None):
    try:
        first = last = ''
        # Preserve explicit historical DST choices only for an unchanged schedule.
        # Newly supplied or changed schedules may never choose an occurrence.
        if existing:
            normalized = (day, normalize_clock(start, 'Start time'),
                          normalize_clock(end, 'End time') if end else '', resolve_timezone(zone)[0])
            saved = tuple(existing.get(k) or '' for k in ('gathering_date', 'start_time', 'end_time', 'timezone'))
            if normalized == saved:
                first = str(existing['start_fold']) if existing.get('start_fold') is not None else ''
                last = str(existing['end_fold']) if existing.get('end_fold') is not None else ''
        return validate_schedule(day, start, end, zone, first, last)[0]
    except TimezoneDataError as exc:
        raise HTTPException(503, str(exc)) from exc
    except ValueError as exc:
        message = str(exc)
        if 'occurs twice' in message or 'does not exist' in message:
            message = 'This local time is repeated or skipped during a clock change in the scheduled timezone. Choose a different time.'
        raise HTTPException(400, message) from exc


@app.post("/host/gatherings")
def create_gathering(request: Request, title: str = Form(...), description: str = Form(...),
                     location: str = Form(...), agenda: str = Form(...),
                     gathering_date: str = Form(...), start_time: str = Form(...),
                     end_time: str = Form(''), timezone: str = Form(...)):
    require_admin(request)
    vals = [validate_text(title, 120), validate_text(description, 1000),
            '', validate_text(location, 120), validate_text(agenda, 2000)]
    schedule = checked_schedule(gathering_date, start_time, end_time, timezone)
    with connection() as db:
        cursor = db.execute("""INSERT INTO gatherings(title,description,when_text,location,agenda,
            gathering_date,start_time,end_time,timezone,start_fold,end_fold) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (*vals, *schedule.values()))
        for position, item in enumerate(vals[4].splitlines()):
            if item.strip():
                db.execute("INSERT INTO agenda_items(gathering_id,position,title) VALUES (?,?,?)", (cursor.lastrowid, position, item.strip()))
    return RedirectResponse("/host", status_code=303)

@app.get("/health")
def health():
    return {"status": "ok"}


def theme_form_key(request, gathering_id, kind):
    payload = [gathering_id, kind, request.session['csrf_token'], secrets.token_urlsafe(24)]
    return URLSafeSerializer(SESSION_SECRET, salt="theme-forms").dumps(payload)


def validate_theme_key(request, gathering_id, kind, key):
    try:
        payload = URLSafeSerializer(SESSION_SECRET, salt="theme-forms").loads(key)
        if not isinstance(payload, list) or len(payload) != 4 or payload[:3] != [gathering_id, kind, request.session.get('csrf_token')]:
            raise BadSignature("Wrong form scope")
    except BadSignature:
        raise HTTPException(400, "Invalid theme form. Reload Manage gathering and try again.")


WORKSPACE_TABS = ('gathering', 'participants', 'themes')


def workspace_action(request):
    """Only existing gathering mutations participate in workspace error rendering."""
    match = re.fullmatch(r'/host/gatherings/(\d+)/(edit|agenda|status|resources(?:/\d+/(?:edit|remove))?|themes(?:/manual|/\d+/[a-z]+)?|analyses/\d+/(?:inactive|reactivate|delete))', request.url.path)
    if request.method != 'POST' or not match:
        return None
    gathering_id, suffix = match.groups()
    section = suffix.split('/')[0]
    tab = 'themes' if section in ('themes', 'analyses') else 'gathering'
    parts = suffix.split('/')
    return {'id': int(gathering_id), 'tab': tab, 'section': section,
            'theme_id': int(parts[1]) if section == 'themes' and len(parts) == 3 else None,
            'action': parts[-1],
            'run_id': int(parts[1]) if section == 'analyses' else None,
            'resource_id': int(parts[1]) if section == 'resources' and len(parts) == 3 else None}


def workspace_redirect(id, tab, section='', theme=None):
    url = f'/host/gatherings/{id}?tab={tab}'
    if theme is not None:
        url += f'&theme={theme}#theme-{theme}'
    elif section:
        url += f'&section={section}#{section}'
    return RedirectResponse(url, 303)


def host_gathering_page(id, request, error="", error_theme=None, error_action="", submitted=None, status_code=200,
                        tab=None, form_state=None, error_section='', error_resource=None, agenda_rows=None, error_run=None):
    require_admin(request)
    gathering = get_gathering(id)
    action = workspace_action(request)
    active_tab = tab or (action['tab'] if action else request.query_params.get('tab',
                        'themes' if 'theme' in request.query_params else 'gathering'))
    if active_tab not in WORKSPACE_TABS:
        raise HTTPException(400, "Unknown workspace tab")
    with connection() as db:
        questions = load_questions(db, id) if active_tab in ('participants', 'themes') else []
        themes = workflow.load_themes(db, id) if active_tab == 'themes' else []
        workspace = workflow.analysis_workspace(db, id, themes) if active_tab == 'themes' else {}
        rsvps = [dict(r) for r in db.execute(
            "SELECT name,created_at FROM rsvps WHERE gathering_id=? ORDER BY id", (id,))] if active_tab == 'participants' else []
    for index, theme in enumerate(themes):
        theme['display_position'] = index + 1
        theme['can_move_up'] = index > 0
        theme['can_move_down'] = index < len(themes) - 1
    try:
        open_theme = error_theme or int(request.query_params.get('theme', '0'))
    except ValueError:
        open_theme = None
    try:
        open_run = error_run or int(request.query_params.get('analysis', '0'))
    except ValueError:
        open_run = None
    # render initializes CSRF for a host's first page; normally login already did so.
    request.session.setdefault('csrf_token', secrets.token_urlsafe(32))
    for run in workspace.get('analysis_runs', []):
        run['action_key'] = URLSafeSerializer(SESSION_SECRET, salt='analysis-actions').dumps(
            [id, run['id'], request.session['csrf_token'], run['action_version']])
    details_saved = (request.method == 'GET' and active_tab == 'gathering'
                     and request.session.get('details_saved') == id)
    if details_saved:
        request.session.pop('details_saved')
    response = render("host_gathering.html", request, gathering=gathering, details_saved=details_saved,
                  questions=questions, rsvps=rsvps, themes=themes, error=error,
                  active_tab=active_tab, form_state=form_state or {},
                  error_section=error_section, error_resource=error_resource,
                  open_section=error_section or request.query_params.get('section', ''),
                  agenda_rows=agenda_rows if agenda_rows is not None else gathering['items'] + [{}],
                  open_theme=open_theme, error_theme=error_theme, error_action=error_action,
                  open_run=open_run, error_run=error_run,
                  submitted=submitted, **workspace,
                  generation_key=theme_form_key(request, id, 'generate'),
                  manual_key=theme_form_key(request, id, 'manual'))
    response.status_code = status_code
    return response


@app.get("/host/gatherings/{id}", response_class=HTMLResponse)
def host_gathering(id: int, request: Request):
    if request.query_params.get('tab') == 'administration':
        require_admin(request)
        get_gathering(id)
        old_section = request.query_params.get('section', '')
        section = {'resource-removal': 'resources', 'status': 'status'}.get(old_section, '')
        response = workspace_redirect(id, 'gathering', section)
        response.headers['Cache-Control'] = 'no-store'
        return response
    return host_gathering_page(id, request)


@app.post("/host/gatherings/{id}/themes")
def gathering_themes(id: int, request: Request, request_key: str = Form(...)):
    require_admin(request)
    get_gathering(id)
    validate_theme_key(request, id, 'generate', request_key)
    with connection() as db:
        numbered_questions = load_questions(db, id)
        question_id_by_number = {q['question_number']: q['id'] for q in numbered_questions}
        # The model only sees the same gathering-local numbers as the host.
        questions = [{"id": q["question_number"], "question": q["question"]} for q in numbered_questions]
        if not questions:
            return host_gathering_page(id, request, "No questions yet. Add participant questions before suggesting themes. Ollama was not called.")
        db.execute('BEGIN IMMEDIATE')
        run_id = workflow.start_analysis(db, id, request_key, len(questions), model=OLLAMA_MODEL)
        workflow.record_question_snapshot(db, id, run_id, numbered_questions)
    # Never hold a SQLite write lock during inference. A committed claim blocks retries.
    try:
        suggestions = suggest_themes(questions, OLLAMA_BASE_URL, OLLAMA_MODEL)
        with connection() as db:
            db.execute('BEGIN IMMEDIATE')
            if not db.execute('SELECT 1 FROM analysis_runs WHERE id=? AND gathering_id=?', (run_id, id)).fetchone():
                raise ThemeError('This analysis was deleted while generation was running. No suggestions were saved.')
            for suggestion in suggestions:
                try:
                    notes = validate_generated_notes(suggestion.get('facilitation_notes'))
                except ValueError as exc:
                    raise ThemeError('Ollama returned missing or invalid facilitation notes. Please try again.') from exc
                title = workflow.plain_text(suggestion['title'], 120)
                description = validate_generated_description(title, suggestion.get('description'))
                description = workflow.plain_text(description, 1000, multiline=True)
                numbers = suggestion.get('question_ids')
                if (not isinstance(numbers, list) or not numbers or
                        any(type(n) is not int or n not in question_id_by_number for n in numbers)):
                    raise ThemeError("Ollama returned invalid question references. Please try again.")
                source_ids = [question_id_by_number[n] for n in numbers]
                theme_id = workflow.insert_theme(db, id, title, description, 'ai', source_ids)
                workflow.insert_generated_notes(db, theme_id, notes)
                db.execute("INSERT INTO theme_analysis_runs VALUES (?,?)", (theme_id, run_id))
            workflow.finish_analysis(db, run_id, 'complete')
            workflow.finish_request(db, request_key, 'complete')
    except (ThemeError, HTTPException) as exc:
        with connection() as db:
            workflow.finish_request(db, request_key, 'failed')
            workflow.finish_analysis(db, run_id, 'failed')
        error = str(exc) if isinstance(exc, ThemeError) else "Ollama returned theme text that could not be saved safely. Please try again."
        return host_gathering_page(id, request, error)
    return workspace_redirect(id, "themes", "discussion-themes")


PRINT_ANALYSIS_SCRIPT = "document.getElementById('print-analysis').addEventListener('click', () => window.print());"
PRINT_ANALYSIS_HASH = base64.b64encode(hashlib.sha256(PRINT_ANALYSIS_SCRIPT.encode()).digest()).decode()


@app.get("/host/gatherings/{id}/analyses/{run_id}/view.html")
def view_analysis(id: int, run_id: int, request: Request):
    return analysis_report(id, run_id, request, inline=True)


@app.get("/host/gatherings/{id}/analyses/{run_id}/export.html")
def export_analysis(id: int, run_id: int, request: Request):
    return analysis_report(id, run_id, request, inline=False)


def analysis_report(id: int, run_id: int, request: Request, *, inline: bool):
    require_admin(request)
    with connection() as db:
        # A consistent read snapshot; export never writes or calls inference.
        db.execute('BEGIN')
        data = load_analysis_export(db, id, run_id)
    zone, fallback = export_timezone(request.query_params.get('timezone'))
    script_policy = f"script-src 'sha256-{PRINT_ANALYSIS_HASH}'" if inline else "script-src 'none'"
    report_csp = f"default-src 'none'; style-src 'unsafe-inline'; {script_policy}; base-uri 'none'; form-action 'none'"
    download_url = f'/host/gatherings/{id}/analyses/{run_id}/export.html'
    if not fallback:
        download_url += '?' + urlencode({'timezone': zone})
    html = templates.get_template('analysis_export.html').render(
        **data, export_zone=zone, timezone_fallback=fallback,
        inline=inline, print_script=PRINT_ANALYSIS_SCRIPT, report_csp=report_csp, download_url=download_url,
        exported_at=datetime.now(timezone.utc).isoformat(),
        export_time=lambda value: timestamp_display(value, zone, fallback))
    return HTMLResponse(html, headers={
        'Content-Disposition': f'{"inline" if inline else "attachment"}; filename="gathering-{id}-analysis-{run_id}.html"',
        'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff',
        'Referrer-Policy': 'no-referrer',
        'Content-Security-Policy': report_csp + "; frame-ancestors 'none'",
        'X-Frame-Options': 'DENY',
    })


@app.post("/host/gatherings/{id}/analyses/{run_id}/{action}")
def analysis_action(id: int, run_id: int, action: str, request: Request,
                    action_key: str = Form(...), confirmation: str = Form('')):
    require_admin(request)
    get_gathering(id)
    try:
        payload = URLSafeSerializer(SESSION_SECRET, salt='analysis-actions').loads(action_key)
        if not isinstance(payload, list) or len(payload) != 4 or payload[:3] != [id, run_id, request.session.get('csrf_token')]:
            raise BadSignature('Wrong analysis scope')
    except BadSignature:
        raise HTTPException(400, 'Invalid analysis form. Reload Discussion Themes and try again.')
    with connection() as db:
        workflow.change_analysis(db, id, run_id, payload[3], action, confirmation)
    if action == 'delete':
        return workspace_redirect(id, 'themes', 'discussion-themes')
    return RedirectResponse(f'/host/gatherings/{id}?tab=themes&analysis={run_id}#analysis-{run_id}', 303)


@app.post("/host/gatherings/{id}/themes/manual")
def manual_theme(id: int, request: Request, request_key: str = Form(...), title: str = Form(...), description: str = Form("")):
    require_admin(request)
    get_gathering(id)
    validate_theme_key(request, id, 'manual', request_key)
    title = workflow.plain_text(title, 120)
    description = workflow.plain_text(description, 2000, required=False, multiline=True)
    with connection() as db:
        db.execute('BEGIN IMMEDIATE')
        workflow.claim_request(db, request_key, id, 'manual')
        workflow.insert_theme(db, id, title, description, 'manual')
        workflow.finish_request(db, request_key, 'complete')
    return workspace_redirect(id, "themes", "discussion-themes")


@app.post("/host/gatherings/{id}/themes/{theme_id}/notes")
def theme_notes(id: int, theme_id: int, request: Request, notes_revision: int = Form(...),
                shared_concerns: str = Form(''), different_perspectives: str = Form(''),
                discussion_questions: str = Form('')):
    require_admin(request)
    get_gathering(id)
    with connection() as db:
        workflow.save_notes(db, id, theme_id, notes_revision, shared_concerns, different_perspectives, discussion_questions)
    return workspace_redirect(id, 'themes', theme=theme_id)


@app.post("/host/gatherings/{id}/themes/{theme_id}/{action}")
def theme_action(id: int, theme_id: int, action: str, request: Request, revision: int = Form(...),
                 title: str = Form(""), description: str = Form(""), confirmation: str = Form("")):
    require_admin(request)
    get_gathering(id)
    try:
        with connection() as db:
            workflow.change_theme(db, id, theme_id, revision, action, title, description, confirmation)
    except HTTPException as exc:
        if exc.status_code not in (400, 409):
            raise
        return host_gathering_page(id, request, str(exc.detail), error_theme=theme_id,
                                   error_action=action, submitted={'title': title, 'description': description},
                                   status_code=exc.status_code)
    return workspace_redirect(id, "themes", "discussion-themes", theme_id if action != 'delete' else None)


@app.post("/host/gatherings/{id}/edit")
def edit_gathering(id: int, request: Request, title: str = Form(...), description: str = Form(...),
                   location: str = Form(...), gathering_date: str = Form(''), start_time: str = Form(''),
                   end_time: str = Form(''), timezone: str = Form('')):
    require_admin(request)
    gathering = get_gathering(id)
    values = [validate_text(title, 120), validate_text(description, 1000), validate_text(location, 120)]
    # Legacy hosts may edit unrelated details without confirming their schedule.
    supplied = any((gathering_date, start_time, end_time))
    schedule = checked_schedule(gathering_date, start_time, end_time, timezone, gathering) if supplied else None
    if not supplied and timezone:
        try:
            resolve_timezone(timezone)
        except TimezoneDataError as exc:
            raise HTTPException(503, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
    if not supplied and gathering.get('gathering_date'):
        raise HTTPException(400, 'A confirmed schedule cannot be cleared. Complete the scheduling fields.')
    with connection() as db:
        db.execute("UPDATE gatherings SET title=?,description=?,location=? WHERE id=?", (*values, id))
        if schedule:
            db.execute("""UPDATE gatherings SET gathering_date=?,start_time=?,end_time=?,timezone=?,
                start_fold=?,end_fold=? WHERE id=?""", (*schedule.values(), id))
    request.session['details_saved'] = id
    return workspace_redirect(id, "gathering", "details-feedback")


@app.post("/host/gatherings/{id}/status")
def set_status(id: int, request: Request, status: str = Form(...)):
    require_admin(request)
    get_gathering(id)
    if status not in ("cancelled", "active"):
        raise HTTPException(400, "Invalid gathering status")
    with connection() as db:
        db.execute("INSERT INTO gathering_status VALUES (?,?) ON CONFLICT(gathering_id) DO UPDATE SET cancelled=excluded.cancelled", (id, int(status == "cancelled")))
    return workspace_redirect(id, "gathering", "status")


@app.post("/host/gatherings/{id}/agenda")
async def save_agenda(id: int, request: Request):
    require_admin(request)
    get_gathering(id)
    form = await request.form()
    titles, durations, notes = (form.getlist(key) for key in ("item_title", "minutes", "notes"))
    if len(titles) > 51 or len(titles) != len(durations) or len(titles) != len(notes):
        raise HTTPException(400, "Provide at most 50 complete agenda items")
    items = []
    for title, duration, note in zip(titles, durations, notes):
        if not all(isinstance(v, str) for v in (title, duration, note)):
            raise HTTPException(400, "Invalid agenda item")
        if not title.strip() and not duration.strip() and not note.strip():
            continue
        title = validate_text(title, 200)
        if duration and (len(duration) > 4 or not duration.isascii() or not duration.isdigit() or not 1 <= int(duration) <= 1440):
            raise HTTPException(400, "Duration must be 1–1440 minutes or blank")
        if len(note) > 1000:
            raise HTTPException(400, "Notes must be at most 1000 characters")
        items.append((title, int(duration) if duration else None, note.strip()))
    if len(items) > 50:
        raise HTTPException(400, "Provide at most 50 agenda items")
    with connection() as db:
        db.execute("DELETE FROM agenda_items WHERE gathering_id=?", (id,))
        for position, item in enumerate(items):
            db.execute("INSERT INTO agenda_items(gathering_id,position,title,minutes,notes) VALUES (?,?,?,?,?)", (id, position, *item))
        db.execute("UPDATE gatherings SET agenda=? WHERE id=?", ("\n".join(item[0] for item in items), id))
    return workspace_redirect(id, "gathering", "agenda")


def resource_values(title, url):
    title, url = validate_text(title, 200), validate_text(url, 2048)
    try:
        parsed = urlsplit(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password or any(c.isspace() or ord(c) < 32 for c in url):
            raise ValueError()
        parsed.port
    except ValueError:
        raise HTTPException(400, "Use an HTTP or HTTPS URL without credentials")
    return title, url


@app.post("/host/gatherings/{id}/resources")
def add_resource(id: int, request: Request, title: str = Form(...), url: str = Form(...)):
    require_admin(request)
    get_gathering(id)
    values = resource_values(title, url)
    with connection() as db:
        db.execute("INSERT INTO resources(gathering_id,title,url) VALUES (?,?,?)", (id, *values))
    return workspace_redirect(id, "gathering", "resources")


@app.post("/host/gatherings/{id}/resources/{resource_id}/{action}")
def change_resource(id: int, resource_id: int, action: str, request: Request,
                    title: str = Form(""), url: str = Form("")):
    require_admin(request)
    get_gathering(id)
    if action not in ("edit", "remove"):
        raise HTTPException(404)
    values = resource_values(title, url) if action == "edit" else None
    with connection() as db:
        if not db.execute("SELECT 1 FROM resources WHERE id=? AND gathering_id=?", (resource_id, id)).fetchone():
            raise HTTPException(404, "Resource not found")
        if action == "edit":
            db.execute("UPDATE resources SET title=?,url=? WHERE id=? AND gathering_id=?", (*values, resource_id, id))
        else:
            db.execute("DELETE FROM resources WHERE id=? AND gathering_id=?", (resource_id, id))
    return workspace_redirect(id, "gathering", "resources")


@app.get("/host/gatherings/{id}/export/{kind}.csv")
def export_csv(id: int, kind: str, request: Request):
    require_admin(request)
    get_gathering(id)
    if kind not in ("rsvps", "questions"):
        raise HTTPException(404)
    field = "name" if kind == "rsvps" else "question"
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    columns = ["id", "gathering_id", field, "created_at"]
    if kind == "questions":
        columns.append("question_number")
    writer.writerow(columns)
    with connection() as db:
        rows = (load_questions(db, id) if kind == "questions" else
                db.execute("SELECT id,gathering_id,name,created_at FROM rsvps WHERE gathering_id=? ORDER BY id", (id,)))
        for record in rows:
            row = [record[column] for column in columns]
            # Prevent spreadsheet applications from evaluating participant text as formulas.
            writer.writerow([("'" + str(v)) if str(v).lstrip().startswith(("=", "+", "-", "@")) or str(v).startswith(("\t", "\r", "\n")) else v for v in row])
    return Response(output.getvalue(), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="gathering-{id}-{kind}.csv"', "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})


def workspace_error(request, context, message, status_code):
    """Retain submitted text on the correct server-rendered view, without writes."""
    form = getattr(request.state, 'workspace_form', {})
    editable_fields = ('title', 'description', 'location', 'url',
                       'gathering_date', 'start_time', 'end_time', 'timezone', 'start_fold', 'end_fold',
                       'shared_concerns', 'different_perspectives', 'discussion_questions')
    state = {key: form[key] for key in editable_fields if isinstance(form.get(key), str)}
    agenda_rows = None
    if context['section'] == 'agenda':
        columns = [form.getlist(key) for key in ('item_title', 'minutes', 'notes')] if hasattr(form, 'getlist') else [[], [], []]
        agenda_rows = [{key: values[i] if i < len(values) and isinstance(values[i], str) else ''
                        for key, values in zip(('title', 'minutes', 'notes'), columns)}
                       for i in range(min(51, max(1, *(len(values) for values in columns))))]
    return host_gathering_page(context['id'], request, message, error_theme=context['theme_id'],
        error_action=context['action'], submitted=state, status_code=status_code, tab=context['tab'],
        form_state=state, error_section=context['section'], error_resource=context['resource_id'],
        agenda_rows=agenda_rows, error_run=context['run_id'])


@app.exception_handler(HTTPException)
async def host_workspace_http_error(request: Request, exc: HTTPException):
    if request.url.path == '/host/gatherings' and is_admin(request) and exc.status_code in (400, 503):
        return dashboard_page(request, str(exc.detail), dict(await request.form()), exc.status_code)
    context = workspace_action(request)
    if context and is_admin(request) and exc.status_code in (400, 409, 503):
        try:
            return workspace_error(request, context, str(exc.detail), exc.status_code)
        except HTTPException as missing:
            return await http_exception_handler(request, missing)
    return await http_exception_handler(request, exc)


@app.exception_handler(RequestValidationError)
async def host_workspace_validation_error(request: Request, exc: RequestValidationError):
    if request.url.path == '/host/gatherings' and is_admin(request):
        return dashboard_page(request, "Please complete the required fields and check their values.", dict(await request.form()), 422)
    context = workspace_action(request)
    if context and is_admin(request):
        try:
            return workspace_error(request, context, "Please complete the required fields and check their values.", 422)
        except HTTPException as missing:
            return await http_exception_handler(request, missing)
    return await request_validation_exception_handler(request, exc)
