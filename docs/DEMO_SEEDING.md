# Explicit fictional demonstration seeding

This dataset supports the independent Common Ground proof of concept for a
Resonance Technical Fellow application. It is not endorsed by the resource
publishers. Events, venues and all participant questions are fictional. There are
no real attendees, fabricated RSVPs, AI themes, or Ollama calls.

Content is reviewable in [the versioned manifest](../app/demo_gatherings.json).
Each event has a concise labeled description, a labeled fictional venue, six
structured agenda items totaling 90 minutes, two verified public resources and
12 distinct questions prefixed `[Fictional demo]`. All five schedules use
America/New_York with an explicit same-day end time.

| Stable key suffix | Gathering | Date | Local time |
|---|---|---|---|
| small-businesses | Supporting Local Small Businesses | 2026-12-08 | 18:30–20:00 |
| aging-well | Aging Well in Our Community | 2026-12-10 | 14:00–15:30 |
| young-voices | Young Voices, Community Futures | 2026-12-12 | 10:00–11:30 |
| food-resilience | Food, Farms, and Community Resilience | 2026-12-15 | 18:30–20:00 |
| community-ai | AI and Our Community's Future | 2026-12-17 | 18:30–20:00 |

The stable key prefix is `common-ground-fictional-december-2026-v1:`. Changing a
content definition is not an instruction to overwrite an existing event.

## Safety and behavior

`python3 -m app.seed_demo` is a standalone CLI. It is never imported or called by
startup, migrations, or HTTP routes. It requires an explicit local file path and
never defaults to DATABASE_PATH or a Docker/production target. The default is a
read-only dry-run, including no metadata table creation. Nonexistent files and
incomplete application schemas are refused; this utility performs no migrations.

A detailed JSON report includes the entire proposed content, stable keys, database
fingerprint, expected IDs, and before/after counts. Dry-run IDs are **provisional**;
apply always uses SQLite-allocated IDs and records the actual mappings.

Apply requires all of the following:

- `--apply` and the operator's explicit `--confirm-local-demo` assertion.
- An existing, separate `--backup` file (not the target or a hardlink to it).
- `--backup-sha256` independently obtained from the verified backup.
- `--expect-database-fingerprint` from a reviewed dry-run.

The confirmation flag is an operator assertion, **not automatic detection of
production**. A locally mounted production copy could look like any other SQLite
file. Check the resolved database path and report before approving a write. This
workflow has no remote-service connection and must not be used on production.

The CLI independently checks backup SHA-256, SQLite integrity and foreign keys,
then takes BEGIN IMMEDIATE with foreign keys enabled. The target's complete logical
schema/data must match both the reviewed fingerprint and backup. Concurrent changes
cause refusal. All checks precede inserts. Any failure rolls back, including the
new registry table. Preexisting rows in every table must remain identical. Tables
unrelated to gatherings/questions/agendas/resources must remain unchanged.

Only an explicit apply can create `demonstration_seed_items`, an additive registry
with stable seed key, allocated gathering ID, manifest hash, child-ID mappings and
application timestamp. Repeat applies validate mapped content and skip existing
items. They do not match approximately on title, refill edited/deleted rows, or
reset questions, schedules, resources or agendas. An unregistered exact-title
collision, changed manifest, or edited seeded record requires manual review and
causes refusal. Additional user records are preserved. Every apply, including a
repeat verification, requires a fresh matching backup and reviewed fingerprint.

No existing Library/Neighborhood question is transferred, copied or renumbered.
No RSVPs, themes, runs, citations or private notes are generated or edited.

## Local disposable workflow

Do not apply to the active local Docker database until explicitly approved.
Start with a consistent SQLite online backup, verify it, and copy it to a disposable
file. Do not copy an actively written database file with ordinary `cp`; WAL contents
might be omitted. The repository's existing backup script can create a snapshot:

```sh
bash scripts/database.sh backup backups/fresh-local.db
# This command reads the running local database; it does not seed or migrate it.
```

Use `app.database_tools.snapshot` to make a disposable copy of that verified backup.
Then inspect the detailed default dry-run:

```sh
python3 -m app.seed_demo --database /absolute/path/disposable.db > /tmp/demo-plan.json
sha256sum /absolute/path/verified-pre-seed-backup.db
```

Independently verify the backup's integrity and foreign keys using a read-only
SQLite connection and `app.scheduling.check_integrity`. The backup must represent
exactly the current disposable target. After reviewing the whole JSON proposal,
substitute its fingerprint and the independently obtained backup hash:

```sh
python3 -m app.seed_demo --database /absolute/path/disposable.db \
  --apply --confirm-local-demo \
  --backup /absolute/path/verified-pre-seed-backup.db \
  --backup-sha256 REVIEWED_BACKUP_SHA256 \
  --expect-database-fingerprint REVIEWED_DRY_RUN_FINGERPRINT
```

The placeholder strings deliberately do not authorize a real write. For a second
apply, take and independently verify a new backup of the seeded disposable target,
review a new dry-run, then repeat with those new values. Expected result:
`applied-no-op`, no record changes, stable IDs. A stale pre-seed backup is refused.

Run tests without live data using the Docker test image, mounting tests only:

```sh
bash scripts/test-docker-timezones.sh
docker run --rm --network none \
  --mount "type=bind,src=$PWD/tests,dst=/project/tests,readonly" \
  cg-timezone-test:local python -m pytest -q -p no:cacheprovider
node --test tests/*.cjs
git diff --check
```

## Resource verification

These exact final URLs were opened and verified on October 28, 2026. No unavailable
or guessed links were included. Links may change in the future; reverify before
revising the content manifest. The CLI itself performs no network requests.

| Gathering | Verified background resources |
|---|---|
| Small businesses | [SBA counseling](https://www.sba.gov/counseling/); [NIST small-business cybersecurity](https://www.nist.gov/itl/smallbusinesscyber) |
| Aging well | [ACL Eldercare Locator](https://eldercare.acl.gov/home); [ACL Area Agencies on Aging](https://acl.gov/programs/aging-and-disability-networks/area-agencies-aging) |
| Young voices | [Tufts CIRCLE youth civic engagement](https://circle.tufts.edu/understanding-youth-civic-engagement); [BLS Occupational Outlook Handbook](https://www.bls.gov/ooh/) |
| Food resilience | [USDA Local Food Directories](https://www.ams.usda.gov/services/local-regional/food-directories); [EPA Sustainable Management of Food](https://www.epa.gov/sustainable-management-food) |
| Community AI | [NIST AI Risk Management Framework](https://www.nist.gov/itl/ai-risk-management-framework); [OECD AI Principles](https://oecd.ai/en/ai-principles) |

## Rehearsal and approval checkpoint

The fresh source backup is `backups/common-ground-20261028T173249Z.db`. Integrity/FK
checks passed. The first apply ran on
`/tmp/cg-demo-seed-rehearsal-20261028T173249Z.db`, never the active database. A second
apply against a new verified post-first-pass backup made no changes. All original
values across all existing tables were preserved. No original 34 questions,
Library/Neighborhood gatherings, 15 themes, two runs, 55 citation rows, 32 coverage
rows, ten facilitation-note records or two RSVPs changed.

| Table | Before | After disposable apply |
|---|---:|---:|
| gatherings | 2 | 7 |
| questions | 34 | 94 |
| agenda_items | 9 | 39 |
| resources | 0 | 10 |
| demonstration_seed_items | absent | 5 |
| rsvps | 2 | 2 |

Rehearsal IDs: gatherings 3–7; questions 41–100; agenda items 10–39; resources 1–10.
These are not hardcoded allocation assumptions. Both HTTP directories showed all
five new events in chronological Upcoming order across the existing two pages
(seven upcoming events total). The detailed review report is
`backups/demo-seed-active-proposal-20261028T173249Z.json`; the rehearsal receipts are
`backups/demo-seed-rehearsal-first-20261028T173249Z.json` and
`backups/demo-seed-rehearsal-second-20261028T173249Z.json`. Backups/reports remain
excluded from Git. A read-only active dry-run matched the original backup fingerprint,
confirming no active records or schema were changed by the rehearsal.

Full verification passed 411 Python tests and 72 JavaScript tests, with five existing
Python deprecation warnings. Integrity/FK checks and `git diff --check` passed.
At that rehearsal checkpoint, approval was still pending and no live seed apply
had been performed. The subsequent explicitly approved local apply is recorded below.


## Approved local application and source checkpoint

After explicit approval, the existing utility applied the unchanged reviewed
proposal to `/data/common-ground.db` in the local `cg_common_ground_data` Docker
volume. The Docker endpoint was a local Unix socket and the web service was bound
to 127.0.0.1:8000. The active preflight exactly matched the reviewed proposal;
the manifest, resource catalog, database fingerprint and verified backup matched.
The original content and seeding implementation were not changed during publication.

The guarded apply used `--apply`, `--confirm-local-demo`, the reviewed database
fingerprint and a separately verified fresh pre-apply backup/hash. It committed only
five new gatherings and their children/registry rows. An independent read-back
compared every original record and schema entry with the pre-apply snapshot.
All 34 original questions and all Library/Neighborhood values, themes, analyses,
citations, coverage, private notes and RSVPs remained unchanged. Integrity and
foreign-key checks passed. A subsequent CLI dry-run recognized every registry key
and proposed zero additional changes; no second write apply was used on the active
local database. Local UI was subsequently visually verified by the user.

| Gathering ID | Gathering | Question IDs | Agenda IDs | Resource IDs |
|---:|---|---|---|---|
| 3 | Supporting Local Small Businesses | 41–52 | 10–15 | 1–2 |
| 4 | Aging Well in Our Community | 53–64 | 16–21 | 3–4 |
| 5 | Young Voices, Community Futures | 65–76 | 22–27 | 5–6 |
| 6 | Food, Farms, and Community Resilience | 77–88 | 28–33 | 7–8 |
| 7 | AI and Our Community's Future | 89–100 | 34–39 | 9–10 |

Final counts: 7 gatherings, 94 questions, 39 agenda items, ten resources and five
registry entries. Existing counts stayed at 15 themes, two analyses, 55 theme-source
rows, 32 coverage rows, ten facilitation-note records and two RSVPs. All five new
90-minute America/New_York schedules matched the proposal and sorted chronologically.

Local recovery/verification artifacts, all excluded from Git:

- Pre-apply backup: `backups/common-ground-20261028T174657Z.db`.
- Apply receipt: `backups/demo-seed-active-apply-20261028T174657Z.json`.
- Independent verification: `backups/demo-seed-active-verified-20261028T174657Z.json`.
- Post-apply dry-run: `backups/demo-seed-active-post-apply-dry-run-20261028T174657Z.json`.
- Latest post-seed backup: `backups/common-ground-20261028T175401Z.db`.

The latest snapshot passed independent integrity/FK checks and contained seven
gatherings, 94 questions and all five seed entries; a read-only plan proposed zero
additions. Its SHA-256 is
`49a56f075f7d215d2887634e17c29835e779792fa031b26790fb95a54ae6b5c3`.
The pre-apply backup checksum was independently reverified as well. Taking the
post-seed online backup read the active database without changing its records.

This publication task does not regenerate records, run a migration, call Ollama,
restart the service or deploy to DigitalOcean. Only source, tests and documentation
are published. The local-demo flag remains an operator assertion, links can change
after their verification date, and host-edited seed content deliberately requires
manual review instead of automatic repair. Each future apply still needs a new
matching verified backup and reviewed fingerprint.
