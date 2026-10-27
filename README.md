# Common Ground — community gatherings prototype

Independent, open-source prototype for neighborhood gathering coordination, built as an AI-assisted software development portfolio project. **Not affiliated with Resonance.**

## First milestone

- Public list of gatherings and individual gathering pages
- RSVP by name (demo; not a validated attendee registration system)
- Participant question submission
- Password-protected host dashboard to create and edit gatherings, manage agendas and URL resources, cancel or restore gatherings, and export submissions
- SQLite persistence in a named Docker volume
- Mobile-friendly server-rendered UI, no frontend build step

Authenticated hosts can request draft discussion themes for an individual gathering using Ollama. Original questions are preserved; suggestions are saved as private drafts and are never automatically approved or published.

## Start in WSL + Docker Desktop

1. Make sure Docker Desktop is running and WSL integration is enabled for your Ubuntu distribution.
2. Open a WSL terminal in this repository.
3. `cp .env.example .env`
4. Change both values in `.env`. Generate the random session secret with `openssl rand -hex 32`.
5. `docker compose up --build -d`
6. Open <http://localhost:8000> for the participant interface and <http://localhost:8000/host> for the organizer interface.
7. Inspect logs: `docker compose logs -f web`.
8. Stop containers: `docker compose down` (preserves database); `docker compose down -v` **deletes demo data**.

Docker publishes only on `127.0.0.1` to avoid unintentionally making this development server public.

## Backup and restore

Before starting an updated version that changes the schema, back up the running
app from the repository root:

```bash
bash scripts/database.sh backup
# Or choose a destination:
bash scripts/database.sh backup backups/before-changes.db
```

Backups use SQLite's online backup API and are checked for integrity. Each file
contains the entire database, including gatherings, RSVPs, questions, and saved themes. Existing backup files are never overwritten.
The default destination is a timestamped file in `backups/` (excluded from Git).
Copy backups to a separate disk or other durable storage for protection against disk loss.
Treat these files as private; they contain all participant contributions and unpublished themes.
After verifying the backup, rebuild with `docker compose up --build -d` when you
are ready to run the updated version.

To replace the current database with a backup:

```bash
bash scripts/database.sh restore backups/before-changes.db --yes
```

Restore briefly stops the web service, validates the incoming database, saves a
`/data/pre-restore-<timestamp>.db` recovery copy in the Docker volume, and replaces
the database. The service restarts if it was running, including after a failed
restore. `--yes` explicitly acknowledges replacement of current data. Run only one
backup or restore operation at a time, with no other processes accessing the database
during restore. Recovery copies share the database volume and are deleted by
`docker compose down -v`; external backups survive that command.

Backups do not include `.env`, host credentials, session secrets, or application
code. Keep those separately in secure storage, and restore with the same application
version that created the backup. To restore after volume loss, first build the image
with `docker compose build web`, configure `.env`, then run the restore command and
`docker compose up -d`.

## Tests

With Python 3.12 available:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pytest -q
```

## Security and privacy status

**Local development only. Do not put this version on the public Internet.** It has deliberately minimal host authentication, no rate limiting, and no participant notice/retention controls. It should use HTTPS-only cookies, robust authentication, spam protection, and a privacy/data deletion design before public deployment. Test only with fictional contributions, no sensitive information. The default demo gathering is fictional. No real community data should be submitted.

## Ollama discussion themes

In `/host`, choose **Manage gathering** beside a gathering, then **Suggest Discussion Themes**. Only that gathering's questions are sent to Ollama; no questions means no model call. Public pages cannot generate themes. Review each draft against its cited original questions: AI output may be inaccurate and is not evidence of participant consensus.

`OLLAMA_BASE_URL` defaults to `http://host.docker.internal:11434`; `OLLAMA_MODEL` defaults to `qwen3:8b`. Both can be overridden in `.env` for Compose, or through environment variables when running Python directly. The endpoint must be reachable from the app's environment (a native Python process may need `http://localhost:11434`). Use an already running local Ollama instance with the configured local model installed.
External endpoints are rejected before sending questions. Allowed hosts are
`localhost`, `host.docker.internal`, `ollama`, loopback IPs, RFC1918 private IPv4
addresses, and IPv6 unique-local addresses. HTTP redirects are not followed.
Operate Ollama without cloud inference or forwarding proxies; the application
cannot audit the behavior of an operator-controlled inference server. This app does not change WSL or Ollama service settings.

Requests use structured JSON output, a 5-second connection timeout and a 45-second network-operation timeout. Connection/model errors, timeouts and invalid output show a retry message while preserving questions. Successful generation saves new private drafts in SQLite and redirects to Manage gathering.
Reloading the page or restarting the app preserves them. A failed request saves no
partial suggestions and preserves existing themes. Tests mock Ollama and require no live model.

## Project layout

- `app/main.py` — routes and SQLite database setup
- `app/templates` — server-rendered HTML
- `app/static` — CSS
- `tests` — end-to-end HTTP tests
- `docs/DECISIONS.md` — architecture and governance log

License: MIT. See LICENSE.

## Host operations

Open **Manage gathering** from `/host` to edit title, description, date/time text, and
location. Save the structured agenda with ordered titles, optional durations
(1–1440 minutes), and public notes. Clear all fields in a row to remove it; save
to obtain another blank row. Revise row contents to change their order. Up to 50
agenda items are supported. Existing line-based agendas migrate automatically;
original gathering IDs, RSVPs, and questions are retained. Migrations are additive
and repeatable; take a verified backup before first starting the updated version.

Add, edit, and remove public HTTP/HTTPS resource links. The server does not fetch
links. Document uploads are deferred pending private storage, file validation,
size limits, and a safe download policy.

Cancel a gathering to display its cancelled status and close participant forms.
Restore it to reopen forms. Both actions preserve all RSVPs and questions; host
review and exports remain available while cancelled.

**Export RSVPs** and **Export questions** download separate, gathering-specific CSV
files with IDs, gathering IDs, contribution text, and UTC timestamps. Downloads
require host login and are marked `no-store`. Spreadsheet formula prefixes are
escaped with an apostrophe; CSV quoting preserves commas, quotes, and newlines.
Treat exports as private participant data.

All modifying forms, including login, logout, theme generation, RSVPs, and questions,
require a session-bound CSRF token. Reload a form after signing in or out if its
token has expired. Host actions still use the existing shared-password session;
there are no per-organizer accounts or gathering ownership permissions.

## Community-governed discussion themes

In **Manage gathering → Discussion themes**, use **Suggest Discussion Themes** or
**Create manual draft**. The existing generator still proposes titles with cited
question IDs; descriptions start blank so hosts can write their own context.
No new external service, analytics, or telemetry is used.

| State | Meaning | Public visibility |
| --- | --- | --- |
| Draft | AI suggestion or host-written content awaiting explicit review | Private |
| Approved | Host explicitly approved the current text; not yet published | Private |
| Published | Approved text explicitly published by the host | Visible on that gathering's page as a curated discussion topic |

Review cited original questions, edit the title (1–120 characters) and optional
plain-text description (up to 2,000 characters), then **Save as draft**.
**Approve theme** and **Publish theme** are separate actions. Editing approved or
published content immediately removes approval and publication; the revised text
requires both actions again. The old public text is not retained as a separate
public version. **Unpublish theme** makes it private while keeping its approval.
Only unapproved drafts can be deleted, using the disclosure, confirmation checkbox,
and **Delete draft permanently**. Questions and RSVPs are never changed by theme
operations. Generated source associations and the original AI title are retained
privately after host editing; source reassignment and full edit history are not
implemented.

**Move up** and **Move down** work with keyboard or touch, show the current
position, and change host/public display order without changing content approval.
Draft, Approved, and Published have both text labels and distinct colors. Public
pages contain only published topic text and a provenance label, never source
questions or host diagnostics. Cancelled gathering pages retain their public
content, including published topics, and keep participation forms closed.

Manual creation and AI generation use signed, gathering- and session-specific
single-use form keys. Repeated submissions return 409 without creating more drafts
or repeating inference. Other actions check a revision counter; stale forms return
409 rather than overwriting later work. Reload Manage gathering to review current
content and obtain a fresh form. A new intentional generation appends drafts and
never replaces existing themes. Inference runs synchronously without holding a
SQLite write lock. If the process stops mid-generation, its request key stays
consumed; reload and explicitly retry. Request receipts are retained to prevent
replay; automatic cleanup is not implemented.

The migration adds `discussion_themes`, `theme_sources`, and `theme_requests` plus
an ordering index, within the existing startup migration transaction. It is
additive and repeatable and does not rewrite Phase 1 records. Themes record UTC
`created_at` and `updated_at`, origin, status, order, and revision. Back up before
first starting this version; backup and restore include the new tables.
