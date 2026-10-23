# Common Ground — community gatherings prototype

Independent, open-source prototype for neighborhood gathering coordination, built as an AI-assisted software development portfolio project. **Not affiliated with Resonance.**

## First milestone

- Public list of gatherings and individual gathering pages
- RSVP by name (demo; not a validated attendee registration system)
- Participant question submission
- Password-protected host dashboard to review submissions and create gatherings
- SQLite persistence in a named Docker volume
- Mobile-friendly server-rendered UI, no frontend build step

This release **does not yet contain AI features**. Those are a separate, testable milestone using Ollama, host review, and synthetic sample data.

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

## Planned next milestone

Use locally served Ollama to suggest discussion themes based on synthetic questions. Hosts must review and approve output. Include a clear fallback when Ollama is unavailable, and measure latency/resource use. Do not treat AI summaries as authoritative.

## Project layout

- `app/main.py` — routes and SQLite database setup
- `app/templates` — server-rendered HTML
- `app/static` — CSS
- `tests` — end-to-end HTTP tests
- `docs/DECISIONS.md` — architecture and governance log

License: MIT. See LICENSE.
