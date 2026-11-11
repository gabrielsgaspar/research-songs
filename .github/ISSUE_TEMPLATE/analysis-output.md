---
name: Analysis output
about: A figure, table, or estimate for the paper.
title: "Analysis: "
labels: []
---

## Output

The figure or table, and where it goes in the paper.

## Question

What the output must show, in one or two sentences.

## Data

Datasets used, by their catalog names. Sample limits (countries, years).

## Method

Estimator, fixed effects, clustering, or the plot type.

## Done when

1. The output is listed in the figure registry and follows `docs/standards/`.
2. The same inputs and code give the same file.
3. `uv run ruff check .`, `uv run ruff format --check .` and `uv run pytest` pass.
