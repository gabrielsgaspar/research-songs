"""Lyric sources: read `resources/lyric_sources.toml`, check it, render its page.

The file lists every place that lyrics come from: sites, bulk dumps, site archives,
and files from people. It says which countries a source can serve. A run record may
name only a source from this file, so "what ran" and "what could run" use one key.

    python -m songs.common.lyric_sources            # print the page
    python -m songs.common.lyric_sources --write    # write docs/standards/lyric_sources.md
"""

import re
import sys
import tomllib
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from songs.common.paths import ISO3, SOURCE, resolve_project_root

SOURCES_FILE = Path("resources") / "lyric_sources.toml"
LANGUAGES_FILE = Path("resources") / "language_countries.toml"
SOURCES_PAGE = Path("docs") / "standards" / "lyric_sources.md"
# The order is the order of use: a copy we hold costs no requests, so it comes first.
KIND_MEANING = {
    "bulk_dump": "A dataset file that we hold. A run sends no requests",
    "site_archive": "A copy of a whole site that we collected. A run sends no requests",
    "manual": "Files that a person prepares for the project",
    "live_site": "A site that a run sends requests to",
    "internal": "A step of the project itself, not a place that lyrics come from",
}
SCOPES = ("global", "languages", "countries")
ACCESS_MEANING = {
    "allowed": "Requests may be sent, with the stated delay",
    "blocked": "Do not send requests to the site. A copy that we hold stays usable",
    "not_applicable": "The source takes no requests",
    "unknown": "Not confirmed. Confirm before a run sends requests",
}
REQUIRED = ("id", "name", "kind", "scope", "url", "stored_path", "routes", "access", "checked")
OPTIONAL = ("languages", "countries", "request_delay_seconds", "notes")
LANGUAGE = re.compile(r"[a-z]{2}")


@dataclass(frozen=True)
class LyricSource:
    """One place that lyrics come from."""

    id: str
    name: str
    kind: str
    scope: str
    url: str
    stored_path: str
    routes: tuple[str, ...]
    access: str
    checked: bool
    languages: tuple[str, ...] = ()
    countries: tuple[str, ...] = ()
    request_delay_seconds: float | None = None
    notes: str = ""


def load_language_countries(root: Path | None = None) -> dict[str, tuple[str, tuple[str, ...]]]:
    """Return language code -> (name, country codes). Raise ValueError on a bad file."""
    path = resolve_project_root(root) / LANGUAGES_FILE
    blocks = tomllib.loads(path.read_text(encoding="utf-8")).get("language", [])
    problems, table = [], {}
    for block in blocks:
        code = block.get("code", "(no code)")
        if set(block) != {"code", "name", "countries"}:
            problems.append(f"{code}: an entry has code, name and countries, nothing else")
            continue
        if not LANGUAGE.fullmatch(code):
            problems.append(f"{code}: code is two lower-case letters (ISO 639-1)")
        if code in table:
            problems.append(f"{code}: code appears twice")
        bad = [c for c in block["countries"] if not ISO3.fullmatch(c)]
        if bad or not block["countries"]:
            problems.append(f"{code}: countries are three capital letters, at least one: {bad}")
        table[code] = (block["name"], tuple(block["countries"]))
    if problems:
        raise ValueError(f"{LANGUAGES_FILE.as_posix()}: " + "; ".join(problems))
    return table


def load_lyric_sources(root: Path | None = None) -> list[LyricSource]:
    """Return every source in the file, in file order. Raise ValueError on a bad file."""
    # Imported here: run_records asks this module for the source ids.
    from songs.common.run_records import ROUTES

    path = resolve_project_root(root) / SOURCES_FILE
    blocks = tomllib.loads(path.read_text(encoding="utf-8")).get("source", [])
    languages = load_language_countries(root)
    problems, sources = [], []
    for block in blocks:
        name = block.get("id", "(no id)")
        missing = [key for key in REQUIRED if key not in block]
        unknown = sorted(set(block) - set(REQUIRED) - set(OPTIONAL))
        if missing or unknown:
            problems.append(f"{name}: missing {missing}, unknown {unknown}")
            continue
        if not SOURCE.fullmatch(block["id"]):
            problems.append(f"{name}: id must be lower case with underscores")
        if block["kind"] not in KIND_MEANING:
            problems.append(f"{name}: kind must be one of {tuple(KIND_MEANING)}")
        if block["scope"] not in SCOPES:
            problems.append(f"{name}: scope must be one of {SCOPES}")
        if block["access"] not in ACCESS_MEANING:
            problems.append(f"{name}: access must be one of {tuple(ACCESS_MEANING)}")
        # The scope decides which list is filled: no list for global, one list for the others.
        filled = {key for key in ("languages", "countries") if block.get(key)}
        wanted = set() if block["scope"] == "global" else {block["scope"]}
        if block["scope"] in SCOPES and filled != wanted:
            problems.append(
                f"{name}: scope {block['scope']} needs {sorted(wanted) or 'no list'}, "
                f"got {sorted(filled) or 'no list'}"
            )
        bad = [c for c in block.get("countries", []) if not ISO3.fullmatch(c)]
        bad += [code for code in block.get("languages", []) if code not in languages]
        if bad:
            problems.append(
                f"{name}: {bad} must be a country code of three capital letters "
                f"or a language in {LANGUAGES_FILE.as_posix()}"
            )
        bad_routes = [route for route in block["routes"] if route not in ROUTES]
        if bad_routes or not block["routes"]:
            problems.append(f"{name}: routes must name at least one of {ROUTES}: {bad_routes}")
        stored = block["stored_path"]
        if re.match(r"[A-Za-z]:|[/\\]", stored) or "://" in stored:
            problems.append(f"{name}: stored_path is a path under the data folder")
        if not str(block["name"]).strip():
            problems.append(f"{name}: name must not be empty")
        sources.append(
            LyricSource(
                **{
                    **block,
                    **{
                        key: tuple(block[key])
                        for key in ("routes", "languages", "countries")
                        if key in block
                    },
                }
            )
        )
    ids = [source.id for source in sources]
    problems += [
        f"{name}: id appears twice" for name in sorted({i for i in ids if ids.count(i) > 1})
    ]
    if problems:
        raise ValueError(f"{SOURCES_FILE.as_posix()}: " + "; ".join(problems))
    return sources


@cache
def source_ids(root: Path | None = None) -> frozenset[str]:
    """Return the ids that a run record may name."""
    return frozenset(source.id for source in load_lyric_sources(root))


def countries_of(
    source: LyricSource, languages: dict[str, tuple[str, tuple[str, ...]]]
) -> tuple[str, ...]:
    """Return the countries that a source names, sorted. A global source names none."""
    codes = set(source.countries)
    for language in source.languages:
        codes.update(languages[language][1])
    return tuple(sorted(codes))


def sources_for(iso3: str, root: Path | None = None) -> list[LyricSource]:
    """Return the sources that can serve a country: copies we hold first, live sites after."""
    languages = load_language_countries(root)
    order = list(KIND_MEANING)
    found = [
        source
        for source in load_lyric_sources(root)
        if source.scope == "global" or iso3 in countries_of(source, languages)
    ]
    return sorted(found, key=lambda s: (order.index(s.kind), s.scope == "global", s.id))


def format_sources_for(iso3: str, sources: list[LyricSource], records: list) -> str:
    """Return the sources of a country as plain lines, each with its earlier runs."""
    lines, ran = [], 0
    for source in sources:
        runs = [record for record in records if record.source == source.id]
        ran += bool(runs)
        delay = source.request_delay_seconds
        lines.append(
            f"{source.id} ({source.kind}, requests {source.access}"
            f"{f', delay {delay:g} s' if delay is not None else ''}"
            f"{'' if source.checked else ', entry not checked'}): "
            f"{'never ran' if not runs else f'{len(runs)} runs'}"
        )
        for run in runs:
            rows = "rows not recorded" if run.rows_added is None else f"{run.rows_added} rows"
            lines.append(f"    {run.started_utc[:10]} {run.route}: {run.state}, {rows}")
    head = (
        f"{iso3}: {len(sources)} sources apply, {ran} already ran, {len(sources) - ran} never ran."
    )
    return "\n".join([head, *lines])


def _cell(text: str) -> str:
    return text.replace("|", "\\|") or "-"


def _scope_cell(source: LyricSource, languages: dict[str, tuple[str, tuple[str, ...]]]) -> str:
    if source.scope == "global":
        return "All countries"
    if source.scope == "languages":
        return "Languages: " + ", ".join(languages[code][0] for code in source.languages)
    return "Countries: " + ", ".join(source.countries)


def _access_cell(source: LyricSource) -> str:
    delay = source.request_delay_seconds
    return source.access + (f", {delay:g} s between requests" if delay is not None else "")


def render_lyric_sources_markdown(
    sources: list[LyricSource], languages: dict[str, tuple[str, tuple[str, ...]]]
) -> str:
    """Return the text of docs/standards/lyric_sources.md."""
    lines = [
        "# Lyric sources",
        "",
        f"This page is generated from `{SOURCES_FILE.as_posix()}` and "
        f"`{LANGUAGES_FILE.as_posix()}`. Do not edit it by hand.",
        "",
        "To rebuild it, run `python -m songs.common.lyric_sources --write`.",
        "",
        "It answers one question: where can lyrics for a country come from? "
        "For one country, with the runs that already used each source, run "
        "`uv run songs lyrics sources <ISO3>`.",
        "",
        "A run record may name only a source on this page. "
        f"To use a new source, add its entry to `{SOURCES_FILE.as_posix()}` first.",
        "",
        "| Kind | Meaning |",
        "| --- | --- |",
        *[f"| {kind} | {meaning} |" for kind, meaning in KIND_MEANING.items()],
        "",
        "| Access | Meaning |",
        "| --- | --- |",
        *[f"| {access} | {meaning} |" for access, meaning in ACCESS_MEANING.items()],
        "",
        '"Checked: no" means that the entry comes from notes or from a name only, '
        "not from code or data. An empty stored path means that no copy is confirmed.",
    ]
    for kind in KIND_MEANING:
        group = [source for source in sources if source.kind == kind]
        if not group:
            continue
        lines += [
            "",
            f"## Kind: {kind}",
            "",
            "| Id | Name | Serves | Routes | Access | Stored copy | Checked | Notes |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
        for s in group:
            name = f"[{_cell(s.name)}]({s.url})" if s.url else _cell(s.name)
            stored = f"`{s.stored_path}`" if s.stored_path else "-"
            lines.append(
                f"| `{s.id}` | {name} | {_cell(_scope_cell(s, languages))} "
                f"| {', '.join(s.routes)} | {_access_cell(s)} | {stored} "
                f"| {'yes' if s.checked else 'no'} | {_cell(s.notes)} |"
            )
    by_country: dict[str, list[str]] = {}
    for source in sources:
        for iso3 in countries_of(source, languages):
            by_country.setdefault(iso3, []).append(source.id)
    everywhere = [f"`{source.id}`" for source in sources if source.scope == "global"]
    lines += [
        "",
        "## Sources by country",
        "",
        f"These sources serve every country: {', '.join(everywhere) or 'none'}. "
        "The table lists the other sources. A country that is not in the table has "
        "only the sources that serve every country.",
        "",
        "| Country | Sources |",
        "| --- | --- |",
        *[
            f"| {iso3} | {', '.join(f'`{i}`' for i in sorted(ids))} |"
            for iso3, ids in sorted(by_country.items())
        ],
        "",
        "## Languages",
        "",
        "A working table: the countries where a source in that language is worth a run. "
        "It is not a list of official languages.",
        "",
        "| Code | Language | Countries |",
        "| --- | --- | --- |",
        *[
            f"| {code} | {name} | {', '.join(countries)} |"
            for code, (name, countries) in languages.items()
        ],
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    """Print the page, or write it with --write."""
    text = render_lyric_sources_markdown(load_lyric_sources(), load_language_countries())
    if argv == ["--write"]:
        page = resolve_project_root() / SOURCES_PAGE
        with page.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
