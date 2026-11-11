---
id: "0002"
title: A public repository with private data
status: accepted
date: 2026-11-11
supersedes: null
---

# A public repository with private data

## Context

Open code makes the research easier to check and to reproduce. The data cannot be open in the same way: song lyrics belong to their owners, and some working files hold details of private resources or of people.

## Decision

The repository is public. These things never go into it, in any file, issue or commit message:

- lyric text;
- data files, except small invented fixtures for tests;
- credentials, tokens and keys;
- email addresses and other personal details;
- identifiers of private resources (cloud project ids, bucket names, spreadsheet ids).

Data lives in a local data folder and in cloud storage. Code finds the local folder through `SONGS_DATA_ROOT` and reads every other identifier from environment variables. The paper lives in `overleaf/`, which is local only.

Tests enforce what a machine can check: no data files outside `tests/fixtures/`, fixtures under 200 KB, no email addresses, and a `.gitignore` that blocks the local folders. GitHub secret scanning with push protection covers credentials.

## Consequences

- Anyone can read, run and check the code.
- A push is permanent in practice. When in doubt, leave it out and ask.
- A fixture cannot be cut from real lyric pages. It must use invented text with the same structure.
- No test can recognize lyric text in general. Review of every pull request is the control for that rule.
