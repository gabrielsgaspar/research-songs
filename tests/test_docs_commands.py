"""Every `uv run songs ...` command in the tracked Markdown files exists in the command line."""

import re
import subprocess

import typer.main

from songs.cli import app
from songs.common.paths import resolve_project_root

ROOT = resolve_project_root()
COMMAND = re.compile(r"uv run songs((?: [A-Za-z0-9<>_./\\-]+)*)")


def markdown_files() -> list[str]:
    out = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "*.md"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout
    return out.split()


def unknown(words: list[str]) -> str | None:
    """Return what is wrong with one documented command, or None when it exists."""
    command, path = typer.main.get_command(app), ["songs"]
    while words and hasattr(command, "commands"):
        word = words.pop(0)
        if word not in command.commands:
            return f"{' '.join(path)} has no command {word!r}"
        command, path = command.commands[word], [*path, word]
    if hasattr(command, "commands"):
        return f"{' '.join(path)} needs a command"
    options = {opt for param in command.params for opt in getattr(param, "opts", [])}
    for word in words:
        if word.startswith("--") and word not in options:
            return f"{' '.join(path)} has no option {word}"
    return None


def test_every_documented_command_exists():
    problems = []
    for path in markdown_files():
        text = (ROOT / path).read_text(encoding="utf-8")
        for number, line in enumerate(text.splitlines(), start=1):
            for match in COMMAND.finditer(line):
                problem = unknown(match.group(1).split())
                if problem:
                    problems.append(f"{path}:{number}: {problem}")
    assert not problems, "\n".join(problems)


def test_an_unknown_command_or_option_is_found():
    assert unknown(["lyrics", "plan", "BRA"]) is None
    assert unknown(["lyrics", "campaign", "open", "BRA", "--goal"]) is None
    assert "no command 'plans'" in unknown(["lyrics", "plans", "BRA"])
    assert "no option --gaol" in unknown(["lyrics", "campaign", "open", "BRA", "--gaol"])
    assert "needs a command" in unknown(["lyrics"])
