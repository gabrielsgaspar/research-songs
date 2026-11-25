---
id: "0012"
title: Each topic scoring run leaves a tracked record per country
status: accepted
date: 2026-11-25
supersedes: null
---

# Each topic scoring run leaves a tracked record per country

## Context

A collection run writes a run record in `countries/<ISO3>/runs/` (decision 0003). A topic scoring run had no record in Git. Its working files are in `staging/scoring/` of the data folder, which never goes to the bucket, and its result is only in the manifest of the new scores folder. So the repository did not show which runs scored a country, with which prompt, at which cost estimate.

A scoring run is not a campaign. Its result is decided by the songs it is given, so it has no open goal and no "next time" note.

## Decision

1. `songs score collect` writes one record for each country of the run: `countries/<ISO3>/scoring/<run id>.json`.
2. The record holds the prompt hash, the model, the decades, the batch state, the collection time, the code commit, the requests and the cost estimate in US dollars of the whole run, the scores folder, the counts of `prepare` for the country and the counts of `collect` for the country.
3. The record is written by code, never by hand, and never overwritten. It holds no lyric text and no bucket name.
4. A `prepare` that only copies scores, with no request, writes no record. Its manifest records the copies.

## Consequences

- The history of scoring for a country is in Git next to its collection history.
- A person commits the new records after each collected run, with `docs/status/scoring.md` (step 9 of `prompts/scoring/README.md`).
- The record gives the estimate, not the billed cost. The billed cost is on the OpenAI account.
