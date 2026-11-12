"""External data sources: read `resources/data_sources.toml`, check it, render its page.

The file says where every variable that is not lyrics comes from, and which
source of each concept the project uses (decision 0006). Analysis code asks
`canonical(concept)` for the source to use and never names a retired one.

    python -m songs.common.data_sources            # print the page
    python -m songs.common.data_sources --write    # write docs/standards/data_sources.md
"""

import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

from songs.common.paths import resolve_project_root

SOURCES_FILE = Path("resources") / "data_sources.toml"
SOURCES_PAGE = Path("docs") / "standards" / "data_sources.md"
STATUSES = ("canonical", "robustness", "supplementary", "retired")
STATUS_MEANING = {
    "canonical": "The source every analysis uses",
    "robustness": "A second source, for robustness checks only",
    "supplementary": "Used by one analysis only",
    "retired": "Was used before; no analysis may read it",
}
REQUIRED = ("id", "concept", "status", "columns", "source", "version", "url", "raw_path", "checked")
OPTIONAL = ("unit", "notes")
SOURCE_ID = re.compile(r"[a-z][a-z0-9_]*")


@dataclass(frozen=True)
class DataSource:
    """One source of one concept."""

    id: str
    concept: str
    status: str
    columns: tuple[str, ...]
    source: str
    version: str
    url: str
    raw_path: str
    checked: bool
    unit: str = ""
    notes: str = ""


def load_sources(root: Path | None = None) -> list[DataSource]:
    """Return every source in the file, in file order. Raise ValueError on a bad file."""
    path = resolve_project_root(root) / SOURCES_FILE
    blocks = tomllib.loads(path.read_text(encoding="utf-8")).get("source", [])
    problems, sources = [], []
    for block in blocks:
        name = block.get("id", "(no id)")
        missing = [key for key in REQUIRED if key not in block]
        unknown = sorted(set(block) - set(REQUIRED) - set(OPTIONAL))
        if missing or unknown:
            problems.append(f"{name}: missing {missing}, unknown {unknown}")
            continue
        if not SOURCE_ID.fullmatch(block["id"]):
            problems.append(f"{name}: id must be lower case with underscores")
        if block["status"] not in STATUSES:
            problems.append(f"{name}: status must be one of {STATUSES}")
        if not all(str(block[key]).strip() for key in ("concept", "source", "version")):
            problems.append(f"{name}: concept, source and version must not be empty")
        if Path(block["raw_path"]).is_absolute() or "://" in block["raw_path"]:
            problems.append(f"{name}: raw_path is a path under the data folder")
        sources.append(DataSource(**{**block, "columns": tuple(block["columns"])}))
    ids = [source.id for source in sources]
    problems += [
        f"{name}: id appears twice" for name in sorted({i for i in ids if ids.count(i) > 1})
    ]
    for concept in sorted({source.concept for source in sources}):
        group = [source for source in sources if source.concept == concept]
        chosen = [source.id for source in group if source.status == "canonical"]
        if len(chosen) > 1:
            problems.append(f"{concept}: more than one canonical source {chosen}")
        if not chosen and any(source.status in ("robustness", "retired") for source in group):
            problems.append(f"{concept}: a robustness or retired source needs a canonical one")
    if problems:
        raise ValueError(f"{SOURCES_FILE.as_posix()}: " + "; ".join(problems))
    return sources


def canonical(concept: str, root: Path | None = None) -> DataSource:
    """Return the one source every analysis uses for a concept."""
    found = [s for s in load_sources(root) if s.concept == concept and s.status == "canonical"]
    if not found:
        raise KeyError(f"no canonical source for {concept!r} in {SOURCES_FILE.as_posix()}")
    return found[0]


def _cell(text: str) -> str:
    return text.replace("|", "\\|") or "-"


def render_sources_markdown(sources: list[DataSource]) -> str:
    """Return the text of docs/standards/data_sources.md."""
    lines = [
        "# Data sources",
        "",
        f"This page is generated from `{SOURCES_FILE.as_posix()}`. Do not edit it by hand.",
        "",
        "To rebuild it, run `python -m songs.common.data_sources --write`.",
        "",
        "It answers one question: where does a variable come from? "
        "Each concept has at most one canonical source, and every analysis uses that one.",
        "",
        "| Status | Meaning |",
        "| --- | --- |",
        *[f"| {status} | {meaning} |" for status, meaning in STATUS_MEANING.items()],
        "",
        '"Checked: no" means that the source or version comes from notes, '
        "not from the download itself.",
    ]
    concepts = list(dict.fromkeys(source.concept for source in sources))
    lines += [
        "",
        "## Summary",
        "",
        "| Concept | Canonical source | Version |",
        "| --- | --- | --- |",
    ]
    for concept in concepts:
        chosen = [s for s in sources if s.concept == concept and s.status == "canonical"]
        if chosen:
            lines.append(f"| {concept} | {_cell(chosen[0].source)} | {_cell(chosen[0].version)} |")
    for concept in concepts:
        lines += ["", f"## {concept}"]
        group = sorted(
            (s for s in sources if s.concept == concept), key=lambda s: STATUSES.index(s.status)
        )
        for source in group:
            columns = ", ".join(f"`{column}`" for column in source.columns)
            lines += [
                "",
                f"### `{source.id}` ({source.status})",
                "",
                f"- Source: {source.source}",
                f"- Version: {source.version}",
                *([f"- Unit: {source.unit}"] if source.unit else []),
                *([f"- Columns: {columns}"] if columns else []),
                *([f"- Link: <{source.url}>"] if source.url else []),
                *([f"- Raw files: `{source.raw_path}`"] if source.raw_path else []),
                f"- Checked: {'yes' if source.checked else 'no'}",
                *([f"- Notes: {source.notes}"] if source.notes else []),
            ]
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    """Print the page, or write it with --write."""
    text = render_sources_markdown(load_sources())
    if argv == ["--write"]:
        page = resolve_project_root() / SOURCES_PAGE
        with page.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
