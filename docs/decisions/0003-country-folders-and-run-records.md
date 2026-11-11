---
id: "0003"
title: One folder and one run history per country
status: accepted
date: 2026-11-11
supersedes: null
---

# One folder and one run history per country

## Context

Lyrics are collected country by country, through several routes: live collection from sites, bulk files, whole-site archives and fallback sources. Without one record of what ran, people repeat work, and nobody can say later which source and which limits produced a country's songs.

## Decision

Collection work is organized by country. Each country has one folder named by its ISO3 code:

```
countries/<ISO3>/
  country.yaml    target, allowed routes, limits, current state
  runs/           one JSON file per collection run
  notes.md        known gaps and their causes
```

Every collection command writes one run record when it ends: country, start and end time, route, source, the path of any bulk file used, request delay, artist and song limits, deadline, code commit, rows added, and known gaps. Nobody writes a record by hand.

Before a run, the command shows the earlier runs for the same country and route. Collection code is shared across countries, one module per route. Code for a single country exists only when that country needs it.

A campaign is a route applied to a list of countries. Each country still gets its own record.

## Consequences

- "What did we do for this country, and how?" has one answer in one place.
- A status page for all countries can be generated from the records.
- A run that crashes before its end writes no record. Each route must write the record in a `finally` step with the state it reached.
