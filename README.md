# Common Ground — community gatherings prototype

Independent, open-source prototype for neighborhood gathering coordination, built as an AI-assisted software development portfolio project. **Not affiliated with Resonance.**

## First milestone

- Public list of gatherings and individual gathering pages
- RSVP by name (demo; not a validated attendee registration system)
- Participant question submission
- Password-protected host dashboard to create and edit gatherings, manage agendas and URL resources, cancel or restore gatherings, and export submissions
- SQLite persistence in a named Docker volume
- Mobile-friendly server-rendered UI, no frontend build step

Authenticated hosts can request draft discussion themes for an individual gathering using Ollama. Original questions are preserved; suggestions are never saved or automatically published.

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

After updating the code, rebuild the container with `docker compose up --build -d`.
From the repository root, back up the running app with:

```bash
bash scripts/database.sh backup
# Or choose a destination:
bash scripts/database.sh backup backups/before-changes.db
```

Backups use SQLite's online backup API and are checked for integrity. Each file
contains gatherings, RSVPs, and questions. Existing backup files are never overwritten.
The default destination is a timestamped file in `backups/` (excluded from Git).
Copy backups to a separate disk or other durable storage for protection against disk loss.
Treat these files as private; they contain all participant contributions.

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

`OLLAMA_BASE_URL` defaults to `http://host.docker.internal:11434`; `OLLAMA_MODEL` defaults to `qwen3:8b`. Both can be overridden in `.env` for Compose, or through environment variables when running Python directly. The endpoint must be reachable from the app's environment (a native Python process may need `http://localhost:11434`). Use an already running Ollama instance with the configured model installed. This app does not change WSL or Ollama service settings.

Requests use structured JSON output, a 5-second connection timeout and a 45-second network-operation timeout. Connection/model errors, timeouts and invalid output show a retry message while preserving questions. Drafts exist only in the returned page; refreshing the host review page clears them. Tests mock Ollama and require no live model.

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
