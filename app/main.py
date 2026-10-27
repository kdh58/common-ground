"""Common Ground: small community gathering prototype.

Development demo only; review security/privacy before public deployment.
"""
import csv
import io
from urllib.parse import urlsplit

import hmac
import os
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader, select_autoescape
from starlette.middleware.sessions import SessionMiddleware

from app.themes import ThemeError, suggest_themes

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


app = FastAPI(dependencies=[Depends(protect_request)], title="Common Ground", docs_url=None, redoc_url=None)
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET, same_site="lax", https_only=False)
app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")
templates = Environment(loader=FileSystemLoader(str(ROOT / "templates")), autoescape=select_autoescape())

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
    return result

def validate_text(value, max_chars):
    value = value.strip()
    if not value or len(value) > max_chars:
        raise HTTPException(400, f"Must have 1–{max_chars} characters")
    return value

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    with connection() as db:
        gatherings = [dict(r) for r in db.execute("SELECT * FROM gatherings ORDER BY id DESC")]
    return render("home.html", request, gatherings=gatherings)

@app.get("/gatherings/{id}", response_class=HTMLResponse)
def gathering_page(id: int, request: Request, thanks: str = ""):
    g = get_gathering(id)
    with connection() as db:
        count = db.execute("SELECT COUNT(*) FROM rsvps WHERE gathering_id=?", (id,)).fetchone()[0]
    return render("gathering.html", request, gathering=g, count=count, thanks=thanks)

@app.post("/gatherings/{id}/rsvp")
def rsvp(id: int, name: str = Form(...)):
    if get_gathering(id)["cancelled"]:
        raise HTTPException(409, "This gathering is cancelled")
    name = validate_text(name, 100)
    with connection() as db:
        db.execute("INSERT INTO rsvps(gathering_id,name,created_at) VALUES (?,?,?)", (id, name, datetime.now(timezone.utc).isoformat()))
    return RedirectResponse(f"/gatherings/{id}?thanks=rsvp", status_code=303)

@app.post("/gatherings/{id}/questions")
def question(id: int, question: str = Form(...)):
    if get_gathering(id)["cancelled"]:
        raise HTTPException(409, "This gathering is cancelled")
    question = validate_text(question, 500)
    with connection() as db:
        db.execute("INSERT INTO questions(gathering_id,question,created_at) VALUES (?,?,?)", (id, question, datetime.now(timezone.utc).isoformat()))
    return RedirectResponse(f"/gatherings/{id}?thanks=question", status_code=303)

def is_admin(request):
    return bool(request.session.get("admin"))

def require_admin(request):
    if not is_admin(request):
        raise HTTPException(403, "Host login required")

@app.get("/host", response_class=HTMLResponse)
def host(request: Request):
    if not is_admin(request):
        return render("login.html", request, error="")
    with connection() as db:
        gatherings = [dict(r) for r in db.execute("SELECT g.*, COALESCE(s.cancelled, 0) AS cancelled FROM gatherings g LEFT JOIN gathering_status s ON s.gathering_id=g.id ORDER BY g.id DESC")]
        questions = [dict(r) for r in db.execute("SELECT q.question, g.title FROM questions q JOIN gatherings g ON g.id=q.gathering_id ORDER BY q.id DESC LIMIT 50")]
        rsvps = [dict(r) for r in db.execute("SELECT r.name, g.title FROM rsvps r JOIN gatherings g ON g.id=r.gathering_id ORDER BY r.id DESC LIMIT 50")]
    return render("host.html", request, gatherings=gatherings, questions=questions, rsvps=rsvps)

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

@app.post("/host/gatherings")
def create_gathering(request: Request, title: str = Form(...), description: str = Form(...),
                     when_text: str = Form(...), location: str = Form(...), agenda: str = Form(...)):
    require_admin(request)
    vals = [validate_text(title, 120), validate_text(description, 1000),
            validate_text(when_text, 120), validate_text(location, 120), validate_text(agenda, 2000)]
    with connection() as db:
        cursor = db.execute("INSERT INTO gatherings(title,description,when_text,location,agenda) VALUES (?,?,?,?,?)", vals)
        for position, item in enumerate(vals[4].splitlines()):
            if item.strip():
                db.execute("INSERT INTO agenda_items(gathering_id,position,title) VALUES (?,?,?)", (cursor.lastrowid, position, item.strip()))
    return RedirectResponse("/host", status_code=303)

@app.get("/health")
def health():
    return {"status": "ok"}


def host_gathering_page(id, request, generate=False):
    require_admin(request)
    gathering = get_gathering(id)
    with connection() as db:
        questions = [dict(r) for r in db.execute(
            "SELECT id, question FROM questions WHERE gathering_id=? ORDER BY id", (id,))]
    themes, error = [], ""
    if generate:
        if not questions:
            error = "No questions yet. Add participant questions before suggesting themes. Ollama was not called."
        else:
            try:
                themes = suggest_themes(questions, OLLAMA_BASE_URL, OLLAMA_MODEL)
            except ThemeError as exc:
                error = str(exc)
    return render("host_gathering.html", request, gathering=gathering,
                  questions=questions, themes=themes, error=error)


@app.get("/host/gatherings/{id}", response_class=HTMLResponse)
def host_gathering(id: int, request: Request):
    return host_gathering_page(id, request)


@app.post("/host/gatherings/{id}/themes", response_class=HTMLResponse)
def gathering_themes(id: int, request: Request):
    return host_gathering_page(id, request, generate=True)


@app.post("/host/gatherings/{id}/edit")
def edit_gathering(id: int, request: Request, title: str = Form(...), description: str = Form(...),
                   when_text: str = Form(...), location: str = Form(...)):
    require_admin(request)
    get_gathering(id)
    values = [validate_text(title, 120), validate_text(description, 1000), validate_text(when_text, 120), validate_text(location, 120)]
    with connection() as db:
        db.execute("UPDATE gatherings SET title=?,description=?,when_text=?,location=? WHERE id=?", (*values, id))
    return RedirectResponse(f"/host/gatherings/{id}", 303)


@app.post("/host/gatherings/{id}/status")
def set_status(id: int, request: Request, status: str = Form(...)):
    require_admin(request)
    get_gathering(id)
    if status not in ("cancelled", "active"):
        raise HTTPException(400, "Invalid gathering status")
    with connection() as db:
        db.execute("INSERT INTO gathering_status VALUES (?,?) ON CONFLICT(gathering_id) DO UPDATE SET cancelled=excluded.cancelled", (id, int(status == "cancelled")))
    return RedirectResponse(f"/host/gatherings/{id}", 303)


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
    return RedirectResponse(f"/host/gatherings/{id}", 303)


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
    return RedirectResponse(f"/host/gatherings/{id}", 303)


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
    return RedirectResponse(f"/host/gatherings/{id}", 303)


@app.get("/host/gatherings/{id}/export/{kind}.csv")
def export_csv(id: int, kind: str, request: Request):
    require_admin(request)
    get_gathering(id)
    if kind not in ("rsvps", "questions"):
        raise HTTPException(404)
    field = "name" if kind == "rsvps" else "question"
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["id", "gathering_id", field, "created_at"])
    with connection() as db:
        for row in db.execute(f"SELECT id,gathering_id,{field},created_at FROM {kind} WHERE gathering_id=? ORDER BY id", (id,)):
            # Prevent spreadsheet applications from evaluating participant text as formulas.
            writer.writerow([("'" + str(v)) if str(v).lstrip().startswith(("=", "+", "-", "@")) or str(v).startswith(("\t", "\r", "\n")) else v for v in row])
    return Response(output.getvalue(), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="gathering-{id}-{kind}.csv"', "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})
