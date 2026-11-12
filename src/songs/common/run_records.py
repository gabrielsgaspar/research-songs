"""Run records: one small JSON file per collection run, per country.

A record says what was collected for a country, from which source, with which
limits, and when (decision 0003). Collection commands write records through
`record_run`; nobody writes one by hand. Records are write-once.
"""

import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field, fields
from datetime import UTC, datetime
from pathlib import Path

from songs.common.paths import ISO3, RUN_ID, SOURCE, project_paths, resolve_project_root
from songs.common.repo import git_sha

SCHEMA_VERSION = 1
ROUTES = (
    "live",
    "roster_update",
    "recover",
    "genius_local",
    "lrclib_local",
    "archive",
    "dump_name",
    "local_source",
    "manual_review",
)
STATES = ("complete", "partial", "failed")
COVERAGE_PAGE = Path("docs") / "status" / "coverage.md"
COVERAGE_COMMAND = "uv run songs lyrics coverage --write"


@dataclass
class RunRecord:
    """One collection run for one country. `None` means "not recorded", never zero."""

    iso3: str
    run_id: str
    route: str
    source: str
    state: str
    started_utc: str
    ended_utc: str
    code_commit: str
    bulk_file: str | None = None
    request_delay_seconds: float | None = None
    artist_limit: int | None = None
    song_limit: int | None = None
    deadline_utc: str | None = None
    artists_attempted: int | None = None
    rows_added: int | None = None
    known_gaps: list[str] = field(default_factory=list)
    notes: str = ""
    backfilled: bool = False
    schema_version: int = SCHEMA_VERSION

    def validate(self) -> None:
        """Raise ValueError when a field breaks the record rules."""
        problems = []
        if not ISO3.fullmatch(self.iso3):
            problems.append(f"iso3 must be three capital letters, got {self.iso3!r}")
        if not RUN_ID.fullmatch(self.run_id):
            problems.append(f"run_id must look like 20260131T235959Z, got {self.run_id!r}")
        if self.route not in ROUTES:
            problems.append(f"route must be one of {ROUTES}, got {self.route!r}")
        if not SOURCE.fullmatch(self.source):
            problems.append(f"source must be a lower-case key such as lrclib, got {self.source!r}")
        if self.state not in STATES:
            problems.append(f"state must be one of {STATES}, got {self.state!r}")
        if self.bulk_file and "://" in self.bulk_file:
            problems.append("bulk_file is a path inside the bucket, without scheme or bucket name")
        if problems:
            raise ValueError("; ".join(problems))

    @property
    def file_name(self) -> str:
        """The file name of this record inside `countries/<ISO3>/runs/`."""
        return f"{self.run_id}_{self.route}_{self.source}.json"


def new_run_id(now: datetime | None = None) -> str:
    """Return a run id for the current UTC second."""
    return (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%SZ")


def utc_now() -> str:
    """Return the current UTC time as an ISO 8601 string, to the second."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def countries_dir() -> Path:
    """Return the tracked `countries/` folder of this repository."""
    return project_paths().countries


def write_run_record(record: RunRecord, countries: Path | None = None) -> Path:
    """Write a record to `countries/<ISO3>/runs/` and return its path. Never overwrites."""
    record.validate()
    path = (countries or countries_dir()) / record.iso3 / "runs" / record.file_name
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(asdict(record), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    return path


def read_run_records(iso3: str | None = None, countries: Path | None = None) -> list[RunRecord]:
    """Return the records of one country, or of all countries, oldest first."""
    base = countries or countries_dir()
    pattern = f"{iso3}/runs/*.json" if iso3 else "*/runs/*.json"
    known = {item.name for item in fields(RunRecord)}
    records = []
    for path in sorted(base.glob(pattern)):
        payload = json.loads(path.read_text(encoding="utf-8"))
        unknown = set(payload) - known
        if unknown:
            raise ValueError(f"{path}: unknown fields {sorted(unknown)}")
        record = RunRecord(**payload)
        record.validate()
        if record.file_name != path.name or record.iso3 != path.parent.parent.name:
            raise ValueError(f"{path}: file name or folder does not match the record")
        records.append(record)
    return sorted(records, key=lambda record: (record.iso3, record.run_id, record.route))


@contextmanager
def record_run(
    iso3: str,
    route: str,
    source: str,
    *,
    countries: Path | None = None,
    **settings: object,
) -> Iterator[RunRecord]:
    """Open a run and write its record when the block ends, also when it fails.

    The caller sets results on the yielded record (`rows_added`, `known_gaps`,
    `state = "partial"`). An exception sets the state to "failed", names the
    error type in `notes`, writes the record, and is raised again.
    """
    record = RunRecord(
        iso3=iso3,
        run_id=new_run_id(),
        route=route,
        source=source,
        state="complete",
        started_utc=utc_now(),
        ended_utc="",
        code_commit=git_sha(resolve_project_root()),
        **settings,  # type: ignore[arg-type]
    )
    record.validate()
    try:
        yield record
    except BaseException as error:
        record.state = "failed"
        record.notes = f"{record.notes} Stopped by {type(error).__name__}.".strip()
        raise
    finally:
        record.ended_utc = utc_now()
        write_run_record(record, countries)


def format_history(records: list[RunRecord]) -> str:
    """Return the earlier runs as plain lines, for a person or an agent to read before a run."""
    if not records:
        return "No runs recorded."
    lines = []
    for record in records:
        limits = ", ".join(
            f"{label} {value}"
            for label, value in (
                ("delay s", record.request_delay_seconds),
                ("artist limit", record.artist_limit),
                ("song limit", record.song_limit),
            )
            if value is not None
        )
        rows = "rows not recorded" if record.rows_added is None else f"{record.rows_added} rows"
        marks = " (backfilled)" if record.backfilled else ""
        lines.append(
            f"{record.iso3} {record.started_utc[:10]} {record.route} {record.source}: "
            f"{record.state}, {rows}{'; ' + limits if limits else ''}{marks}"
        )
        lines.extend(f"    gap: {gap}" for gap in record.known_gaps)
    return "\n".join(lines)


def render_coverage(records: list[RunRecord]) -> str:
    """Return the coverage page: one row per country, built only from the records."""
    lines = [
        "# Coverage by country",
        "",
        f"Generated from `countries/*/runs/` by `{COVERAGE_COMMAND}`. Do not edit by hand.",
        "",
    ]
    if not records:
        return "\n".join([*lines, "No runs recorded yet.", ""])
    lines += [
        "| Country | Runs | Last run | Routes | Sources | Rows added |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    by_country: dict[str, list[RunRecord]] = {}
    for record in records:
        by_country.setdefault(record.iso3, []).append(record)
    for iso3 in sorted(by_country):
        runs = by_country[iso3]
        counted = [run.rows_added for run in runs if run.rows_added is not None]
        lines.append(
            f"| [{iso3}](../../countries/{iso3}/) | {len(runs)} "
            f"| {max(run.started_utc[:10] for run in runs)} "
            f"| {', '.join(sorted({run.route for run in runs}))} "
            f"| {', '.join(sorted({run.source for run in runs}))} "
            f"| {sum(counted) if counted else 'not recorded'} |"
        )
    return "\n".join([*lines, ""])


def write_coverage(root: Path | None = None) -> Path:
    """Regenerate the coverage page from the records and return its path."""
    base = resolve_project_root(root)
    path = base / COVERAGE_PAGE
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(render_coverage(read_run_records(countries=base / "countries")))
    return path
