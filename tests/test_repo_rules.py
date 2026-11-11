"""Rules of the repository that a machine can check. AGENTS.md states them in words."""

import ast
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

REQUIRED = [
    "AGENTS.md",
    "CLAUDE.md",
    "CONTRIBUTING.md",
    "README.md",
    "LICENSE",
    "pyproject.toml",
    "uv.lock",
    ".github/CODEOWNERS",
    ".github/workflows/ci.yml",
    "docs/decisions/README.md",
]
DATA_SUFFIXES = {
    ".parquet",
    ".duckdb",
    ".sqlite",
    ".db",
    ".zip",
    ".gz",
    ".7z",
    ".tar",
    ".xlsx",
    ".xls",
    ".dta",
    ".pkl",
    ".npy",
    ".npz",
    ".feather",
    ".jsonl",
}
FIXTURES = "tests/fixtures/"
FIXTURE_MAX_BYTES = 200_000
# Addresses that may appear: commit trailers and documentation examples.
ALLOWED_EMAIL_DOMAINS = ("example.com", "example.org", "users.noreply.github.com", "anthropic.com")
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
MUST_STAY_COMMITTABLE = [
    "src/songs/build/x.py",
    "src/songs/common/data/x.py",
    "countries/BRA/runs/x.json",
    "docs/standards/figures.md",
    ".claude/settings.json",
    ".claude/skills/x/SKILL.md",
    ".env.example",
    "uv.lock",
]
MUST_BE_IGNORED = [
    "data/lyrics/BRA/x.parquet",
    "outputs/x.png",
    "reports/x.md",
    "scratch/x.py",
    "overleaf/main.tex",
    ".local/notes.md",
    ".env",
    "gcp-service-account-key.json",
]


def committable_files() -> list[str]:
    """Every file Git tracks or would track: committed, staged, or new and not ignored."""
    out = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    ).stdout
    return [line for line in out.splitlines() if (ROOT / line).is_file()]


def is_ignored(path: str) -> bool:
    """True when .gitignore would keep this path out of Git."""
    return (
        subprocess.run(["git", "check-ignore", "-q", "--no-index", path], cwd=ROOT).returncode == 0
    )


def test_required_files_exist():
    missing = [name for name in REQUIRED if not (ROOT / name).is_file()]
    assert not missing, f"missing required files: {missing}"


def test_no_data_files_outside_fixtures():
    bad = [
        path
        for path in committable_files()
        if Path(path).suffix.lower() in DATA_SUFFIXES and not path.startswith(FIXTURES)
    ]
    assert not bad, f"data files do not go to Git: {bad}"


def test_fixtures_are_small():
    big = [
        path
        for path in committable_files()
        if path.startswith(FIXTURES) and (ROOT / path).stat().st_size > FIXTURE_MAX_BYTES
    ]
    assert not big, f"fixtures over {FIXTURE_MAX_BYTES} bytes: {big}"


def test_no_email_addresses_in_the_repository():
    """The repository is public. A person's address never goes into it."""
    found = []
    for path in committable_files():
        try:
            text = (ROOT / path).read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for address in EMAIL.findall(text):
            if not address.lower().endswith(ALLOWED_EMAIL_DOMAINS):
                found.append(f"{path}: {address.split('@')[1]}")
    assert not found, f"email addresses found (domain shown): {found}"


@pytest.mark.parametrize("path", MUST_STAY_COMMITTABLE)
def test_gitignore_keeps_project_paths(path):
    assert not is_ignored(path), f".gitignore would hide {path}; anchor the pattern to the root"


@pytest.mark.parametrize("path", MUST_BE_IGNORED)
def test_gitignore_blocks_data_and_secrets(path):
    assert is_ignored(path), f".gitignore must ignore {path}"


def test_text_io_names_its_encoding():
    """Windows defaults to cp1252, so every text open, read and write names an encoding."""
    bad = []
    for path in committable_files():
        if not path.endswith(".py"):
            continue
        tree = ast.parse((ROOT / path).read_text(encoding="utf-8"), filename=path)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
            keywords = {keyword.arg for keyword in node.keywords}
            if name in {"read_text", "write_text"} and "encoding" not in keywords:
                bad.append(f"{path}:{node.lineno} {name}")
            if name == "open" and "encoding" not in keywords:
                mode = node.args[1] if len(node.args) > 1 else None
                for keyword in node.keywords:
                    if keyword.arg == "mode":
                        mode = keyword.value
                binary = isinstance(mode, ast.Constant) and "b" in str(mode.value)
                if not binary:
                    bad.append(f"{path}:{node.lineno} open")
    assert not bad, f"text I/O without encoding=: {bad}"
