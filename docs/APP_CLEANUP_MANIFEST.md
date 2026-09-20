# Fulton Web App Cleanup Manifest

Created: 2026-07-27

## Completed Non-Destructive Changes

- Grouped the Wordle backend implementation and word data under `games/wordle/`.
- Kept root `wordle_game.py` as a compatibility import so existing server/tests still work.
- Updated Docker copy rules for the new `games/` package.
- Updated README and `.gitignore` for the new `games/wordle/used_words.txt` location.
- Added `tools/training_data_store.py` as a shared reader/writer for map review feedback.
- Added `tools/consolidate_training_data.py` to regenerate consolidated training artifacts.
- Created `data/training/map_place_review_feedback_all.jsonl` from the 27 legacy feedback files.
- Updated the map selector profile builder, selector model, and candidate generator to read the consolidated feedback file when present.
- Added rerun guards so consolidated JSONL archives are preserved after source files are cleaned up.

Initial map feedback consolidation:

- Legacy feedback files: 27
- Legacy feedback rows: 270
- Unique consolidated rows: 265
- Duplicate rows removed from consolidated file: 5

During the delete pass, the legacy feedback files were removed and an old rerun path briefly overwrote the consolidated feedback file. The tool guard was fixed. The feedback JSONL was then reconstructed from `map_selector_profile_20260727T141105Z.json` plus `data/fultons.db`.

Recovered map feedback state:

- Reconstructed feedback rows: 170
- Rows matched back to `map_place_pool`: 131
- Recovery report: `data/training/map_place_review_feedback_reconstruction_report.json`
- The pre-cleanup `map_selector_profile_latest.json` and `map_selector_model_latest.json` were already built from the full 265-row consolidated source before this happened.

## Completed Destructive Cleanup

- Removed the 27 legacy `map_place_review_feedback_*.json` files after consolidation.
- Removed 18 exact duplicate generated artifacts while retaining the newest file per artifact family.
- Consolidated 245 map candidate CSV rows into `data/training/map_ai_place_candidates_all.jsonl`.
- Consolidated 50 map candidate JSON runs into `data/training/map_ai_place_candidate_runs_all.jsonl`.
- Consolidated 34 legacy quiz JSON/JSONL records into `data/legacy_quizzes_all.jsonl`.
- Consolidated 501 map place selection batch records into `data/training/map_place_selection_batches_all.jsonl`.
- Consolidated 35 map clue rewrite reports into `data/training/map_clue_ai_rewrite_reports_all.jsonl`.
- Removed 124 generated map candidate source CSV/JSON files.
- Removed 5 unreferenced legacy `data/quizzes` source files.
- Removed 47 individual selection batch, rewrite report, and review-probe files.
- Removed 92 older generated timestamped artifacts/logs.
- Moved `data/training/fultons-before-map-final-import-20260719T102608.db` to `data/backups/`.
- Removed generated Python cache folders and old local log files.
- Removed unused frontend spare files:
  - `src/components/NewsTicker.tsx`
  - `src/components/PlaceholderPage.tsx`
  - `src/components/StatCard.tsx`
  - `src/assets/crest-placeholder.svg`
- Removed the paused, unreachable facts frontend cluster:
  - `src/pages/Facts.tsx`
  - `src/components/HistoryKnowledge.tsx`
  - `src/components/FactCardImage.tsx`
- Removed the corresponding unused client API types, request cache, and background
  facts prewarm.
- Removed the retired server facts/history implementation, provider configuration,
  prewarm worker, generated-image wrapper, and feature-specific tests. The three
  retired API paths return `410 Gone` for one compatibility release.
- Removed thirteen repository-unreferenced Python helpers and consolidated a
  duplicated map workoutability scorer, timezone loader, production cookie
  implementation, and crest asset.

## Keep In Place

- `server.py`: main API/static server and route owner.
- `daily_quiz.py`: daily quiz generation, validation, storage, and provider logic.
- `daily_map_game.py`: map game generation, selection, clue validation, scoring, and storage logic.
- `data/fultons.db`: live local SQLite database. Do not merge this into JSON; it is the operational source of truth.
- `tools/templates/map-place-review.html`: source template for the generated local
  place/clue review page.
- `dist/`: build output. It can be deleted and regenerated, but keep if using the local production server without rebuilding.

## Safe Archive Candidates

Completed in this cleanup pass. Keep this section as historical context for what was removed or consolidated.

## Exact Duplicate Candidates

Completed in this cleanup pass. A post-cleanup duplicate-content scan found no remaining duplicate file contents in `data/training`.

## Delete Candidates After Approval

Completed in this cleanup pass.

## Completed Moves

- Moved `check-and-fix-after-power-outage.cmd` and
  `check-and-fix-after-power-outage.ps1` into `deploy/`.
- Keep `restart-fultons-site.bat` and `run-local-ops-dashboard.cmd` at root unless you are happy to update README commands and personal shortcuts.

## Product Decisions Needed

- Existing databases may still contain `history_fact_rotations`,
  `history_fact_review_failures`, and `history_fact_prewarm_jobs`. Runtime no
  longer creates or uses these tables. Drop them only in a reviewed, backed-up
  offline database migration after the `410 Gone` compatibility release.
- `daily_quiz.py` and `daily_map_game.py` are large root modules. They can be moved into a backend package later, but that is higher risk than the Wordle move because many tools/tests import them directly and both modules compute project paths.
- `data/training` still contains many candidate-generation CSV/JSON runs. These are mostly experiment history, while the playable place bank now lives in `data/fultons.db`. Archive old candidate runs after confirming no current review batch still depends on them.

## Suggested Next Cleanup Pass

1. After the compatibility release, confirm retired API traffic is absent and
   schedule the backed-up offline table-drop migration.
2. Keep the power-outage scripts in `deploy/`; that move is already complete (see Completed Moves).
3. Optionally split the large root backend modules into a package in a later, higher-risk refactor.

## Audit cleanup — 20 September 2026

- Removed 87 regenerable Python bytecode files from seven checked cache directories (about 3.23 MiB).
- Preserved application data, training feedback, backups, release evidence and sibling worktrees.
- Rebuilt the frontend successfully. No runtime source or dependency changes were made.
- See [the current audit](AUDIT_2026-09-20.md) for production health, pending maintenance and map/quiz quality findings.

## Verification

- `npm run test:server` passed after cleanup on 2026-07-27: 274 tests.
- `npm run build` passed after cleanup on 2026-07-27.
- `data/training` after cleanup: 38 files, about 40.63 MiB.
- `data` after cleanup: 43 files, about 54.65 MiB.
- Post-cleanup duplicate-content scan: no remaining duplicate file contents in `data/training`.
