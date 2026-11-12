---
id: "0008"
title: Analysis code is one module per method, in Python where possible
status: accepted
date: 2026-11-12
supersedes: null
---

# Analysis code is one module per method, in Python where possible

## Context

The analysis code grew by adding a new file for each new specification. Local projections alone had nine files that differed only in options. Regressions ran in R, which is one more tool to install and keep in step.

## Decision

- One module per method (regressions, local projections, synthetic control, factors), with options in place of copies.
- Regressions run in Python with `pyfixest`. R is used only where no Python tool gives the same result: the prediction intervals for synthetic control (`scpi`).
- One generation of the factor model is kept: the one behind the current results.
- Topic labels, families and colors come only from `songs.stage_30_topics.topic_ids` and `songs.common.plot_style`. Topic T27 is in family G.

## Consequences

- Less code to read and test, and one place to add a specification.
- Standard errors from `pyfixest` can differ slightly from the earlier R results. A port must compare them and report the difference.
- R stays a requirement for one job, and that job cannot run in CI until R is set up there.
