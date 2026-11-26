"""The rule table: each rule of AGENTS.md next to the tests that check it.

AGENTS.md holds the rules as list items under "## Rules". `resources/rules.toml`
names the tests that check a rule. A rule with no entry there is "not checked":
nothing fails when someone breaks it.

    python -m songs.common.rules            # print the page
    python -m songs.common.rules --write    # write docs/standards/rules.md
"""

import ast
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

from songs.common.paths import resolve_project_root

RULES_SOURCE = Path("AGENTS.md")
CHECKS_FILE = Path("resources") / "rules.toml"
RULES_PAGE = Path("docs") / "standards" / "rules.md"
REQUIRED = ("rule", "tests")
OPTIONAL = ("part",)


@dataclass(frozen=True)
class Rule:
    """One rule of AGENTS.md and the tests that check it."""

    section: str
    text: str
    tests: tuple[str, ...] = ()
    part: str = ""


def read_rule_texts(root: Path) -> list[tuple[str, str]]:
    """Return (section, rule text) for every list item under "## Rules" in AGENTS.md."""
    return parse_rule_texts((root / RULES_SOURCE).read_text(encoding="utf-8"))


def parse_rule_texts(text: str) -> list[tuple[str, str]]:
    """Return (section, rule text) for every list item under "## Rules" in an AGENTS.md text."""
    rules, section, inside = [], "", False
    for line in text.splitlines():
        if line.startswith("## "):
            inside = line == "## Rules"
        elif inside and line.startswith("### "):
            section = line[4:]
        elif inside and line.startswith("- "):
            rules.append((section, line[2:]))
    return rules


def test_exists(root: Path, test: str) -> bool:
    """Return whether `tests/test_x.py::test_name` names a test function in the repository."""
    file, _, name = test.partition("::")
    path = root / file
    if not name or not path.is_file():
        return False
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return any(isinstance(node, ast.FunctionDef) and node.name == name for node in tree.body)


def load_rules(root: Path | None = None) -> list[Rule]:
    """Return every rule of AGENTS.md with its tests. Raise ValueError on a bad checks file."""
    base = resolve_project_root(root)
    texts = read_rule_texts(base)
    blocks = tomllib.loads((base / CHECKS_FILE).read_text(encoding="utf-8")).get("check", [])
    problems, found = [], {}
    for block in blocks:
        name = str(block.get("rule", "(no rule)"))
        missing = [key for key in REQUIRED if key not in block]
        unknown = sorted(set(block) - set(REQUIRED) - set(OPTIONAL))
        if missing or unknown:
            problems.append(f"{name!r}: missing {missing}, unknown {unknown}")
            continue
        matches = [index for index, (_, text) in enumerate(texts) if text.startswith(name)]
        if len(matches) != 1:
            problems.append(f"{name!r}: starts {len(matches)} rules of AGENTS.md, must start one")
            continue
        if matches[0] in found:
            problems.append(f"{name!r}: this rule has two entries")
        if not block["tests"]:
            problems.append(f"{name!r}: an entry names at least one test")
        problems += [
            f"{name!r}: no such test {test}"
            for test in block["tests"]
            if not test_exists(base, test)
        ]
        found[matches[0]] = block
    if problems:
        raise ValueError(f"{CHECKS_FILE.as_posix()}: " + "; ".join(problems))
    return [
        Rule(
            section,
            text,
            tuple(found[index]["tests"]) if index in found else (),
            found[index].get("part", "") if index in found else "",
        )
        for index, (section, text) in enumerate(texts)
    ]


def render_rules_markdown(rules: list[Rule]) -> str:
    """Return the text of docs/standards/rules.md."""
    full = sum(1 for rule in rules if rule.tests and not rule.part)
    part = sum(1 for rule in rules if rule.part)
    lines = [
        "# Rules and their checks",
        "",
        f"This page is generated from `{RULES_SOURCE.as_posix()}` and "
        f"`{CHECKS_FILE.as_posix()}`. Do not edit it by hand.",
        "",
        "To rebuild it, run `python -m songs.common.rules --write`.",
        "",
        "It answers one question: what fails when someone breaks a rule? "
        'A rule that is "not checked" depends on the reader. Nothing fails when it is broken.',
        "",
        "| Status | Rules |",
        "| --- | --- |",
        f"| Checked | {full} |",
        f"| Partly checked | {part} |",
        f"| Not checked | {len(rules) - full - part} |",
        "",
        "When you add a rule to `AGENTS.md`, add a test for it and name the test in "
        f"`{CHECKS_FILE.as_posix()}`. If no test can check the rule, it stays not checked.",
    ]
    for section in dict.fromkeys(rule.section for rule in rules):
        lines += ["", f"## {section}", "", "| Rule | Checked by |", "| --- | --- |"]
        for rule in rules:
            if rule.section != section:
                continue
            tests = "<br>".join(f"`{test}`" for test in rule.tests) or "not checked"
            if rule.part:
                tests = f"Partly: {rule.part}<br>{tests}"
            lines.append(f"| {rule.text.replace('|', '\\|')} | {tests} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    """Print the page, or write it with --write."""
    text = render_rules_markdown(load_rules())
    if argv == ["--write"]:
        page = resolve_project_root() / RULES_PAGE
        with page.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
