# Fulton's Quiz

Mobile-first daily quiz, map game, Wordle, scores, and account app backed
by a Python/SQLite server.

## Run Locally

Start the Python API in one terminal:

```bash
npm run api
```

The API reads the process environment directly. Export any AI provider keys
before starting it; the launcher does not automatically load `.env.local`.

Start the Vite frontend in another terminal:

```bash
npm run dev
```

The Vite dev server proxies `/api` to `http://127.0.0.1:8000`.

## Production-Style Run

Use `.env.example` as the configuration template, but export or inject the
values into the process environment before launch. The Python entry points do
not automatically read `.env` or `.env.local`.

```bash
npm run build
npm start
```

`npm start` runs `server.py` directly. Secure cookies are enabled by default;
set `FULTONS_COOKIE_SECURE=0` only for explicit plain-HTTP local development.
Password policy, security headers, origin checks, and login throttling are
implemented by the core server.

## Local Ops Dashboard

Run the local external-monitor board with:

```bat
run-local-ops-dashboard.cmd
```

That launcher starts a localhost-only board at `http://127.0.0.1:8765/ops`, enables the SSH/public-health monitor endpoints, and reuses the existing process if the board is already up. Use `run-local-ops-dashboard.cmd --no-browser` if you want it to start quietly in the background.

## Homeserver Deployment

The production container is built once in CI and served through the
Traefik-facing Compose file at `deploy/compose.yaml` by a signed, immutable
registry digest. Host paths and the digest are supplied through a private
Compose dotenv outside the repository. The updater verifies the signature and
canonical OCI source/revision labels, creates a checked SQLite online backup,
supports a fail-closed encrypted off-host-copy gate, and health-verifies
rollback. Local builds require an explicit development-only override.

See [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) for the full server clone, environment, build, and update process.

The current QA/remediation state is recorded in
[`docs/QA_SECURITY_AUDIT_2026-08-12.md`](docs/QA_SECURITY_AUDIT_2026-08-12.md).
That report describes local work only; it is not evidence that production has
been updated.

## Security Notes

Production defaults are intentionally stricter than local development:

- Demo users are not seeded unless `FULTONS_SEED_DEMO_USERS=1` is set.
- Cookies are marked `Secure` by default. Plain-HTTP local development must opt
  out with `FULTONS_COOKIE_SECURE=0`.
- New and reset passwords must be at least 12 characters by default.
- Failed login attempts are throttled per username/client combination.
- Concurrent password verifications are bounded to protect server capacity;
  tune `FULTONS_LOGIN_MAX_CONCURRENT_VERIFICATIONS` only after load testing.
- Forwarded client IPs are trusted only from configured proxy CIDRs. The
  deployment assumes one operator-controlled Traefik hop and no direct public
  connection to the app container; verify that topology before rollout.
- The Docker Compose service runs with a read-only container filesystem, dropped Linux capabilities, and `no-new-privileges`.

## Storage

- User accounts, sessions, daily Wordle games, guesses, and results are stored in `data/fultons.db` locally or `/app/data/fultons.db` inside the container.
- Daily quiz state is stored in the SQLite database tables `daily_quiz_sets`, `daily_quiz_questions`, and `daily_quiz_attempts`. Unfinished AI-generated quizzes stay in `generating` and retry missing slots rather than falling back to local bank content.
- Daily map game state is stored in `map_place_pool`, `daily_map_puzzles`, `daily_map_levels`, and `daily_map_guesses`.
- Map selection blocks place types used in the previous three rounds by default; configure this with `FULTONS_DAILY_MAP_PLACE_TYPE_COOLDOWN_DAYS`. Explicit launch sequences can override the cooldown without weakening clue or evidence checks.
- The Wordle implementation and word data live under `games/wordle/`. The root `wordle_game.py` file is a compatibility import for older scripts/tests. The local used-word tracker is stored at `games/wordle/used_words.txt`.
- The former facts/history feature is retired. Its UI and runtime implementation
  have been removed, and its old API paths return `410 Gone` for a compatibility
  release rather than retaining a second content subsystem.

## Quiz Model Training Data

The first step toward a trained quiz-generation model is exporting reviewed production history into repeatable datasets. The exporter uses accepted published questions as supervised fine-tuning examples, carries recent accepted questions and prior failed-attempt feedback into each prompt, and holds out the newest quiz dates for evaluation.

```bash
python tools/export_quiz_training_data.py --db data/fultons.db --out-dir data/training --eval-days 7
```

Generated files are written under `data/training/`, which is ignored by git:

- `quiz_sft_train_*.jsonl`: OpenAI chat fine-tuning JSONL with `messages`.
- `quiz_eval_*.jsonl`: held-out prompt, expected output, and metadata for offline evals.
- `quiz_export_manifest_*.json`: counts, source dates, eval dates, and export settings.

Reviewed football workbooks can be added as a second, curated data source. This exporter treats high-scoring confirmed rows as positive examples, holds out every fifth high-scoring row for evals, and keeps failures plus low-scoring confirmed rows in a separate negative file for review or later preference training.

```bash
python tools/export_reviewed_football_training_data.py --workbook path/to/football_quiz_review_corrected_verified.xlsx --out-dir data/training
```

Reviewed workbook outputs use the same JSONL shapes where possible:

- `football_review_sft_train_*.jsonl`: high-score confirmed football examples for SFT.
- `football_review_eval_*.jsonl`: held-out reviewed football examples for offline evals.
- `football_review_negative_*.jsonl`: ambiguous, incorrect, and low-score examples to avoid as positives.
- `football_review_manifest_*.json`: counts, filters, skipped rows, and validation failures.

Validate reviewed-football evals with the same fixture evaluator, using the `football_review_eval_*.jsonl` file as input.

Prepare an OpenAI fine-tuning dataset and registry entry without making API calls:

```bash
python tools/openai_quiz_finetune.py --dry-run --out-dir data/training
```

When OpenAI credentials and a fine-tunable base model are available, create and poll a job explicitly:

```bash
set OPENAI_FT_BASE_MODEL=your-base-model
python tools/openai_quiz_finetune.py --create-job --out-dir data/training
python tools/openai_quiz_finetune.py --poll-job
```

Evaluate a candidate fine-tuned model before changing live config:

```bash
python tools/evaluate_quiz_generator.py --eval-file data/training/football_review_eval_YYYYMMDDTHHMMSSZ.jsonl --provider openai-compatible --generator-model ft:model-id --out data/training/eval_report_ft_football.json
```

If fine-tuning access is unavailable, build a deployable learning profile from reviewed negative examples:

```bash
python tools/build_quiz_learning_profile.py --out-dir data/training
```

Set `QUIZ_LEARNING_PROFILE_PATH` to the generated JSON file to add compact learned feedback to future quiz generation prompts while keeping the existing validators and critic active.

The two-stage candidate pipeline can be shadow-tested without touching the live
database or published quizzes:

```bash
QUIZ_SHADOW_GEMINI_API_KEY=... python tools/evaluate_quiz_candidate_pipeline.py --start-date 2026-08-14
```

It copies quiz history into `data/qa/quiz-candidate-shadow/shadow.db`, generates
seven unpublished comparison dates, writes automated metrics to `report.json`,
and exports a 12-question human review sample. Production activation remains
controlled by `QUIZ_CANDIDATE_PIPELINE_ENABLED`, which defaults to `0`. The
pipeline enforces `QUIZ_CANDIDATE_MAX_CALLS_PER_QUIZ` (default `30`) before
making each discovery or composition request. Shadow evaluation requires
dedicated `QUIZ_SHADOW_*` credentials by default so it cannot exhaust the live
generator's quota. `--allow-shared-provider-quota` is reserved for isolated
environments where no production scheduler uses those credentials.

Run the safe fixture evaluator to confirm the held-out eval file is structurally valid:

```bash
python tools/evaluate_quiz_generator.py --eval-file data/training/quiz_eval_YYYYMMDDTHHMMSSZ.jsonl --provider fixture --out data/training/eval_report_fixture.json
```

Run the configured generator against the same eval file only when the required AI provider credentials are available:

```bash
python tools/evaluate_quiz_generator.py --eval-file data/training/quiz_eval_YYYYMMDDTHHMMSSZ.jsonl --provider current --out data/training/eval_report_current.json
```

Do not upload a training file until the manifest and eval examples have been reviewed. The current deterministic validators and duplicate checks must remain in the generation path even when using a fine-tuned model.

## Automatic map place selection

Set `FULTONS_DAILY_MAP_AUTOMATIC_ENABLED=1`, keep the map scheduler and map AI
generation enabled, and configure the server-only `MAP_AI_API_KEY` and
`MAP_AI_MODEL`. The scheduler checks its queue every 15 minutes, including when
today's games are already prepared. This mode takes precedence over the older
controlled-catalogue generator.

The service discovers new places, retrieves Wikipedia/Wikidata evidence and
coordinates, writes three progressive clues, and performs a separate model
verification against the retrieved passages. Local checks enforce source IDs,
identity, coordinate agreement, map areas, clue format and repeat cooldowns.
Passing rounds enter a persistent queue automatically; no routine manual
promotion or hand-maintained place list is required. Machine checking reduces
errors but is not a guarantee of factual accuracy.

The queue targets seven eligible rounds. Unused entries expire after 14 days;
used entries cannot publish twice. Maintenance makes at most four attempts,
12 model requests and 64 source requests per UTC day, across restarts and future
puzzle dates. An attempt allows at most three model calls: proposals, clue
composition and verification. Publication consumes saved, checked clues without
another model call. Failed candidates stay out; failed names are avoided on
subsequent attempts. Quota or source failures defer replenishment while available
rounds remain usable. The existing reviewed reserve is an optional one-time
bootstrap and emergency fallback, not the source of automatic discovery.

Queue entries, evidence verdicts and request accounting live in the production
SQLite database (`automatic_map_*` tables); private source reports are stored
beside it under `qa/automatic-map`. Publication and queue consumption share one
transaction. Already published games and their guesses are preserved.

To exercise discovery with no seed catalogue against a disposable initialized
database, run:

```bash
python tools/automatic_map_pool.py --source-db data/qa/test.db --no-bootstrap
```

## Checks

```bash
npm run build
npm run test:server
```
