# Map Clue AI Rewrite Workflow

The live map game uses stored clue ladders from `map_place_pool`. AI rewriting is an explicit operator workflow:

1. Find active approved rows that fail the deterministic clue quality gate.
2. Ask the configured AI provider to write a new hard / medium / easy / reveal ladder.
3. Run the local clue critic.
4. By default, accept local-critic passes for bulk map rewrites to reduce free-tier API usage.
5. Optionally run the configured AI critic with `--critic-mode ai`.
6. Save only accepted rewrites back into `map_place_pool`.

This workflow does not train Gemini or change model weights. It learns operationally by using the curated place dataset, the map learning profile, and prior rejection feedback as prompt context. Failed local or AI critiques feed the next attempt for the same place, and recurring issues can be exported into the learning profile for later runs.

Rewrite runs now maintain an append-only failure log at `data/training/map_clue_failure_log.jsonl`. Each rejected clue attempt records the generated ladder, failure reasons, feedback, provider/model context, prompt/profile version, and machine-readable categories such as `weak_known_for_hook`, `location_based`, `unsupported_fact`, `too_long_for_mobile`, or `broad_multi_site_target`. Provider deferrals such as rate limits are logged for operations, but they are not treated as clue-writing negatives.

`refresh_map_learning_profile.py` reads both exported negative training rows and the failure log. It writes a timestamped candidate plus `data/training/map_learning_profile_latest.json`, which the generator uses by default when `MAP_LEARNING_PROFILE_PATH` is not set. That gives the next generation run targeted instructions without fine-tuning model weights.

Rejected rows are exported as negative learning examples even if they are inactive. This is deliberate: inactive broad targets still teach the generator which kinds of places and clue patterns to avoid.

The local quality gate now expects clue ladders to be about what a place is known for. Every playable clue must use a recognisable hook such as landmarks, history, culture, industry, architecture, institutions, events, nicknames, or famous products. A single weak clue that mainly says the place is a capital, large city, coastal city, near something, beside something, or on a river is rejected.

For enriched rows, the local gate also checks that each playable clue overlaps with the row's verified facts or nearby context. This does not prove every generated sentence is true, but it prevents the generator from inventing unsupported landmarks, industries, products, institutions, or events just to satisfy the known-for rule.

Broad UNESCO serial properties are held back until they are split into clearer pin targets. Examples include Ancient Thebes with its Necropolis, Ancient Villages of Northern Syria, Aflaj Irrigation Systems of Oman, Baekje Historic Areas, and Bagrati Cathedral and Gelati Monastery. Prefer replacements such as one temple, one monastery, one fort, one bridge, or one archaeological mound.

Clues are also held to a child-readable mobile style: one short sentence per clue, normally around 10-16 words, with tighter character limits than the live card. This is intentional; generated text should feel like a clear quiz clue, not an encyclopaedia sentence.

Dry-run first:

```powershell
python .\tools\rewrite_map_clues_with_ai.py --limit 10 --request-delay-sec 8 --max-attempts-per-place 2
```

The command writes a rewrite report and appends any rejected attempts to `data/training/map_clue_failure_log.jsonl`. To disable failure logging for a one-off diagnostic run:

```powershell
python .\tools\rewrite_map_clues_with_ai.py --limit 10 --no-failure-log
```

If the provider is rate-limited or timing out, run a conservative dry-run that records deferred candidates and stops after the first provider failure:

```powershell
python .\tools\rewrite_map_clues_with_ai.py --limit 10 --timeout-sec 45 --transient-retries 1 --request-delay-sec 30 --max-attempts-per-place 2 --retry-after-minutes 60
```

To let it wait and retry until the provider clears, add retry mode. Retry mode resumes remaining places within the same process instead of spending requests on already-collected accepted examples:

```powershell
python .\tools\rewrite_map_clues_with_ai.py --limit 10 --retry-until-processed --retry-sleep-minutes 60 --max-retry-attempts 0 --timeout-sec 45 --transient-retries 1 --request-delay-sec 30 --max-attempts-per-place 2 --retry-after-minutes 60
```

For a sampled AI review, use:

```powershell
python .\tools\rewrite_map_clues_with_ai.py --limit 3 --critic-mode ai --request-delay-sec 30 --max-attempts-per-place 2
```

Persist accepted rewrites:

```powershell
python .\tools\rewrite_map_clues_with_ai.py --limit 10 --save --request-delay-sec 8 --max-attempts-per-place 2
```

Reports use `deferred` for provider problems such as `HTTP 429`, sockets, or timeouts. Deferred rows are not counted as rejected clue rewrites and can be retried later.

Provider configuration uses the same environment variables as the daily quiz generator:

The command automatically loads `.env.local` by default. If `GEMINI_API_KEY` is present, the map rewrite tool uses `gemini-3.1-flash-lite` by default for both generation and optional AI critique. This intentionally differs from the daily quiz default of `gemini-3.5-flash` so bulk map rewrites use a lighter model.

```powershell
$env:GEMINI_API_KEY="..."
$env:MAP_CLUE_GENERATOR_MODEL="gemini-3.1-flash-lite"
$env:MAP_CLUE_CRITIC_MODEL="gemini-3.1-flash-lite"
```

or:

```powershell
$env:AI_PROVIDER="openai-compatible"
$env:AI_API_KEY="..."
$env:AI_BASE_URL="https://api.openai.com/v1"
$env:AI_GENERATOR_MODEL="..."
$env:AI_CRITIC_MODEL="..."
```

After saving rewrites, refresh the training artifacts and profile:

```powershell
python .\tools\export_map_clue_training_data.py
python .\tools\refresh_map_learning_profile.py
```

To build a profile from the failure log alone:

```powershell
python .\tools\refresh_map_learning_profile.py --no-negative-file --failure-log-file ".\data\training\map_clue_failure_log.jsonl"
```
