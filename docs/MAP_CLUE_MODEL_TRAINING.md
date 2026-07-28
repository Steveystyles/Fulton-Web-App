# Map Clue Model Training

## Current State

The map clue dataset can now be prepared for supervised fine-tuning as OpenAI chat JSONL.

```powershell
python .\tools\openai_map_clue_finetune.py --dry-run
```

The retained source training artifacts are:

- `data/training/map_clue_sft_train_20260719T092627Z.jsonl`
- `data/training/map_clue_eval_20260719T092627Z.jsonl`
- `data/training/map_clue_negative_20260719T092627Z.jsonl`
- `data/training/map_clue_manifest_20260719T092627Z.json`
- `data/training/map_model_registry.json`

The `openai_map_clue_combined_*` files are generated prep files. They can be recreated with `python .\tools\openai_map_clue_finetune.py --dry-run`, so they are not retained as source-of-truth cleanup artifacts.

## Hosted Fine-Tuning Attempt

The first OpenAI launch attempt used:

```powershell
python .\tools\openai_map_clue_finetune.py --create-job --base-model gpt-4.1-mini-2025-04-14
```

The API returned `training_not_available` for this organization. No fine-tuning job ID or fine-tuned model was created. The failed attempt is recorded in `data/training/map_model_registry.json`.

The tool loads `.env.local` by default and expects `OPENAI_API_KEY` for launch and polling. It deliberately requires a base model on `--create-job` so a paid external job is never created accidentally with an implicit model.

## Provider Reality

OpenAI still documents `/v1/fine_tuning/jobs` and lists `gpt-4.1-mini-2025-04-14` among supported fine-tuning snapshots, but this project key's organization is blocked from creating new jobs.

Google's Gemini API documentation says direct Gemini API or AI Studio fine-tuning is not currently available. Gemini tuning is only available through Google's enterprise platform path, not the standard Gemini API key.

## Practical Routes

### 1. Operational Learning

This is the current working route.

The app learns from the dataset and failures by:

- storing approved clue ladders in `map_place_pool`;
- exporting good examples to training JSONL;
- exporting rejected or low-quality examples as negative learning records;
- appending rewrite failures to `data/training/map_clue_failure_log.jsonl`;
- refreshing `data/training/map_learning_profile_latest.json`;
- feeding that profile into the next generation prompt.

Refresh after reviews or rewrite failures:

```powershell
python .\tools\export_map_clue_training_data.py
python .\tools\refresh_map_learning_profile.py
```

This does not change model weights, but it is available now and already affects the next generation loop.

### 2. Hosted Model-Weight Training

Use this only if an OpenAI organization or enterprise provider account can create fine-tuning jobs.

```powershell
python .\tools\openai_map_clue_finetune.py --create-job --base-model gpt-4.1-mini-2025-04-14
python .\tools\openai_map_clue_finetune.py --poll-job
```

After a successful run, the registry should contain a `fine_tuned_model`. That model can then be wired into the map clue rewrite provider as the generator model.

### 3. Open-Weight Training

If hosted fine-tuning remains blocked, the model-weight route is to train an open model such as Gemma with LoRA/QLoRA outside this app, then expose it through an OpenAI-compatible endpoint.

The current SFT JSONL already contains the key training signal, but an open-weight pipeline would need:

- a chosen base model and runtime;
- a conversion script from chat JSONL to that trainer's format;
- GPU access;
- an evaluation pass against `map_clue_eval_*.jsonl`;
- an OpenAI-compatible serving endpoint for the app.
