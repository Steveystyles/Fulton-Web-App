# Audit remediation — 20 September 2026

## Implemented in the working tree

- Quiz: reject answer giveaways and repeated subject-round themes; retain failed-answer feedback across scheduler retries; strengthen difficulty and factual-support instructions.
- Decode HTML entities as plain text, preserving historical grading identifiers and versions. Show the verified interesting fact after submission, never in the unsolved public payload.
- Map discovery: enforce exclusions before source work and after identity resolution; reject stadiums disguised as another type; disregard ended country claims.
- Map review: require correct type, a distinctive hard hook and an unambiguous easy target. Reject age/material-only hard hooks.
- Correct the Wembley fallback's old/new stadium distinction and replace the unsupported A406 direction. Sources are recorded with the fallback.
- Private operations: expose map reserve shortages, excessive quiz rejections and missed evening publication readiness.
- Compatible npm lockfile updates; no major framework migration.
- Daily verified-backup wrapper and example systemd user service/timer for the inspected host.

## Verification

Build and 26 client tests passed. Full server suite: 675 tests, one Windows symlink-related skip. Ten targeted remediation regressions passed again after final topic-filter refinement. Bandit: 39 existing reviewed findings, no new findings; all snippets were matched to the old baseline after adjusting line numbering before refreshing fingerprints. The comparison passes with all 55 required files scanned. npm reported zero vulnerabilities.

## Production changes and remaining work

A fresh online backup was created and verified at `/srv/storage/backups/fultons-quiz/fultons-quiz-20260920T004741Z-597399d6`. The backup wrapper was copied to `/home/ste/fultons-daily-backup.sh`; no timer has been activated.

**Application changes are not deployed.** Follow `DEPLOYMENT.md`: reviewed main commit, passing CI, signed immutable image and verified updater. Do not bypass these controls with a container hotpatch. The existing production image remains unchanged.

The host lacks `crontab`; its user systemd manager is running but `Linger=no`. After deploying the backup script at the service's configured source path, install the service/timer in the deployment user's systemd directory, reload it and enable the timer. An administrator must first enable persistent user services (`sudo loginctl enable-linger ste`) for reliable operation while logged out. Verify an actual timer-triggered backup and its integrity. Off-host recovery and a restore drill remain outstanding.

Host updates and reboot require administrator access: passwordless sudo is unavailable. Schedule maintenance and recheck the proxy, Docker, storage, application and schedulers afterwards. Do not send passwords through chat.

Existing published map rows are not rewritten by editing the fallback bundle. Future problematic rows (including the September 21 Panathenaic clue and September 22 Wembley clue) still need guarded, source-reviewed repair that preserves played rounds and shared records. No historical quiz content or player scores were changed.

The map reserve still needs replenishment and the revised generators need observation over real runs. No paid generation calls were made. These fixes improve enforceable quality gates; they do not establish human enjoyment. Fun-target acceptance still requires play-testing and enough solve/feedback data.
