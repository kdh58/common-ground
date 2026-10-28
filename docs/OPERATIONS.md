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
