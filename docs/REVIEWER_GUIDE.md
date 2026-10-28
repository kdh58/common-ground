# Disposable reviewer demonstration

Follow this guide only in a **new checkout on a reviewer-controlled machine**.
Do not reuse an installation's directory, credentials, Compose project or database.
Use fictional content. This path requires neither private Ollama hardware nor
production secrets. It is separate from [existing-installation operations](OPERATIONS.md).

## Generate reviewer-only credentials

From the fresh checkout root, use a dedicated Bash shell. These commands refuse to overwrite a
reviewer environment file. They never read or copy an existing `.env`:

```sh
umask 077
(
  set -e
  set -o noclobber
  {
    printf 'ADMIN_PASSWORD=%s\n' "$(openssl rand -hex 24)"
    printf 'SESSION_SECRET=%s\n' "$(openssl rand -hex 32)"
    printf 'OLLAMA_BASE_URL=http://127.0.0.1:1\n'
  } > .env.reviewer
)
chmod 600 .env.reviewer
reviewer_project="cg-review-$(openssl rand -hex 4)"
```

Continue only if credential generation succeeded. The generated password is for
this review only: read it locally from `.env.reviewer` when signing in, and do not
paste its contents into reports, screenshots or commits. The file is excluded by
both Git and Docker ignore rules. Do not replace a deployment `.env`.

Keep `reviewer_project` in the same shell throughout this session; record its
nonsecret value privately if resuming later. A new random project name gets a new
project-scoped volume. Do not substitute an existing installation's project name.

## Validate and start

Compose shell variables take precedence over an environment file. In this dedicated
reviewer shell, clear inherited application/Compose overrides so another session's
credentials or model endpoint cannot silently override the generated file:

```sh
unset ADMIN_PASSWORD SESSION_SECRET OLLAMA_BASE_URL OLLAMA_MODEL
unset DEMO_CONTACT_NAME DEMO_CONTACT_EMAIL DEMO_CONTACT_PHONE REVIEW_PORT
unset COMPOSE_FILE COMPOSE_PROFILES COMPOSE_PROJECT_NAME
```

Use only a local Docker Engine/Desktop daemon on this reviewer machine. The
following refuses environment-selected or SSH/TCP remote contexts without printing
any endpoint value. A local socket is still an operator-controlled resource; this
check does not establish that every local volume is disposable:

```sh
if [ -n "${DOCKER_HOST:-}" ] || [ -n "${DOCKER_CONTEXT:-}" ]; then
  printf 'Stop: select a verified local Docker context in a clean reviewer shell.\n' >&2
  exit 1
fi
reviewer_docker_endpoint="$(docker context inspect --format '{{.Endpoints.docker.Host}}')"
case "$reviewer_docker_endpoint" in
  unix://*|npipe://*) ;;
  *) printf 'Stop: a local Docker socket is required for this review.\n' >&2; exit 1 ;;
esac
```

Then validate and start only the standalone example:

```sh
docker compose --project-name "$reviewer_project" --env-file .env.reviewer \
  -f examples/compose.reviewer.yaml config --quiet
docker compose --project-name "$reviewer_project" --env-file .env.reviewer \
  -f examples/compose.reviewer.yaml up --build -d
```

Open <http://localhost:18080> and <http://localhost:18080/host>. If port 18080 is
already occupied, choose another unused port by adding `REVIEW_PORT=18081` to
`.env.reviewer` before starting, then use that port in the URLs. Do not stop an
unrelated service to free a port. Credentials are not printed by configuration
validation; avoid plain `docker compose config`, which can print resolved secrets.

This standalone configuration builds from the parent checkout, binds to loopback,
uses `/data/reviewer.db` in its own `reviewer_data` volume and has no bind mount to
an existing database. It does not inherit `compose.yaml`. Stop if you see external
volumes, host database mounts or a non-loopback port in a locally modified example.
The default Ollama endpoint is an unavailable port inside the container; it cannot
reach the developer's private inference hardware.

Follow the [README walkthrough](../README.md#reviewer-walkthrough-without-ai-hardware).
The fresh instance contains one fictional Library gathering and no submissions.
Create a future gathering in the host interface if you want to demonstrate structured
schedules. Adding optional seed data is a separate, guarded workflow described in
[DEMO_SEEDING.md](DEMO_SEEDING.md); it is not necessary for the core review.

Successful live AI generation, its saved run reports and semantic output quality
are not demonstrated by this offline path. Automated tests exercise analysis,
reports and recovery using synthetic model responses. Do not present test fixtures
as live AI output or real community contributions.

## Stop, resume, or deliberately reset this reviewer instance

Stop without deleting the review database:

```sh
docker compose --project-name "$reviewer_project" --env-file .env.reviewer \
  -f examples/compose.reviewer.yaml down
```

Use the same project name and `up -d` to resume. A new random name intentionally
starts another empty instance; it does not reset the old one.

Only if you want to permanently discard **this disposable review**, first confirm
the recorded project name and inspect its containers/volume labels:

```sh
docker compose --project-name "$reviewer_project" --env-file .env.reviewer \
  -f examples/compose.reviewer.yaml ps --all
docker volume ls --filter "label=com.docker.compose.project=$reviewer_project"
```

After confirming those resources belong only to this review, the following is the
**destructive reviewer-only reset**. Do not run it with an installation project name:

```sh
case "$reviewer_project" in
  cg-review-????????) ;;
  *) printf 'Refusing: expected the recorded reviewer project name.\n' >&2; exit 1 ;;
esac
docker compose --project-name "$reviewer_project" --env-file .env.reviewer \
  -f examples/compose.reviewer.yaml down --volumes
```

The name check is only a guard against mistakes, not proof of provenance. This
removes that project's review database. Never use global prune, wildcard volume
removal or an operational Compose file to clean up a review. Do not copy the review
database over any real installation. Handle local credential-file disposal yourself
when the review is finished; no cleanup command here targets deployment files.
