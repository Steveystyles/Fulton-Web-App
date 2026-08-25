# Production Deployment

This application is designed to run as a Docker container behind an
operator-controlled Traefik proxy. Production uses the image built, scanned,
signed, and published by CI. Deployments select that image by full registry
digest and are performed by `deploy/homeserver-update.sh`.

> This is an operator runbook, not a deployment record. Never infer live state
> from this file; verify the exact running digest and revision before rollout.

## Release invariants

A production rollout is allowed only when all of these conditions are true:

- The reviewed commit is merged to `main`, is identified by its full
  40-character SHA, and its build, secret-scan, and Python SAST jobs pass.
- CI publishes `ghcr.io/steveystyles/fulton-web-app@sha256:<digest>` and the
  digest is copied from the CI release evidence. A tag alone is not a release
  identifier.
- The deployment host can read the GHCR package. The package must either be
  public or the host must be authenticated with a dedicated account/token that
  has only the required `read:packages` access.
- Cosign is installed through a managed, verified installation method.
- The exact digest verifies against the repository's `build.yml` workflow on
  `main` and GitHub's OIDC issuer.
- The source checkout is clean, has the canonical Git origin, and its `HEAD`
  equals the selected image's OCI revision label.
- The application environment and SQLite data are private, writable by the
  service operator, and backed up before the container changes.

These invariants also apply to the first production deployment. There is no
unsigned image, mutable-tag, or local-build exception for initial rollout.

## 1. Host prerequisites and layout

Install Docker Engine with the Compose plugin, Git, Python 3, `flock`, and
[Cosign](https://docs.sigstore.dev/cosign/system_config/installation/). Keep
them current through the host's normal package/update process.

The updater resolves Cosign from the deployment user's `~/.local/bin` and the
two standard system locations without relying on `PATH`, and rejects symlinks.
For manual Cosign commands in SSH or scheduler shells, make the user-local
directory explicit because those shells do not reliably load the user's profile:

```bash
env PATH="$HOME/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" \
  cosign version
```

The following paths are neutral examples, not a description of any live host.
Choose private paths appropriate to the target system and use them consistently:

```bash
FULTONS_DEPLOY_ROOT=/srv/fultons

sudo install -d -m 0750 -o "$USER" -g "$USER" \
  "$FULTONS_DEPLOY_ROOT/source" \
  "$FULTONS_DEPLOY_ROOT/state" \
  "$FULTONS_DEPLOY_ROOT/deploy" \
  "$FULTONS_DEPLOY_ROOT/backups"

git clone https://github.com/Steveystyles/Fulton-Web-App.git \
  "$FULTONS_DEPLOY_ROOT/source"
```

For a private repository, the source checkout may instead use the exact
canonical SSH origin `git@github.com:Steveystyles/Fulton-Web-App.git` with a
dedicated read-only deploy key. Host aliases and alternate repository URLs are
rejected by the updater.

The updater deliberately refuses to clone a repository during deployment.
Provision the canonical checkout first, and never store secrets in it.

The current image runs `appuser` as numeric UID `1000`. Before startup, make
the selected data directory writable by that identity and readable by the
operator's backup process, using a dedicated group or ACL when host UIDs differ.
Do not make application state world-writable.

## 2. Private application environment

Copy `.env.example` to a private file outside the checkout, edit it without
printing secrets, and restrict its mode:

```bash
FULTONS_DEPLOY_ROOT=/srv/fultons
cp "$FULTONS_DEPLOY_ROOT/source/.env.example" \
  "$FULTONS_DEPLOY_ROOT/state/app.env"
chmod 600 "$FULTONS_DEPLOY_ROOT/state/app.env"
```

The application reads the process environment directly; it does not load
`.env` or `.env.local` itself. The container receives this file through
Compose's `env_file` setting.

For an established production database, keep at least these fail-closed
settings:

```env
FULTONS_COOKIE_SECURE=1
FULTONS_SEED_DEMO_USERS=0
FULTONS_ALLOWED_ORIGINS=https://fultons-quiz.co.uk,https://www.fultons-quiz.co.uk
FULTONS_ALLOWED_HOSTS=fultons-quiz.co.uk,www.fultons-quiz.co.uk
FULTONS_EXPECT_DATA_DIR=/app/data
FULTONS_REQUIRE_EXISTING_DB=1
FULTONS_MIN_DB_USERS=1
QUIZ_EVIDENCE_REQUIRED=1
```

Generate independent random values for `FULTONS_NEWS_MONITOR_KEY` and
`INTERNAL_QUIZ_TOKEN`, for example with `openssl rand -base64 32`. Provider
credentials, bootstrap credentials, and internal tokens must remain blank in
Git and must never be exposed to browser code.

Set both `FULTONS_BOOTSTRAP_ADMIN_*` variables only while initializing a new,
empty database. Remove them immediately after the admin exists.

## 3. Private Compose configuration

Create `/srv/fultons/deploy/.env` (or the equivalent chosen private path) with
mode `0600`. Its content should use the operator's selected paths and the exact
CI digest:

```env
FULTONS_SRC_DIR=/srv/fultons/source
FULTONS_ENV_FILE=/srv/fultons/state/app.env
FULTONS_HOST_DATA_DIR=/srv/fultons/state
FULTONS_IMAGE=ghcr.io/steveystyles/fulton-web-app@sha256:<64-hex-digest>

# Uncomment both only after the executable performs encrypted upload and
# independent remote verification as described in the backup section.
# FULTONS_OFFHOST_BACKUP_REQUIRED=1
# FULTONS_OFFHOST_BACKUP_COMMAND=/srv/fultons/bin/copy-backup-encrypted
```

Do not commit this file. Keep the deployment directory private:

```bash
chmod 700 /srv/fultons/deploy
chmod 600 /srv/fultons/deploy/.env
```

When using a different layout, pass the deployment and backup roots explicitly
for every updater invocation:

```bash
export COMPOSE_DIR=/srv/fultons/deploy
export BACKUP_ROOT=/srv/fultons/backups
```

## 4. GHCR access and signed-digest preflight

If the GHCR package is public, the host can pull without registry credentials.
If it is private, authenticate before any deployment. Use a dedicated service
account where possible and enter the token without placing it in shell history:

```bash
read -r -s -p 'GHCR read token: ' GHCR_READ_TOKEN
printf '\n'
printf '%s' "$GHCR_READ_TOKEN" | \
  docker login ghcr.io --username '<service-account>' --password-stdin
unset GHCR_READ_TOKEN
```

Protect the Docker credential store according to the host's security policy.
Package visibility or working `docker login` is a release prerequisite, not a
step to discover during an outage.

Resolve `APP_COMMIT` and `IMAGE_REF` from the reviewed `main` workflow output,
then verify the exact digest before first use:

```bash
APP_COMMIT=<full-40-character-main-commit-sha>
IMAGE_REF='ghcr.io/steveystyles/fulton-web-app@sha256:<64-hex-digest>'

cosign verify \
  --certificate-identity-regexp '^https://github\.com/Steveystyles/Fulton-Web-App/\.github/workflows/build\.yml@refs/heads/main$' \
  --certificate-oidc-issuer 'https://token.actions.githubusercontent.com' \
  "$IMAGE_REF"

docker pull "$IMAGE_REF"
docker image inspect "$IMAGE_REF" \
  --format '{{ index .Config.Labels "org.opencontainers.image.source" }} {{ index .Config.Labels "org.opencontainers.image.revision" }}'
```

The source label must be the canonical Git repository URL and the revision must
equal `APP_COMMIT`. The updater repeats these checks and fails closed.

## 5. Verify the reverse-proxy trust boundary

`deploy/compose.yaml` enables forwarded-client-IP handling and pins a CIDR for
the external `proxy` Docker network. That value is an environment-specific
assumption and must be verified before release.

The current request model assumes:

- Traefik is the app container's only non-loopback HTTP peer.
- The app port is exposed to Docker networks but is not published directly to
  untrusted hosts.
- Traefik owns and sanitizes `X-Forwarded-For`/`X-Real-IP`.
- The trusted CIDR contains only direct proxy peers, not browser/client ranges.
- There is a single trusted proxy hop. A multi-proxy chain requires a fresh
  review of client-IP selection before deployment.

Inspect the target network rather than copying a CIDR from another host:

```bash
docker network inspect proxy
```

If the reviewed Compose CIDR does not exactly match the target proxy network,
correct `deploy/compose.yaml` in a reviewed commit and produce a new signed
digest. Do not compensate with a broad trusted range. A range that is too
narrow groups users under the proxy address for throttling/audit purposes; a
range that is too broad trusts unapproved peers.

## 6. Initial production rollout

### Existing production data

For an existing SQLite database, update the canonical checkout to the reviewed
`main` commit without local changes, then use the updater. It verifies the
signature/digest, checks the live database, creates a verified backup, applies
the reviewed Compose file, and health-checks the result with rollback support:

```bash
FULTONS_DEPLOY_ROOT=/srv/fultons
git -C "$FULTONS_DEPLOY_ROOT/source" switch main
git -C "$FULTONS_DEPLOY_ROOT/source" pull --ff-only
APP_COMMIT="$(git -C "$FULTONS_DEPLOY_ROOT/source" rev-parse HEAD)"
IMAGE_REF='ghcr.io/steveystyles/fulton-web-app@sha256:<64-hex-digest>'

COMPOSE_DIR="$FULTONS_DEPLOY_ROOT/deploy" \
BACKUP_ROOT="$FULTONS_DEPLOY_ROOT/backups" \
FULTONS_DEPLOY_IMAGE="$IMAGE_REF" \
  bash "$FULTONS_DEPLOY_ROOT/source/deploy/homeserver-update.sh" "$APP_COMMIT"
```

The script requires the selected commit to be reachable from `origin/main`.
The unreachable-commit and local-build switches exist for deliberately reviewed
exceptions/development only; they are not normal production paths.

### Brand-new empty data directory

For a genuinely new instance, put these one-time values in the private app
environment (mode `0600`) while the data directory is otherwise empty:

```env
FULTONS_REQUIRE_EXISTING_DB=0
FULTONS_MIN_DB_USERS=0
FULTONS_SEED_DEMO_USERS=0
FULTONS_BOOTSTRAP_ADMIN_USERNAME=<initial-admin-name>
FULTONS_BOOTSTRAP_ADMIN_PASSWORD=<strong-one-time-password>
```

Then run the normal signed-digest updater with both explicit bootstrap guards.
The reviewed commit must exactly equal the commit passed to the updater:

```bash
FULTONS_DEPLOY_ROOT=/srv/fultons
APP_COMMIT="$(git -C "$FULTONS_DEPLOY_ROOT/source" rev-parse HEAD)"
IMAGE_REF='ghcr.io/steveystyles/fulton-web-app@sha256:<64-hex-digest>'

FULTONS_ALLOW_DATABASE_BOOTSTRAP=1 \
FULTONS_REVIEWED_COMMIT="$APP_COMMIT" \
FULTONS_DEPLOY_IMAGE="$IMAGE_REF" \
COMPOSE_DIR="$FULTONS_DEPLOY_ROOT/deploy" \
BACKUP_ROOT="$FULTONS_DEPLOY_ROOT/backups" \
  bash "$FULTONS_DEPLOY_ROOT/source/deploy/homeserver-update.sh" "$APP_COMMIT"
```

The updater verifies the signature, image labels, and reviewed commit; creates
the database in a read-only, no-network container; requires at least one admin;
atomically promotes the database; clears both bootstrap credentials; enables
the normal database guards; creates and verifies the first backup; then starts
and health-checks the service. The bootstrap flags are one-shot shell variables,
not persistent Compose settings. Never bypass this path with a direct
`docker run` or a mutable image tag.

## 7. Updates, backup gate, and rollback

Every normal update takes a full commit SHA and a canonical digest:

```bash
COMPOSE_DIR=/srv/fultons/deploy \
BACKUP_ROOT=/srv/fultons/backups \
FULTONS_DEPLOY_IMAGE='ghcr.io/steveystyles/fulton-web-app@sha256:<64-hex-digest>' \
  bash /srv/fultons/source/deploy/homeserver-update.sh \
  <full-40-character-main-commit-sha>
```

Before rollout, the updater uses SQLite's online-backup API, runs
`PRAGMA quick_check`, archives other durable files separately, and verifies a
private manifest and checksums. Environment files, SQLite sidecars, logs,
caches, QA output, and temporary churn are excluded from the archive.

For a required encrypted off-host copy, configure:

```env
FULTONS_OFFHOST_BACKUP_REQUIRED=1
FULTONS_OFFHOST_BACKUP_COMMAND=/srv/fultons/bin/copy-backup-encrypted
```

The command is invoked directly with the verified backup directory as its only
argument. After encrypted upload and independent remote verification, it must
write `offhost-copy.verified` containing exactly the lowercase SHA-256 digest
of `manifest.json`. Missing or mismatched proof stops the deployment before
Compose changes anything.

Review retention in dry-run mode before applying it:

```bash
python3 deploy/backup-retention.py --backup-root /srv/fultons/backups
python3 deploy/backup-retention.py --backup-root /srv/fultons/backups --apply
```

Retention defaults to daily, monthly, and annual restore points. Malformed or
unverifiable backup directories are protected rather than deleted. Schedule a
real restore drill; a copied file is not a proven backup until it can be
restored.

The updater records the prior healthy image and Compose definition. A rollout,
image/revision, or health failure triggers rollback and verifies the restored
revision and health. If rollback verification fails, stop and perform the
documented manual recovery; do not delete the database or data directory.

## 8. Health and diagnostics

```bash
docker compose --env-file /srv/fultons/deploy/.env \
  -f /srv/fultons/deploy/compose.yaml ps
docker compose --env-file /srv/fultons/deploy/.env \
  -f /srv/fultons/deploy/compose.yaml logs --tail=100 quiz-app
docker exec fultons-quiz python -c \
  "import json,urllib.request; print(json.dumps(json.load(urllib.request.urlopen('http://127.0.0.1:3000/api/health', timeout=3)), indent=2))"
```

The public health response is intentionally minimal by default and deep storage
checks are cached. Enable `FULTONS_HEALTH_DETAIL=1` only when operationally
appropriate; detailed health output can disclose internal state.

The container healthcheck calls `/api/health` internally. Startup also verifies
the mounted data path, SQLite writability/integrity, database presence, and the
minimum user count when the corresponding guards are enabled.

If health reports a storage error, inspect the mount and run a read-only SQLite
check. Preserve a bad database for forensics and restore a verified backup; do
not let an incorrect mount silently create a replacement database.

## 9. Daily content generation

The quiz and map are player-facing routes. Quiz questions use opaque public
question/choice IDs, are graded by the server against an immutable published
version, and reveal adjudication only after submission. Map clues and scoring
progression are also server-controlled. Do not expose generation tokens or
internal review payloads to clients.

The scheduler normally prepares future content. Production keeps evidence and
critic gates enabled; incomplete or failed generation remains unpublished and
is retried according to the configured transient/backoff intervals.

Administrators can review quiz generation state through authenticated routes:

```http
GET /api/admin/daily-quiz-status?date=YYYY-MM-DD
GET /api/admin/question-attempts?date=YYYY-MM-DD
```

An operator can trigger an internal generation request from loopback only when
the private token is available to the process:

```bash
curl --fail-with-body -X POST http://127.0.0.1:3000/internal/generate-daily-quiz \
  -H "Authorization: Bearer ${INTERNAL_QUIZ_TOKEN}" \
  -H 'Content-Type: application/json' \
  -d '{"date":"YYYY-MM-DD","force":false}'
```

Force regeneration is subject to server-side safety checks and must not replace
a published quiz after it has first been served to a player, or
played/adjudicated content. Use the admin review workflow rather than editing
SQLite directly.

The former facts/history feature is retired. Its UI and runtime provider logic
are removed; the old API routes return `410 Gone` for one compatibility release.
After that window, review access logs before removing compatibility routes or
legacy tables through an explicit, backed-up migration.

## 10. Operational security checklist

Before every production rollout:

- Review the exact commit and diff; require clean CI on that commit.
- Confirm GHCR public visibility or authenticated read access.
- Verify the Cosign identity, issuer, digest, OCI source, and OCI revision.
- Confirm the proxy network/CIDR assumption and that the app port is not
  directly reachable by untrusted clients.
- Check permissions on the app env, SQLite data, deploy state, backups, and
  Docker credentials.
- Rotate bootstrap/internal/provider credentials if their confidentiality is
  uncertain; handle any host-history cleanup privately.
- Create and verify the local backup and, when required, the encrypted off-host
  proof before rollout.
- Confirm sufficient storage, a clean checkout, and a healthy current service.
- After deployment, verify container health, the running digest/revision, login,
  quiz/map submission, and rollback readiness.

The container runs as a non-root user with a read-only root filesystem, dropped
capabilities, `no-new-privileges`, a PID limit, and only `/app/data` writable.
Those controls reduce impact but do not replace host patching, Docker socket
protection, least-privilege file modes, credential rotation, or restore tests.
