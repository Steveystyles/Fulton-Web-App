# Place selection and three-clue AI

## New place discovery

The discovery command in [MAP_PLACE_DISCOVERY.md](MAP_PLACE_DISCOVERY.md) proposes places beyond the starter catalogue, retrieves source text and coordinates, and returns a selected place with three clues for source review. It has a persistent two-request budget per date. Reviewed candidates can be added to the runtime catalogue using the exact candidate hash. A live run selected Tower Bridge, and its saved result passed the real publisher and player serializer in a temporary database. Discovery is not automatically enabled in the production scheduler; the detailed record includes earlier failures and the remaining review requirement.

## Recommended development workflow: controlled generation

Run the new one-request workflow from the application directory:

```powershell
python tools/controlled_map_round.py --source-db data/fultons.db --date 2026-09-11
```

This uses `GEMINI_API_KEY_DEV` from `.env.local` and defaults to `gemini-3.5-flash-lite`. `--model` is an explicit override; no model fallback is attempted. It works without Gemini Search grounding or an Antigravity agent.

The source-reviewed starter catalogue is `deploy/map-evidence-catalog.json`: Sydney Opera House, Gateway Arch, Atomium, Eiffel Tower and Golden Gate Bridge. Each entry contains a stable recognition fact, geographic and local-map facts, references to official source pages, a target coordinate, and two independently stored guidance centres. These are source-reviewed development seeds, not human-approved published rounds. The catalogue is deliberately separate from the older database's broad `approved` flags, which alone do not establish fact-level evidence quality.

The generator reads actual puzzle history through a read-only SQLite connection. It excludes recently played places by name and coordinate proximity, rejects existing puzzle dates, and rotates a maximum six-place candidate window as the catalogue grows. The model chooses one interesting candidate and writes hard, medium and easy clues from the corresponding evidence facts. Target coordinates and map geometry never come from model output.

There is one model request per run, no automatic retries, no external model tools, at most 16,000 prompt characters and a 2,048 output-token setting. Prompt characters are not a token or billing guarantee; actual provider usage is included in the report. The supplied development credential is isolated using the same checks as the older preview tool.

Local checks require exactly three clues, valid fact references, no answer leaks, sensible length, an interesting recognition hook, progressively useful geography, the supplied map anchor names and no invented numeric details. Both guidance circles must contain the target, and the easy circle must fit within the medium circle. They represent search areas, not administrative borders. The existing game's hint counts are preserved: 1 for medium and 2 for easy. The final answer reveal is assembled separately by code.

JSON and Markdown reports are written under `data/qa/map-previews`. They include clues, evidence, validation failures, coordinates, compatible map guidance, request accounting and a catalogue fingerprint. All model text in the Markdown review is indented as inert text. `ready_for_review` indicates local checks passed; it does not establish semantic truth, human approval or publication. Fact references and text heuristics cannot prove every paraphrase is faithful. Review the sources and map guidance before promoting a round through the existing release process.

The starter catalogue supports five distinct places, not an indefinite daily schedule. Expand it with additional source-reviewed entries before production adoption. Every fact must cite a supplied HTTPS source reference; each place needs at least two source pages, a coordinate reference and evidence checked within 180 days. Exhausting eligible entries stops the run with a clear error, without repeating answers or substituting fallback content. Runtime generation does not fetch or follow catalogue URLs, so model content cannot trigger arbitrary network access.

### Live result, 6 September 2026

The stored map guidance includes the target anchor required by the existing publication gate. The player serializer removes answer-naming and exact-target anchors before the reveal, preserving answer secrecy. Tests verify one clue and no anchors initially, two clues and one search area after medium, then three clues and two search areas after easy.

One request selected the Atomium and produced a complete three-clue round. The provider reported 743 input tokens, 186 output tokens and 929 total tokens. The clues matched the supplied evidence and passed local checks. This is one successful development example, not a broad quality qualification. No production database, scheduled round or deployment was changed.

This replaces the Antigravity experiment as the recommended development path. Antigravity had search access but returned an incomplete result with no final clues and reported 43,203 tokens against a best-effort 8,000-token setting. The earlier grounded Gemini discovery workflow also encountered free-tier search restrictions; successful plain text generation does not imply grounding access.

Final validation: 607 tests completed successfully, with one expected skip. Bandit 1.9.4 passed with 39 existing reviewed findings and all 52 production Python files scanned. The 13 moved findings in `daily_quiz.py` were refreshed only after their source context matched exactly with line numbers shifted; no new findings were accepted. `git diff --check` passed.

## Production integration and rollout

The scheduler now supports `FULTONS_DAILY_MAP_CONTROLLED_ENABLED=1`. It is off by default until release review. With this flag on (and the existing `FULTONS_DAILY_MAP_AI_GENERATION_ENABLED` enabled), scheduled map generation uses the same bounded selection and validation functions, then the real transactional publisher. Clues, sources, the new place row and map geometry succeed or roll back together. Existing published rounds are preserved even when `force` is requested. Explicit admin selection of a preferred place retains its existing behaviour.

The Docker image includes both new tools and the catalogue at `/app/map-evidence-catalog.json`. Local server execution resolves the catalogue under `deploy/`; `MAP_AI_CATALOG_PATH` can explicitly select a reviewed replacement.

The user selected a **dedicated production map project**. Configure `MAP_AI_API_KEY` privately in the deployment host's existing application environment file, with `MAP_AI_MODEL=gemini-3.5-flash-lite`. The runtime factory requires that exact credential variable and never falls back to `GEMINI_API_KEY_DEV` or general Gemini keys. The story-first discovery path may use the separately configured `AI_FALLBACK2_API_KEY` only when its provider is OpenRouter, both model fields are exactly `openrouter/free`, and Gemini encounters a transient provider failure. Do not transfer the development key as part of deployment. API keys remain server-side.

For the automatic Map pool, `MAP_AI_CRITIC_MODEL` can select a separate Gemini model for source and editorial verification; proposal generation continues to use `MAP_AI_MODEL`. If unset, verification uses the generator model, preserving existing behaviour. Set the critic only after checking that the chosen model is available on this project's free tier and that it rejects known weak hooks in a saved-example comparison. A critic error leaves the candidate unapproved; it does not silently fall back to the generator. `MAP_PREVIEW_CRITIC_MODEL` remains specific to the development preview and does not configure the production pool.

On a missing key, exhausted catalogue, provider error or rejected generation, the scheduler uses the existing reviewed fallback publisher. It does not launch the old multi-stage AI workflow. This preserves service continuity without another AI request, but fallback content is not a successful fresh generation. The one-request limit applies per generation invocation, not an account-wide daily cap.

Before enabling: review the five seed entries and clue examples, provision the dedicated production project key, merge the reviewed release and pass CI, then deploy its signed immutable image digest using `docs/DEPLOYMENT.md`. Back up the environment and database before rollout. Verify a future unused date through the internal authenticated endpoint, check the three clue stages and map areas, and confirm the existing day's game remains unchanged. Rollback disables the controlled flag and restores the previous verified image through the same updater.

On 6 September 2026 a real development-key request was run through the production publication function against a disposable backup of the local database. It published an Atomium round and returned the normal player payload, using 1,246 tokens in one request. Source and live databases were unchanged. This verifies the application path, not the production credential, container deployment or live map tiles.

Integration validation: 611 server tests passed (one expected skip), the frontend production build and client contract test passed, and Bandit passed with 39 existing reviewed findings across all 52 production Python files. Seven additional server finding locations moved by three lines; their source contexts were verified unchanged before refreshing the baseline.

The release dependency audit required compatible lockfile updates to Browserslist 4.28.9 and postcss-selector-parser 6.1.4, plus Browserslist's data dependencies. The resulting npm audit reports zero vulnerabilities. Secret scanning remains enabled; splitting adjacent Python keyword arguments avoids a generic-key false positive without introducing a scanner exclusion.

## Legacy multi-stage pipeline

The existing Map system selects an interesting, pinnable place and writes a hard, medium and easy clue. It uses Gemini through the current provider adapter, the human-reviewed selection profile, and the existing clue and map validation gates. No hosted model training or new player UI is required.

The solving path is:

1. Discover several varied places from memorable stories, filtering recent answers and recent place types.
2. Rank qualifying hooks using the existing learned human preferences.
3. Research the selected event and independently check that it belongs to the exact place.
4. Generate the three clues: recognition story, geographic narrowing, local map placement.
5. Reject weak, repetitive, answer-leaking or invalid ladders using local and AI critics.
6. Verify staged map search boundaries and target anchors.
7. Save clues, guidance and publication atomically. A failed candidate cannot leave newly approved clues in the place pool, and a publication failure rolls back only this candidate's writes.

The final name reveal remains a separate existing game action after the three clues. Current scoring is unchanged.

## Isolated preview

Use the new preview command for development and human review:

```powershell
python tools/preview_ai_map_round.py --source-db data/fultons.db --date 2026-09-10
```

Choose a date that is not already published in the source database. The command reads `.env.local` by default; `--env-file` selects another file. Set `GEMINI_API_KEY_DEV` privately to a key from a **separate Google AI project with independent quota**. Do not commit or paste the key into a review report. A second key in the production project does not isolate quota.

The preview:

- Requires the dedicated key and rejects a value matching any other configured API key. This catches direct reuse; the operator must still confirm separate project ownership.
- Constructs a Gemini-only provider without OpenAI, OpenRouter or production fallback credentials.
- Allows at most 30 model requests, including discovery, research, clue writing, criticism and failed requests. `--max-requests` may lower this ceiling, but cannot raise it. Internal transport retries are disabled so they cannot escape the counter.
- Stops making model requests after the first provider error. It does not try production providers when quota is exhausted.
- Copies SQLite with the backup API from a read-only connection. All discovery, clue changes and test publication happen in that temporary copy, preserving production history for repetition checks.
- Uses a temporary event-research cache. The database copy and that cache are deleted after the run.
- Never substitutes a reviewed fallback for failed fresh generation.
- Exports a JSON report and a Markdown review sheet under `data/qa/map-previews`, including the selected place, three clues, selection reason, verification metadata, map geometry and request counts.

`ready_for_review` means the automated pipeline accepted the round inside the disposable database. It is not a human quality pass or a production deployment. A source date that was already published fails before any model call, preventing old content being reported as new output.

The model settings `MAP_PREVIEW_GENERATOR_MODEL` and `MAP_PREVIEW_CRITIC_MODEL` default to the existing Map Gemini model. Keep these fixed for the initial comparison so process changes can be assessed consistently. A real API run is needed to verify account access, model availability and output quality.

## Human review and release

Use `MAP_CLUE_GRADING_MATRIX.md`. Review unseen examples across different place types and countries. Confirm the actual sources support the important claims, check that the three clues provide distinct progress, and inspect the map at phone zoom. Model confidence is not proof of truth.

Keep failed reports as evaluation evidence. Do not relax gates or increase the request limit to label a failing run successful. The existing local model artifacts and reviewed feedback remain the selection baseline; this preview does not update learning profiles automatically.

The new preview tool has no production promotion command. Production continues to use the existing scheduler, quality gates and reviewed fallbacks. Any later release must follow `DEPLOYMENT.md`, with human review and the existing CI, signed image and backup requirements.

## Validation status

The automated tests exercise credential isolation, request accounting, provider failure stopping, source database preservation, review export, existing-date rejection and atomic publication success/failure through the real publisher. Their generated content is a fixture, not evidence of live Gemini quality.

On 6 September 2026, all 598 server tests passed (one expected skip). Bandit 1.9.4 passed the exact-site comparison: 39 existing reviewed findings and all 51 production Python files scanned. Four existing finding locations were refreshed only after comparing their unchanged source contexts; no new findings were allowed.

The user configured `GEMINI_API_KEY_DEV` in `.env.local`. Two isolated attempts each stopped at their first request; the diagnostic attempt returned `429 RESOURCE_EXHAUSTED` for `gemini-3.1-flash-lite`. No candidate or clue output was generated and production was not changed. Check the development project's model quota in Google AI Studio before retrying. Quotas are project-wide, so creating another key within the same project does not provide independent allowance. Live quality qualification remains pending.
