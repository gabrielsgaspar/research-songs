---
id: "0004"
title: The paper and the presentation share one exhibits folder
status: accepted
date: 2026-11-12
supersedes: null
---

# The paper and the presentation share one exhibits folder

## Context

The project has two documents: a paper and a presentation. The presentation is ahead of the paper. It is where results are put together first, so it shows what the project uses today. Both documents live in `overleaf/`, which is local and never in Git. Figures and tables need a home that is not inside a document.

## Decision

Both documents are in scope. Analysis code that serves only the presentation is as live as code that serves the paper.

Every figure and table that a document uses is an exhibit. Exhibits live in one tracked folder:

```
exhibits/
  figures/    PNG files at 300 dpi
  tables/     tables as text files
```

Code writes every exhibit. Nobody edits one by hand. `overleaf/` stays local and ignored by Git; the documents read copies of the exhibits. Trial figures and other scratch results go to `outputs/`, which stays local.

## Consequences

- A reader of the repository sees the current results without the data.
- A change to a result shows up as a changed file in a pull request.
- The repository grows with every regenerated figure. A list of exhibits, with the command that makes each one and the document that uses it, arrives with the first exhibit.
- An exhibit must hold no lyric text and no private identifier, because the repository is public.
