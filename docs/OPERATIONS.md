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

## Processing and interrupted AI analyses

An analysis commits its `pending` receipt, run and question snapshot before calling
Ollama, and releases the SQLite write lock during inference. Only the original
application request saves the generated themes and commits the terminal status.
If that process is killed, the pending record survives, even if Ollama finishes on
the separate inference machine. There is no background job, heartbeat, lease,
resume mechanism or automatic stale-request cleanup. A pending timestamp alone
cannot distinguish a slow request from an interrupted one.

Use the host's **Refresh analysis status** control to reconcile the original
receipt without starting inference. Correlate its analysis run ID with the original
request's activity events, application process/container lifetime and, where
available, Ollama's current processing state. A live original application request
may still finish; an Ollama response alone does not prove themes were saved.
`AI_ANALYSIS_COMPLETE` and the committed run state provide persistence evidence.
Missing terminal logs alone are inconclusive because logging is best effort.
Confirm that the original application request/process has ended before treating
its pending run as interrupted. A timeout also does not prove that remote Ollama
has stopped computing.

Never automatically regenerate a pending request or clear its receipt. Otherwise
an original request that is merely delayed could still save results alongside a
second inference. Same-key replay remains protected, including after run deletion.
If interruption is confirmed, retain the old run, snapshot and receipt for review.
Optionally mark that run **Make inactive** in the host UI; this is not cancellation
and does not stop an active inference. Start a separate analysis only as an
explicit host decision using a freshly rendered generation form. Existing themes,
private notes and participant questions must be retained. Do not delete analysis
history, reset statuses with ad hoc SQL, remove receipts, or restore a backup just
to make a pending request retryable. If the original process may still finish,
continue checking status instead of starting another attempt.

Before an authorized container replacement:

1. Identify the exact Compose project, existing named data volume, configuration
   and rollback image. Preserve the existing session secret (at least 24 characters)
   so recovery forms remain valid. Take and verify an online backup as above.
2. Coordinate a maintenance window with all hosts. Prevent new generation POSTs
   at the existing ingress, or otherwise ensure hosts cannot submit them during
   the drain. Keep status checks available. Do not create a new public inference
   endpoint; ingress changes require their own operational authorization.
3. Let active original application requests finish and confirm their terminal run
   states. Check every nonterminal run against process/log evidence; historical
   interrupted pending runs will not become terminal merely by waiting. Do not
   replace a container while it still owns an active analysis request. Docker's
   stop timeout alone is not an application drain guarantee.
4. Build and validate the intended image separately, then replace only the
   identified application container while retaining its data volume and settings.
   Never remove the volume. Reload host tabs to use the matching scripts/templates;
   first save unsaved edits. Verify health, existing history and recovery of a
   known completed analysis without requesting new inference, then reopen access.

The production procedure below applies this drain checklist to the identified
installation. Replacement can interrupt HTTP
connections; saved results remain recoverable by their original valid receipt.

## Before any public service deployment

Source publication is separate from deployment. The prototype is not ready for an
unrestricted public service: shared-password authentication, non-Secure session
cookies, absent rate limiting and incomplete participant data-retention/privacy
controls need review. HTTPS, robust authorization, abuse prevention, protected
backups, monitoring, accessibility and a privacy/deletion policy remain operator
work. Do not expose the container or Ollama through a public port or tunnel merely
to make an application demonstration available.

The production inventory below identifies the deployment without credentials or a
complete proxy configuration. [Architecture decisions](DECISIONS.md) describe historical plans,
not a deployment runbook or an authorization to execute those plans. Public URLs
in the fictional manifest are background resources, not infrastructure credentials.

## Production environment and November 13, 2026 release

Release `f7712f9` was successfully deployed on November 13, 2026. This record
and the procedure below do not authorize executing production changes. Never
record secret values or print environment files, container environments or full
resolved Compose configuration.

| Setting | Production value |
| --- | --- |
| Host | DigitalOcean Ubuntu droplet |
| Application directory | `/opt/common-ground` |
| Git repository | `https://github.com/kdh58/common-ground` |
| Compose project / service | `common-ground` / `web` |
| Container | `common-ground-web-1` |
| Compose configuration | `/opt/common-ground/compose.yaml` |
| Environment file | `/opt/common-ground/.env` |
| Application listener | `127.0.0.1:8000` |
| Public domain | `common-ground.itresidentexpert.com` |
| Nginx configuration | `/etc/nginx/sites-available/common-ground` |
| Persistent volume | `common-ground_common_ground_data`, mounted at `/data` |
| Database | `/data/common-ground.db` |
| Activity log | `/data/logs/activity.jsonl` |
| Ollama endpoint / model | `http://172.19.0.1:11435` / `qwen3:8b` |

Release artifacts:

- Candidate tag: `common-ground-web:candidate-f7712f9`.
- Candidate image: `sha256:9c5e7ff895675b226567824fcf35d6156f4b5cd86c3f7ba63a32b54e36af4d09`.
- Rollback tag: `common-ground-web:rollback-20261113`.
- Rollback image: `sha256:b198c9d7d78b868d6c89755f82bf1da83d3bdda92e95ad7049a493cb0b059f45`.
- Online database backup: `/data/backups/common-ground-pre-release-20261113T162548Z.db`.
  An independent copy was transferred to SNAIL. Verification found SQLite integrity
  OK and zero foreign-key violations.

Validation passed: 466 Python tests, 96 JavaScript tests, candidate application
import and timezone checks, isolated HTTP smoke testing and production database
integrity checks. Existing analyses #22, #23 and #24 were visible. New analysis #25
was generated successfully, Ollama returned HTTP 200 and total request duration
was approximately 26.07 seconds. HTTPS and Basic Authentication were restored.
Lost-response recovery was covered by automated regression tests; a deliberate
live-browser network-interruption test was **not performed**.

## Production deployment procedure

These reusable commands follow repository interfaces; they are not a verbatim
transcript of the November 13 session. Execute only on the identified host during
an authorized maintenance window. Use Bash and stop on failed checks. Replace all
`REPLACE_...` placeholders. Never use `down`, volume removal or image pruning.

1. **Verify the Git revision and clean working tree.** Resolve any dirty tree
   before proceeding; do not reset or clean it. Verify the remote matches the
   inventory. Use unique artifact names for each deployment.

   ```bash
   set -euo pipefail
   set +x
   umask 077
   cd /opt/common-ground
   REV=REPLACE_WITH_APPROVED_COMMIT
   STAMP=REPLACE_WITH_UTC_TIMESTAMP
   CANDIDATE="common-ground-web:candidate-$REV"
   ROLLBACK="common-ground-web:rollback-$STAMP"
   BACKUP="/data/backups/common-ground-pre-release-$STAMP.db"
   CANDIDATE_OVERRIDE="/opt/common-ground/candidate-$STAMP.yaml"
   ROLLBACK_OVERRIDE="/opt/common-ground/rollback-$STAMP.yaml"
   dc() { docker compose --project-name common-ground \
     --env-file /opt/common-ground/.env -f /opt/common-ground/compose.yaml "$@"; }
   git remote get-url origin
   test -z "$(git status --porcelain)"
   test "$(git rev-parse HEAD)" = "$(git rev-parse "$REV^{commit}")"
   git rev-parse HEAD
   ```

2. **Identify the running project, image and volume.** Confirm labels match
   `common-ground` / `web` and the existing named volume is mounted at `/data`.
   Abort if the expected volume is absent; never substitute a new empty volume.

   ```bash
   test "$(dc ps -q web)" = "$(docker inspect -f '{{.Id}}' common-ground-web-1)"
   docker inspect -f '{{index .Config.Labels "com.docker.compose.project"}} / {{index .Config.Labels "com.docker.compose.service"}}' common-ground-web-1
   OLD_IMAGE=$(docker inspect -f '{{.Image}}' common-ground-web-1)
   docker inspect -f '{{.Image}} {{range .Mounts}}{{.Name}} -> {{.Destination}} {{end}}' common-ground-web-1
   docker volume inspect common-ground_common_ground_data --format '{{.Name}}'
   ```

3. **Verify session-secret continuity without displaying it.** Compare the running
   secret with Compose's resolved setting in memory. Print only the result. Keep
   `.env` unchanged through deployment and rollback and preserve its protected
   independent backup using the host's credential procedure.

   ```bash
   python3 - <<'PY'
   import json, subprocess
   running = json.loads(subprocess.check_output(
       ['docker', 'inspect', 'common-ground-web-1']))[0]
   env = dict(item.split('=', 1) for item in running['Config']['Env'])
   config = json.loads(subprocess.check_output([
       'docker', 'compose', '--project-name', 'common-ground',
       '--env-file', '/opt/common-ground/.env', '-f',
       '/opt/common-ground/compose.yaml', 'config', '--format', 'json']))
   secret = config['services']['web']['environment']['SESSION_SECRET']
   assert len(secret) >= 24 and secret == env['SESSION_SECRET'], 'Continuity failed'
   print('SESSION_SECRET continuity OK')
   PY
   ```

4. **Create and verify a SQLite online backup.** This uses SQLite's backup API
   without importing the application or triggering migrations. It refuses an
   existing filename. Failed attempts may leave an incomplete file: investigate
   and choose a new filename before retrying.

   ```bash
   dc exec -T -e BACKUP_PATH="$BACKUP" web python - <<'PY'
   import os, sqlite3
   from pathlib import Path
   os.umask(0o077)
   target = Path(os.environ['BACKUP_PATH'])
   target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
   target.open('xb').close()
   with sqlite3.connect('file:/data/common-ground.db?mode=ro', uri=True) as src:
       with sqlite3.connect(target) as dst:
           src.backup(dst)
           assert dst.execute('PRAGMA integrity_check').fetchall() == [('ok',)]
           assert dst.execute('PRAGMA foreign_key_check').fetchall() == []
   print('Backup integrity OK; zero foreign-key violations')
   PY
   dc exec -T web sha256sum "$BACKUP"
   ```

   Transfer an independent protected copy to SNAIL through the approved account
   and destination; compare checksums. Transfer details require host-side
   verification. The snapshot excludes later writes; take another verified backup
   after draining if the recovery plan requires it.

5. **Preserve the running image.** Require unused tags and record immutable IDs.

   ```bash
   if docker image inspect "$ROLLBACK" >/dev/null 2>&1; then exit 1; fi
   if docker image inspect "$CANDIDATE" >/dev/null 2>&1; then exit 1; fi
   docker image tag "$OLD_IMAGE" "$ROLLBACK"
   test "$(docker image inspect -f '{{.Id}}' "$ROLLBACK")" = "$OLD_IMAGE"
   ```

6. **Build and label the candidate without replacing production.** Build only
   from the verified clean checkout; do not use Compose `up --build`.

   ```bash
   docker build --label "org.opencontainers.image.revision=$(git rev-parse HEAD)" \
     --tag "$CANDIDATE" /opt/common-ground
   CANDIDATE_ID=$(docker image inspect -f '{{.Id}}' "$CANDIDATE")
   docker image inspect -f '{{.Id}} {{index .Config.Labels "org.opencontainers.image.revision"}}' "$CANDIDATE"
   ```

7. **Validate imports, timezone support and isolated HTTP.** Confirm port 18000
   and the smoke-container name are unused. Use temporary credentials and tmpfs;
   never mount production storage or supply production `.env`. These checks do
   not test production authentication or inference.

   ```bash
   docker run --rm --network none "$CANDIDATE_ID" python -c \
     'import app.main; from app.scheduling import verify_timezone_database; verify_timezone_database()'
   SMOKE="common-ground-smoke-$STAMP"
   docker run -d --name "$SMOKE" --restart no \
     --tmpfs /data:rw,mode=0700 -p 127.0.0.1:18000:8000 \
     -e DATABASE_PATH=/data/smoke.db \
     -e ADMIN_PASSWORD="$(openssl rand -hex 24)" \
     -e SESSION_SECRET="$(openssl rand -hex 32)" "$CANDIDATE_ID"
   curl --fail --silent --show-error --retry 10 --retry-connrefused \
     --retry-delay 1 -o /dev/null http://127.0.0.1:18000/
   docker stop "$SMOKE"
   docker rm "$SMOKE"
   ```

   If validation fails, remove the isolated container before investigating; do
   not proceed. Its tmpfs database is intentionally disposable.

8. **Prepare candidate and rollback overrides.** Pin immutable image IDs and
   declare production storage external, so Compose cannot create a replacement
   volume. Keep these private host-side artifacts out of tracked source files.

   ```bash
   write_override() {
     test ! -e "$1"
     cat > "$1" <<EOF
   services:
     web:
       image: $2
       pull_policy: never
   volumes:
     common_ground_data:
       external: true
       name: common-ground_common_ground_data
   EOF
   }
   write_override "$CANDIDATE_OVERRIDE" "$CANDIDATE_ID"
   write_override "$ROLLBACK_OVERRIDE" "$OLD_IMAGE"
   dc -f "$CANDIDATE_OVERRIDE" config --quiet
   dc -f "$ROLLBACK_OVERRIDE" config --quiet
   ```

9. **Back up the Common Ground Nginx configuration.** Confirm this is the active
   vhost file. Keep the backup outside `sites-enabled` to avoid enabling it twice.

   ```bash
   NGINX_BACKUP="/etc/nginx/common-ground-pre-release-$STAMP.conf"
   sudo test ! -e "$NGINX_BACKUP"
   sudo cp -p /etc/nginx/sites-available/common-ground "$NGINX_BACKUP"
   sudo nginx -t
   ```

10. **Enter maintenance for Common Ground only.** Prepare and review a change
    confined to its existing server/location blocks: reject new writes and
    generation with HTTP 503 while retaining authenticated status checks during
    draining. Preserve TLS and Basic Authentication. Do not edit shared includes,
    default servers, CUMC or CUMC-Legacy vhosts. Exact location rules depend on
    the host configuration and require verification there; do not substitute a
    generic server block. Apply the reviewed change, then:

    ```bash
    sudo nginx -t && sudo systemctl reload nginx
    ```

    Confirm maintenance behavior and both CUMC sites' normal behavior using their
    known URLs. Never reload after a failed configuration test.

11. **Drain requests and verify no pending analyses.** Coordinate with hosts and
    reconcile every nonterminal analysis using the interrupted-analysis guidance
    above. Inspect activity logs and application/proxy request evidence. Query
    the database read-only to identify pending blockers:

    ```bash
    dc exec -T web python - <<'PY'
    import sqlite3
    with sqlite3.connect('file:/data/common-ground.db?mode=ro', uri=True) as db:
        pending = db.execute("SELECT id FROM analysis_runs WHERE status='pending'").fetchall()
    print('Pending analysis IDs:', [row[0] for row in pending])
    assert not pending, 'Stop: pending analyses require reconciliation'
    PY
    ```

    Require zero pending analyses and no active original requests. Historical
    interrupted pending records require a separate operator decision; never reset
    them with SQL. After draining, block all Common Ground upstream traffic with
    maintenance 503, test/reload Nginx and confirm no requests remain. Keep other
    vhosts unchanged. A fixed sleep or Docker stop timeout does not prove draining.
    Save unsaved browser edits before replacement.

12. **Deploy only `web`, without rebuilding or pulling.** Immediately recheck
    secret continuity, existing volume and override image IDs before replacement.

    ```bash
    dc -f "$CANDIDATE_OVERRIDE" up -d --no-build --no-deps --force-recreate web
    ```

13. **Verify image, volume, HTTP and production integrity before reopening.**
    Repeat the secret continuity check against the replacement and inspect startup
    logs for errors. Require the original volume at `/data`:

    ```bash
    test "$(docker inspect -f '{{.Image}}' common-ground-web-1)" = "$CANDIDATE_ID"
    test "$(docker inspect -f '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Name}}{{end}}{{end}}' common-ground-web-1)" = common-ground_common_ground_data
    curl --fail --silent --show-error -o /dev/null http://127.0.0.1:8000/
    dc exec -T web python - <<'PY'
    import sqlite3
    with sqlite3.connect('file:/data/common-ground.db?mode=ro', uri=True) as db:
        assert db.execute('PRAGMA integrity_check').fetchall() == [('ok',)]
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []
    print('Production integrity OK; zero foreign-key violations')
    PY
    ```

14. **Restore Nginx and verify HTTPS authentication.** Restore only the saved
    Common Ground configuration. If validation fails, keep maintenance active and
    investigate. Require HTTP 401 without credentials and success with Basic
    Authentication; `curl --user` prompts for the password. Never put passwords
    on the command line or bypass certificate verification.

    ```bash
    sudo cp -p "$NGINX_BACKUP" /etc/nginx/sites-available/common-ground
    sudo nginx -t && sudo systemctl reload nginx
    curl --silent --show-error -o /dev/null -w '%{http_code}\n' \
      https://common-ground.itresidentexpert.com/
    BASIC_USER=REPLACE_WITH_BASIC_AUTH_USERNAME
    curl --fail --silent --show-error --user "$BASIC_USER" -o /dev/null \
      https://common-ground.itresidentexpert.com/
    ```

    Verify CUMC and CUMC-Legacy again. Verify application host login separately
    from Basic Authentication in the browser.

15. **Perform browser tests and inspect activity logs.** Reload host tabs for the
    matching scripts/templates. Verify existing history and recovery of a completed
    analysis without new inference first. With host approval, generate a new
    analysis, verify persisted results and correlate its run/request IDs with
    Ollama HTTP status, completion and duration in `/data/logs/activity.jsonl`.
    Use the activity-log commands below. Record exactly which recovery scenarios
    were exercised; automated tests do not establish a live interruption test.
    Retain images, overrides, Nginx backup and independent database backups.

## Application rollback

Use the same maintenance and drain gates (steps 9–11). Never replace a container
owning an active analysis, clear pending receipts or remove persistent volumes.
Verify the preserved image exists and is compatible with the current schema before
starting it. Keep `.env` and `SESSION_SECRET` unchanged and repeat the continuity
check before and after rollback.

In a new shell, reconstruct `dc` from step 1 and set `ROLLBACK_OVERRIDE`,
`OLD_IMAGE` and `NGINX_BACKUP` to the preserved artifacts from the deployment,
not newly generated filenames. After maintenance is active and requests drained:

```bash
docker image inspect "$OLD_IMAGE" --format '{{.Id}}'
docker volume inspect common-ground_common_ground_data --format '{{.Name}}'
dc -f "$ROLLBACK_OVERRIDE" config --quiet
# Confirm the preserved override pins OLD_IMAGE and the external production volume.
dc -f "$ROLLBACK_OVERRIDE" up -d --no-build --no-deps --force-recreate web
test "$(docker inspect -f '{{.Image}}' common-ground-web-1)" = "$OLD_IMAGE"
test "$(docker inspect -f '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Name}}{{end}}{{end}}' common-ground-web-1)" = common-ground_common_ground_data
```

Repeat step 13's secret, HTTP and database checks using the rollback image ID,
then restore Nginx and verify HTTPS/authentication and browser history as in steps
14–15. If schema compatibility is uncertain, keep maintenance active and plan
recovery separately rather than starting the older application.

**Application rollback does not automatically roll back database contents.** The
existing volume retains subsequent writes and candidate startup schema changes.
Never restore an older database over a live database during image rollback.
Database recovery requires a separate, deliberate procedure with approval, stopped
writers, a fresh recovery copy, verified backup provenance/integrity and compatible
application version; see Backup and restore above. Restoring the pre-release
snapshot can discard all subsequent writes, including completed analyses.

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

Receipt reconciliation has separate terminal events: `AI_ANALYSIS_RECOVERED`
(complete), `AI_ANALYSIS_PENDING_STATUS`, `AI_ANALYSIS_FAILED_RECOVERY`,
`AI_ANALYSIS_DELETED_RECOVERY`, and `AI_ANALYSIS_UNRECORDED_STATUS`. They include
`gathering_id`, `receipt_state` and `analysis_run_id` when a run still exists.
Status checks start with `AI_ANALYSIS_STATUS_REQUEST`; generation-endpoint replays
start with `AI_ANALYSIS_REQUEST` and end with the appropriate recovery event.
Here `succeeded` means that reconciliation succeeded, not that a failed/pending
analysis completed. Recovery never emits `AI_ANALYSIS_COMPLETE` or model events.
Raw signed request keys and participant/generated content are never logged.

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
