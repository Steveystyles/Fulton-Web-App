# Server, website and content audit follow-up — 20 September 2026

## Outcome

The live application is available and matches the latest `main` commit
(`80be73d50ec4e1c039c90ecb3d6a2ced838fb515`). Storage and SQLite integrity
checks pass, the container is healthy, the public routes render, the dependency
tree has no known npm advisories, and the local build and automated suites pass.

The system is not fully up to date operationally. The Ubuntu host has pending
system and Docker updates and requires a reboot. A fresh verified backup exists.
The Fulton user timer was subsequently installed and enabled for 03:15 UTC
daily; because the deployment user still has `Linger=no`, an administrator must
enable lingering before logged-out execution is guaranteed.

The latest map clue ladders meet the written editorial shape much better than
the earlier sample: each has a memorable hard hook, geographic narrowing and a
practical final map route. Automatic creation still does not meet its operating
target because the ready reserve remains zero. Failed discovery is correctly
rejected instead of being published.

The quiz is publishing complete, evidenced sets before the play date. Recent
rounds have broad topic variety and good post-answer facts, but generation is
still inefficient and difficulty calibration is uneven. The 21 September set
required 383 recorded attempts for six accepted questions.

There is not enough player evidence to confirm the fun targets. No guesses were
recorded for the inspected 12–22 September map rounds, and only six quiz results
were recorded from 12–20 September. Editorial quality can be assessed; player
enjoyment, fairness and retention cannot yet be established from that sample.

## Verification performed

- Public health returned HTTP 200 with `ok: true`, healthy storage and build
  `80be73d`.
- `/`, `/quiz` and `/map` returned HTTP 200 with CSP, HSTS, frame denial and
  content-type protections.
- The login surface rendered cleanly at 1280×720 and 390×844, with no horizontal
  overflow or browser console warnings/errors.
- The production container was healthy, had zero restarts, ran as `appuser` and
  retained a read-only root filesystem.
- Production SQLite `PRAGMA quick_check` returned `ok`.
- The 20 and 21 September quizzes were published with six questions each; every
  inspected question had evidence and verification records.
- Map puzzles were published through 22 September, but all nine automatic-map
  entries were already used and none were ready.
- The newest backup, created 20 September at 11:48 UTC, contains an online
  SQLite backup and durable-files archive. Their SHA-256 hashes match the
  manifest, whose database quick check is `ok`.
- `npm audit` reported zero vulnerabilities across 170 dependencies. Compatible
  package ranges are current; newer React, Tailwind, TypeScript and related major
  versions require deliberate migrations rather than a cleanup update.

## Code and file cleanup

Two pending generator fixes were retained and regression-covered:

- quiz prompts now distinguish current-round questions from historical context,
  preventing historical topics from being treated as same-round duplicates,
  place prior rejected answers in the explicit answer embargo, and require the
  critic to compare relative easy/medium/hard ordering within each subject;
- map evidence units preserve a complete named anchor when it crosses a
  fixed-size evidence chunk boundary.

Regenerable Python bytecode caches were removed after verification. Application
data, training evidence, deployment backups, release records, sibling worktrees
and parent-level rollout history were intentionally preserved.

## Remaining actions

1. Replenish the automatic-map reserve on an isolated run and observe whether
   the revised exclusion and evidence handling materially improve the acceptance
   rate before relying on it for future coverage.
2. Reduce quiz proposal/retry waste without weakening evidence, verification or
   critic rejection. Track attempts, elapsed time and topic/difficulty balance
   per slot.
3. Verify the first timer-triggered Fulton backup, enable lingering for the
   deployment user, then perform an off-host restore drill.
4. Apply host and Docker updates in a maintenance window, reboot, and recheck the
   proxy, container, storage, schedulers and public health.
5. Collect explicit player ratings (fun/fair/unclear) and enough completions to
   set measurable acceptance thresholds for both games.

This follow-up supersedes deployment-state statements in
`AUDIT_2026-09-20.md`; that earlier report and `REMEDIATION_2026-09-20.md` remain
the detailed finding and remediation history.
