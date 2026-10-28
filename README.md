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
characters), gathering-local question IDs and private facilitation notes, a bounded
4,800-token output budget with thinking disabled, a 5-second connection timeout
and a 90-second network-operation timeout. Connection/model errors, timeouts and invalid output show a retry message while preserving questions. Successful generation saves new private drafts in SQLite and redirects to Manage gathering.
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
always leaves existing analyses and themes unchanged. Each intentional request
creates a new private run; manage a run only through its own accordion controls. Inference runs synchronously without holding a
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

**AI analysis history** groups suggestions by explicit run ID: active runs first
(newest first), then inactive runs (newest first).
Each native disclosure header shows generation time, input question count, original
number of generated themes, and current state counts. Only the first run in this
order starts open; individual themes start collapsed with title, status, and a description
preview. Approved/published themes remain in Current Themes; history retains their
status and a link to the current editor. Timestamps use an explicit English
12-hour format in your browser's detected timezone; without JavaScript they show the explicitly labeled
America/New_York prototype fallback (see Timezone handling below).
All disclosures and modifying forms work without JavaScript. Links can also be
opened by manually expanding the destination disclosure without JavaScript.

**New AI Analysis** contains only **Suggest Discussion Themes** and a short
explanation. Each intentional request creates a new private analysis; there are
no archive/keep/delete choices and no automatic changes to previous runs or themes.
Old browser forms that still send the removed options cannot trigger those actions.
Single-use generation keys still prevent double-submit/replay.

Manage each run independently inside its accordion:

- **Make inactive** reversibly marks that run inactive. Its unapproved AI drafts
  cannot be edited or approved until **Reactivate**; private notes remain editable.
  No theme text, individual archive flag, source citation or publication state is
  changed. Approved/published themes remain visible in Current Themes and publicly
  according to their existing status.
- **Reactivate** re-enables that run's drafts. It preserves pre-existing individual
  theme archives; those still need their existing Restore draft action.
- **Delete** requires the explicit confirmation checkbox and permanently removes
  that run and its unapproved AI drafts, including private notes and dependent run
  snapshots/associations. Runs containing approved, published or manual themes
  cannot be deleted; make them inactive instead. Participant submissions and all
  other runs/themes/citations are untouched. The generation receipt remains to
  prevent replay.

Signed, session/gathering/run-scoped action keys detect stale run, theme and notes
revisions. Invalid/stale actions preserve all records, reopen the affected run and
show nearby feedback. Deleting a still-running analysis discards its later model
response rather than recreating it; it does not interrupt the model server request.
Failed runs can also be managed independently. No historical drafts are implicitly
archived, deleted, restored or regenerated by a new analysis.

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
Normal page timestamp formatting stays in the browser. Analysis download links send the detected IANA timezone to the authenticated export route so the script-free document can be formatted before download; it is not stored as a preference.

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
3. Generate another analysis and show that the previous run is unchanged and
   collapsed. Make a run inactive, Reactivate it, and demonstrate confirmed Delete
   only on a disposable run without approved/published themes.
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
| Discussion Themes | `/host/gatherings/1?tab=themes` | Existing manual themes, analyses, nested accordions, citations, run Make inactive/Reactivate/confirmed Delete, legacy individual archives, edits, approval, publication, unpublishing and ordering |

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

## Phase 5: Private facilitation notes and question coverage

All new controls stay in **Discussion Themes**. New AI analyses propose three
host-private fields inside each theme's existing accordion:

- **Shared concerns:** 1–3 sentences about related issues in that theme's citations,
  without asserting consensus.
- **Different perspectives:** 1–3 sentences about supported tensions, tradeoffs or
  priorities; when disagreement is not supported, explicitly say evidence is
  insufficient instead of inventing a conflict.
- **Suggested discussion questions:** 2–3 distinct, neutral, open-ended prompts
  based on the same cited contributions.

These are **AI suggestions, not findings or community decisions**. Review them
against the original cited questions. All three fields are editable. **Save private
notes** saves only notes: it does not change public title/description, theme
revision, approval or publication. The ordinary public-text **Save as draft** still
requires reapproval/republication. Notes have their own optimistic revision check;
a stale notes form returns 409 with the affected editor open and entered text
retained. Their update time uses the existing browser-local formatter.

Generated prose fields are limited to 1,000 characters and use the existing
1–3-sentence heuristic; generated prompts are 2–3 nonempty distinct strings of at
most 300 characters. Missing/malformed notes reject the whole generation batch.
Host working drafts may be blank, use prose up to 2,000 characters per field, and
up to three prompt lines of 500 characters each. Create a manual theme normally,
then enter its notes without Ollama. Legacy AI themes show **Not generated** and
blank fields until the host writes notes; nothing is regenerated automatically.
The original AI note proposal is retained privately, separately from current edits.

Notes persist through approving, publishing, unpublishing, archiving, restoring,
public-text edits, and restart. Archived themes permit private-note work without
restoring public editing. Notes remain private even on a published theme; public
queries/rendering never include them or append them to a description. Explicitly
deleting a draft also removes that draft's dependent notes. Generation never modifies earlier drafts or their notes. Run actions reject stale
forms after public theme or private-note edits.

Each new analysis records the exact input question IDs and their local numbers
before calling Ollama. **Question coverage** within that run displays the recorded
input count, distinct questions cited by its remaining saved themes, and the
number not cited. Open **Review uncited original questions** for the original text
and gathering-local numbers. Repeated citations count once; other runs, new
questions arriving during/after inference, and unrelated published themes do not
inflate coverage. Archived/approved/published themes within the run still count.
Deleting a theme can reduce its run's citation coverage because counts reflect
remaining saved source associations, not an immutable report of deleted output.

Old runs with no recorded ID snapshot show **Coverage unavailable**. Failed,
pending or inconsistent snapshots also show an explicit unavailable state; the app
does not guess from current questions. Coverage is calculated deterministically,
never by AI, and is not evidence of representativeness, agreement or adequate
discussion. Snapshot IDs/numbers do not duplicate participant text or establish
historical edits to participant text; participant-question editing is not provided.

Before running this version against an existing database, create and verify a
backup using the existing scripts. The additive, repeatable migration adds
`theme_facilitation_notes`, `analysis_run_snapshots`, and `analysis_run_questions`.
It does not rewrite legacy themes, statuses, citations, runs, or contributions.
No external model service, new top-level tab, dependency, automatic retry or
historical regeneration is introduced. Prompt constraints and structural checks
cannot prove faithful grounding or neutrality; host review remains essential.

The larger notes contract uses a 4,800-token generation ceiling and a 90-second
read/network timeout (5-second connect timeout), with `think: false`, temperature
0.2, local-endpoint restrictions and truncation rejection unchanged. The synthetic
local probe completed one theme with two prompts in 10.02 seconds (9.91 seconds
inference, 210 output tokens), without truncation. This is one synthetic case,
not a latency guarantee for larger gatherings or five-theme outputs. Longer runs
may time out or hit the token ceiling; failures preserve existing work and require
an explicit retry. No participant/model text is logged by diagnostics.

Phase 5 validation: **239 Python tests and 35 JavaScript tests passed**, with five
existing dependency deprecation warnings. `git diff --check` passed. The migration
was tested twice on a verified backup copy; all original records remained unchanged.
No running database/service was updated, and changes remain uncommitted.

## Independent run controls: migration and preservation

Before starting this version, use the existing backup/verification workflow. The
additive `analysis_run_states` table holds active/inactive state and its revision.
Legacy runs default to active without changing any existing row or archive flag.
The old `analysis_runs.draft_action` column is preserved for SQLite compatibility
and historical data only: new rows use `keep`, and generation never processes it.
The old generation-side previous-draft snapshot/Archive/Delete processing and
form options have been removed. Existing legacy individual draft archive/restore
controls remain available; run state is separate.

Run-control actions use the existing host authorization, CSRF, no-store rendering,
gathering scope and browser-local timestamps. Protected-run deletion is rejected
as a whole, not partially applied. Confirmed deletion removes only the selected
run and its unapproved AI themes; it never removes original questions/RSVPs or
citations of surviving themes. Pending inference may finish in the background
after deletion, but its result cannot restore the deleted run. There is no new
Ollama prompt/model behavior, dependency, top-level tab or public-page control.

Independent-run validation: **255 Python tests and 35 JavaScript tests passed**,
with five existing dependency deprecation warnings. Diff checks passed. The
migration was verified twice on a copy of the independently validated backup
`backups/common-ground-20261027T193245Z.db`; all original records remained unchanged.
No running database/service was updated. Changes remain unstaged and uncommitted.

In **Current Themes**, AI themes show **From Analysis #…**, the originating
analysis's creation time in the existing browser-local format, and **Analysis
inactive** when applicable. The analysis link opens its original history accordion
with JavaScript; without it, follow the link and expand the native disclosure.
Manual themes are labeled **Manually created**. Legacy AI themes without recorded
run provenance say it is unavailable and show the theme's creation time instead.
These are host-only display details: history sorting never changes explicit host
theme order, approval, publication, original timestamps or citations. Current
Themes and public topic order continue to use the host's saved position/id order.


## Private AI Analysis Export

Each analysis accordion has **View / Print Analysis**, which opens a private report in a new tab.
Use **Print / Save PDF** to print the report, or **Download HTML** to save a
self-contained, print-friendly HTML document. **Save theme edits and Save private notes before
exporting**: the download reads current saved database values, never unsaved form
fields. Save private notes remains a separate persistence action.

Exports include gathering schedule/location, run metadata, all remaining themes
associated with that run (including archived drafts and approved/published themes
from inactive runs), saved descriptions and facilitation notes, locally numbered
original citations, and reliable run-snapshot coverage/uncited questions. No
archive filter is applied. Unrelated runs, RSVPs, credentials and diagnostics are
excluded. AI suggestions are labeled private host working material, not consensus.
Historical missing notes and unavailable coverage are explicitly identified.

The authenticated, gathering-scoped download uses escaped HTML, no scripts or
external resources, restrictive security headers and no-store caching. Open the
downloaded file and use the browser's Print command to print or save as PDF.
Downloaded copies contain private notes: protect them when storing or sharing.
This is a snapshot of remaining saved content, not recovery of deleted themes or
an immutable record of original model output.

The workspace passes the browser-detected timezone in the download URL. Without
JavaScript or a supported timezone, export timestamps use visibly labeled
America/New_York. The downloaded document retains that timezone when moved to
another device. Gathering schedule text is preserved as entered. New runs record
the requested model identifier; historical unknown models are not guessed from
current settings. This identifier is not a model-weights fingerprint.

Before startup, follow the existing verified-backup workflow. The additive,
repeatable `analysis_run_models` table records model metadata for new runs only;
it neither backfills old runs nor changes themes, notes, approval or publication.

Export validation: **277 Python tests and 39 JavaScript tests passed**, with five
existing FastAPI/Starlette deprecation warnings. `git diff --check` passed. The
schema was applied twice to an isolated copy of the verified backup above;
all original records were preserved, integrity/foreign-key checks passed, and
no legacy model metadata was inferred. Browser print pagination and screen-reader
review remain manual; no running database/service was updated.

## Completed-work checkpoint verification

On October 27, 2026, the complete suites passed again: **277 Python tests** and
**39 JavaScript tests**, with five existing FastAPI/Starlette deprecation warnings.
`git diff --check` passed. A fresh backup,
`backups/common-ground-20261027T202253Z.db`, passed SQLite integrity and foreign-key
checks and remains outside Git. The local checkpoint is named
`Complete AI facilitation, analysis management, and reporting`.
Earlier “uncommitted” notes describe verification at those earlier task stages;
this checkpoint supersedes that source-control status. No deployment or live
schema migration is included. Download exports remain the implemented report
workflow; no new-tab report feature was added. Semantic AI grounding and browser
print/accessibility reviews retain the limitations described above.

Gathering directories use compact full-width horizontal entries, stacked on mobile,
with five entries per server-rendered page. Previous/Next and page counts appear
above and below a list only when it has more than one page. Each directory is a
native keyboard-accessible accordion with a total count. Upcoming is open by
default; Schedule to be confirmed, Past, and host-only Canceled start collapsed.
Pagination opens the relevant accordion and targets its summary heading. Individual
sections can be expanded independently, without JavaScript.
The host creation form and recent activity retain native disclosures and validation.
Descriptions are escaped plain-text previews; detail pages keep complete descriptions.

Gathering schedules now use nullable `gathering_date`, `start_time`, `end_time`,
`timezone`, `start_fold`, and `end_fold` columns. New gatherings require a date,
start time and an IANA timezone detected by the browser and submitted in a hidden
field. There is no guessed timezone fallback for scheduling.
The optional end time must be later on the same local date. Times have minute
precision. Display uses the gathering's local timezone, abbreviation, UTC offset,
and IANA name; it does not depend on the server or viewer timezone.

At the end instant (or start instant when no end is supplied), participation closes
and the gathering moves to Past. Ongoing events remain in Upcoming until their end.
Upcoming sorts by start instant ascending, Past by start descending, with IDs
breaking ties. Canceled gatherings remain absent from public directories. Direct
URLs and all associated data remain available; restoring a canceled past event does
not reopen participation. Accordion counts and independent five-entry pagination
remain unchanged. Invalid/empty pages default to 1; numeric pages clamp to range.
`open_section` and explicit section page parameters reopen the relevant accordion.

DST gaps and repeated local times are rejected for new or changed schedules;
choose a different time. Previously saved explicit occurrence choices remain
readable and are preserved on edits that leave the entire schedule unchanged.
New form submissions cannot select or forge an occurrence. An end time on
a different date is not supported. No missing dates or timezones are inferred.

The original `when_text` is retained verbatim and never updated by create/edit.
New records have an empty legacy string. Existing schedules, even ISO-like legacy
text, remain Schedule to be confirmed until a host explicitly supplies the
structured fields. Hosts may edit unrelated legacy details with the visible date/time fields blank;
auto-initializing the hidden timezone does not confirm or partially persist a
legacy schedule. Partial schedules are rejected, and confirmed schedules cannot be
cleared through Edit Gathering. The edit screen displays the original legacy text.

Migration is additive and repeatable. Before adding missing columns to a populated
database, it checks SQLite integrity and foreign keys, creates and verifies a
mode-0600 `pre-scheduling-<UTC timestamp>.db` backup beside the database, and applies
nullable columns in one transaction. Failure rolls back; rerunning is a no-op.
There are no backfills or record updates. Application startup applies this migration
before existing initialization logic. The offline command (requires a writable
database directory and no enclosing transaction) is:

```sh
python -m app.scheduling /path/to/common-ground.db
```

Scheduling migration rehearsal: `backups/common-ground-20261028T161935Z.db` is a
verified online SQLite backup. Applying the new migration twice to an isolated
copy preserved all original values across 18 tables, passed integrity and FK
checks, and left every structured scheduling field NULL. The running database and
service were not migrated or restarted in this task. Backup files remain ignored
by Git. Before deploying, take another fresh backup using
`bash scripts/database.sh backup`; startup also takes its own pre-scheduling backup
when needed.

Original schedule diagnosis (read-only inspection): Library stores
`Saturday, November 14 · 2:00 PM`; Neighborhood stores
`Saturday, November 21st 2:00 PM - 3:30 PM`. Both lack a year and timezone.
Neither November schedule was changed, and no December demonstrations were created.
Run all JavaScript tests with `node --test tests/*.cjs`.

Structured scheduling verification: **346 Python tests** and **44 JavaScript tests**
passed; five existing FastAPI/Starlette deprecation warnings remain.
`git diff --check` passed. Browser and assistive-technology review remains manual.

Schedule save investigation — October 28, 2026: read-only inspection of the running
`cg-web-1` container confirmed `DATABASE_PATH=/data/common-ground.db` on volume
`cg_common_ground_data`. All six scheduling columns and a pre-scheduling backup
were present; integrity and foreign-key checks passed. The deployed scheduling,
route and form source matched the workspace before this fix. Neighborhood's
structured fields were NULL; its POST returned HTTP 400, not a successful save.
The historical POST body was not logged, so its exact invalid field cannot be
proven from the access log.

On a disposable online snapshot, the rendered form with the reported date,
14:00–15:30 and Automatic DST options committed and reloaded correctly. Equivalent
HTML time values `14:00:00`/`15:30:00` reproduced a 400 because validation accepted
only HH:MM. Minute-aligned zero-second values (including zero fractional seconds)
now normalize to HH:MM before validation/storage. Nonzero seconds are rejected,
never rounded. The same reproduction now commits both representations.

Edit failures prominently say "Details were not saved", preserve submitted fields,
and target the validation feedback when the browser follows the form's fragment.
A successful committed edit redirects to a one-time, session-backed confirmation;
GET reloads read the persisted SQLite values, not a query-string success marker.
The edit button also links back to the validation error on failed submissions.
No running service, database schema or stored schedule was changed by this fix;
no migration or manual SQL repair is needed. Re-enter the intended schedule through
the host form after the fix is deployed through the normal approved process.
Verification: 362 Python tests and 45 JavaScript tests pass; five existing Python
deprecation warnings remain. `git diff --check` passes. Browser/screen-reader review
remains manual.

IANA timezone validation investigation — October 28, 2026: the active web image
had system `tzdata 2026e-0+deb13u1`. `ZoneInfo('America/New_York')` and
`ZoneInfo('Europe/London')` both loaded successfully inside `cg-web-1`. The optional
Python `tzdata` package was absent, which is normal when system rules are present.
The exact error was reproduced by surrounding whitespace, including a pasted
nonbreaking space: validation previously tested the raw input against a global
zone-name enumeration. Literal unpadded names worked; the historical submitted
payload was not retained, so its exact contents cannot be established.

Scheduling now strips surrounding Unicode whitespace, resolves names directly with
`ZoneInfo`, and stores the normalized IANA name. Invalid names, system-local aliases,
and internal posix/right paths remain rejected. It never substitutes UTC. Missing
server rules produce a distinct configuration error; create/edit errors retain
submitted values with HTTP 503 instead of calling the user-entered name invalid.
The Dockerfile explicitly installs system tzdata and verifies New York/London during
the build. Startup repeats that check before database initialization.

To test the actual application image without deploying or mounting live data:

```sh
bash scripts/test-docker-timezones.sh
# Then run the entire Python suite against that same built image:
docker run --rm --network none \
  --mount "type=bind,src=$PWD/tests,dst=/project/tests,readonly" \
  cg-timezone-test:local python -m pytest -q -p no:cacheprovider
```

The script builds a separate `cg-timezone-test:local` image from the real Dockerfile.
Only tests are mounted; application code and installed timezone data come from the
image. `CG_TEST_IMAGE` can select another test-only image tag. No existing gathering,
live database, container service or migration is changed by these checks.

Timezone-image verification: all 24 targeted timezone tests and the complete
386-test Python suite passed against the built image; all 45 JavaScript tests and
`git diff --check` passed. Five existing Python deprecation warnings remain.

Browser-based scheduling: Create/Edit shows only Date, Start time and optional End
time as inputs. `app/static/scheduling.js` reads
`Intl.DateTimeFormat().resolvedOptions().timeZone`, validates it with Intl, and
fills the hidden timezone before submit. A visible status identifies the scheduled
zone. Missing/invalid detection blocks scheduling with a clear error; JavaScript
is needed to initialize an unset zone. No UTC or America/New_York fallback is used.
The server still independently normalizes/validates IANA names using system tzdata.

Editing preserves a saved zone even when the browser is in another zone. When
zones differ, **Change timezone** explicitly switches to the browser zone and
leaves local date/time inputs untouched; review and Save details to persist it.
A validation rerender retains the chosen timezone. Existing structured schedules
also remain editable without detection when a saved valid zone is available.
DST occurrence selectors and technical timezone entry are removed. Repeated or
nonexistent new local times return a validation error and require a different time;
existing saved occurrence resolutions are preserved only for unchanged schedules.
Schema, legacy schedule text, expiration, pagination and security are unchanged.

The browser detection change is independent of the earlier timezone-input issue:
whitespace normalization, direct ZoneInfo lookup, explicit Docker tzdata checks,
and distinct missing-server-data errors remain in place and tested. Run all JS
suites using `node --test tests/*.cjs` (including `tests/test_scheduling.cjs`).

Browser-scheduling verification: all 396 Python tests passed against the rebuilt
web test image; all 71 JavaScript tests and `git diff --check` passed. The 24
standalone server-timezone regressions also passed. Five existing Python
deprecation warnings remain. No live data, service, commit, push or deployment changed.

Reviewed source checkpoint: the final review corrected an unintended resource-edit
feedback fragment and clarified the legacy schedule help. All 396 Python tests in
the actual web test image, all 72 JavaScript tests, and `git diff --check` passed.
This source checkpoint supersedes earlier uncommitted-status notes. Database files,
backups, credentials and environment files are excluded; publishing source does
not deploy the application or modify the live database.
