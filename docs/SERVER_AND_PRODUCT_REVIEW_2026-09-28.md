# Server and product review — 28 September 2026

## Verdict

The machine is not being asked to do too much. At inspection it had a 0.09
one-minute load, 6.8% memory use, no swap use, 40–47% use on active filesystems,
and healthy containers with zero restarts. Public app TTFB from the review PC
was 53–76 ms. Replacing the server or database would not address the current
problems.

The system is asking too much of its *content-generation process*. During the
current 31-date generation window it stored 7,905 quiz attempts to accept 175
questions: a 97.8% rejection/failure rate. The attempt table occupies 91.4 MB,
88% of the 104 MB database. On 28 September the live quiz was still at five of
six questions after 287 failures while the configured Gemini and OpenRouter
free routes were quota-limited. The web app's availability now depends too
directly on unreliable free inference.

The product is also asking two players to sustain four daily activities without
enough evidence that all four earn their place. Wordle is the retention anchor;
the map is not yet one. The best next architecture is to simplify the daily
product, build verified content reserves, put hard cost/retry budgets around AI,
and instrument the player funnel before adding more features.

## Authoritative state inspected

- Live build `1e3e91fcc1ed841c784dde8ba58ecb14eadf8e2b`, matching repository `main`.
- Ubuntu 24.04.5 LTS on an i5-6200U (2 cores/4 threads), 15.5 GiB RAM.
- Root 1 TB SSD plus two active 1 TB ext4 data branches. Mergerfs presents
  2.7 TB with 1.5 TB free.
- Four running containers: Fulton app, Jellyfin, Pi-hole and Traefik. Pi-hole was
  subsequently upgraded to 2026.09.0 and pinned to its tested image digest.
- Fulton uses about 61 MiB RAM; Jellyfin 430 MiB; Pi-hole 37 MiB; Traefik
  117 MiB at the idle sample.
- Fulton SQLite `quick_check` is `ok`; the public and internal health probes pass.
- Daily verified Fulton backups have run successfully since the timer was
  enabled. The current backup series has 28 restore points.
- The user-level `fultons-resilience.timer` is enabled and active. It recovers
  stopped/unhealthy Fulton containers and records power events, but currently
  writes only to the local journal and event log rather than an observed alert
  destination.
- Local build passed, 26 client contracts passed, and 684 server tests passed
  with one platform-specific skip.

## Player evidence

Only two accounts exist, so these are directional signals, not statistically
stable product conclusions. Player identifiers were anonymised during analysis.

| Signal | All recorded | Last 30 days | Last 7 days | Reading |
|---|---:|---:|---:|---|
| Wordle starts | 150 on 111 dates | 29 on 26 dates | 7 on 7 dates | Clear daily habit and strongest surface |
| Wordle outcomes | 103 wins, 10 losses, 37 incomplete | 21 wins, 2 losses, 6 incomplete | 5 wins, 1 loss, 1 incomplete | Healthy challenge; incomplete starts are worth instrumenting |
| Quiz completions | 92 on 59 dates | 20 on 15 dates | 4 on 4 dates | Useful, but substantially behind Wordle |
| Quiz average correct | 1.71 of 3 | 1.40 of 3 | 1.75 of 3 | Recent answer rate is about 47%, so calibration matters |
| Map completed guesses | 6 on 6 dates | 2 on 2 dates | 0 | Not behaving like a daily retention feature |
| Map unfinished progress | — | 4 rows without a final guess | — | Suggests interaction or confidence friction before submission |

Recent adjudicated quiz answers show football easy at 75%, medium at 31%, and
hard at 44% (16 answers per band). Medium performing worse than hard means the
labels are not calibrated even in this small sample. General knowledge has only
four recent adjudicated answers per band: easy 100%, medium 0%, hard 0%. Do not
tune from four answers, but do treat that as a prompt to collect better evidence.

Football has 71 recorded category completions and general knowledge 21. Some of
that difference may be launch timing, but the current two-tab quiz divides a
very small audience. Test one mixed six-question daily quiz instead of presenting
football and general as separate daily obligations.

### Product experiments to run

1. Change the home promise from “four every day” to a **Daily Three**: Wordle,
   one mixed quiz, and the map. Preserve both quiz subjects inside the mixed
   round and score them separately if desired.
2. Run the map two or three featured days per week for four weeks, with a visible
   teaser on the home card. A scarce, dependable event is preferable to an empty
   or ignored daily queue.
3. Record privacy-minimal events for impression, start, first interaction,
   completion, abandon, elapsed bucket and hint count. Add a one-tap
   `Fun / Fair / Too hard / Unclear` response after a round.
4. Set initial success gates before the experiment: at least 60% start-to-finish
   for map, less than 15% “unclear”, and median quiz accuracy targets by stated
   difficulty (for example 70–85% easy, 45–65% medium, 20–45% hard).
5. Do not add more game modes until four weeks of funnel data can explain why a
   player starts, stops or returns.

## Quiz generation redesign

The largest rejection reason in the current window is “correct answer already
appeared recently” (2,870 failures, 37% of all failures). The model is being
asked to rediscover novelty after composing a full question, which is the wrong
order of work.

### Recommended pipeline

1. Maintain an answer/topic ledger. Select an eligible, unused answer and topic
   lane *before* asking a model to compose a question.
2. Generate a seven-day verified reserve, not only today's six slots. General
   knowledge can be produced in weekly batches. Football can keep a smaller
   current-events lane plus an evergreen reserve.
3. Apply cheap checks first: schema, length, duplicate answer, topic cooldown and
   giveaway checks. Retrieve evidence and invoke a critic only after those pass.
4. A persistent per-provider circuit breaker is now implemented for explicit
   daily-quota failures. It pauses only the exhausted provider/model, keeps
   healthy fallbacks available, and resumes Gemini after its documented
   midnight-Pacific reset or OpenRouter after midnight UTC. Ordinary minute-rate
   429s retain the existing short retry behavior.
5. A hard failed-attempt budget across scheduler invocations is now implemented
   with a default ceiling of 180 per quiz-date. Reaching it pauses ordinary
   generation without another provider call; an explicit forced regeneration
   remains available after the underlying issue is corrected. Per-provider call
   budgets and reset-aware circuit state remain follow-up work.
6. Publish from a vetted reserve when providers are unavailable. For two family
   players, a repeated format with trustworthy content is better than a missing
   daily game. Reserve reuse can be prevented by the same answer ledger.
7. Consider a small paid model allowance with a monthly ceiling instead of three
   nominally free routes. Reliability and predictable spend matter more than
   provider count at this scale.

Store compact diagnostics (`reason_code`, model, latency, token count, date and
hash) in SQLite. Keep full rejected provider payloads for 7–14 days in compressed
operator-only files, or sample them. Reduce the default row cap from 50,000 to a
few thousand after exporting training evidence. Once that policy is tested,
prune and run a planned `VACUUM` after a verified backup; do not vacuum the live
database casually.

## Web application and delivery

The live login experience is clean at desktop and 390×844 mobile sizes. It has
clear focus targets, no horizontal overflow and a coherent visual hierarchy.
The public map promo also renders correctly after its media loads. The route
code uses lazy page chunks, and the app/container security baseline is strong.

The main performance omission is HTTP compression. The live hashed core bundle
is 194.2 KB but builds to 64.6 KB gzip; the main CSS is 54.3 KB versus 11.6 KB
gzip. The live response has no `Content-Encoding`. Traefik's official compress
middleware supports gzip, Brotli and Zstandard and defaults to compressing
eligible bodies above 1 KB ([Traefik documentation](https://doc.traefik.io/traefik/v3.3/middlewares/http/compress/)).
The repository now attaches this middleware to the Fulton router. It is not live
until the normal signed-image deployment process runs.

Do not replace the Python `ThreadingHTTPServer` or SQLite yet. With two users,
current latency and headroom do not justify that migration. If the audience
grows beyond one host process, first split schedulers into a single worker,
move the HTTP layer to a maintained WSGI/ASGI server, then consider PostgreSQL.
Multiple web workers must not each run the current in-process schedulers.

## Storage and recovery

The mergerfs layout is working as a capacity pool, not as RAID. Every file lives
on one branch; one branch failing loses the files on that branch. This is stated
explicitly in the project's non-features, which include no RAID-like parity or
redundancy ([mergerfs documentation](https://github.com/trapexit/mergerfs)).
It also does not make one video stream faster; a single file reads at the speed
of its underlying branch ([mergerfs performance notes](https://github.com/trapexit/mergerfs/blob/master/mkdocs/docs/performance.md)).

The live SQLite bind correctly bypasses mergerfs and uses `/disk4` directly.
The local operations monitor did not: it opened the same database via
`/srv/storage`, producing a SQLite disk-I/O error and hiding host metrics. This
review changed the default and saved local paths to `/disk4`; the full SSH probe
now passes with disk, memory, Docker and SQLite details.

### Required recovery changes

1. Replace or physically disconnect `/dev/sdd`. It is retired and unmounted but
   still reports five pending and four offline-uncorrectable sectors every 30
   minutes. Smartd's attempted mail notification fails because no mail command
   is installed. Keeping a known-bad disk spinning adds noise and risk.
2. Send SMART, backup, container and public-health failures to a channel that is
   actually observed. The existing weekly log is evidence, not notification.
3. Enable encrypted off-host Fulton backups and perform a restore drill. Current
   verified backups are distributed across the same physical machine and the
   off-host gate is disabled.
4. An initial verified Jellyfin recovery point now exists at
   `/disk2/backups/jellyfin/jellyfin-20260928T003251Z`. It contains a compressed
   configuration/metadata archive and an online SQLite copy; all checksums,
   archive validation and SQLite `quick_check` pass. A disposable restore drill
   then parsed all five XML configurations, opened all 34 database tables and
   recovered six plugin assemblies without touching the live service. A weekly
   verified backup script and systemd timer are prepared on the review branch;
   install them after merge, then define retention before a major upgrade.
   Jellyfin's documentation explains that major migrations may not be reversible
   without a backup
   ([Jellyfin backup guidance](https://jellyfin.org/docs/general/administration/backup-and-restore/)).
5. After 30 current daily Fulton points exist, review and activate the existing
   30-daily/12-monthly/3-annual retention plan. Old one-off backup directories
   should be catalogued before removal.
6. If media is expensive to replace, add a parity disk at least as large as the
   largest protected data branch and use SnapRAID for the mostly static media
   tree, excluding live databases, caches and download-in-progress paths. Parity
   is not a backup; keep irreplaceable media off-site or in a second copy.

## Jellyfin

Jellyfin is active: two users were active in the last 30 days and 675 playback
start events have been logged since May. Its idle use is modest. There are no
FFmpeg transcode logs in the inspected directory, so do not enable acceleration
only because it exists; first record direct-play/remux/transcode proportions.

If transcoding is observed, the host exposes Intel render devices but the
container does not mount `/dev/dri` and Jellyfin reports hardware acceleration
as `none`. The official container guidance mounts the render device, and
Jellyfin recommends Intel QSV on Linux
([container guidance](https://jellyfin.org/docs/general/installation/container/),
[hardware acceleration](https://jellyfin.org/docs/general/post-install/transcoding/hardware-acceleration/)).
On this dual-core Skylake CPU, validated QSV would be a material improvement for
incompatible remote clients; it will not improve direct play.

Other changes:

- Mount `/media/content` read-only unless Jellyfin is intentionally allowed to
  delete or write media-side metadata.
- Remove the direct `0.0.0.0:8096` publication if all clients use Traefik, or
  bind it explicitly to the LAN address if local direct access is required.
- Add `no-new-privileges`, drop unneeded capabilities, set a PID limit and add a
  container health check. Do the same review for Pi-hole.
- Pin Jellyfin to a reviewed version/digest and stage upgrades with a full config
  backup. The inspected 10.11.9 is behind 10.11.11 and the current 12.0 major;
  Jellyfin's release notes warn that 12.0 database changes prevent rollback
  without restoring a full backup
  ([official releases](https://github.com/jellyfin/jellyfin/releases)).

## Security and container operations

Pi-hole was upgraded from 2026.05.0 to 2026.09.0, which fixes multiple
high-severity issues including remote code execution paths
([Pi-hole Docker releases](https://github.com/pi-hole/docker-pi-hole/releases)).
Before the change, its configuration and a consistent online SQLite copy were
backed up with verified checksums. The new container is pinned to digest
`sha256:5b9c8cf51de7d6d3f2240dbe72baf5f06e1fd39cb4d77a99fab4fa13e23bd1be`.
DNS, version and container-health checks passed after the upgrade with zero
restarts. The stopped prior container remains temporarily available as
`pihole-rollback-20260928T001520Z`. Docker Compose accepts digest-addressed
images ([Compose service reference](https://docs.docker.com/reference/compose-file/services/)).

Traefik also has no health check and has broad Docker-daemon visibility through
the socket. A read-only filesystem mount does not make the Docker API read-only.
Introduce a restricted socket proxy or equivalent least-privilege provider path,
then test dynamic discovery before removing direct access. Keep the daemon local
and protected; Docker warns that insecure daemon access can grant root-level host
control ([Docker daemon guidance](https://docs.docker.com/engine/security/protect-access/)).

Container log handling is already good: the `local` driver rotates and compresses
logs by default. Docker documents a default ceiling of about 100 MB per container
([local logging driver](https://docs.docker.com/engine/logging/drivers/local/)).

## Prioritised plan

### Now: reliability and security

1. Completed: backed up, upgraded and digest-pinned Pi-hole 2026.09.0; retain
   the stopped rollback container until the agreed observation window passes.
2. Disconnect the failed retired disk and make SMART alerts deliver somewhere.
3. Turn on an encrypted off-host Fulton backup and prove a restore.
4. Completed in code: persistent per-date failed-attempt budget and reset-aware,
   provider-specific daily-quota circuits. Still ensure a vetted reserve can
   publish a missing slot.
5. Deploy the Fulton compression labels through the signed release path.

### Next two weeks: product and cost

1. Build the answer-first seven-day quiz reserve and shrink diagnostic retention.
2. Add funnel/difficulty/fun telemetry and a private weekly operator report.
3. Test Daily Three and a less frequent featured map cadence.
4. Initial Jellyfin backup and disposable restore drill completed; merge and
   install the prepared weekly timer, then stage the version upgrade and
   hardening.
5. Measure Jellyfin playback method before deciding on QSV.

### Later, only if evidence demands it

- Add SnapRAID parity or a second replicated media copy.
- Add a socket proxy and uniform container hardening.
- Move schedulers out of the web process and adopt PostgreSQL only if concurrency,
  write contention or horizontal scaling becomes real.
- Replace hardware only for a measured media-transcode or disk-throughput limit.

## Changes made during this review

- Corrected the local ops default and saved monitor paths from the mergerfs view
  to the actual `/disk4` production bind. A full remote probe now passes.
- Added Traefik response compression labels and a deployment contract test.
- Added a persistent default ceiling of 180 failed generation attempts per
  quiz-date, including exact-budget, retry-persistence and forced-recovery tests.
- Added durable, provider-specific daily-quota circuits. Exhausted Gemini models
  pause through the next Pacific reset and OpenRouter pauses through its next
  UTC reset, while another configured provider can continue.
- Backed up Pi-hole to `/disk2/backups/pihole/pihole-20260928T001435Z`, upgraded
  it to 2026.09.0, pinned the tested digest, and retained the stopped old
  container for rollback. Pi-hole performed its own schema migration from 21 to
  22 and remained healthy; Fulton data, content and scores were not changed.
- Created and independently re-verified the first Jellyfin recovery point at
  `/disk2/backups/jellyfin/jellyfin-20260928T003251Z`. It is owner-only, contains
  a consistent 34-table database plus the configuration/metadata archive, and
  did not interrupt or restart Jellyfin. A disposable restore of the database,
  XML configuration and plugins also passed; a reviewed weekly backup script
  and timer are included in the release branch.
- No paid AI calls were made.
