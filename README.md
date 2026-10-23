# Common Ground — community gatherings prototype

Independent, open-source prototype for neighborhood gathering coordination, built as an AI-assisted software development portfolio project. **Not affiliated with Resonance.**

## First milestone

- Public list of gatherings and individual gathering pages
- RSVP by name (demo; not a validated attendee registration system)
- Participant question submission
- Password-protected host dashboard to review submissions and create gatherings
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

## Tests

With Python 3.12 available:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pytest -q
```

## Security and privacy status

**Local development only. Do not put this version on the public Internet.** It has deliberately minimal host authentication, no CSRF protection or rate limiting, and no participant notice/retention controls. It should use HTTPS-only cookies, robust authentication, spam protection, and a privacy/data deletion design before public deployment. Test only with fictional contributions, no sensitive information. The default demo gathering is fictional. No real community data should be submitted.

## Ollama discussion themes

In `/host`, choose **Host review** beside a gathering, then **Suggest Discussion Themes**. Only that gathering's questions are sent to Ollama; no questions means no model call. Public pages cannot generate themes. Review each draft against its cited original questions: AI output may be inaccurate and is not evidence of participant consensus.

`OLLAMA_BASE_URL` defaults to `http://host.docker.internal:11434`; `OLLAMA_MODEL` defaults to `qwen3:8b`. Both can be overridden in `.env` for Compose, or through environment variables when running Python directly. The endpoint must be reachable from the app's environment (a native Python process may need `http://localhost:11434`). Use an already running Ollama instance with the configured model installed. This app does not change WSL or Ollama service settings.

Requests use structured JSON output, a 5-second connection timeout and a 45-second network-operation timeout. Connection/model errors, timeouts and invalid output show a retry message while preserving questions. Drafts exist only in the returned page; refreshing the host review page clears them. Tests mock Ollama and require no live model.

## Project layout

- `app/main.py` — routes and SQLite database setup
- `app/templates` — server-rendered HTML
- `app/static` — CSS
- `tests` — end-to-end HTTP tests
- `docs/DECISIONS.md` — architecture and governance log

License: MIT. See LICENSE.
