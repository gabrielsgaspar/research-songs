"""The weekly learner: gather last week's work, and check the learner's change.

    python -m songs.common.weekly_learner gather <folder>   # write context.json and src.diff
    python -m songs.common.weekly_learner check [<root>]    # check the change in a checkout

`gather` runs in `.github/workflows/weekly-learner.yml` with a read-only token. It
collects the pull requests merged in the last 7 days, their comments by people with
write access, the commits on main, the failed workflow runs on main, the open
learner pull request, and the diff of `src/`. It writes `idle=true` to GITHUB_OUTPUT
when no pull request was merged and no commit landed, so the workflow stops before
it starts a model.

`check` compares the working tree of a checkout with its HEAD. It returns the
problems that make the learner's change unusable: a path outside `ALLOWED_FILES`
and `ALLOWED_DIRS`, a deleted file or a deleted line in a test, a binary file, a
token, a change to a protected part of AGENTS.md, more than `MAX_NEW_RULES` new or
changed rules, a new rule with no test, or fewer checked rules than before.
"""

import json
import os
import re
import subprocess
import sys
import tomllib
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from songs.common import rules

DAYS = 7
DIFF_LIMIT = 200_000
MAX_NEW_RULES = 5
WRITE_PERMISSIONS = frozenset({"admin", "write"})
TRUSTED_BOTS = frozenset({"github-actions[bot]"})
LEARNER_BRANCH_PREFIX = "learner/weekly-"
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"

ALLOWED_FILES = frozenset({"AGENTS.md", "README.md", "CONTRIBUTING.md", "resources/rules.toml"})
ALLOWED_DIRS = ("docs/standards/",)
TEST_FILE = re.compile(r"tests/test_[a-z0-9_]+\.py")
FORBIDDEN_TESTS = frozenset(
    {
        "tests/test_repo_rules.py",
        "tests/test_code_rules.py",
        "tests/test_agent_roles.py",
        "tests/test_weekly_learner.py",
    }
)
PROTECTED_AGENTS_SECTIONS = ("Scope",)
PROTECTED_RULE_SECTIONS = ("This repository is public", "Git", "Agents")
TOKEN = re.compile(r"sk-ant-|gh[pousr]_[A-Za-z0-9]|github_pat_|-----BEGIN|ya29\.")

Run = Callable[[list[str]], str]


def run_command(args: list[str]) -> str:
    """Run a command and return its standard output. Raise CalledProcessError on failure."""
    done = subprocess.run(args, check=True, capture_output=True, text=True, encoding="utf-8")
    return done.stdout


# --- gather -----------------------------------------------------------------------


def _pages(text: str) -> list[dict]:
    """Flatten the output of `gh api --paginate --slurp`: a list of pages, each a list."""
    data = json.loads(text or "[]")
    return [item for page in data for item in (page if isinstance(page, list) else [page])]


class Trust:
    """Answer whether a login may speak to the learner: write access, or a trusted bot."""

    def __init__(self, run: Run, repo: str) -> None:
        self.run, self.repo, self.known = run, repo, {}

    def __call__(self, login: str) -> bool:
        if login in TRUSTED_BOTS:
            return True
        if login not in self.known:
            try:
                path = f"repos/{self.repo}/collaborators/{login}/permission"
                permission = self.run(["gh", "api", path, "--jq", ".permission"]).strip()
            except subprocess.CalledProcessError:
                permission = "none"
            self.known[login] = permission in WRITE_PERMISSIONS
        return self.known[login]


def pr_comments(run: Run, repo: str, number: int, trust: Trust, counts: dict) -> list[dict]:
    """Return the comments, reviews and line comments of one pull request by trusted authors."""
    kept = []
    sources = (
        ("review", f"repos/{repo}/pulls/{number}/reviews"),
        ("line", f"repos/{repo}/pulls/{number}/comments"),
        ("conversation", f"repos/{repo}/issues/{number}/comments"),
    )
    for kind, path in sources:
        for item in _pages(run(["gh", "api", "--paginate", "--slurp", path])):
            body = (item.get("body") or "").strip()
            login = (item.get("user") or {}).get("login", "")
            if not body:
                counts["comments_left_out_empty"] += 1
            elif not trust(login):
                counts["comments_left_out_untrusted_author"] += 1
            else:
                counts["comments_kept"] += 1
                entry = {"kind": kind, "author": login, "body": body}
                if kind == "line":
                    entry["path"] = item.get("path", "")
                if kind == "review":
                    entry["state"] = item.get("state", "")
                kept.append(entry)
    return kept


def cap(text: str, limit: int = DIFF_LIMIT) -> str:
    """Cut text to `limit` characters and say so at the end."""
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n[cut: the full text has {len(text)} characters; {limit} are shown]\n"


def gather(run: Run, repo: str, now: datetime) -> tuple[dict, str]:
    """Return the context of the last `DAYS` days and the capped diff of src/."""
    since = now - timedelta(days=DAYS)
    day, moment = f"{since:%Y-%m-%d}", since.isoformat()
    counts = {
        "pull_requests": 0,
        "comments_kept": 0,
        "comments_left_out_empty": 0,
        "comments_left_out_untrusted_author": 0,
        "commits": 0,
        "failed_runs": 0,
    }
    fields = "number,title,body,author,mergedAt,mergeCommit,files,url"
    found = json.loads(
        run(
            ["gh", "pr", "list", "--repo", repo, "--state", "merged"]
            + ["--search", f"merged:>={day}", "--limit", "100", "--json", fields]
        )
        or "[]"
    )
    trust = Trust(run, repo)
    pulls = []
    for pr in found:
        pulls.append(
            {
                "number": pr["number"],
                "title": pr.get("title", ""),
                "url": pr.get("url", ""),
                "merged_at": pr.get("mergedAt", ""),
                "merge_commit": (pr.get("mergeCommit") or {}).get("oid", ""),
                "author": (pr.get("author") or {}).get("login", ""),
                "body": (pr.get("body") or "")
                if trust((pr.get("author") or {}).get("login", ""))
                else "",
                "files": [f.get("path", "") for f in pr.get("files") or []],
                "comments": pr_comments(run, repo, pr["number"], trust, counts),
            }
        )
    counts["pull_requests"] = len(pulls)

    log = run(["git", "log", f"--since={moment}", "--format=%H%x09%s", "HEAD"])
    commits = [
        dict(zip(("sha", "subject"), line.split("\t", 1), strict=False))
        for line in log.splitlines()
        if line
    ]
    counts["commits"] = len(commits)

    base = run(["git", "rev-list", "-1", f"--before={moment}", "HEAD"]).strip() or EMPTY_TREE
    diff = cap(run(["git", "diff", "--no-color", "--no-ext-diff", base, "HEAD", "--", "src/"]))
    run_records = run(["git", "diff", "--name-only", base, "HEAD", "--", "countries/"]).split()

    failed = json.loads(
        run(
            ["gh", "run", "list", "--repo", repo, "--branch", "main", "--status", "failure"]
            + ["--created", f">={day}", "--limit", "50"]
            + ["--json", "workflowName,displayTitle,headSha,url,createdAt"]
        )
        or "[]"
    )
    counts["failed_runs"] = len(failed)

    open_prs = json.loads(
        run(
            ["gh", "pr", "list", "--repo", repo, "--state", "open", "--limit", "20"]
            + ["--json", "number,headRefName,body,url"]
        )
        or "[]"
    )
    previous = [p for p in open_prs if p.get("headRefName", "").startswith(LEARNER_BRANCH_PREFIX)]

    context = {
        "since": moment,
        "until": now.isoformat(),
        "base_commit": base,
        "counts": counts,
        "pull_requests": pulls,
        "commits": commits,
        "changed_country_files": run_records,
        "failed_runs_on_main": failed,
        "open_learner_pull_requests": previous,
        "src_diff_file": "src.diff",
    }
    return context, diff


def is_idle(context: dict) -> bool:
    """Return whether the week had no merged pull request and no commit."""
    return not context["pull_requests"] and not context["commits"]


def write_gather(folder: Path, context: dict, diff: str) -> None:
    """Write context.json and src.diff into `folder`."""
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / "context.json").open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(context, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    with (folder / "src.diff").open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(diff)


# --- check ------------------------------------------------------------------------


def path_problems(changes: list[tuple[str, str]], deleted_lines: dict[str, int]) -> list[str]:
    """Return problems with the changed paths. `changes` holds (git status letter, path)."""
    problems = []
    for status, path in changes:
        if status == "D":
            problems.append(f"{path}: the learner may not delete a file")
        elif TEST_FILE.fullmatch(path) and path not in FORBIDDEN_TESTS:
            if deleted_lines.get(path, 0):
                problems.append(f"{path}: the learner may add lines to a test, not delete them")
        elif path not in ALLOWED_FILES and not path.startswith(ALLOWED_DIRS):
            problems.append(f"{path}: outside the files the learner may change")
    return problems


def sections(text: str) -> dict[str, str]:
    """Return the text of each `## ` section of a Markdown file, by heading."""
    found, name = {}, ""
    for line in text.splitlines():
        if line.startswith("## "):
            name = line[3:]
        found[name] = found.get(name, "") + line + "\n"
    return found


def checked_count(texts: list[tuple[str, str]], checks: str) -> int:
    """Return how many rules a rules.toml text names, by the same prefix match as `rules`."""
    prefixes = [str(b.get("rule", "")) for b in tomllib.loads(checks).get("check", [])]
    return sum(1 for _, text in texts if any(p and text.startswith(p) for p in prefixes))


def rule_problems(
    old_agents: str, new_agents: str, old_checks: str, new_rules: list[rules.Rule]
) -> list[str]:
    """Return problems with the rule changes in AGENTS.md."""
    problems = []
    old_sections, new_sections = sections(old_agents), sections(new_agents)
    for name in PROTECTED_AGENTS_SECTIONS:
        if old_sections.get(name) != new_sections.get(name):
            problems.append(f"AGENTS.md: the learner may not change the section {name!r}")
    old = rules.parse_rule_texts(old_agents)
    new = [(rule.section, rule.text) for rule in new_rules]
    for section in PROTECTED_RULE_SECTIONS:
        if [t for s, t in old if s == section] != [t for s, t in new if s == section]:
            problems.append(f"AGENTS.md: the learner may not change the rules under {section!r}")
    added = [rule for rule in new_rules if (rule.section, rule.text) not in set(old)]
    if len(added) > MAX_NEW_RULES:
        problems.append(f"AGENTS.md: {len(added)} new or changed rules; at most {MAX_NEW_RULES}")
    problems += [
        f"AGENTS.md: the new rule {rule.text[:60]!r} has no test in resources/rules.toml"
        for rule in added
        if not rule.tests
    ]
    before = checked_count(old, old_checks)
    after = sum(1 for rule in new_rules if rule.tests)
    if after < before:
        problems.append(f"resources/rules.toml: {after} checked rules, fewer than {before} before")
    unchecked_before, unchecked_after = len(old) - before, len(new_rules) - after
    if unchecked_after > unchecked_before:
        problems.append(
            f"AGENTS.md: {unchecked_after} rules with no check, more than {unchecked_before} before"
        )
    return problems


def token_problems(added_lines: dict[str, list[str]]) -> list[str]:
    """Return a problem for each changed file with an added line that looks like a token."""
    return [
        f"{path}: an added line looks like a token or a key"
        for path, lines in added_lines.items()
        if any(TOKEN.search(line) for line in lines)
    ]


def _git(root: Path, *args: str) -> str:
    base = ["git", "-C", str(root), "-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null"]
    return run_command([*base, *args])


def check(root: Path) -> list[str]:
    """Return every problem with the change in the working tree of `root`, against its HEAD.

    New files are marked with `git add --intent-to-add`, so the diff against HEAD shows them.
    """
    _git(root, "add", "--all", "--intent-to-add")
    changes = []
    for line in _git(root, "diff", "HEAD", "--name-status", "--no-renames").splitlines():
        status, _, path = line.partition("\t")
        changes.append((status[:1], path))
    deleted, binary = {}, []
    for line in _git(root, "diff", "HEAD", "--numstat", "--no-renames").splitlines():
        plus, minus, path = line.split("\t", 2)
        if plus == "-" or minus == "-":
            binary.append(path)
        else:
            deleted[path] = int(minus)
    added: dict[str, list[str]] = {}
    for _, path in changes:
        patch = _git(root, "diff", "HEAD", "--no-color", "--unified=0", "--", path)
        added[path] = [
            line[1:]
            for line in patch.splitlines()
            if line.startswith("+") and not line.startswith("+++")
        ]
    problems = path_problems(changes, deleted)
    problems += [f"{path}: a binary change" for path in binary]
    problems += token_problems(added)
    try:
        new_rules = rules.load_rules(root)
    except ValueError as error:
        return [*problems, str(error)]
    problems += rule_problems(
        _git(root, "show", "HEAD:AGENTS.md"),
        (root / "AGENTS.md").read_text(encoding="utf-8"),
        _git(root, "show", f"HEAD:{rules.CHECKS_FILE.as_posix()}"),
        new_rules,
    )
    return problems


# --- command line -----------------------------------------------------------------


def main(argv: list[str]) -> int:
    if len(argv) == 2 and argv[0] == "gather":
        repo = os.environ["GH_REPO"]
        context, diff = gather(run_command, repo, datetime.now(UTC))
        write_gather(Path(argv[1]), context, diff)
        idle = is_idle(context)
        counts = ", ".join(f"{key} {value}" for key, value in context["counts"].items())
        print(f"gathered {counts}; idle {str(idle).lower()}")
        target = os.environ.get("GITHUB_OUTPUT")
        if target:
            with open(target, "a", encoding="utf-8", newline="\n") as handle:
                handle.write(f"idle={str(idle).lower()}\n")
        return 0
    if argv[:1] == ["check"] and len(argv) <= 2:
        root = Path(argv[1] if len(argv) == 2 else ".").resolve()
        problems = check(root)
        for problem in problems:
            print(f"problem: {problem}")
        print(
            "the change passes the learner check" if not problems else f"{len(problems)} problem(s)"
        )
        return 1 if problems else 0
    print(
        "usage: python -m songs.common.weekly_learner gather <folder> | check [<root>]",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
