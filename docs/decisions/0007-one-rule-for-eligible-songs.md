---
id: "0007"
title: One rule decides which songs enter an analysis, with named exceptions
status: accepted
date: 2026-11-12
supersedes: null
---

# One rule decides which songs enter an analysis, with named exceptions

## Context

Each analysis had its own filter for which songs count. The filters differed, for example on re-releases, so the same question gave different samples. Some songs also enter by another path: for countries where the catalog route finds few songs, people collect songs by hand.

## Decision

One shared function decides whether a song is eligible, and it returns the reason. Every analysis calls it. No analysis writes its own filter.

Each song carries its entry route: `discogs` for the catalog route, `manual` for songs collected by hand. Exceptions to the rule are named groups in a tracked file under `resources/`. Each group has a country, a reason and a date, and no lyric text. An analysis reports how many of its songs entered by exception, per country.

## Consequences

- Samples are the same across analyses, and a paper can state the rule once.
- Results that used a looser filter change. The family analysis is one: it kept re-releases.
- A hand-collected song is visible as such in every result, not hidden inside the data.
