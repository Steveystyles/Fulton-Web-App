# Fulton backup catalog — 28 September 2026

This is a read-only catalog of `/disk2/backups/fultons-quiz` after the signed
deployment of commit `051a8327470df93444d91415b78d9ceb4ff89633`. The catalog
covers 26 `fultons-quiz-*` directories with 1,276,431,305 payload bytes. The
whole root reported 1.2 GiB and also contained the separate 2,460-byte
`map-rollout-20260907T112416Z/published-fingerprints.json`, which is outside the
Fulton database retention policy. No backup was changed, promoted or deleted
during this review.

`Verified` below means the repository's current `backup_manager.py verify`
accepted the complete directory. For protected legacy directories, `ok` records
only a manual, read-only artifact check: SQLite `PRAGMA quick_check`, `gzip -t`,
JSON parsing, or `sha256sum -c manifest.sha256`. A partial directory is not a
verified restore point even when one of its surviving artifacts is readable.

| Backup directory | Payload bytes | Current verifier | Database | Durable archive | Manifest | Manifest checksum |
|---|---:|---|---|---|---|---|
| `fultons-quiz-20260822T171139Z-91e33143` | 0 | Protected | — | — | — | — |
| `fultons-quiz-20260827T170045Z-91ee43f4` | 45,142,016 | Protected | ok | — | — | — |
| `fultons-quiz-20260827T173656Z-609237b8` | 0 | Protected | — | — | — | — |
| `fultons-quiz-20260829T000252Z-b2f83442` | 25,047,527 | Protected | — | ok | — | — |
| `fultons-quiz-20260829T005400Z-f1379a44` | 80 | Protected | — | — | — | invalid/incomplete |
| `fultons-quiz-20260907T112444Z-f7c5df72` | 59,855,658 | Protected | ok | — | ok | — |
| `fultons-quiz-20260907T130148Z-1e0f58d1` | 80 | Protected | — | — | — | invalid/incomplete |
| `fultons-quiz-20260908T185305Z-d7144b29` | 25,058,120 | Protected | — | ok | ok | — |
| `fultons-quiz-20260908T190318Z-67955c4e` | 25,058,121 | Protected | — | ok | ok | — |
| `fultons-quiz-20260910T122613Z-fe8aa344` | 25,058,199 | Protected | — | ok | ok | ok |
| `fultons-quiz-20260911T123645Z-553a5223` | 25,057,391 | Protected | — | ok | — | invalid/incomplete |
| `fultons-quiz-20260911T192225Z-dbc639d4` | 68,628,480 | Protected | ok | — | — | — |
| `fultons-quiz-20260920T004741Z-597399d6` | 112,311,112 | Protected | ok | ok | ok | — |
| `fultons-quiz-20260920T112832Z-739b2b87` | 115,091,486 | Protected | ok | ok | — | — |
| `fultons-quiz-20260920T114847Z-7ac1b0c4` | 25,057,310 | Protected | — | ok | — | — |
| `fultons-quiz-20260920T162553Z-f5ce87fa` | 115,301,272 | Verified | ok | ok | ok | ok |
| `fultons-quiz-20260920T162859Z-237385e0` | 0 | Protected | — | — | — | — |
| `fultons-quiz-20260920T184826Z-482d5bab` | 810 | Protected | — | — | ok | — |
| `fultons-quiz-20260921T032039Z-b3f9c22a` | 25,057,389 | Protected | — | ok | — | invalid/incomplete |
| `fultons-quiz-20260922T031739Z-9736447e` | 810 | Protected | — | — | ok | — |
| `fultons-quiz-20260923T031539Z-59eef611` | 810 | Protected | — | — | ok | — |
| `fultons-quiz-20260925T031906Z-48685a24` | 98,341,674 | Protected | ok | — | ok | — |
| `fultons-quiz-20260926T031728Z-6a50fab3` | 125,565,038 | Protected | ok | ok | — | invalid/incomplete |
| `fultons-quiz-20260927T031705Z-beb0f596` | 127,191,070 | Protected | ok | ok | — | — |
| `fultons-quiz-20260928T031738Z-187662cd` | 104,002,347 | Protected | ok | — | ok | — |
| `fultons-quiz-20260928T103325Z-da45f5a0` | 129,604,505 | Verified | ok | ok | ok | ok |

## Recovery reading

- Two complete directories pass the current verifier and are the preferred
  restore points.
- Sixteen protected legacy directories retain at least one readable recovery
  artifact. Nine contain a database that passes `quick_check`; eleven contain a
  durable-files archive that passes gzip validation; four contain both.
- Eight protected directories contain neither a database nor a durable-files
  archive. Metadata or a detached checksum alone is not a recovery point.
- The current retention policy keeps both verified directories and refuses to
  delete all 24 protected directories. Any future removal requires an explicit,
  separately reviewed decision; this catalog is evidence, not authorization.

