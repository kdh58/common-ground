"""Common Ground: small community gathering prototype.

Development demo only; review security/privacy before public deployment.
"""
import hmac
import os
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
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

app = FastAPI(title="Common Ground", docs_url=None, redoc_url=None)
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
        existing = db.execute("SELECT COUNT(*) FROM gatherings").fetchone()[0]
        if existing == 0:
            db.execute("INSERT INTO gatherings (title, description, when_text, location, agenda) VALUES (?, ?, ?, ?, ?)", (
                "The Future of Our Library", "A fictional community gathering to plan new library services.",
                "Saturday, November 14 · 2:00 PM", "Community Library · Meeting Room",
                "Welcome and introductions\nWhat does our community need?\nIdeas and next steps"))

@app.on_event("startup")
def on_startup():
    init_db()

def render(name, request, **kwargs):
    return HTMLResponse(templates.get_template(name).render(request=request, **kwargs))

def get_gathering(id):
    with connection() as db:
        row = db.execute("SELECT * FROM gatherings WHERE id=?", (id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Gathering not found")
    return dict(row)

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
    get_gathering(id)
    name = validate_text(name, 100)
    with connection() as db:
        db.execute("INSERT INTO rsvps(gathering_id,name,created_at) VALUES (?,?,?)", (id, name, datetime.now(timezone.utc).isoformat()))
    return RedirectResponse(f"/gatherings/{id}?thanks=rsvp", status_code=303)

@app.post("/gatherings/{id}/questions")
def question(id: int, question: str = Form(...)):
    get_gathering(id)
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
        gatherings = [dict(r) for r in db.execute("SELECT * FROM gatherings ORDER BY id DESC")]
        questions = [dict(r) for r in db.execute("SELECT q.question, g.title FROM questions q JOIN gatherings g ON g.id=q.gathering_id ORDER BY q.id DESC LIMIT 50")]
        rsvps = [dict(r) for r in db.execute("SELECT r.name, g.title FROM rsvps r JOIN gatherings g ON g.id=r.gathering_id ORDER BY r.id DESC LIMIT 50")]
    return render("host.html", request, gatherings=gatherings, questions=questions, rsvps=rsvps)

@app.post("/host/login")
def login(request: Request, password: str = Form(...)):
    if not ADMIN_PASSWORD or not hmac.compare_digest(password, ADMIN_PASSWORD):
        return render("login.html", request, error="Incorrect password")
    request.session["admin"] = True
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
        db.execute("INSERT INTO gatherings(title,description,when_text,location,agenda) VALUES (?,?,?,?,?)", vals)
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
