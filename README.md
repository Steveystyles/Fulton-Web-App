# Fulton's Quiz

Mobile-first quiz app with a server-side daily Wordle draft.

## Run Locally

Start the Python API in one terminal:

```bash
npm run api
```

Start the Vite frontend in another terminal:

```bash
npm run dev
```

The Vite dev server proxies `/api` to `http://127.0.0.1:8000`.

## Production-Style Run

```bash
cp .env.example .env
npm run build
npm start
```

`npm start` runs the hardened production wrapper in `production_server.py`. It preserves the existing API while adding stronger password requirements, secure cookies, security headers, restricted CORS preflight handling, and basic login throttling.

## Local Ops Dashboard

Run the local external-monitor board with:

```bat
run-local-ops-dashboard.cmd
```

That launcher starts a localhost-only board at `http://127.0.0.1:8765/ops`, enables the SSH/public-health monitor endpoints, and reuses the existing process if the board is already up. Use `run-local-ops-dashboard.cmd --no-browser` if you want it to start quietly in the background.

## Homeserver Deployment

The production container is built with `Dockerfile` and served through the Traefik-facing compose file at `deploy/compose.yaml`. The host runtime paths come from `~/fulton-web-app-deploy/.env`, which sets `FULTONS_ENV_FILE` and `FULTONS_HOST_DATA_DIR` for the live container.

See [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) for the full server clone, environment, build, and update process.

## Security Notes

Production defaults are intentionally stricter than local development:

- Demo users are not seeded unless `FULTONS_SEED_DEMO_USERS=1` is set.
- Cookies are marked `Secure` by default when using the production wrapper.
- New and reset passwords must be at least 12 characters by default.
- Failed login attempts are throttled per username/client combination.
- The Docker Compose service runs with a read-only container filesystem, dropped Linux capabilities, and `no-new-privileges`.

## Storage

- User accounts, sessions, daily Wordle games, guesses, and results are stored in `data/fultons.db` locally or `/app/data/fultons.db` inside the container.
- Daily quiz state is stored in the SQLite database tables `daily_quiz_sets`, `daily_quiz_questions`, and `daily_quiz_attempts`. Unfinished AI-generated quizzes stay in `generating` and retry missing slots rather than falling back to local bank content.
- Daily map game state is stored in `map_place_pool`, `daily_map_puzzles`, `daily_map_levels`, and `daily_map_guesses`.
- The Wordle implementation and word data live under `games/wordle/`. The root `wordle_game.py` file is a compatibility import for older scripts/tests. The local used-word tracker is stored at `games/wordle/used_words.txt`.

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
python tools/evaluate_quiz_candidate_pipeline.py --start-date 2026-08-14
```

It copies quiz history into `data/qa/quiz-candidate-shadow/shadow.db`, generates
seven unpublished comparison dates, writes automated metrics to `report.json`,
and exports a 12-question human review sample. Production activation remains
controlled by `QUIZ_CANDIDATE_PIPELINE_ENABLED`, which defaults to `0`.

Run the safe fixture evaluator to confirm the held-out eval file is structurally valid:

```bash
python tools/evaluate_quiz_generator.py --eval-file data/training/quiz_eval_YYYYMMDDTHHMMSSZ.jsonl --provider fixture --out data/training/eval_report_fixture.json
```

Run the configured generator against the same eval file only when the required AI provider credentials are available:

```bash
python tools/evaluate_quiz_generator.py --eval-file data/training/quiz_eval_YYYYMMDDTHHMMSSZ.jsonl --provider current --out data/training/eval_report_current.json
```

Do not upload a training file until the manifest and eval examples have been reviewed. The current deterministic validators and duplicate checks must remain in the generation path even when using a fine-tuned model.

## Checks

```bash
npm run build
npm run test:server
```
