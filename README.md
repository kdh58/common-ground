# Common Ground

Common Ground is an independent community-gathering prototype and AI-assisted
software development portfolio project for a Resonance Technical Fellowship
application. It is **not affiliated with or endorsed by Resonance**. Use fictional
data only. Publishing this source does not deploy a service.

## Video Demonstration

**[Watch the 85-second Common Ground demonstration](https://common-ground.itresidentexpert.com/demo.mp4)**

The video demonstrates the working participant interface, host administration,
AI-assisted discussion preparation, and human review and publication.

The deployed interactive demonstration is password-protected, while the video
and source code are publicly accessible.

## What works today

Participants browse paginated gathering directories and see gathering details,
schedules, agendas, URL resources and host-published discussion topics. They may
RSVP with a name or nickname and independently submit a question without an RSVP.
Questions are not linked to RSVP records. Neither names nor original questions
are displayed publicly. Past and cancelled gatherings close both submission forms.

Organizers sign in using a shared host password. The workspace has three tabs:

- **Gathering:** edit details and structured schedules, manage ordered agenda
  items and HTTP/HTTPS resource links, cancel or restore a gathering.
- **Participants:** review original contributions and download private, gathering-
  scoped RSVP and question CSV exports with spreadsheet-formula escaping.
- **Discussion Themes:** create manual drafts or request optional Ollama analysis;
  review citations, edit themes and private facilitation notes, approve and publish.

AI output is private draft material, not evidence of community consensus. Approval
and publication are separate host actions. Editing approved or published text
returns it to draft and removes it from the participant page. Manual themes work
without AI. Repeated AI analyses append independent runs; hosts can make runs
inactive, reactivate them or confirm deletion where permitted. Protected approved
or published content prevents run deletion. Coverage shows cited/uncited input
questions, not whether the model understood them.

Saved analyses have authenticated **View / Print Analysis** reports in a new tab
and downloadable HTML. Reports contain saved values, citations, coverage and private
notes; exporting never invokes Ollama. Keep reports and CSV exports private.

## Prerequisites

- Git and access to this repository (while private, authorized GitHub access).
- Docker Engine with Compose v2, or Docker Desktop with WSL integration on Windows.
- Bash and OpenSSL for the isolated reviewer setup; a modern browser with JavaScript.
- For native tests: Python 3.12, venv/pip, system IANA timezone data and Node.js 20+.
- Network access for the initial image/dependency installation. No GPU or Ollama is
  required for non-AI features or the automated suites.

## Clone and start an isolated local review

Use a new checkout on your own machine, not an existing installation directory:

```sh
git clone https://github.com/kdh58/common-ground.git common-ground-review
cd common-ground-review
```

Follow [the reviewer guide](docs/REVIEWER_GUIDE.md) to generate separate local
credentials and start the standalone [reviewer Compose example](examples/compose.reviewer.yaml).
It binds only to `127.0.0.1:18080` by default and uses its own project-scoped database
volume. It does not use an existing installation's `.env` or database. Do not use
production secrets, copy a real database or expose this prototype through a tunnel.

The operational `compose.yaml` binds `127.0.0.1:8000` and requires `ADMIN_PASSWORD`
and `SESSION_SECRET`. [.env.example](.env.example) documents configuration names
and public contact defaults; its password/secret values are placeholders. Python
itself does not load `.env` files: native runs need explicit environment variables.
Never overwrite an installation's existing `.env` to follow this guide.

## Reviewer walkthrough without AI hardware

1. Open the participant page, then the fictional Library gathering. Submit a
   fictional question without an RSVP, then submit a fictional nickname separately.
2. Open `/host`, sign in with the reviewer password, choose **Manage gathering**
   and inspect **Participants** and both CSV exports.
3. In **Discussion Themes**, create a manual draft and private facilitation notes.
   Approve it; verify it is still absent publicly. Publish it; verify the public
   curated topic. Edit it and verify it becomes private again.
4. In **Gathering**, update an agenda/resource and confirm participant visibility.
   Cancel and restore the gathering; submissions should close and reopen if it
   has not ended. Create another fictional gathering with a future date.
5. With a question present, click **Suggest Discussion Themes**. The reviewer
   default has no AI service: expect loading feedback followed by inline standby
   guidance and Retry, without page navigation. Other features remain available.
6. Run the suites below to exercise successful AI responses, citations, report
   generation, timeouts and recovery with mocked Ollama. This is test coverage,
   not a claim that live inference ran during the walkthrough.

A new database starts with **one fictional Library gathering, zero questions and
zero RSVPs**. Its legacy schedule has no year/timezone and appears as Schedule to
be confirmed. The optional [seed manifest](app/demo_gatherings.json) adds five
December 2026 gatherings and 60 questions: **six gatherings and 60 questions total**
when applied immediately to an untouched fresh instance. Seven gatherings and 94
questions were an earlier developer-local state, not a dataset shipped here.
See [seeding and reset safety](docs/DEMO_SEEDING.md). Events become Past after their
scheduled dates; create a future event rather than changing your system clock.

## Optional Ollama assistance

Ollama is optional and runs separately. Install a model on hardware you control
and configure an endpoint reachable **from the web process/container**:

| Variable | Application/operational default | Reviewer default |
|---|---|---|
| `OLLAMA_BASE_URL` | `http://host.docker.internal:11434` | `http://127.0.0.1:1` (offline) |
| `OLLAMA_MODEL` | `qwen3:8b` | `qwen3:8b` |
| `DEMO_CONTACT_NAME` | Kevin | same public demo contact |
| `DEMO_CONTACT_EMAIL` | `kevin@itresidentexpert.com` | same |
| `DEMO_CONTACT_PHONE` | `+15717584756` | same |

These contact defaults were explicitly requested for demonstration inquiries;
they are public contact information, not credentials. The owner should reconfirm
continued publication consent before changing visibility; see [licensing and
publication review](docs/LICENSING.md).

For the reviewer example, put any overrides only in `.env.reviewer` before
launching it; do not edit a deployment `.env`. Confirm the exact installed model
name with `ollama list` on your own Ollama installation.

Docker Desktop commonly provides `host.docker.internal`. Native Python commonly
uses `http://localhost:11434`; container `localhost` means that container, not the
host. Linux Engine setups may need operator-provided local connectivity. This
repository does not configure private networks, proxies or Ollama hardware. Leave
the reviewer offline default in place unless you have your own reachable service.
Do not publish Ollama's port or credentials to obtain a demonstration.

Before inference, a server-side `/api/tags` check verifies the configured model,
without generating text: one-second connection and three-second I/O timeouts,
with a per-process cache of 15 seconds for readiness and five seconds for failures.
Unreachable service/missing model shows standby guidance with telephone/email
links. That wording describes the demo's normal operating arrangement; it does
not establish the technical cause of downtime. Processing failures and running
analysis timeouts have a separate error and Retry.

With JavaScript, requests show an accessible spinner and disable duplicate submits;
failures update an inline alert without moving focus or navigating the page. Retry
uses a fresh server request key when available. Successful analysis navigates to
the saved themes section. Without JavaScript the form still submits, but reloads
and has no animated loading enhancement.

Generation sends only that gathering's questions, using gathering-local question
numbers. It uses structured JSON, thinking disabled, a 4,800-token output budget,
a five-second connection timeout and a 90-second network-operation timeout.
Incomplete/invalid batches save no partial themes. External endpoint hosts are
rejected: accepted hosts are localhost, host.docker.internal, ollama, loopback,
RFC1918 IPv4 and IPv6 unique-local addresses. Inference redirects are not followed.
The app cannot audit an operator-controlled server or forwarding proxy. Review
[model licensing](docs/LICENSING.md) and [Ollama's API](https://docs.ollama.com/api/chat)
before using another model/version.

## Scheduling and persistence

New gatherings require a date and start time, with an optional same-day end time.
JavaScript detects the browser's IANA timezone and fills a hidden field; there is
no guessed timezone fallback for scheduling. Editing preserves the saved zone;
**Change timezone** explicitly switches to the browser's detected zone. New times
that are skipped/repeated at a daylight-saving transition are rejected. Historical
saved occurrence choices survive unchanged edits. Legacy schedule text is retained
without guessing a year/timezone. Existing legacy details can be edited while
leaving their unconfirmed schedule blank.

System timestamps are UTC in SQLite/CSV. Browser display uses the detected timezone;
without detection it visibly falls back to America/New_York. This timestamp fallback
is distinct from scheduling, which needs a valid explicit zone. Full browser and
assistive-technology review remains manual; JavaScript tests use native Intl and
DOM fixtures rather than a real browser.

SQLite persists in the configured Docker volume. Startup creates/migrates schema;
scheduling migration backs up populated legacy databases before adding fields.
Back up an existing installation **before starting newer code**. Source checkout or
push alone performs no migration. See [operator notes](docs/OPERATIONS.md).

## Complete tests

Native environment, from the repository root:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pytest -q -p no:cacheprovider
node --test tests/*.cjs
bash -n scripts/database.sh scripts/test-docker-timezones.sh
git diff --check
```

The suites use temporary SQLite databases and mocked Ollama; no live model, existing
installation or participant data is required. Dependencies use version ranges and
the base image uses a mutable tag, so exact installations are not locked.

To test the actual Dockerfile application without mounting live data:

```sh
bash scripts/test-docker-timezones.sh
docker run --rm --network none --read-only --tmpfs /tmp \
  --mount "type=bind,src=$PWD/tests,dst=/project/tests,readonly" \
  -e PYTHONDONTWRITEBYTECODE=1 \
  cg-timezone-test:local python -m pytest -q -p no:cacheprovider
# If Node is not installed locally:
docker run --rm --network none --read-only \
  --mount "type=bind,src=$PWD,dst=/project,readonly" -w /project \
  node:22-alpine sh -c 'node --test tests/*.cjs'
```

The timezone script builds a test-only image and runs targeted timezone tests;
the subsequent command runs the complete Python suite. The Node image must be
available locally before the network-disabled test run.

## Limitations and publication boundaries

**Local fictional-data prototype, not ready for an unrestricted public service.**
Authentication is a shared password, not individual accounts or ownership roles.
Session cookies are not configured Secure; rate limiting, participant deletion/
retention controls and a complete privacy design remain unfinished. Questions
have no RSVP identity field; this is not a guarantee of network-level anonymity.

Resource links are URLs only; document upload/storage is not implemented. AI output
needs human review for grounding, representation and interpretation. There is no
full edit history, automatic analysis-history cleanup or inference cancellation.
Scheduling creation requires browser JavaScript and valid timezone data.

The Docker build context is deny-by-default: only required source/build files are
allowed, excluding credentials, backups, databases, Git history and local caches.
The running app volume is separate from that context. Never publish workspace
archives, ignored local artifacts, model weights, backup branches or mirror refs.
Public GitHub visibility and public service deployment require separate explicit
approval. No DigitalOcean deployment is performed by these instructions.

## Documentation and license

- [Organizer and administrator guide](docs/ORGANIZER_ADMIN_GUIDE.md)
- [Social impact brief](docs/SOCIAL_IMPACT.md)
- [Technical architecture and implementation](docs/TECHNICAL_ARCHITECTURE.md)
- [Reviewer setup and disposable cleanup](docs/REVIEWER_GUIDE.md)
- [Fictional seed data and guarded apply](docs/DEMO_SEEDING.md)
- [Existing-installation backup/restore and deployment boundaries](docs/OPERATIONS.md)
- [Licensing, model terms and human publication review](docs/LICENSING.md)
- [Architecture decisions and historical development notes](docs/DECISIONS.md)
- [Historical model-response investigation](docs/THEME_INVESTIGATION.md)
- [MIT license for Common Ground source](LICENSE)

Third-party dependencies, container components and optional models retain their
own terms; the MIT project license does not replace them. No model weights,
participant database or developer-local backups are included in this repository.
