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

- Retain the 700-token output limit and temperature of 0.2 for the current experiment.
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

Retain local Qwen3/Ollama JSON generation, `think: false`, 700 tokens, temperature
0.2, existing timeouts, truncation rejection, response validation, and bounded
opt-in diagnostics. Only this gathering's question IDs and text are sent; RSVPs
and theme edits are not sent. AI descriptions are not generated: hosts supply
optional context. Errors preserve all submissions and existing themes.

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
