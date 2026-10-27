# Common Ground — Architecture and Design Decisions

**Project:** Common Ground

**Document:** `docs/DECISIONS.md`

**Updated:** October 27, 2026

**Status:** Living document — prototype development

## Purpose

Common Ground is an independent, open-source prototype designed to help community organizations host gatherings, collect participant questions, and identify discussion themes with assistance from locally operated artificial intelligence.

Our design emphasizes simplicity, community control, transparency, and human judgment. This document records our principal engineering decisions, their rationale, and their consequences.

Common Ground belongs to its creators and is not a Resonance product or endorsement. The current prototype is for local development with fictional contributions only; local success does not establish readiness for public deployment or real participant data.

## ADR-001 — FastAPI Rather Than WordPress

**Status: Implemented**

We selected Python and FastAPI for the backend rather than building a WordPress plugin or theme. The interface uses server-rendered HTML and CSS without a frontend build step.

**Rationale**

- Common Ground is a focused application rather than a content-heavy website.
- FastAPI provides a lightweight foundation for forms, database operations, and AI integration.
- Python supports straightforward integration with Ollama and automated testing.
- Docker allows independent application deployment.
- Avoiding WordPress reduces the infrastructure and maintenance required for this prototype.

**Tradeoff and consequence**

WordPress offers mature content management, user administration, and familiar editing tools. We gain architectural independence and fewer application components, but must implement the capabilities we need and remain responsible for security, administration, accessibility, and maintenance.

## ADR-002 — SQLite for Initial Persistence

**Status: Implemented**

SQLite stores gatherings, RSVPs, and participant questions.

**Rationale**

- Small anticipated initial data volume.
- No separate database server.
- Minimal infrastructure requirements.
- Straightforward backup and portability.
- Suitable for a single application instance with modest concurrent writes.

**Tradeoff and consequence**

SQLite does not provide the same multi-instance concurrency and operational features as a dedicated database server. We will reconsider PostgreSQL if usage, concurrency, or hosting requirements justify the complexity.

Compose stores the database in a persistent named Docker volume, separate from the application image. Removing that volume deletes its data; backup and restoration procedures remain necessary.

## ADR-003 — Local AI with Ollama and Qwen3

**Status: Implemented and experimentally validated**

We selected Ollama to serve the default `qwen3:8b` open-weight language model.

**Rationale**

- Inference can run without sending participant questions to a commercial AI provider.
- Organizations can operate inference under their own administrative control.
- Ollama exposes a straightforward HTTP interface.
- Model execution is separate from application logic.
- The model is practical for experimentation on available local hardware.

**Reported development experiment**

The developer reported the following observations from an 18-question experiment:

- Model: `qwen3:8b`.
- Hardware: NVIDIA RTX A5500 laptop GPU.
- GPU processing: 100%, as reported by Ollama.
- Loaded model memory: approximately 5.6 GB.
- Result: 18 fictional participant questions organized into five themes.
- Response time: approximately three seconds.

These are observations from one development environment, not minimum production requirements, guaranteed performance, or automated acceptance criteria. The separate three-question failure investigation is recorded in [THEME_INVESTIGATION.md](THEME_INVESTIGATION.md).

**Tradeoff and consequence**

Local inference improves operational control but introduces hardware costs, model maintenance, performance constraints, and deployment complexity. The endpoint and model name are configurable; the application is not tied to a particular machine. Phase 2 rejects external endpoint hosts before sending questions (ADR-012).

Participant workflows remain available when inference is unavailable. Model licensing, supported request options, and deployment suitability must be verified before public release or changing models.

## ADR-004 — Disable Extended Thinking for Theme Generation

**Status: Implemented and tested**

Discussion-theme requests explicitly set top-level `think: false` for the configured Qwen3 task.

**Reason**

A reproduced request involving three fictional questions exhausted the 700-token generation budget. Ollama returned `done=true` with `done_reason="length"`, 700 generated tokens, and only three characters of answer content. Most output was in the separate thinking field.

The same three-question task with thinking disabled completed successfully using 77 generated tokens. The two-question comparison succeeded using 653 tokens with default thinking behavior. The reproduced failure was output exhaustion rather than a network timeout.

**Consequence**

- Keep output bounded and temperature at 0.2. The initial 700-token title-only
  budget is now 1,600 tokens for titles plus descriptions (ADR-013).
- Retain the 5-second connection timeout and 45-second network-operation timeout.
- Explicitly reject `done_reason="length"`, even if the returned JSON otherwise parses.
- Require structured JSON and validate theme shape, titles, and references against the supplied question IDs.
- Treat participant text as untrusted data in the model instructions.

Development diagnostics are disabled by default and require `CG_DEV_THEME_DIAGNOSTICS=1`. They distinguish truncated output, malformed JSON, schema mismatch, invalid question references, and invalid response envelopes. Logs contain only bounded categories and numeric counts, never participant text, model answers, thinking traces, endpoints, or credentials.

This setting addresses a constrained theme-generation task; it is not a general conclusion that disabling reasoning is always preferable. The request currently sends `think: false` for any configured model, so compatibility must be checked when changing models.

## ADR-005 — AI Suggestions Require Human Review

**Status: Persistent drafts, host editing, approval, and publication implemented (Phase 2)**

AI-generated themes are advisory. The model may categorize a question inaccurately, overlook a concern, or associate a contribution with an inappropriate theme.

**Reported example**

In the developer's 18-question experiment, a question about control over patron information was grouped under digital literacy rather than data governance. A question about opting out of AI recommendations was assigned to categories that did not explicitly address consent.

These observations demonstrate why valid JSON and valid source references do not establish a correct interpretation.

**Policy and current implementation**

- Preserve original participant contributions.
- Label AI-generated themes as drafts.
- Display each suggested theme with its cited source questions.
- Never present model output as evidence of community consensus.
- Require an organizer to review interpretations before publication.

Only an authenticated host can request suggestions, and only the selected gathering's questions are sent. Empty gatherings do not trigger inference. Drafts are saved privately in SQLite. Approval and publication require separate host actions; neither happens automatically.

**Current review workflow and remaining work**

Hosts can edit theme titles and descriptions, create manual themes, order themes,
approve individual themes, and publish or unpublish them. Editing approved or
published text resets it to a private draft. AI origin, original suggested title,
and cited question IDs remain distinguishable from edited text. Source association
editing and a complete revision history remain future work. See ADR-012.

## ADR-006 — Community Ownership and Data Governance

**Status: Design policy; implementation incomplete**

Common Ground is intended to serve communities rather than acquire or monetize participant information.

**Proposed governance model**

- The deploying organization controls its gathering and participant data.
- Participants receive understandable information about collection and use.
- Organizers can export and delete information under an established retention policy.
- Data is not shared with external AI providers without an explicit, authorized decision.
- AI processing uses only information necessary for its stated purpose.

**Current limitation**

The prototype provides local persistence, basic host authentication, and development privacy guidance. It does not yet provide a complete participant notice, deletion, retention, or role-based authorization system. Use fictional contributions only until these requirements are addressed.

**Open questions**

Who may authorize data use? How should individual deletion requests be handled? What retention period is appropriate?

These policies must be determined with the deploying organization, not unilaterally by its software developer.

## ADR-007 — Docker and Reproducible Deployment

**Status: Local implementation complete; public deployment planned**

Docker Compose packages and runs Common Ground, while Ollama operates separately.

**Rationale**

- Consistent application dependencies.
- Configuration supplied separately from source code.
- Repeatable local execution and testing.
- Portability between development and hosting environments.
- Independent persistent database storage.

The reported development environment uses Windows 11, a dedicated Ubuntu 24.04 WSL distribution, Docker Desktop, and Ollama. Compose currently publishes the application on localhost only.

**Tradeoff and consequence**

Containers introduce operational concepts that small organizations may find unfamiliar. Clear deployment instructions, configuration management, and tested backup procedures are essential. Dependencies use version ranges rather than a complete lockfile, so exact dependency reproducibility remains future work.

## ADR-008 — DigitalOcean Deployment

**Status: Planned; not implemented**

Following local testing and deployment-readiness work, we intend to deploy a public demonstration to DigitalOcean using the tested application code with environment-specific configuration.

**Required work**

- Replace development credentials and protect session secrets.
- Configure HTTPS, an appropriate hostname, and secure session cookies.
- Review authentication and authorization; maintain CSRF protection.
- Implement abuse prevention for public forms.
- Establish database backups and test restoration.
- Review accessibility and define acceptance criteria.
- Use fictional demonstration data.
- Restrict access to Ollama and administrative interfaces.

The current prototype has minimal shared-password host authentication and no rate limiting. It must not be exposed publicly in this state.

**AI hosting decision remains open**

The existing DigitalOcean environment is not intended to host the full GPU-based model. Alternatives include saved sample outputs, a separately operated inference server, or suitable hosted inference.

The demonstration must accurately disclose whether AI output is live or prerecorded. Any remote inference arrangement must satisfy the deploying organization's data-governance decisions.

## ADR-009 — AI-Assisted Development with Human Responsibility

**Status: Implemented**

We use OpenAI Codex as a coding assistant in local development. It can inspect source code, propose and implement modifications, execute tests, and help diagnose failures.

The human developer remains responsible for requirements, architecture, security decisions, validation, and release approval.

**Established workflow**

1. Define a small feature or correction.
2. Have Codex inspect and implement it.
3. Run automated tests.
4. Review modifications and conduct manual testing.
5. Commit the verified result using Git after human review.

**Observed example**

Codex investigated an incomplete AI response, reproduced output-token exhaustion, recommended a targeted correction, and added regression coverage. The subsequent correction disabled thinking and explicitly rejected truncated generations.

The full automated suite passed **30 tests**, with five dependency deprecation warnings. Tests cover normal structured responses, truncated responses, model errors, safe diagnostics, and existing application behavior. Automated Ollama tests use mocks; the investigation also compared live local inference requests.

These results describe the tested revision, not a security audit, a guarantee of model interpretation quality, or public deployment approval. Changes from this investigation and correction were left uncommitted for review.

**Consequence**

AI assistance supports development speed while requiring independent validation and engineering accountability.

## ADR-010 — Independent and Anonymous Participation

**Status: Implemented in prototype; verification required**

Common Ground allows participants to RSVP and submit questions independently.

- RSVPs may include a participant's name.
- Questions do not require an RSVP or participant identity.
- Questions are associated with a gathering, not an individual RSVP.
- Organizers should not infer who submitted a question based on attendance records.

**Rationale**

Participants should be able to express ideas, concerns, and disagreements without identifying themselves. Anonymous contributions can encourage participation, especially when discussing sensitive or controversial community matters.

**Tradeoff**

Anonymous submissions complicate moderation, abuse prevention, and individual requests to remove previously submitted questions.

**Consequence**

We must design appropriate moderation and privacy controls without unnecessarily collecting identifying information.

Anonymity in the database does not automatically guarantee anonymity at the infrastructure level. Server logs and other metadata require review before making assurances about participant anonymity.

## Outstanding Decisions

Before public deployment, finalize:

- Complete revision history and editing of theme source associations.
- Participant notice, data export, deletion, and retention policies.
- Authentication and administrative access controls.
- Accessibility and security acceptance criteria.
- Production AI availability and hosting.
- Model and software licensing verification.
- Backup and disaster recovery procedures.

## Guiding Principle

**Common Ground uses artificial intelligence to help communities understand their conversations—not to decide what their communities think.**

People contributing information retain their voices. People organizing gatherings remain responsible for interpreting and acting on what they hear.

## ADR-011 — Host Operations and Additive Migrations

**Status: Implemented — October 27, 2026**

Host review now edits gathering details, ordered agenda titles with optional
minutes and public notes, and public URL resources. Separate additive tables hold
agenda items, resource links, and cancellation status. Startup converts legacy
agenda lines once in a transaction; repeat startup does not overwrite revisions.
The legacy agenda column remains synchronized when hosts revise an agenda.
Existing participant records and gathering IDs are preserved.

Cancellation closes public submissions while preserving contributions, host review,
and exports. Restoration reopens submissions. There is no destructive gathering
removal action. Resources accept only HTTP/HTTPS URLs without embedded credentials;
they are not fetched by the server. Document uploads are deferred because safe
storage, content validation, size limits, and download handling need separate work.

Every host action requires the existing shared-password session. All POST actions
require a session-bound CSRF token, including authentication and participant forms.
Login rotates the token; logout clears the session. Rendered pages and CSV exports
are marked no-store. Host-only, gathering-scoped CSV downloads separate RSVPs from
anonymous questions, retain timestamps, quote CSV fields, and neutralize spreadsheet
formula prefixes. Public pages expose attendance counts, never RSVP identities or
participant questions. This remains a local prototype without rate limiting,
individual organizer accounts, ownership authorization, or retention controls.

Before this implementation, `scripts/database.sh backup` produced
`backups/common-ground-20261027T161710Z.db`; integrity and required application
tables were independently verified using `app.database_tools.validate`.

## ADR-012 — Persistent, Human-Governed Discussion Themes

**Status: Implemented — October 27, 2026**

**Prerequisites**

Phase 1 was clean at Git checkpoint `b69c836`. Before schema work,
`scripts/database.sh backup` created `backups/common-ground-20261027T163632Z.db`.
The backup utility's integrity check was independently repeated using
`app.database_tools.validate`. No backup, database, or secret is included in Git.

**State and public visibility**

- **Draft**: private, unapproved AI suggestion or manual/edited host text.
- **Approved**: the host explicitly approved the current text; still private.
- **Published**: approved content that the host separately chose to publish.
  Only this state appears publicly, labeled as curated discussion topics rather
  than facts or community consensus. AI-assisted origin remains visible.

Saving any edit, even unchanged text, returns the theme to Draft and immediately
removes it from public view. Reapproval and republication are explicit. We chose
one current version per theme rather than keeping a separate live version during
revision. Unpublishing returns Published to Approved without deleting text.
Deletion is limited to Draft and requires a confirmation checkbox. Keyboard-friendly
Move up/down actions change display order, not content or approval; they update
revision counters so stale forms cannot overwrite newer work.

**Persistence and isolation**

The additive startup migration creates `discussion_themes` (content, origin,
original AI title, state, order, revision, UTC creation/update timestamps),
`theme_sources` (immutable cited question IDs), and `theme_requests` (single-use
creation/generation receipts), with an index on gathering/order/ID. Migration DDL
shares the existing explicit transaction, is repeatable, and does not modify
legacy records. Theme IDs use AUTOINCREMENT to avoid accidentally targeting a
replacement draft with a stale deleted ID.

Every read and mutation is scoped to a gathering. Source questions are verified
to belong to the same gathering before insertion; hosts cannot change those
associations through forms. Public queries select only published title,
description, and origin. Original question text, attendee identities, provenance
metadata, timestamps, revisions, and diagnostics remain private. Participant tables
are never written by theme operations. Cancelled gatherings retain their existing
public visibility and published topics; participation forms remain closed.

**Duplicate and stale requests**

Signed creation/generation keys are scoped to session, gathering, and operation.
SQLite receipts prevent replay, including concurrent duplicate generation. The
claim commits before inference; no write transaction remains open while Ollama
runs. A complete set of suggestions and source references is saved atomically, or
none is saved. New generations append Draft rows; they never replace existing
Draft, Approved, or Published themes. Successful POSTs redirect to GET.

Mutations use serialized read/modify/write transactions and per-theme revision
checks. Stale or duplicate mutation forms return 409. Ordering swaps update both
rows' revisions. After a failed/interrupted generation, reload to obtain a new
request key and explicitly retry. There is no background queue, automatic retry,
or request-receipt cleanup.

**AI and input safeguards**

Retain local Qwen3/Ollama JSON generation, `think: false`, bounded output (initially
700 tokens, now 1,600 with descriptions; ADR-013), temperature
0.2, existing timeouts, truncation rejection, response validation, and bounded
opt-in diagnostics. Only this gathering's question IDs and text are sent; RSVPs
and theme edits are not sent. AI descriptions are now generated and hosts can revise their context (ADR-013). Errors preserve all submissions and existing themes.

External endpoint hostnames/public IPs are rejected before networking. Permitted
hosts are localhost, host.docker.internal, ollama, loopback IPs, RFC1918 private
IPv4 addresses, and IPv6 unique-local addresses. Redirects are not followed and
HTTP client environment proxies remain disabled. Operators must still use a local
model and an inference server without cloud routing; endpoint validation cannot
audit an independently configured server. No new external API, tracking, or
telemetry is introduced.

Host authorization and existing CSRF checks protect every modifying route.
Parameterized SQL and server-side text limits reject empty titles, overlong text,
and unsupported control characters. Titles and descriptions are plain text;
Jinja autoescaping renders markup literally in text and attributes. Theme labels
use text and color, large buttons, and the Phase 1 focus/contrast styles.

**Limitations**

Shared-password authentication remains; individual reviewer attribution, full
revision history, editable source associations, and retention automation are not
implemented. Publishing curated text can intentionally disclose a participant's
idea; hosts remain responsible for reviewing it for identifying or sensitive
content. There is no automated privacy redaction. Tests mock inference; live model
interpretation and a full assistive-technology audit remain human checks.

## ADR-013 — Grounded Theme Descriptions

**Status: Implemented — October 27, 2026**

Investigation found that the original Ollama prompt and strict schema only
requested `title` and `question_ids`; parsing rejected extra fields. The generation
route explicitly inserted an empty description, despite storage and host/public
templates already supporting descriptions. No schema migration was needed.

The schema now requires `title`, `description`, and `question_ids`. The prompt
requests a concise, meaningful title and 1–3 sentences explaining common concerns
or opportunities, recognizing competing perspectives and tradeoffs only where
supported by cited original questions. It asks for fewer distinct themes when
appropriate, merging redundant or substantially overlapping topics and preserving
supported minority perspectives without inventing opinions, priorities, or consensus.

Validate generated descriptions as nonempty strings of at most 1,000 characters,
reject unsupported control characters, and reject duplicate normalized titles or
descriptions in a batch. A later plain-text heuristic also bounds sentence count (see the description
investigation below). These checks do not establish semantic distinctness or accuracy; hosts must review those against the source questions.
Reject invalid batches atomically rather than silently dropping topics or sources.
The existing 2,000-character limit for host-edited descriptions remains unchanged.

The route now saves generated descriptions in the existing description column.
Host display and edit controls already escape this text; the public template shows
it only after approval and publication. Existing drafts, approvals, published
content, and original participant questions are not rewritten. New generations
still append private drafts. Manual creation, reapproval after any edit, duplicate
request protection, and unpublishing retain their Phase 2 behavior.

Increase the bounded generation budget from 700 to 1,600 tokens to accommodate
up to five descriptions plus titles and source IDs. Retain `think: false`, the
configured local model and endpoint, temperature 0.2, existing timeouts, explicit
truncation rejection, response validation, and private bounded diagnostics. Longer
output may increase generation time; timeouts and invalid output preserve existing
themes and show the existing retry path. No automatic retry or external service is
introduced. Tests mock inference; actual wording quality remains a host judgment.

## Gathering-local question display numbers

Compute `question_number` over all questions in each gathering in ascending
`created_at, id` order, before citation filtering or the recent-question limit.
This keeps creation order deterministic, starts each gathering at 1, and keeps
existing numbers stable as newly timestamped participant submissions arrive.
Use that shared query for host lists and question CSV exports. Append the CSV
column to preserve the existing column positions. Use gathering-local numbers in model input and output (see review corrections
below); map them back to database IDs for persisted theme source relationships. No participant
records, keys, or stored citations are rewritten. This relies on the existing
append-only question workflow: creation timestamps cannot be edited through the
application. A future backdated import or question deletion would need an explicit
numbering policy.

Strengthen the description prompt to name specific subjects from each theme’s own
citations and frame questions as possibilities rather than established facts.
Schema validation cannot prove semantic grounding; source review remains required.

## Description disappearance investigation (2026-10-27)

The older generation contract requested titles and source IDs only, rejected extra
response fields, and explicitly passed an empty string to `insert_theme`. SQLite
stored that empty string correctly; the template renders descriptions only when
nonempty. This was a generation/route contract issue, not a database or rendering
loss. The current source requires and persists descriptions with a 1,600-token
budget rather than the older 700-token title budget.

Read-only container inspection found the current source predates process startup
at 17:33:17 UTC. All 20 empty AI descriptions were created before startup
(last at 17:32:24 UTC); all 10 later AI themes had nonempty descriptions. This
supports legacy records as the observed blanks; it does not recover historical
model responses. A local synthetic two-question Ollama probe completed without
truncation and returned one validated theme with a 339-character description.
Only counts, lengths, timestamps and validation flags were printed. No production
generation, raw participant/model logging, database updates, restart or deployment
was performed.

Both parser and generation route now reject missing/blank descriptions, normalized
title repetitions, and descriptions exceeding three sentences. The route repeats
validation before persistence so an invalid batch rolls back without changing
existing themes or sources. Sentence splitting is a plain-text heuristic (including
an unterminated final sentence), and may treat abbreviations as boundaries; it
cannot prove meaningfulness or factual grounding. Prompt instructions and host
review remain responsible for semantic accuracy and preserving perspectives.
Manual themes and host edits retain their existing optional-description behavior.
Legacy blanks are deliberately not backfilled or republished automatically.

## ADR-014 — Explicit Analysis Runs and Reversible Draft Archives

**Status: Implemented, not deployed — October 27, 2026**

Before schema work, `bash scripts/database.sh backup` saved
`backups/common-ground-20261027T174713Z.db`. Independently verified SQLite integrity,
required tables and foreign keys. Applied migration twice to an isolated copy of
that backup: every original table record was unchanged, integrity/foreign-key
checks passed, and no historical run membership was invented. The running database
and service were not migrated or restarted.

**Additive provenance**

`analysis_runs` records the generation receipt, gathering, UTC start/completion,
input question count, selected previous-draft action, status, and original generated
theme count. `theme_analysis_runs` associates each newly generated theme ID with
its run. `archived_themes` stores reversible private-draft archive metadata. No
existing table or theme record is rewritten by migration. IDs, sources, original
AI titles, approval/publication states, and participant submissions remain intact.
No timestamps are used to guess old run boundaries: unassociated AI themes remain
honestly labeled legacy suggestions with unknown runs/input counts.

A run and its single-use receipt are claimed in one short write transaction before
inference. No write lock is held across Ollama. Success inserts all new drafts and
sources, associates them with the run, and applies the requested previous-draft
choice in one transaction. Failure rolls back the entire batch and marks the
receipt/run failed. Process interruption can leave a pending run; the UI labels
it in progress or interrupted, not complete. There is no background recovery.
Original generated counts survive explicit theme deletion; current status counts
reflect remaining records. Unsuccessful runs have no generated count.

**Previous-draft choices and concurrency**

Default Archive creates metadata only for earlier unapproved AI drafts. Keep
preserves their active state. Delete requires a separate explicit checkbox and
removes earlier unapproved AI drafts (including archived ones) plus their dependent
sources/run association/archive metadata. It never deletes participant questions
or the run receipt itself. Protected manual, approved, and published themes are
excluded. Snapshot eligible IDs/revisions when claiming the run; apply the choice
only to matching still-unapproved AI drafts at success. Edits, approvals, restores,
archives, ordering changes and concurrent new drafts therefore survive inference.

Archive/Restore are authenticated, CSRF-protected, gathering-scoped, revision-checked
POST operations. Both increment the theme revision to reject stale forms. Archived
drafts remain private, keep original citations/run provenance, and require Restore
before editing or approval. They may still be explicitly deleted with confirmation.
Public queries and the Draft → Approved → Published workflow are unchanged.

**Host disclosure design**

Current Themes appears first and contains every manual or approved/published theme.
New runs appear newest first with native `details/summary` headers showing readable
generation time, known input count, original generated count and status counts.
Only the newest run opens initially; theme rows stay collapsed with title, state
and a short description preview. Old active/archived AI drafts stay under their
original run. Approved/published history entries retain a collapsed summary and
link to the sole editor in Current Themes, avoiding duplicate IDs or conflicting
forms. Provenance links work in both directions with progressive enhancement.
Legacy history is collapsed and clearly disclaims known run grouping.

Theme actions retain the original global ordering (including history drafts), so
moving across a group boundary may not visibly change that group's local order;
position numbers identify the gathering-wide order. Save/Approve validation or
revision errors retain HTTP 400/409, expand the affected theme/run, keep attempted
edit text, and render escaped feedback next to the form. Success returns to the
affected theme. Authorization/CSRF/not-found failures retain their existing policy.

The existing palette, focus outlines, high contrast and 44px targets extend to
new summaries and radio choices. A small external script opens linked disclosure
targets; a shared formatter now displays dates in the browser's timezone (ADR-015). Native
forms/disclosures work without scripting; timestamp fallback is now the explicit
America/New_York prototype zone (ADR-015).
No participant/model content is logged, fetched for display from other services,
or exposed publicly by the history UI.

**Verification and limitations**

Regression tests cover explicit grouping, disclosure defaults, unique IDs, Current
Themes visibility, legacy migration, all three choices, default archive and restore,
confirmation, failed generation, edits/approvals during inference, source/submission
preservation, foreign-key-safe deletion, stale revisions, scope, CSRF and nearby
error feedback. Browser-local formatting and full assistive-technology behavior
still need a manual browser audit; this environment has no browser runner. History
loads all records without pagination. Run metadata does not store a full input-text
snapshot, model-response archive, or reviewer revision history. Input counts refer
to the actual question list sent to inference; citations continue using stable DB
IDs and gathering-local question numbers in displays. No production migration,
deployment, commit, or automatic historical cleanup was performed.

## ADR-015 — Automatic Browser Timezones for System Timestamp Display

**Status: Implemented, not deployed — October 27, 2026**

Use `Intl.DateTimeFormat().resolvedOptions().timeZone` to detect each browser's
IANA timezone. Validate the detected zone with Intl and explicitly pass it to the
display formatter. Never derive the user's zone from the container, assume Eastern
Time for everyone, or send browser timezone information to the server. Native Intl
applies daylight-saving transitions. Format with English month names, numeric
calendar date/year, 12-hour AM/PM time, and short timezone name or GMT offset:
`Oct 27, 2026 · 1:22 PM EDT`. Tooltips show readable text and the IANA zone, without
raw ISO timestamps or microseconds.

When detection is unavailable, empty, invalid or throws, use America/New_York for
this prototype and append the visible label `(America/New_York; fallback)`. The
server renders the same readable, labeled fallback using explicit `ZoneInfo`, not
the server's default timezone. This also handles no-JavaScript/no-Intl browsers.
The existing Docker image has the required IANA timezone data; other Python hosts
must supply that standard-library runtime data. Browsers may have different
versions of IANA timezone rules, so very recent rule changes depend on updates.

The shared Jinja timestamp macro and Python display filter normalize only emitted
machine-readable attributes to UTC seconds. The shared external browser script
formats all `time[data-local-time]` elements, including analysis start/completion
and theme creation/update. No schema changes, timestamp migrations, UTC storage
changes, or CSV changes are introduced. Invalid/missing or timezone-naive values
show `Time unavailable`; they are not guessed or echoed. The client rejects
impossible dates that JavaScript Date would otherwise normalize. All markup stays
Jinja-escaped and browser updates use `textContent`, never `innerHTML`.

Gathering `when_text` is preserved verbatim as human-entered event schedule text.
It is never interpreted as UTC or passed through this formatter. Structured event
dates and event-specific IANA timezone configuration remain future work.

Remove timestamp formatting from the analysis-specific script and load the shared
formatter from the base template. Its disclosure/link-opening code, run grouping,
archive behavior, forms, statuses, and existing layout/focus styles are unchanged.
The native details/summary behavior requires no scripting.

Regression coverage includes UTC-to-New-York/Los-Angeles conversion, winter/summer,
both spring and fall DST boundaries, previous-day conversion, midnight AM,
non-US timezone offsets, default Intl detection, detection failures, invalid and
missing timestamps, text-only DOM updates, no-Intl fallback, shared theme/run
rendering, and unchanged system timestamps/event text. JavaScript tests run against
native Node.js Intl (`node tests/test_timestamps.cjs`); Node is test tooling only,
not a production dependency. Python tests run with the complete existing suite.
A full browser and assistive-technology audit remains manual. No service restart,
production database write, deployment, or commit was performed.

## Focused AI review corrections — local model references and single descriptions

Collapsed theme summaries retain title, state and a short description preview.
The preview is hidden with an open-state CSS selector when expanded, and host
static full-description paragraphs are removed. Active themes retain the existing
single edit textarea; archived themes have one read-only textarea until Restore.
Approved/published history references continue linking to their sole Current Themes
editor. No disclosure, grouping, archive, approval or publication transitions change.
Public published-description rendering is unchanged.

The generation route now builds a snapshot mapping from gathering-local display
numbers to database IDs. Only local numbers and question text enter Ollama, using
the existing input `id` and output `question_ids` field names. Prompt/schema text
explicitly defines those as local numbers and asks for natural issue prose without
question-number references. The parser validates returned numbers against the
supplied inputs; before persistence the route also rejects missing, noninteger,
boolean or unmapped sources and translates them through its request snapshot.
The existing persistence layer independently checks selected-gathering ownership.
Invalid batches roll back as before, without applying archive/delete choices.

Database IDs, foreign keys, existing citations, submissions and historical theme
text are not migrated or rewritten. No schema change is needed. Regression tests
exercise separate gatherings, nonconsecutive IDs, ID/local-number collisions,
invalid references, atomic rejection, preserved approved/published records, and
single-description editor markup/open-state hiding. Natural-language adherence
remains a host review responsibility; no automatic prose-number rewriting occurs.

## End-to-end demonstration checkpoint verification

Reviewed the complete uncommitted implementation and documentation before the
local checkpoint `Prepare Common Ground for end-to-end demonstration`. No blocking
runtime defects were found; corrected stale documentation statements about the
Archive/Keep/Delete choice and explicit English 12-hour formatting. No additional
feature changes were introduced during checkpoint preparation.

The complete suite passed 167 Python tests (five dependency deprecation warnings)
and 35 JavaScript tests using native Intl. A disposable synthetic-data application
with the current code completed two real local Ollama analyses. Verified saved
descriptions, database-ID mapping from local citations, newest-run disclosure
markup, default archiving and restoration, RSVP and gathering creation, approval,
publication, unchanged original submissions and SQLite integrity/foreign keys.
Only counts and pass/fail flags were printed; no raw participant or model output.
The existing live database/service was not changed or restarted.

All four available SQLite backups passed read-only integrity, required-application-
table and foreign-key checks; the existing code archive was readable. The most
recent available database snapshot is
`backups/common-ground-20261027T174713Z.db`. Backups remain private, ignored local
artifacts; this checkpoint contains application code, tests and documentation only.

The README includes a fictional-data demonstration sequence. A real browser and
assistive-technology audit, fresh host review of model interpretations, and starting
an updated local demo instance are still manual steps. Existing limitations remain:
legacy run provenance cannot be reconstructed, history has no pagination, interrupted
analyses require an explicit retry, and human-entered event schedules have no
structured event-specific timezone configuration. No push or deployment is part
of this checkpoint.

## ADR-016 — Three-View Server-Rendered Host Workspace (Phase 4)

**Status: Implemented; local checkpoint “Complete three-tab Host workspace redesign”; not deployed**

Before changes, confirmed a clean working tree at
`c83ce6cff872439c4cf2f03b602397033aa10d16` (Checkpoint AI analysis management and local
time). Reviewed the README, architecture decisions, existing FastAPI routes,
templates, styles and tests. This phase restructures the long Manage Gathering
page without changing its persistence or inference workflow.

**Inventory and placement**

- Dashboard gathering creation, login/logout, recent submissions and navigation
  remain on the existing host dashboard.
- Gathering: details, structured agenda, resource creation/editing/removal. Agenda
  and resources use secondary native disclosures, reopened after relevant saves/errors.
  Resource removal retains its separate per-resource disclosures, away from Save.
  A clearly separated Gathering Status section at the bottom contains Cancel/Restore.
- Participants: scoped RSVP count/names, original gathering-local numbered
  questions, and both CSV downloads. Names and questions are not linked to each
  other. Received system timestamps reuse the existing shared timezone formatter.
- Discussion Themes: unchanged run grouping/current themes/manual drafts,
  nested disclosures, original source citations, description editor, generation,
  archive/keep/confirmed deletion, archive/restore, optimistic revisions, approval,
  publication, unpublishing, individual draft deletion and global ordering.
- Theme deletion retains its established contextual disclosures and confirmations
  in Discussion Themes. The initial Administration view and redundant informational
  sections were removed in favor of three views. No new gathering deletion, RSVP
  deletion or database maintenance UI is invented; backup/restore scripts are unchanged.

**Navigation and validation**

Use `?tab=gathering|participants|themes`, with Gathering as default.
Authenticated GETs to the old `?tab=administration` URL redirect to Gathering;
old resource-removal/status section links map to the appropriate Gathering section.
Authorization and gathering existence checks run before redirecting. Legacy form
POSTs still use the existing mutation endpoints and return/errors render on Gathering.
The persistent workspace header shows title, state, human-entered schedule and
location plus a dashboard link. Ordinary links in a labeled nav use
`aria-current="page"`; full-document navigation preserves native browser history
and bookmarking without implementing a scripted tablist/keyboard model. Links
wrap on small screens and retain contrast, 44px targets and visible focus.
Only the selected view's content is rendered, reducing clutter and unnecessary
loading of private records. Invalid view keys return HTTP 400. Existing
`?theme=ID` links continue selecting Discussion Themes when no explicit tab is
provided. Fragment-only historical links require an updated tab query because
servers cannot inspect URL fragments.

Existing mutation routes remain. Their HTML forms name the owning view, and 303
redirects explicitly return to it. Section/theme identifiers reopen the relevant
disclosure and scroll to it. Theme action errors retain existing affected-run/theme
feedback. Scoped HTTP/validation handlers render host workspace 400/409/422 errors
on the correct view, retain plain submitted edit fields/agenda rows, and never
write during error rendering. The valid-CSRF form data is retained on request
state for this rendering; credentials/tokens are not echoed. API-style responses
for public validation errors, authentication/CSRF failures and not-found records
are preserved. Missing fields for a nonexistent gathering do not cause an error
while attempting to render a missing workspace.

Manual creation errors now show next to the manual form; missing/invalid required
fields also remain within Discussion Themes. Existing single-use keys, host auth,
CSRF, input validation and concurrency checks are retained. All server-rendered
values are escaped. Views and CSV exports remain no-store and gathering-scoped.

**Preservation**

No schema migration or stored-data rewriting. RSVP/question IDs and records,
numbering order, agenda/resource records, theme IDs/text, analysis provenance,
citations, archive metadata and approvals/publication remain governed by the same
code. The Ollama prompt/parser, question-number mapping, archive implementation,
public visibility rules and UTC storage are unchanged. No framework or dependency
is added. Production services/database are not restarted, deployed or modified.

**Verification and limitations**

Existing regression tests now visit the explicit view relevant to their assertions;
the generation-key helper reads the Discussion Themes form's query-aware action.
New tests cover all three contents/URLs, active-link semantics, scoped loading and
privacy, persistent header, readonly navigation, redirects, failed/missing forms,
retained escaped input, reopened sections/theme editors, cancellation/restore,
resources, RSVP/CSV, generation/archive/restore and approval/publication/unpublishing.
The full existing workflow suite also exercises all three AI draft choices,
atomic failures, concurrent edits, duplicate receipts and immutable citations.

Full browser/assistive-technology testing remains manual. Navigation is ordinary
page loading, so unsaved edits are not automatically saved when switching views.
No pagination is added to participant lists or analysis history. Global theme
ordering still spans history/current groups as before. Existing dependency
warnings and shared-password prototype limits remain outside this UI phase.

Final three-view Phase 4 validation passed 196 Python tests and all 35 native-Intl JavaScript
tests; five existing dependency deprecation warnings remain. `git diff --check`
passed. No staging, commit, push, deployment, production database mutation or
service restart was performed.

The three-view simplification removes the Administration template entirely. Legacy
GET redirects and old form POSTs are covered for authentication, missing gatherings,
validation feedback, correct target section and unchanged participant/theme records.
Cancel/Restore returns to Gathering Status; resource removal reopens Resources.
Theme deletion confirmations and AI analysis controls remain unchanged.

## Three-tab Host checkpoint verification

Reviewed the full Phase 4 diff and new templates/tests before the local commit
`Complete three-tab Host workspace redesign`. Confirmed exactly Gathering,
Participants and Discussion Themes; Gathering Status owns Cancel/Restore, resource
removal remains in Resources, and old Administration URLs redirect after auth and
existence checks. No functionality was changed during checkpoint preparation.

The complete automated suite passed 196 Python tests and 35 native-Intl JavaScript
tests. Five existing dependency deprecation warnings remain. Workspace and existing
regressions cover RSVP, questions, exports, agenda/resources, AI generation and
citations, all draft choices, archive/restore, approval/publication, authorization,
CSRF, validation feedback and concurrency. `git diff --check` passed.

Created a fresh online SQLite snapshot at
`backups/common-ground-20261027T184037Z.db`, then independently verified integrity,
required application tables and foreign keys. The backup is private and ignored;
it is not part of the commit. Only the reviewed source, tests and documentation
are included. Existing limitations remain: manual browser/accessibility and AI
interpretation review, unsaved edits when switching tabs, unpaginated histories,
legacy provenance gaps and shared-password prototype authentication. No new AI
work, schema changes, deployment, service restart or push was performed.
