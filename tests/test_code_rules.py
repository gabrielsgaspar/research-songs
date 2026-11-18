"""Rules of AGENTS.md that a search of the code can check, and the rule table itself.

Each check is a function that reads one file and returns the problems it finds.
`test_each_check_catches_a_bad_example` proves that every check fails on a bad file.
"""

import ast
import io
import json
import re
import subprocess
import tokenize
from collections.abc import Callable
from pathlib import Path

import pytest

from songs.common import rules
from songs.common.data_sources import load_sources
from songs.stage_30_topics import topic_ids

ROOT = Path(__file__).resolve().parents[1]
SRC = "src/songs/"
ABSOLUTE_PATH = re.compile(r"[A-Za-z]:[\\/]|/(Users|home)/")
BUCKET_ADDRESS = re.compile(r"gs://[A-Za-z0-9]")


def tracked(prefix: str = "", suffix: str = "") -> list[str]:
    """Every file Git tracks or would track, under a prefix and with a suffix."""
    out = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    ).stdout
    return [
        line
        for line in out.splitlines()
        if line.startswith(prefix) and line.endswith(suffix) and (ROOT / line).is_file()
    ]


def strings(text: str) -> list[tuple[int, str]]:
    """Every string in Python source, with its line. Docstrings and f-string parts count."""
    return [
        (node.lineno, node.value)
        for node in ast.walk(ast.parse(text))
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]


def figure_saved_without_save_png(path: str, text: str) -> list[str]:
    if path.endswith("common/plot_style.py"):
        return []
    return [
        f"{path}:{node.lineno} calls savefig; save a figure with "
        "songs.common.plot_style.save_png, which sets PNG and 300 dpi"
        for node in ast.walk(ast.parse(text))
        if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "savefig"
    ]


def topic_text_typed_by_hand(path: str, text: str) -> list[str]:
    typed = {*topic_ids.TOPIC_LABELS.values(), *topic_ids.TOPIC_DEFINITIONS.values()}
    return [
        f"{path}:{line} types a topic label or definition; take it from "
        "songs.stage_30_topics.topic_ids (the text lives in resources/topics.toml)"
        for line, value in strings(text)
        if value in typed
    ]


def absolute_path_in_code(path: str, text: str) -> list[str]:
    return [
        f"{path}:{line} holds an absolute path; ask songs.common.paths.data_root() "
        "for the data folder (it reads SONGS_DATA_ROOT)"
        for line, value in strings(text)
        if ABSOLUTE_PATH.match(value)
    ]


def data_folder_built_by_hand(path: str, text: str) -> list[str]:
    if path.endswith("common/paths.py"):
        return []
    problems = []
    for node in ast.walk(ast.parse(text)):
        joined = isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div) and node.right
        only = (
            isinstance(node, ast.Call)
            and getattr(node.func, "id", "") == "Path"
            and len(node.args) == 1
            and node.args[0]
        )
        for part in (joined, only):
            if isinstance(part, ast.Constant) and part.value == "data":
                problems.append(
                    f'{path}:{node.lineno} builds a "data" folder by hand; '
                    "ask songs.common.paths.data_root() for the data folder"
                )
    return problems


def retired_source_named(path: str, text: str) -> list[str]:
    retired = {source.id for source in load_sources() if source.status == "retired"}
    return [
        f"{path}:{line} names the retired source {value}; "
        "ask songs.common.data_sources.canonical(concept) for the source to use"
        for line, value in strings(text)
        if value in retired
    ]


def bucket_named(path: str, text: str) -> list[str]:
    if path.startswith("tests/"):
        return []  # tests use invented names to show what the code refuses
    return [
        f"{path}:{number} names a storage bucket; read the name from SONGS_GCS_BUCKET"
        for number, line in enumerate(text.splitlines(), start=1)
        if BUCKET_ADDRESS.search(line)
    ]


MARKDOWN_START = re.compile(r"\s*([-*+>|#<]|\d+\.|---)")
LIST_ITEM = re.compile(r"\s*([-*+]|\d+\.)\s")


def paragraph_hard_wrapped(path: str, text: str) -> list[str]:
    if path.startswith(".claude/"):
        return []  # skills keep the layout of their authors
    problems, fence, front, open_text = [], False, False, False
    for number, line in enumerate(text.splitlines(), start=1):
        if number == 1 and line == "---":
            front = True
        elif front:
            front = line != "---"
        elif line.lstrip().startswith("```"):
            fence, open_text = not fence, False
        elif fence or not line.strip():
            open_text = False
        elif MARKDOWN_START.match(line):
            open_text = bool(LIST_ITEM.match(line))
        else:
            if open_text:
                problems.append(
                    f"{path}:{number} continues the paragraph of the line before; "
                    "write each paragraph and each list item on one line"
                )
            open_text = True
    return problems


CONSTRAINT_COMMENT = re.compile(
    r"do not (change|remove|touch|edit)|don't (change|remove|touch|edit)|workaround|\bhack\b",
    re.IGNORECASE,
)


def comment_stands_in_for_a_test(path: str, text: str) -> list[str]:
    return [
        f"{path}:{token.start[0]} has a comment that states a constraint or a workaround; "
        "write a test that fails when the constraint is broken, then delete the comment"
        for token in tokenize.generate_tokens(io.StringIO(text).readline)
        if token.type == tokenize.COMMENT and CONSTRAINT_COMMENT.search(token.string)
    ]


# Each check, the files it reads, and one bad example that it must catch.
CHECKS: list[tuple[Callable[[str, str], list[str]], str, str, str]] = [
    (figure_saved_without_save_png, SRC, ".py", 'fig.savefig("figure.png", dpi=200)'),
    (topic_text_typed_by_hand, "", ".py", f"LABEL = {topic_ids.TOPIC_LABELS['T01']!r}"),
    (absolute_path_in_code, SRC, ".py", 'FOLDER = "C:/Users/someone/data/raw"'),
    (absolute_path_in_code, SRC, ".py", 'FOLDER = "/home/someone/data"'),
    (data_folder_built_by_hand, SRC, ".py", 'folder = root / "data" / "raw"'),
    (data_folder_built_by_hand, SRC, ".py", 'folder = Path("data")'),
    (retired_source_named, SRC, ".py", 'SOURCE = "gini_swiid"'),
    (bucket_named, "", "", 'ADDRESS = "gs://some-bucket/raw"'),
    (comment_stands_in_for_a_test, SRC, ".py", "x = 1  # do not change: the panel needs it\n"),
    (comment_stands_in_for_a_test, SRC, ".py", "# Workaround for the bad header row\nx = 1\n"),
    (paragraph_hard_wrapped, "", ".md", "A paragraph that goes on\nto a second line.\n"),
    (paragraph_hard_wrapped, "", ".md", "- A list item that goes on\n  to a second line.\n"),
]


@pytest.mark.parametrize(
    ("check", "prefix", "suffix"),
    sorted({(check, prefix, suffix) for check, prefix, suffix, _ in CHECKS}, key=str),
    ids=lambda value: getattr(value, "__name__", None),
)
def test_the_code_follows_the_rule(check, prefix, suffix):
    problems = []
    for path in tracked(prefix, suffix):
        if path == "tests/test_code_rules.py":
            continue  # holds the bad examples
        try:
            text = (ROOT / path).read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        problems += check(path, text)
    assert not problems, "\n".join(problems)


@pytest.mark.parametrize(
    ("check", "bad"),
    [(check, bad) for check, _, _, bad in CHECKS],
    ids=lambda value: getattr(value, "__name__", None),
)
def test_each_check_catches_a_bad_example(check, bad):
    assert check("src/songs/stage_50_analysis/example.py", bad)


def test_every_clean_builder_names_a_concept_with_a_canonical_source():
    """A variable that is not lyrics has an entry in the data source file before code reads it."""
    canonical = {source.concept for source in load_sources() if source.status == "canonical"}
    problems = []
    for path in tracked(f"{SRC}stage_10_clean/", ".py"):
        tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
        for node in tree.body:
            if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Constant):
                continue
            for target in node.targets:
                name = getattr(target, "id", "")
                if name.endswith("CONCEPT") and node.value.value not in canonical:
                    problems.append(
                        f"{path}:{node.lineno} {name} = {node.value.value!r} has no canonical "
                        "entry; add one to resources/data_sources.toml first"
                    )
    assert not problems, "\n".join(problems)


def test_the_settings_deny_a_merge_by_an_agent():
    deny = json.loads((ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))[
        "permissions"
    ]["deny"]
    assert any(rule.startswith("Bash(gh pr merge") for rule in deny), (
        ".claude/settings.json must deny `gh pr merge`; agents never merge"
    )


def test_no_new_workflow_while_most_rules_have_no_check():
    """Automation waits for the checks. `ci.yml` and the three agent workflows exist already."""
    known = {"ci.yml", "agent-plan.yml", "agent-build.yml", "agent-review.yml"}
    new = sorted(
        Path(path).name for path in tracked(".github/workflows/") if Path(path).name not in known
    )
    listed = rules.load_rules()
    unchecked = sum(1 for rule in listed if not rule.tests)
    assert not new or unchecked * 2 <= len(listed), (
        f"new workflows {new}, but {unchecked} of {len(listed)} rules have no check; "
        "add checks first (docs/standards/rules.md shows the rules that have none)"
    )


# --- The rule table ---------------------------------------------------------------


def test_every_entry_matches_one_rule_and_names_real_tests():
    listed = rules.load_rules()  # raises on an entry with no rule or with a missing test
    assert len(listed) > 30
    assert any(rule.tests for rule in listed) and any(not rule.tests for rule in listed)


@pytest.mark.parametrize(
    ("entry", "message"),
    [
        ('rule = "No such rule"\ntests = ["tests/test_code_rules.py::tracked"]', "starts 0 rules"),
        ('rule = "Data never"\ntests = ["tests/test_code_rules.py::test_gone"]', "no such test"),
        ('rule = "Data never"\ntests = []', "at least one test"),
        ('rule = "Data never"\ntests = ["tests/x.py::test_a"]\nwhy = "x"', "unknown"),
    ],
)
def test_a_bad_checks_file_is_refused(tmp_path, entry, message):
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text(
        "## Rules\n\n### Data\n\n- Data never goes to Git.\n", encoding="utf-8"
    )
    (tmp_path / "resources").mkdir()
    (tmp_path / rules.CHECKS_FILE).write_text(f"[[check]]\n{entry}\n", encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        rules.load_rules(tmp_path)


def test_generated_page_is_current():
    on_disk = (ROOT / rules.RULES_PAGE).read_text(encoding="utf-8")
    assert on_disk == rules.render_rules_markdown(rules.load_rules()), (
        "docs/standards/rules.md is out of date. Run: python -m songs.common.rules --write"
    )
