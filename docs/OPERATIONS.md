# Existing-installation operations and deployment boundaries

These notes are for an operator who has already identified and authorized work on
an existing installation. They are **not part of the reviewer setup**. Reviewers
should instead use [the isolated guide](REVIEWER_GUIDE.md). No commands in this
file authorize changing production, restarting services or running migrations.

## Storage and configuration

The operational [compose.yaml](../compose.yaml) binds `127.0.0.1:8000`, reads
configuration through Compose and stores `/data/common-ground.db` in a project-
scoped named volume. Never replace an existing `.env` with example credentials.
Keep environment files and backup storage private and outside source control.
Application startup creates/migrates schema. Therefore, do not start newer source
against an existing database just to inspect it or run tests.

## Backup and restore

When an operator has separately approved an online backup of the identified
installation, the existing wrapper supports:

```sh
bash scripts/database.sh backup backups/before-approved-update.db
```

This command targets the operational Compose project selected in that shell;
it is not a reviewer-volume backup. Verify the intended context first. It uses
SQLite's online backup API, checks integrity and refuses to overwrite the chosen
backup file. Independently verify foreign keys as well before relying on a backup.
Do not copy a database being written with ordinary `cp`; SQLite sidecars may matter.
Each backup contains the entire database, including contributions, private themes,
notes and analyses. Store an additional protected copy on separate durable storage.

The restore interface is `bash scripts/database.sh restore BACKUP_FILE --yes`.
Do not run it as part of a review. Restore stops the web service, validates the
incoming database, creates a pre-restore recovery copy in the data volume, replaces
the database and restarts the service if it was running. This is destructive work
requiring separate approval, correct application-version matching and no concurrent
database access. Recovery copies in the volume are lost if that volume is deleted.
The wrapper's validation is not a substitute for independently checking integrity,
foreign keys, backup provenance and recovery procedures.

Backups do not contain environment credentials, session secrets, application code
or container images. Preserve those separately in secure storage. Scheduling's
startup migration also creates a verified backup beside populated legacy databases
before adding missing scheduling columns; it does not replace an operator backup.
Other additive startup schema changes still require pre-update backup planning.

## Before any public service deployment

Source publication is separate from deployment. The prototype is not ready for an
unrestricted public service: shared-password authentication, non-Secure session
cookies, absent rate limiting and incomplete participant data-retention/privacy
controls need review. HTTPS, robust authorization, abuse prevention, protected
backups, monitoring, accessibility and a privacy/deletion policy remain operator
work. Do not expose the container or Ollama through a public port or tunnel merely
to make an application demonstration available.

No production Nginx, Tailscale, DigitalOcean or private inference configuration is
provided here. [Architecture decisions](DECISIONS.md) describe historical plans,
not a deployment runbook or an authorization to execute those plans. Public URLs
in the fictional manifest are background resources, not infrastructure credentials.

## Application activity logs

Common Ground writes allowlisted JSON Lines events through the Python
`common_ground.activity` logger. Compose sets `ACTIVITY_LOG_PATH` to
`/data/logs/activity.jsonl` in the existing `common_ground_data` volume, so events
survive container replacement and restart. Native runs default to
`/tmp/common-ground-logs/activity.jsonl`; set `ACTIVITY_LOG_PATH` to durable local
storage when retention is needed. No database migration is involved.

The log directory is created with mode 0700 and the file with 0600. Rotation keeps
five backups of at most 5 MiB each, plus the current file (approximately 30 MiB
maximum). Rotation assumes the existing single Uvicorn worker; use a centralized
logging collector before running multiple workers against one file. Backups of
the data volume include logs; apply the same access controls and retention to
those backups. Storage failures are best effort and never block user actions;
operators should monitor free space and log freshness.

Inspect current events or follow activity:

```sh
docker compose exec web tail -n 100 /data/logs/activity.jsonl
docker compose exec web tail -F /data/logs/activity.jsonl
# Filter one request across action, inventory and inference events:
docker compose exec web sh -c 'cat /data/logs/activity.jsonl*' | jq -c 'select(.correlation_id == "REPLACE_WITH_ID")'
```

Every instrumented request gets a server-generated correlation ID, returned in
`X-Correlation-ID`. Each has one started event and one terminal outcome (these
are lifecycle stages, not duplicate actions). Inference also carries the analysis
run ID once created. Shared authenticated organizer sessions are recorded as
`host`; the app has no distinct admin or identified participant accounts. Public
submissions use `participant` without identity; unauthenticated host actions use
`anonymous`. No names, IP addresses, form bodies, URLs, credentials, prompts,
participant text or generated analysis are logged. Correlation IDs supplied by
clients are deliberately ignored.

Events cover host login/logout, gathering create/edit/cancel/reactivate, RSVP and
question submission, agenda save, resource add/edit/remove, manual theme creation,
private notes save, theme edit/approve/publish/unpublish/archive/restore/delete and
ordering, analysis inactive/reactivate/delete, CSV export, analysis view/export,
and AI analysis request/complete/failed. Validation, authorization, model errors
and login failures produce failed outcomes, including errors rendered as HTTP 200.

`OLLAMA_REQUEST_SUBMITTED` records a local send attempt. `OLLAMA_HTTP_RESPONSE`
means an HTTP response was observed, with its status; connection failures and
timeouts without a response never produce this event. This is HTTP receipt
evidence, not a claim that the model accepted or executed the request.
`OLLAMA_MODEL_RESPONSE` requires successful HTTP, a decoded envelope with
`done: true`, and no model error. Token counts are recorded only if numeric.
Schema validation and database persistence can still fail afterward, producing
`AI_ANALYSIS_FAILED`. Inventory checks use `operation: inventory`; cached checks
do not issue requests or produce synthetic network events. Timing uses a
monotonic clock, while event timestamps use ISO 8601 UTC.

`ANALYSIS_PRINT_REQUEST` records the Print / Save PDF click using a bounded,
CSRF-protected host endpoint; it never claims that printing completed. Browser-only
controls (opening review panels, schedule editors,
and adding/removing unsaved agenda rows) are not instrumented. Saved changes and
report opens/downloads are recorded on the server. A report view does not prove
that the browser printed or saved a PDF; no such completion is claimed.
