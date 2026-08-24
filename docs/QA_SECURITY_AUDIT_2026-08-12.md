# QA and Security Remediation Status

Original audit date: 2026-08-12

Status refreshed: 2026-08-24

## Current verdict

The earlier audit identified critical game-integrity, local-operations, data,
authentication, outbound-request, and deployment weaknesses. Those remediations
and their targeted regression coverage have since reached `main`; the old P0
descriptions are therefore not an accurate description of the current source.

This is not a production closure statement:

- A signed production digest and its running revision were verified during the
  follow-up, but this document deliberately does not act as a live deployment
  inventory. Re-verify the runtime before every rollout.
- The SAST gate described below is a new review-branch change. It remains
  unreleased until its PR passes CI and is approved and merged.
- No secret values, personal usernames, workstation paths, live host paths, or
  exploit reproduction details are intentionally recorded here. Credential and
  host-history follow-up belongs in a private operator record.

## Scope and method

The review covered the repository root, tracked and untracked source,
application/server structure, Git status, linked worktrees and retained stashes,
frontend and backend behavior, SQLite lifecycle, authentication/session flows,
outbound HTTP, local operations, container configuration, CI provenance,
backup/rollback logic, and documented deployment procedure.

The review used source inspection, Git inventory, focused regression tests,
frontend compilation, dependency review, static checks, and read-only
operational inspection. Destructive host cleanup and production rollout were
deliberately excluded.

## Remediation status

| Area | Current local state | Release evidence still required |
| --- | --- | --- |
| Daily quiz integrity | Public payloads use opaque question/choice IDs, answers stay server-side until submission, grading is server-authoritative, submissions bind to an immutable quiz version, and public play is limited to the active round. | Browser submission smoke test, CI repeat of the locally passing suite, and signed production rollout. |
| Daily map integrity | Unrevealed clues/answer state remain on the server, map choices use server-issued selection tokens, reveal progress and scoring are server-controlled, and force regeneration is blocked after player activity. | Multi-user browser smoke test, CI repeat of the locally passing suite, and signed production rollout. |
| Local operations | Mutating ops functionality is separated from the player server into a loopback-only service protected by a per-launch random header token. Inputs and external probes are constrained and work is bounded. | Confirm launcher permissions and loopback-only binding on the operator workstation. Do not proxy the service publicly. |
| Sessions and login | Session tokens are stored as digests with compatibility migration, successful authentication rotates sessions, password changes revoke other sessions, unknown-user verification follows the password-cost path, login buckets are bounded/expiring, and concurrent password verifications are capped by `FULTONS_LOGIN_MAX_CONCURRENT_VERIFICATIONS` (default `4`). | Validate the production proxy trust boundary so rate limiting and audit records use the intended client address. |
| HTTP and browser security | Host/origin checks, CSRF protection, CSP/security headers, content-length validation, request-size limits, read timeouts, and bounded request workers are present. | Re-run browser/API negative tests through the real reverse proxy. |
| Outbound HTTP | User-influenced public fetches validate scheme/port/destination, pin a validated public address, revalidate redirects, strip credentials across origin changes, reject compressed bodies where required, and cap response size. Fixed providers also use endpoint-specific timeouts/bounds. | Exercise provider failures and redirects in CI without real credentials; review any future outbound integration before adding it. |
| SQLite integrity | Contended create/guess paths use atomic conflict handling and transactions; mutation responses are committed before success is sent; profile input is validated before writes; submitted scores are versioned/immutable; WAL and busy-timeout handling reduce contention. | Full concurrency regression suite and a backup/restore rehearsal on production-like storage. |
| Content regeneration | Quiz and map replacements are staged and validated before activation; a published quiz is locked before its first playable response, played/adjudicated rounds cannot be destructively replaced, and boolean inputs are parsed strictly. | Operator review of the force/regeneration workflow using unpublished test dates. |
| Retention and bounded state | Sessions, login buckets, news, streams, audits, health checks, Wordle definitions, reverse-geocode responses/cache/concurrency, and quiz diagnostics have explicit bounds. Quiz diagnostic defaults are `QUIZ_DIAGNOSTIC_RETENTION_DAYS=180` and `QUIZ_DIAGNOSTIC_MAX_ROWS=50000`. | Confirm production values, monitor pruning, and size thresholds after rollout. |
| Map startup and performance | Starter rows no longer overwrite reviewed data during recurring initialization, geocoder activity is cached/rate-limited/concurrency-limited, and map snapping uses an indexed geographic prefilter before distance calculation. | Profile representative production data and monitor upstream geocoder policy/rate behavior. |
| Auditability | Durable audit events cover authentication and sensitive administrative/content actions, with configurable age and row retention. | Define who reviews/export alerts, protect logs from ordinary users, and test retention. |
| Retired facts/history feature | The unreachable UI and runtime provider/cache code are removed. Legacy API paths return `410 Gone` for a compatibility release; they are not retained as an active backend feature. | Review access logs before removing compatibility routes/tables in a separate backed-up migration. |
| Supply chain and deployment | Actions are commit-pinned; CI builds/tests/audits/scans, gates medium-or-higher Python SAST findings against an exact-site reviewed allowlist, produces SBOM evidence, publishes a full-SHA GHCR image, scans the exact digest, and signs it with GitHub OIDC. The updater verifies signature, digest, OCI source/revision, database backup, optional off-host proof, health, and rollback. | Reduce the reviewed SAST allowlist over time, add equivalent TypeScript semantic analysis when a deterministic supported gate is available, merge to `main`, pass required CI, resolve GHCR access, and deploy only the resulting signed digest. |
| Frontend and repository cleanup | Large routes are lazy-loaded; verified dead/duplicated facts UI, legacy production wrapper, duplicate assets, and reproducible generated artifacts were removed or consolidated. The final local bundle passes. | Human review and CI repeat before merge. |
| Linked Remotion worktree | The promo branch is pushed as a render-only Remotion project: inherited server, application UI, deploy code, Python tests, word lists, and unused web dependencies/assets are removed. Its isolated CI checks pass. | Keep it standalone or move it to a separate repository; do not merge its deliberate application deletions into `main`. |

## Release blockers

These are the remaining operational and governance gates:

1. Review the SAST change through a PR and require its build, secret, and SAST
   jobs before merging. The private repository plan does not currently enforce
   branch protection, so this remains a human governance control.
2. Add equivalent deterministic TypeScript semantic analysis when a supported
   fail-closed option is available; Bandit covers Python only.
3. Keep GHCR read access, Cosign, and the exact signed-digest/OCI-label checks
   working on the deployment host; do not substitute a tag or local build.
4. Re-verify the trusted-proxy CIDR against the actual Docker `proxy` network. The
   current logic assumes one operator-controlled Traefik hop, sanitized
   forwarding headers, and no direct untrusted access to the app container. If
   that topology differs, review the client-IP logic and Compose configuration
   before release.
5. Verify SQLite integrity, local backup, retention dry run, permissions, and
   the encrypted off-host proof when that gate is required. Perform a real
   restore drill before relying on the backup design.
6. Complete credential rotation and host-history sanitation as a private
   operator task wherever confidentiality cannot be proved. Do not copy secret
   values or sensitive command history into issues, commits, or this report.
7. Run every deployment and post-release smoke check deliberately; a previously
   verified runtime is not evidence for the next release.

See the [production deployment runbook](DEPLOYMENT.md) for the exact gates.

## Explicitly unresolved private decisions

The following items were not deleted because ownership and historical value
cannot be inferred safely:

- A retained Git stash records older local rollback work. Its contents may be
  private or still useful. The owner must inspect it before applying, exporting,
  or dropping it.
- Local runtime data, dotenv files, and training/review outputs were not treated
  as redundant source. Archive/delete decisions require a data owner, retention
  policy, and a verified backup. Generated caches/build output were removed;
  committed promo delivery media was retained intentionally.
- Remote backup pruning, retired container removal, host patch/reboot work, and
  credential-history cleanup remain private operational tasks. This repository
  review did not perform them.

The separately reviewed promo worktree and retained stash are not application
release inputs. The stash remains an explicit private cleanup/accountability
decision.

## Retained compatibility and migration items

- `wordle_game.py` remains as a documented compatibility import for older
  scripts/tests; the canonical implementation is under `games/wordle/`.
- Retired facts/history API paths return `410 Gone` for a compatibility window.
  Existing legacy tables may remain inert until an explicit backed-up migration.
- Runtime databases, caches, and generated training artifacts are not deleted by
  repository cleanup merely because they are untracked.
- Development-only deployment overrides remain available for isolated local
  work, but they are not production release paths.

## Residual backlog

The following work is important but is not classified as a currently known P0
in the remediated local tree:

- Add an explicit multi-proxy client-IP strategy if the single-Traefik topology
  ever changes.
- Connect durable audit events to an operator review/alerting process and test
  tamper resistance, export, and retention behavior.
- Monitor the new cache/table retention jobs on realistic data and tune only
  from measured load.
- Run regular restore drills and independently verify encrypted off-host copies.
- Remove the `410 Gone` compatibility routes and inert legacy tables only after
  the agreed observation window.
- Continue decomposing large server/game modules when doing so reduces change
  risk; avoid broad refactors immediately before release.
- Re-run dependency, SAST, secret, image, and SBOM gates on every release rather
  than treating this point-in-time audit as permanent assurance.

## SAST baseline policy

Bandit 1.9.4 scans production Python on every CI run. Image publication depends
on that job. CI accepts only Bandit's documented finding/no-finding statuses,
requires a non-empty error-free JSON report, and then runs the repository's
dependency-free comparator. A scanner error, malformed input, or unreviewed
medium-or-higher, medium-confidence finding stops the release.

The canonical allowlist contains 41 exact sites: 23 parameterized/fixed-fragment
SQL heuristics (`B608`), 11 bounded fixed or operator-configured URL calls
(`B310`), six bounded XML parse sites (`B314`), and one forbidden-root denylist
literal (`B108`). All 41 are medium severity; 17 are high confidence and 24 are
medium confidence. No high-severity finding is allowed.

Each reviewed identity includes its normalized repository-relative path, rule,
severity/confidence, CWE, issue text, exact line/range/columns, and a SHA-256 of
newline-normalized code context. Path separators are normalized across Windows
and Linux without duplicating records. Resolved sites may disappear. New,
shifted, code-changed, or duplicate current occurrences fail, as do missing,
malformed, or duplicate allowlist records. CI does not use Bandit's permissive
`--baseline` matching.

The allowlist also records the canonical production Python file set. Every
required path must remain present in Bandit's normalized per-file metrics;
additional scanned files are allowed. A regression test keeps that manifest in
sync with the production Python tree, so an empty report or broadened scanner
exclusion cannot be mistaken for wholesale remediation.

Do not add broad test skips. An allowlist change requires an exact Bandit 1.9.4
scan of the reviewed source, site-by-site source review, and an explicit
rationale. Prefer removing entries as XML handling and outbound HTTP are further
consolidated. Bandit covers Python only. TypeScript still relies on type checking,
tests, dependency audit, CSP/runtime controls, and manual review until an
equivalently deterministic semantic gate is adopted.

## Verification policy

The full local server suite, focused security/quiz/map/deployment regressions,
frontend build, dependency audit, and Remotion checks passed during remediation.
No fixed test count is recorded here because the suite evolves and stale counts
misrepresent later commits. Results from the exact reviewed release SHA are
authoritative.

Before merge/release, run at minimum:

```bash
npm ci
npm audit --audit-level=high
npm run build
npm run test:server
report="$(mktemp)"
set +e
python -m bandit -r . -c bandit.yaml --severity-level medium \
  --confidence-level medium --format json --output "$report"
bandit_status=$?
set -e
if [ "$bandit_status" -ne 0 ] && [ "$bandit_status" -ne 1 ]; then
  exit "$bandit_status"
fi
test -s "$report"
python tools/check_bandit_baseline.py \
  --baseline bandit-baseline.json --current "$report"
rm -f "$report"
git diff --check
```

CI must additionally complete its fail-closed Python SAST and secret scans,
container vulnerability scan, SBOM generation, exact-digest scan, signing, and signature
verification. On the deployment host, validate `docker compose config`, Cosign,
the running digest/revision, `/api/health`, login/session behavior, quiz/map
submission, backup verification, and rollback readiness.

The [cleanup manifest](APP_CLEANUP_MANIFEST.md) records repository-specific
retention/deletion rationale. Recheck it against the final release diff.

## Security interpretation

This report is a point-in-time engineering assessment, not a guarantee that the
system is vulnerability-free. Local remediation reduces known risk; production
risk changes only after the reviewed commit is built, verified, deployed, and
operated with the documented trust boundaries and recovery controls.
