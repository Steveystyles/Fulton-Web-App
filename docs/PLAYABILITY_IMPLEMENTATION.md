# Playability implementation handoff

Local implementation completed: 10 September 2026. Release preparation was subsequently authorized; this document describes the implementation and local checks, not the current production deployment state.

This implements the core product and playability improvements from the 9 September review. It is a completed local implementation, not a claim that every longer-term research idea in that review has shipped.

## What changed

- **A daily games club home:** Today shows Wordle, Football, General Knowledge, and Map as ready, in progress, completed, or unavailable. Players can resume a round, view saved results, and choose their next game without searching the navigation.
- **A balanced weekly league:** Monday-to-Sunday standings, game filters, tied ranks, nearby-rival gaps, and previous-week winners. The original score history and Wordle mastery remain accessible separately.
- **Reliable quiz progression:** Players can change a choice before confirming it. Confirmed answers and completed results are saved to the account and restored across devices. Duplicate submissions, conflicting confirmed answers, legacy browser progress, and interrupted saves have recovery paths. Results explain accuracy, points, and answers.
- **Unranked quiz practice:** Published quizzes from previous dates can be replayed without changing ranked scores or account progress. Today's and future quizzes cannot be fetched through the practice endpoints.
- **More usable Map rounds:** Active-clue focus, expandable prior clues and help, a wider desktop layout, mobile map sizing, direct confirmation of a named place, keyboard-centre selection, clearer miss feedback, and protection against losing an existing selection after a failed replacement lookup.
- **More accessible Wordle:** Non-colour feedback symbols and labels, spoken last-guess feedback, expandable previous guesses in large-print mode, properly focused result dialogs, and keyboard shortcuts that respect focused controls. Sound defaults off while preserving an existing explicit preference.
- **A better finish to each round:** Next-game suggestions and spoiler-free sharing, including clipboard/manual fallbacks. Account preferences use the existing browser-local settings.
- **Less disruption:** App updates require an explicit reload instead of interrupting a round. Requests have bounded waits and recovery messages. News merges updates without duplicate stories or fake freshness timestamps.

## League scoring

The new league is calculated from existing game records; it does not rewrite their scores.

| Activity | Daily league points |
| --- | --- |
| Wordle | A win in 1–6 attempts earns 10, 9, 8, 7, 6, or 5; a loss earns 0. Mastery bonuses do not change league points. |
| Football quiz | Game score divided by that round's maximum, scaled to 10. |
| General Knowledge quiz | Game score divided by that round's maximum, scaled to 10. |
| Map | Earned points, capped at 10 per player per day across stored rounds. |

Quiz league points use hundredth-point precision. Equal totals share a rank; zero-point entries are not ranked. All four activities therefore contribute at most 40 league points per day in total.

## Data and deployment

- The only new database structure is the additive `daily_quiz_progress` table, created by the existing schema-initialization path. Existing result tables are retained.
- `playability.py` supplies read-only Today and league projections. The Dockerfile now copies this module into the application image.
- The existing OpenAI key and `.env.local` were left unchanged, as requested. No live AI requests were made during this implementation or its checks; the content-generation pipeline is unchanged.
- Interactive checks used a separate audit database under the parent workspace's `.codex-logs` directory, with background generation and news scheduling disabled. The original application database and live scores were not changed.
- No dependencies, public services, credentials, or production settings were added.

For deployment, use the normal signed-image, database-backup, and health-check procedure in `DEPLOYMENT.md`. Confirm current production state from the release evidence and running revision rather than this implementation document.

## Verification

- Full server suite: **662 tests run, successful, with 1 skipped**.
- The Windows-only skip is `BackupManagerTests.test_verify_and_retention_reject_symlink_candidates`: Windows error 1314 prevents the test account from creating a directory symbolic link. The assertions protect backup verification and retention from following symlinks; they have not been disabled or weakened. The Ubuntu CI build runs the same test suite and must exercise this test before production release.
- Client API/merge checks: **5 of 5 passed**.
- TypeScript check and production Vite build: **passed**, including the final quiz-recovery fix and mobile map-control CSS.
- `git diff --check`: **passed**.
- Security baseline comparison: **no new findings**; 39 existing reviewed findings remain. Baseline changes account for shifted source locations, not new exemptions.
- Independent read-only regression review: no release-blocking issue found. Its non-blocking legacy/cross-device quiz hydration conflict was fixed.

New server coverage includes private quiz progress, immutable confirmed answers, idempotent final submissions, legacy-endpoint protection, invalid dates/choices/order, authenticated new routes, Today without an accidental Wordle start, balanced projections without score mutation, real news freshness, read-only practice grading, and packaging of the new module.

Earlier interactive checks covered desktop and phone layouts, saved quiz results, changing an unconfirmed answer, saving and resuming a quiz, completing a quiz, league totals, and Map clue progression.

### Verification limits

Browser access became unavailable during the final verification pass. The last mobile Map confirmation-button positioning adjustment was build-checked but could not receive a final visual recheck. A complete keyboard/screen-reader playthrough of the new Wordle dialogs and a full browser playthrough of the practice archive also remain manual QA items; automated checks do not substitute for those checks.

Longer-term human content-quality playtesting, retention measurement, feedback telemetry, and a new AI-content evaluation harness remain follow-up work. This pass does not claim to have implemented or validated them.
