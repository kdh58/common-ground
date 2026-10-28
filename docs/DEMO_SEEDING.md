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

## Counts on a fresh clone

Startup creates one fictional Library gathering, three agenda items and no questions
or RSVPs. Applying this manifest before entering other content produces **six
gatherings, 60 questions, 33 agenda items, ten resources and five registry entries**.
The Library's schedule remains unconfirmed legacy text; the five seeded events use
the explicit December 2026 schedules above. No AI analyses, themes or RSVPs are added.

The previously documented seven gatherings and 94 questions came from an existing
developer-local database with two gatherings and 34 questions before seeding.
Those counts, allocated IDs and private recovery artifacts are not a reproducible
fresh-clone fixture and are not shipped. Never obtain them by importing an existing
installation's database. On dates after the scheduled events, they appear as Past;
use the UI to create a separate future fictional gathering for participation tests.

## Optional disposable file workflow

This optional workflow is independent of the reviewer Compose volume. It requires
Python 3.12 with the dependencies and IANA timezone data from the [test setup](../README.md#complete-tests).
Do not point it at an existing installation or reuse any real database copy.
From the checkout root, create an entirely new temporary directory and initialize
only its explicitly named local file:

```sh
umask 077
reviewer_dir="$(mktemp -d -t cg-review-seed.XXXXXXXX)"
DATABASE_PATH="$reviewer_dir/reviewer.db" python -c 'from app.main import init_db; init_db()'
```

Initialization runs application schema setup on that disposable file only. No
service is started and no environment `.env` is loaded. The following creates a
separate SQLite online snapshot, refuses to overwrite a prior backup, checks both
files read-only for integrity and foreign keys, and prints only the backup hash:

```sh
python - "$reviewer_dir" <<'PYTHON'
from pathlib import Path
import hashlib
import sqlite3
import sys
from app.database_tools import snapshot
from app.scheduling import check_integrity
folder = Path(sys.argv[1]).resolve()
source = folder / 'reviewer.db'
backup = folder / 'verified-before-seed.db'
if not source.is_file() or backup.exists():
    raise SystemExit('Expected fresh reviewer source and unused backup path')
snapshot(source, backup)
for path in (source, backup):
    with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as db:
        check_integrity(db)
print(hashlib.sha256(backup.read_bytes()).hexdigest())
PYTHON
python -m app.seed_demo --database "$reviewer_dir/reviewer.db" > "$reviewer_dir/plan.json"
```

Review the entire plan locally: target path, proposed content, before/after counts,
manifest hash and `database_fingerprint`. A dry-run makes no metadata table or other
writes. Its proposed IDs are provisional. Reports contain full content; do not
use this workflow on private data or publish local reports. After reviewing, obtain
the independently verified hash above and the fingerprint from that exact plan:

```sh
read -r -p 'Reviewed backup SHA-256: ' reviewed_backup_sha
read -r -p 'Reviewed database_fingerprint: ' reviewed_fingerprint
python -m app.seed_demo --database "$reviewer_dir/reviewer.db" \
  --apply --confirm-local-demo \
  --backup "$reviewer_dir/verified-before-seed.db" \
  --backup-sha256 "$reviewed_backup_sha" \
  --expect-database-fingerprint "$reviewed_fingerprint"
python -m app.seed_demo --database "$reviewer_dir/reviewer.db"
```

Only the explicit apply writes to the new disposable database. The post-apply
dry-run should propose zero additions. For another write apply, first create and
verify a **new matching backup** with a new filename and review a new dry-run;
the pre-seed backup is stale after the first apply. Changed host content/definitions
cause refusal, not automatic repair. The local-demo flag is an operator assertion,
not automatic production detection.

To inspect this seeded file through the app, use a separate native process on an
unused loopback port, with newly generated credentials; never attach it to an
existing service. The basic [reviewer guide](REVIEWER_GUIDE.md) is simpler and does
not require seeding. Stop only your own disposable process after reviewing.
Dispose of this recorded temporary directory yourself when no longer needed;
there is no blanket filesystem deletion or installation reset command here.
For reviewer Compose-volume cleanup, follow the explicitly scoped destructive step
in [the reviewer guide](REVIEWER_GUIDE.md#stop-resume-or-deliberately-reset-this-reviewer-instance).

## Existing installations are separate

Do not seed, reset or migrate an existing installation while following reviewer
instructions. Backup/restore wrappers target operational Compose resources and
must not be substituted for the disposable-file steps. See [operator notes](OPERATIONS.md).
Any future existing-local-demo apply needs explicit operator review, a separate
fresh verified backup/hash, exact target/backup equality and a reviewed fingerprint.
Production seeding is outside this workflow.

Run the complete mocked suites using [the README commands](../README.md#complete-tests).

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

## Historical development evidence

Earlier development rehearsals tested guarded apply, preservation, rollback and
idempotency against disposable snapshots. A separately approved developer-local
apply later produced seven gatherings and 94 questions while preserving existing
records. That is historical context, not an instruction to reproduce or distribute
the developer database. Local database snapshots, receipts and backup identifiers
are deliberately omitted from this reviewer guide. Automated tests create their
own fictional databases and exercise seeding without requiring those artifacts.
