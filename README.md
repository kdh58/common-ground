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
# Native Intl/date-formatting tests require Node.js 20+ (test tooling only):
node tests/test_timestamps.cjs
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

Requests use structured JSON output with required titles, descriptions (up to 1,000
characters), and question IDs, a bounded 1,600-token output budget with thinking
disabled, a 5-second connection timeout and a 45-second network-operation timeout. Connection/model errors, timeouts and invalid output show a retry message while preserving questions. Successful generation saves new private drafts in SQLite and redirects to Manage gathering.
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

Open **Manage gathering** from `/host`; the **Gathering** tab edits title, description, date/time text, and
location. Save the structured agenda with ordered titles, optional durations
(1–1440 minutes), and public notes. Clear all fields in a row to remove it; save
to obtain another blank row. Revise row contents to change their order. Up to 50
agenda items are supported. Existing line-based agendas migrate automatically;
original gathering IDs, RSVPs, and questions are retained. Migrations are additive
and repeatable; take a verified backup before first starting the updated version.

Add, edit, and remove public HTTP/HTTPS resource links. The server does not fetch
links. Document uploads are deferred pending private storage, file validation,
size limits, and a safe download policy.

Use **Gathering → Gathering Status** to cancel a gathering, display its cancelled status, and close participant forms.
Restore it to reopen forms. Both actions preserve all RSVPs and questions; host
review and exports remain available while cancelled.

In **Participants**, **Export RSVPs** and **Export questions** download separate, gathering-specific CSV
files with IDs, gathering IDs, contribution text, and UTC timestamps. Downloads
require host login and are marked `no-store`. Spreadsheet formula prefixes are
escaped with an apostrophe; CSV quoting preserves commas, quotes, and newlines.
Treat exports as private participant data.

All modifying forms, including login, logout, theme generation, RSVPs, and questions,
require a session-bound CSRF token. Reload a form after signing in or out if its
token has expired. Host actions still use the existing shared-password session;
there are no per-organizer accounts or gathering ownership permissions.

## Community-governed discussion themes

In **Manage gathering → Discussion Themes**, use **Suggest Discussion Themes** or
**Create manual draft**. The generator proposes concise titles and 1–3 sentence descriptions with cited
question IDs. Descriptions explain supported concerns, opportunities, competing
perspectives, and tradeoffs without claiming community consensus. The prompt asks
for distinct topics, merging redundant or substantially overlapping themes instead
of filling a quota.
Generated descriptions are validated, saved in the existing description field,
and shown privately with the draft and its edit form. They appear publicly only
after approval and publication. Missing, empty, overlong, or invalid descriptions
and duplicate normalized titles/descriptions reject the entire batch. A sentence-count
heuristic also rejects more than three sentences and repeated-title descriptions.
Semantic overlap and faithful representation still need host review.
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
applies the selected Archive/Keep/Delete choice to eligible previous AI drafts.
Manual, approved, and published themes are preserved. Inference runs synchronously without holding a
SQLite write lock. If the process stops mid-generation, its request key stays
consumed; reload and explicitly retry. Request receipts are retained to prevent
replay; automatic cleanup is not implemented.

The migration adds `discussion_themes`, `theme_sources`, and `theme_requests` plus
an ordering index, within the existing startup migration transaction. It is
additive and repeatable and does not rewrite Phase 1 records. Themes record UTC
`created_at` and `updated_at`, origin, status, order, and revision. Back up before
first starting this version; backup and restore include the new tables.

Question display numbers start at 1 for each gathering, ordered by creation time
with database ID breaking ties. Host lists and theme source citations use the same
numbers, including when only a subset is cited. New submissions append to this
order. Question CSV exports retain database IDs and add a separate
`question_number` column; citation relationships continue to use database IDs.

## Managing repeated AI analyses

**Current Themes** keeps every manual theme and every approved/published theme
visible above AI history, regardless of how old its original analysis is. Open a
theme row to edit, review original citations, approve, publish, move, or delete as
permitted by its state. Editing still removes approval/publication. Move actions
retain the gathering-wide ordering used on the public page.

**AI analysis history** groups new suggestions by explicit run ID, newest first.
Each native disclosure header shows generation time, input question count, original
number of generated themes, and current state counts. Only the newest run starts
open; individual themes start collapsed with title, status, and a description
preview. Approved/published themes remain in Current Themes; history retains their
status and a link to the current editor. Timestamps use an explicit English
12-hour format in your browser's detected timezone; without JavaScript they show the explicitly labeled
America/New_York prototype fallback (see Timezone handling below).
All disclosures and modifying forms work without JavaScript. Links can also be
opened by manually expanding the destination disclosure without JavaScript.

Before generating, choose how to handle previous unapproved AI drafts:

- **Archive** (default): keep the original records and citations but make them
  inactive. Open the old run and use **Restore draft** before editing or approving.
- **Keep**: leave previous drafts active alongside the new analysis.
- **Delete**: permanently remove previous AI drafts, including archived ones,
  only after checking the explicit confirmation box. Questions remain intact.

These choices never affect manual, approved, or published themes, or drafts that
changed while inference was running. They take effect atomically only when the
new analysis saves successfully. Failed analyses keep earlier drafts unchanged
and appear as failed runs; an interrupted request may remain marked in progress
or interrupted. Explicitly start a fresh analysis to retry. Existing single-use
request keys and theme revision checks continue to reject duplicate/stale forms.
Save/Approve errors reopen the affected theme and run and show feedback nearby.

Back up and verify SQLite before starting this version: the additive migration
introduces `analysis_runs`, `theme_analysis_runs`, and `archived_themes`. Original
theme/question IDs, content, source relationships, statuses, and participant
submissions are preserved. Older suggestions appear in **Legacy suggestions —
analysis run unknown**; their original input count and run boundaries were not
recorded and are not guessed from timestamps. No legacy themes are automatically
archived or deleted by migration. No pagination or automatic history cleanup is
implemented; collapsed history still loads on the host page.

## Timezone handling

System timestamps remain UTC in SQLite and CSV exports. Only their display changes.
Every system timestamp uses a shared formatter, including analysis start/finish and
theme Created/Updated dates. The browser detects its IANA timezone with
`Intl.DateTimeFormat().resolvedOptions().timeZone`; no Docker/container timezone,
server timezone, stored preference, or assumption about a user's location is used.
No detected timezone is sent to the server.

Dates display in an explicit English 12-hour format such as
**Oct 27, 2026 · 1:22 PM EDT**. Native Intl applies the selected zone's daylight-saving
rules; abbreviations or GMT offsets distinguish repeated fall-back hours. The
browser uses its detected timezone, including America/Los_Angeles and non-US zones.
If detection is missing, unsupported, or fails, this prototype uses
**America/New_York**, visibly labeled **(America/New_York; fallback)**. The readable
server-rendered fallback uses that same explicit zone via Python's standard-library
`zoneinfo` and is independent of the container's default timezone. It remains
visible without JavaScript or Intl. Server environments need IANA timezone data
(the existing Docker image provides it).

Visible dates and tooltips contain neither raw ISO values nor microseconds.
Machine-readable `datetime` attributes retain an explicit UTC offset with second
precision. Invalid, missing, or timezone-naive system timestamps display **Time
unavailable** rather than guessing a timezone or echoing raw data. Output uses
Jinja autoescaping and browser `textContent`, never HTML insertion.

Gathering schedules such as “Saturday, November 14 · 2:00 PM” are human-entered
**event text**, not UTC system timestamps. They remain unchanged in forms and on
public pages and are never automatically parsed or converted. Event-specific
IANA timezone configuration and structured event scheduling are future features.
Full browser/assistive-technology review remains a manual check; automated tests
exercise native Intl plus server rendering and storage preservation.

AI review descriptions appear as a short preview only while a theme is collapsed.
Expanded active themes show the description once in the editable textarea;
archived themes use a read-only textarea until restored. History references link
to the existing Current Themes editor instead of duplicating it.

New Ollama requests use gathering-local question numbers, starting at 1, in the
input `id` fields and returned `question_ids` field. The server validates against
the exact request's local-number map, maps sources back to database IDs, and checks
gathering ownership before saving. Global database IDs are not sent as model
identifiers. The prompt asks for natural issue descriptions without numbered
references in prose; model adherence still needs host review. Existing descriptions
and stored source citations are not rewritten.

## End-to-end demonstration sequence

Use fictional data and a local test instance of this checkpoint. Before running
an updated instance, follow the verified-backup instructions above; schema startup
is additive. Preparing the checkpoint does not update an already running service.

1. As a participant, open a gathering, RSVP, and submit several questions with
   differing concerns. Use a second gathering to demonstrate numbering restarting
   at 1; gathering schedules remain human-entered event text.
2. Sign in as host, manage the gathering, and verify the original questions and
   CSV exports. Generate an AI analysis and open one theme to review its description
   and local-numbered source questions.
3. Generate another analysis with the default Archive choice. Show the newest run
   open, older run collapsed, and Restore an older archived draft. Keep and confirmed
   Delete are alternative choices, not automatic cleanup of approved themes.
4. Edit a theme, approve it, and check it remains private. Publish it and show the
   curated public topic. Return to Current Themes to find approved/published content
   independently of its original run. Editing published text makes it private again.
5. Check a system timestamp in your browser's detected timezone; compare another
   browser/device timezone if available. Without JavaScript, the visible prototype
   fallback is America/New_York. Keyboard-check summaries, forms and focus indicators.

Checkpoint verification: 167 Python tests and 35 native-Intl JavaScript tests pass.
An isolated synthetic-data smoke test also completed two real local Ollama analyses,
archive/restore, RSVP/gathering creation, citation mapping, approval and publication.
No running application database or service configuration was modified. Full browser
and assistive-technology review, model interpretation review, and operating the
updated demo instance remain manual steps.

## Phase 4: Host workspace

Manage Gathering now has three server-rendered, bookmarkable views. Its header
always shows gathering title, Active/Cancelled state, scheduled time text, location,
and Back to Host dashboard.

| View | URL example | Existing controls |
| --- | --- | --- |
| Gathering (default) | `/host/gatherings/1?tab=gathering` | Details; collapsible agenda and resource management including removal; a separated Gathering Status section for Cancel/Restore at the bottom |
| Participants | `/host/gatherings/1?tab=participants` | Gathering-scoped RSVP names/count, anonymous numbered questions, both CSV exports |
| Discussion Themes | `/host/gatherings/1?tab=themes` | Existing manual themes, analyses, nested accordions, citations, archive/keep/confirmed delete, restore, edits, approval, publication, unpublishing and ordering |

Tabs are ordinary navigation links with `aria-current="page"`, not scripted ARIA
tab widgets. They work without JavaScript, support browser Back/Forward and wrap
on narrow screens. Only the selected view is rendered; RSVP information stays
private to Participants and the existing host dashboard. Public routes are unchanged.
Theme citations still include their original question text in Discussion Themes.

Existing POST endpoints retain their behavior and security checks, returning to
the owning view. Agenda/resource saves reopen the relevant secondary section;
theme actions preserve the affected theme/run opening. Validation failures return
the same HTTP 400/409/422 status, show escaped feedback on the owning view, and
retain submitted details, agenda rows, resource text or theme text where applicable.
Authentication/CSRF failures and not-found responses retain their existing policy.
Old `?theme=ID` links still select Discussion Themes; old fragment-only links such
as `#discussion-themes` need the explicit `?tab=themes` URL because fragments are
not sent to the server.

No schema, stored UTC timestamps, gathering schedule interpretation, inference
prompt/model settings, citation mapping or workflow state rules change in Phase 4.
No new frontend dependencies are introduced. Theme deletion remains inside its
existing review/confirmation context in Discussion Themes. Resource removal stays
inside resource management, in secondary removal disclosures separate from Save.
Cancel/Restore stays in the separated Gathering Status section at the bottom of
Gathering. The former Administration view and its redundant informational sections
are removed; old `?tab=administration` URLs redirect to Gathering. Existing forms
posted from old Administration URLs also return to Gathering, with unchanged
authorization, CSRF and validation checks. Database maintenance remains in the existing command-line scripts.

Usability limits: navigation reloads the page and does not automatically save
unsaved form edits; save before switching views. RSVP/question lists and analysis
history remain unpaginated. Browser/assistive-technology verification remains a
manual check; automated coverage checks navigation markup, wrapping/focus styles,
view-specific contents, validation, redirect destinations, data preservation and
all existing workflows.

Three-view Phase 4 validation: **196 Python tests and 35 JavaScript tests passed**, with five
existing dependency deprecation warnings. `git diff --check` passed. The existing
inference tests use mocked Ollama; no live service update is performed by this UI
verification. The reviewed three-tab implementation is saved by the local checkpoint
`Complete three-tab Host workspace redesign`; it is not deployed.

Three-view regressions also verify authorized legacy Administration redirects,
old form submissions, Gathering Status placement and error feedback, resource
removal returning to resource management, and preservation of submissions/themes.
