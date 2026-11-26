# Agent roles

Three agents work on GitHub issues in this repository, and a fourth runs once a week. Each one runs in its own workflow, with its own limits. A person starts each issue stage with a label, and a person merges.

| Role | Instructions | Starts when | May | May not |
| --- | --- | --- | --- | --- |
| planner | `planner.md`, loaded by `.github/workflows/agent-plan.yml` | A person with write access adds the label `agent-plan` to an issue | Read the repository and `git log`. Return one plan with its file list. | Change a file, label, issue or setting. Plan work that `AGENTS.md` puts out of scope. |
| builder | `builder.md`, loaded by `.github/workflows/agent-build.yml` | A person with write access adds the label `agent-build` to an issue that has a plan | Edit the files the plan lists. Run `uv sync --all-groups`, ruff, pytest and a few git commands. Commit. | Touch a file outside the plan. Push, use the network, or add a dependency. |
| reviewer | `reviewer.md`, loaded by `.github/workflows/agent-review.yml` | CI passes on a pull request that the builder opened | Read the diff, the checkout of `main` and `git log`. Return a verdict and a list of items to fix. | Change anything, run the code, approve or merge. |
| learner | `learner.md`, loaded by `.github/workflows/weekly-learner.yml` | Every Monday at 09:17 UTC, or by hand from the Actions tab. It stops before the model runs when the last 7 days had no merged pull request and no commit. | Read the last 7 days of work. Fix stale text in `README.md`, `CONTRIBUTING.md` and `docs/standards/`. Add at most 5 rules to `AGENTS.md`, each with a test in `tests/` and an entry in `resources/rules.toml`. | Change any other file, delete a file or a test line, or change the Scope section or the rules on public data, Git and agents. `songs.common.weekly_learner check` refuses such a change before anything is pushed. |

## The flow

1. Write an issue. Say what must be true when the work is done.
2. Add the label `agent-plan`. The planner writes one comment: a plan, a list of questions, or "out of scope".
3. Read the plan. If it is right, add the label `agent-build`. If it is wrong, edit the issue and add `agent-plan` again.
4. The builder writes the code on the branch `agent/issue-<number>`. Plain checks then test every commit: only files from the plan, no secrets, ruff, pytest. The `songs-agent` App pushes the branch and opens a pull request.
5. CI runs. When it passes, the reviewer writes one comment on the pull request. If it asks for changes, the builder gets up to 3 fix rounds.
6. The pull request gets the label `agent-approved` or `needs-human`. A person reviews and merges. No workflow merges.

When a stage stops, it writes the cause in a comment and adds the label `needs-human`.

## The weekly learner

1. On Monday, the learner reads the pull requests merged in the last 7 days, their comments by people with write access, the commits and failed runs on main, and the diff of `src/`.
2. It opens one pull request on the branch `learner/weekly-<date>`. The text says what changed and why, with pull request numbers and commit SHAs.
3. CI runs. Read the text, then merge or close. If last week's learner pull request is still open, the new one closes it, and the learner gets its text as input.

## Role files

Each role file has a short front matter and a body:

- `role`: planner, builder, reviewer or learner.
- `model`: the model the workflow runs.
- `max_turns`: the turn limit, a whole number from 1 to 200.
- `workflow`: the workflow that loads it.
- `notes` (optional): one line each, the history behind a value.

The body is the prompt, exactly as the agent receives it. Each workflow runs `python3 -I src/songs/common/roles.py <role>` on its checkout of `main` just before Claude starts, and passes the model, the turn limit and the prompt to the Claude step. Everything else (tools, permissions, sandbox, output format, tokens) stays in the workflow.

Only Gabriel changes this folder: `.github/CODEOWNERS` lists it, and the build refuses a change to it.

## What the workflows need on GitHub

| Name | Kind | Use |
| --- | --- | --- |
| `CLAUDE_CODE_OAUTH_TOKEN` | secret | Runs Claude in the four workflows |
| `AGENT_APP_PRIVATE_KEY` | secret | Key of the `songs-agent` GitHub App, which pushes the branch and opens the pull request |
| `AGENT_APP_CLIENT_ID` | variable | Client ID of the App |
| `agent-plan`, `agent-build`, `agent-approved`, `needs-human` | labels | Start a stage or show its result |

The App has read and write access to contents, pull requests and issues, and no access to workflows. GitHub therefore refuses any push from it that changes `.github/workflows/`.
