---
id: "0013"
title: A weekly learner keeps the rules and the documentation current
status: accepted
date: 2026-11-26
supersedes: null
---

# A weekly learner keeps the rules and the documentation current

## Context

Review comments often point out the same mistake more than once. The rule for that case says: add a check, not a sentence. Nobody does this work on a schedule, so it waits. The documentation also drifts from the code: commands, options, paths and column names change in `src/`, and the text in `README.md` and `docs/standards/` stays the same.

Gabriel wants this work done every week without his time, except to merge or close one pull request.

## Decision

1. `.github/workflows/weekly-learner.yml` runs every Monday at 09:17 UTC. It uses the same sandbox, tokens and job split as `agent-build.yml`. Its prompt is `prompts/roles/learner.md`.
2. The workflow first collects the last 7 days with `songs.common.weekly_learner gather`. Comments count only when their author has write access. When no pull request was merged and no commit landed, the run stops before the model starts.
3. The learner may change only `AGENTS.md`, `README.md`, `CONTRIBUTING.md`, `docs/standards/`, `resources/rules.toml` and test files. In test files it may only add lines. It may not change the Scope section of `AGENTS.md` or the rules on public data, Git and agents.
4. It adds at most 5 new or changed rules a week. Each one has a test named in `resources/rules.toml`. The count of checked rules never goes down, and the count of rules with no check never goes up.
5. `songs.common.weekly_learner check`, run from main in a separate checkout, enforces points 3 and 4 before anything is pushed. Then ruff and pytest run.
6. The workflow opens one pull request on a new branch, `learner/weekly-<date>`. It never force-pushes. It closes last week's learner pull request if that one is still open. A person merges.
7. The learner does not write decision files. It lists choices that need one in its pull request text.

## Consequences

- Each week brings at most one pull request. Its text names the pull requests and commits behind each change.
- The automation can only add checked rules, so the share of rules with no check goes down over time. The workflow gate in `tests/test_code_rules.py` stays in force for this workflow too.
- One model run costs money each week that had activity.
- A rule that only a person can judge does not enter `AGENTS.md` through the learner. It appears in the pull request text, and a person decides.
- `tests/test_docs_commands.py` now fails CI when a document names a `songs` command or option that does not exist.
