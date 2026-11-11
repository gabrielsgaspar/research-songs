---
id: "0001"
title: Changes reach main only through pull requests
status: accepted
date: 2026-11-11
supersedes: null
---

# Changes reach main only through pull requests

## Context

Several people and several coding agents change this repository. A wrong change to shared code or to a rule file can damage results that took weeks to build. A guard that runs only on one person's computer does not protect the branch.

## Decision

`main` accepts only pull requests. CI must pass: `ruff check`, `ruff format --check` and `pytest`. Gabriel merges. Nobody force-pushes or deletes `main`. Paths listed in `.github/CODEOWNERS` (rules, workflows, settings, dependencies, decisions) need Gabriel's review.

People and agents work on short branches. Agents never merge.

The project uses Python 3.14 and uv, with a committed `uv.lock`, so every computer and CI install the same packages.

## Consequences

- Every change has a visible diff, a passing test run and a reason.
- Small edits cost a pull request too. Batch small documentation edits with the task they belong to.
- The tests must stay fast and must run with no data, no network and no credentials. A slow or data-bound test carries a marker and does not run in CI.
