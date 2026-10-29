# Map candidate funnel

**Goal:** Keep independently sourced, route-checked Map places available when one clue ladder or verifier verdict fails. Selection should consume these candidates before asking the model for fresh leads.

**Scope:** Map generation and tests only. No UI, backup, paid-tier, or publication changes.

## Design

The story-first discovery report becomes a durable batch of candidate cards: each resolved candidate and its exact checked story passage. A later run may resume a recent batch under the same independent clue and verifier gates. The selected/failed card is marked attempted; another card gets the next chance. Only a place-level failure excludes the place itself. Reports are read only from the configured report root with size and age limits, and a candidate already queued or used is ineligible.

## Tasks

1. Write a failing test showing a source-backed second candidate survives the first candidate's clue failure, then persist the candidate cards and attempted IDs in the report.
2. Write a failing test showing the next stocking run resumes the untried card without a fresh proposal/source/route call, then implement report recovery and resumed clue selection.
3. Write a failing test showing invalid or stale reports and queued places are not resumed, then enforce those boundaries.
4. Write a failing test showing clue-only failure does not blacklist the place, while truly bad source/identity failures still do; implement scoped exclusion.
5. Run focused and full tests. Replay saved unpublished failed runs where possible, and only then consider deployment.
