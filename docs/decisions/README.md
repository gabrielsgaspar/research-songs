# Decisions

One file per decision: `NNNN-short-title.md`. A decision records a real choice and its reason, so nobody has to ask again. Gabriel accepts every decision; this folder has a code owner.

Each file starts with this front matter:

```
---
id: "0001"
title: Short title
status: accepted
date: 2026-11-11
supersedes: null
---
```

`status` is `proposed`, `accepted` or `superseded`. A decision is never edited to mean something new. A new decision supersedes it.

Then three sections: **Context** (the problem), **Decision** (what we do), **Consequences** (what follows, including the costs).

| id | Title | Status | Date |
| --- | --- | --- | --- |
| 0001 | [Changes reach main only through pull requests](0001-pull-requests-only.md) | accepted | 2026-11-11 |
| 0002 | [A public repository with private data](0002-public-repository-private-data.md) | accepted | 2026-11-11 |
| 0003 | [One folder and one run history per country](0003-country-folders-and-run-records.md) | accepted | 2026-11-11 |
| 0004 | [The paper and the presentation share one exhibits folder](0004-paper-presentation-and-exhibits.md) | accepted | 2026-11-12 |
| 0005 | [Songs are scored on topics only, with one fixed model and prompt](0005-topic-scoring-model-and-prompt.md) | accepted | 2026-11-12 |
| 0006 | [One file says where every external variable comes from](0006-one-file-for-external-data-sources.md) | accepted | 2026-11-12 |
| 0007 | [One rule decides which songs enter an analysis, with named exceptions](0007-one-rule-for-eligible-songs.md) | accepted | 2026-11-12 |
| 0008 | [Analysis code is one module per method, in Python where possible](0008-analysis-code-shape.md) | accepted | 2026-11-12 |
