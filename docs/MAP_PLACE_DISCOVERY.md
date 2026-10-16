# Place discovery AI

`tools/discover_map_places.py` proposes new places beyond the starter catalogue, retrieves evidence, selects a candidate and writes three clues. It uses the dedicated `MAP_AI_API_KEY` and Gemini first. If the separately configured `AI_FALLBACK2_PROVIDER=openrouter`, both fallback model variables equal `openrouter/free`, and `AI_FALLBACK2_API_KEY` is present, it retries a Gemini 429/5xx/timeout once through that free-model route. Other errors do not switch providers; paid model names are never accepted for this Map fallback. Every provider attempt consumes the persistent request budget. The same source and editorial checks apply regardless of which model answered.

This is a separate discovery and review command. The deployed daily scheduler continues using its reviewed catalogue. Discovery does not publish games, alter scores, update training feedback or enable the unrelated quiz candidate pipeline.

## What the selector does

1. Reads the requested date and recent place history through a read-only database connection. Published dates are rejected before any model request.
2. Asks Gemini for three varied landmark proposals, including Wikipedia titles for the target and two nearby search-area centres. Existing catalogue places and recent answers are excluded. Broad regions, private homes, demolished structures and stadiums are excluded from this initial discovery version.
3. Retrieves the exact target, city and local-feature articles from the fixed English Wikipedia API. It rejects missing and disambiguation pages, missing coordinates, duplicate identities, recent place types and broad or unusable map areas.
4. Retrieves the linked Wikidata entity and country. Target coordinates must agree within 250 metres. This is a cross-dataset consistency check: Wikipedia and Wikidata may share sources, so it is not independent survey verification.
5. Makes one further AI request to choose the best supported place and write hard, medium and easy clues. The proposed hook remains an unverified hypothesis: source passages matching it are included even when they occur beyond the article introduction. When there is a strong source match, the hard clue must cite that story and remain about it; an unrelated easy-to-source fact is rejected. Each clue cites 1–3 IDs for retrieved article passages. Code copies the original passages into the report; the model does not retype quotations. Geographic passages must name the corresponding map area. Unsupported numbers, answer leaks and failures of the existing clue and map checks are rejected.
6. Writes a JSON evidence report and readable Markdown review, including source revisions, quotations, rejection reasons, request counts, model usage and a hash of the selected candidate.

The AI chooses proposals and the final candidate. Code obtains target coordinates and creates nested map search circles; the model cannot invent map geometry. The three clue stages remain compatible with the existing player interface.

## Run discovery

From the application directory, with `MAP_AI_API_KEY` privately configured:

```powershell
python tools/discover_map_places.py --source-db data/fultons.db --date 2026-09-10
```

Choose an unused date. The command reads `.env.local` by default; on a production container the credential is already in its private process environment. `MAP_AI_MODEL` selects the configured model, defaulting to `gemini-3.5-flash-lite`.

Outputs default to `data/qa/map-discovery/discovery-YYYY-MM-DD.json` and `.md`. A successful machine-checked candidate has status `needs_source_review`, not `published`, `verified_true` or `approved`. Failed discovery reports remain available and no stored fallback is presented as fresh discovery.

The Docker build includes the command. It is not scheduled automatically. A container invocation can use `/app/data/fultons.db` and `/app/data/qa/map-discovery`; public source retrieval happens on that server, so discovery does not depend on a developer's local place file or browser session.

## Review and connect to daily selection

Check the source-supported story, important qualifiers, current existence, identity, aliases, place type and practical phone-map placement. Wikipedia quotations establish traceability, not semantic truth; a copied quote does not prove the model interpreted it correctly. Check an authoritative source for the important recognition claim before accepting it. The current tool does not autonomously establish independent primary-source confirmation.

After reviewing the exact candidate, add it to a working copy of the reviewed catalogue:

```powershell
python tools/discover_map_places.py --reviewed-report data/qa/map-discovery/discovery-2026-09-10.json --reviewed-sha256 <candidate_sha256_from_report> --catalog deploy/map-evidence-catalog.json
```

This explicit operator action reruns validation, checks the exact candidate hash, rejects source retrieval older than seven days and duplicate entries, then atomically extends the catalogue. It does not call an AI or publish a game. Pending candidates are rejected by the runtime catalogue loader. Existing hand-reviewed starter entries remain compatible.

Catalogue changes then follow the normal reviewed Git/CI/signed-image deployment process in `DEPLOYMENT.md`. Once deployed, the existing daily AI can choose the new place and generate clues from its reviewed facts. Existing published rounds remain unchanged.

## Request and security boundaries

- At most two Gemini attempts per discovery date and 16 public source HTTP requests. There are no automatic retries or search-grounding tools. A provider error stops model work immediately.
- A persistent SQLite ledger reserves the date before network work and increments counters before each attempt. Restarting after a failure or crash does not silently reset the slot. Inspect the report or ledger instead of deleting it to repeat a failing attempt.
- Limits are scoped to this discovery ledger and target date. They are not an account-wide spend cap; another output directory, other dates or the production scheduler have separate usage. There is no automatic daily replenishment loop in this release.
- Each model prompt is limited to 36,000 characters and each response requests at most 4,096 output tokens. Character counts are not token guarantees. Actual usage is recorded when supplied by the provider.
- Source requests use HTTPS to two fixed hosts, ignore model-supplied URLs, reject redirects, have a 20-second timeout and read at most 2 MB. Source text is untrusted data, never executable instructions.
- The first Gemini prompt contains recent place names, types and dates and existing catalogue names. The second contains retrieved public article excerpts, public place metadata and map-area geometry. User identities, guesses, scores and API keys are not prompt content.
- Source snapshots and generated text stay in private QA output. Markdown model text is indented as inert text. Reports redact provider credentials from errors.
- Wikipedia extracts retain revision links and CC BY-SA attribution; Wikidata structured data is CC0. These sources share an ecosystem and must not be described as two independent factual confirmations.

## Validation status

Offline tests cover persistent budgets, provider failures and credential isolation, fixed-host fetching and response bounds, title injection, exact quotations, unsupported numbers, source-derived geometry, duplicate identities, cooldowns, promotion hashes, pending-candidate rejection and publication through the real game serializer after review.

All 634 server tests completed successfully (one expected skip), including 20 discovery tests. Bandit 1.9.4 passed the existing baseline gate: 39 existing reviewed findings, no new findings, all 53 required production Python files scanned.

The user authorized live testing with the map key and the history-only exclusion payload. Six bounded evaluations were retained:

| Target date | AI requests | Outcome |
| --- | --- | --- |
| 2026-09-10 | 1 | Failed: missing Wikidata revision metadata. Added the `info` property. |
| 2026-09-11 | 2 | Failed: shortened article omitted the local feature. Removed the API's capped `exchars` parameter and narrowed country-data retrieval. |
| 2026-09-12 | 2 | Rejected: easy clue lacked useful city-sector guidance. Clarified role requirements. |
| 2026-09-13 | 2 | Rejected: model altered supporting quotations. Replaced quotation generation with source-passage IDs. |
| 2026-09-14 | 2 | Rejected: answer leakage and poor easy clue. Added a role example and explicit final checks. |
| 2026-09-15 | 2 | Passed automated checks: selected Tower Bridge outside the starter catalogue, with all three clues; 3,228 total tokens. |

No counter or acceptance threshold was reset to convert a failure into a pass. The successful saved model response was replayed through the real publisher in a disposable copy of SQLite, without another API request. It published successfully and the real player serializer returned 1/2/3 clues and 0/1/2 map areas, with no answer result disclosed. Production games and the runtime catalogue were unchanged.

Assistant source review checked the recognition hook against the [bridge owner's account](https://www.citybridgefoundation.org.uk/news-and-blog/london-bridge-buyers-grandson-quashes-wrong-bridge-myth) and [Tower Bridge's official comparison](https://www.towerbridge.org.uk/stories/tower-bridge-vs-london-bridge). The clue correctly describes an urban legend; the buyer did not actually purchase the wrong bridge. The official site also supports the upstream relationship and proximity to the Tower of London. This is an assistant source check, not a claim of human approval or a broad quality qualification.

Reports remain under `data/qa/map-discovery/`, including `discovery-2026-09-15.json`, its Markdown review and `discovery-publication-check-2026-09-15.json`. The selector remains a reviewed discovery command, not an automatically approved daily replenishment system. More varied successful samples are needed before considering unattended promotion.

API references: [MediaWiki REST and API documentation](https://www.mediawiki.org/wiki/API:Main_page), [Wikidata data access](https://www.wikidata.org/wiki/Wikidata:Data_access).

## Reviewed publication addition

The user authorized publishing this release. The catalogue now includes the source-checked Tower Bridge entry, bringing it to six places. Its recognition fact cites both the official Tower Bridge comparison and City Bridge Foundation account. A regression check requires generated clues to preserve the myth/legend qualifier. The discovery command remains review-gated; this does not enable unattended candidate promotion.
