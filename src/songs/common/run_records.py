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

from songs.common import lyric_sources
from songs.common.paths import ISO3, RUN_ID, SOURCE, project_paths, resolve_project_root
from songs.common.repo import git_sha

SCHEMA_VERSION = 2
# Version 1 has no campaign and no counts of requests, songs and limits. It still loads.
SCHEMA_VERSIONS = (1, 2)
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
    "old_layout",
)
STATES = ("complete", "partial", "failed")
# The settings that make two runs of one country, route and source "the same job".
JOB_SETTINGS = ("bulk_file", "request_delay_seconds", "artist_limit", "song_limit")
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
    campaign_id: str | None = None
    requests_sent: int | None = None
    songs_attempted: int | None = None
    songs_accepted: int | None = None
    songs_rejected: dict[str, int] | None = None
    limits_hit: dict[str, int | str] | None = None
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
        elif self.source not in lyric_sources.source_ids():
            problems.append(
                f"source {self.source!r} is not in {lyric_sources.SOURCES_FILE.as_posix()}; "
                "add its entry to that file before the run"
            )
        if self.state not in STATES:
            problems.append(f"state must be one of {STATES}, got {self.state!r}")
        if self.campaign_id is not None and not RUN_ID.fullmatch(self.campaign_id):
            problems.append(f"campaign_id must look like a run id, got {self.campaign_id!r}")
        if self.schema_version not in SCHEMA_VERSIONS:
            problems.append(f"schema_version must be one of {SCHEMA_VERSIONS}")
        if self.bulk_file and "://" in self.bulk_file:
            problems.append("bulk_file is a path inside the bucket, without scheme or bucket name")
        if problems:
            raise ValueError("; ".join(problems))

    @property
    def corrects_existing_songs(self) -> bool:
        """Identify a review manifest applied to existing rows with no new songs."""
        return (
            self.route == "manual_review"
            and self.rows_added == 0
            and (self.bulk_file or "").startswith("raw/reviewed_corrections/")
        )

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


def open_campaign_id(iso3: str, countries: Path | None = None) -> str | None:
    """Return the id of the open campaign of a country, or None.

    A campaign is open when it has an open file and no close file
    (`songs.common.campaigns` writes both).
    """
    folder = (countries or countries_dir()) / iso3 / "campaigns"
    closed = {path.name.removesuffix("_close.json") for path in folder.glob("*_close.json")}
    opened = {path.name.removesuffix("_open.json") for path in folder.glob("*_open.json")}
    return max(opened - closed, default=None)


def check_not_repeated(record: RunRecord, earlier: list[RunRecord], reason: str | None) -> None:
    """Raise FileExistsError when a complete run already did the same job and no reason is given.

    The same job is the same country, route, source and `JOB_SETTINGS`.
    """
    job = [getattr(record, name) for name in ("iso3", "route", "source", *JOB_SETTINGS)]
    for past in earlier:
        same = [getattr(past, name) for name in ("iso3", "route", "source", *JOB_SETTINGS)]
        if past.state == "complete" and same == job and not (reason or "").strip():
            raise FileExistsError(
                f"run {past.run_id} already did this job for {record.iso3}: route {record.route}, "
                f"source {record.source}, the same bulk file, delay and limits. "
                "Use its result, change a setting, or give a reason for a second run."
            )


@contextmanager
def record_run(
    iso3: str,
    route: str,
    source: str,
    *,
    countries: Path | None = None,
    repeat_reason: str | None = None,
    coverage_page: Path | None = None,
    **settings: object,
) -> Iterator[RunRecord]:
    """Open a run and write its record when the block ends, also when it fails.

    After the record, the coverage page is written again, so it never needs a separate step.
    The page is `coverage_page`, or the committed page when `countries` is this repository's.

    The caller sets results on the yielded record (`rows_added`, `known_gaps`,
    `state = "partial"`). An exception sets the state to "failed", names the
    error type in `notes`, writes the record, and is raised again.

    The run joins the open campaign of the country, when there is one. A run that
    repeats a complete run with the same settings is refused before any work,
    unless `repeat_reason` says why; the reason goes to `notes`.
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
    check_not_repeated(record, read_run_records(iso3, countries), repeat_reason)
    if repeat_reason and repeat_reason.strip():
        record.notes = f"{record.notes} {repeat_reason.strip()}".strip()
    if record.campaign_id is None:
        record.campaign_id = open_campaign_id(iso3, countries)
    try:
        yield record
    except BaseException as error:
        record.state = "failed"
        record.notes = f"{record.notes} Stopped by {type(error).__name__}.".strip()
        raise
    finally:
        record.ended_utc = utc_now()
        write_run_record(record, countries)
        page = coverage_page or coverage_page_for(countries)
        if page is not None:
            write_coverage_page(page, countries or countries_dir())


def duration_text(record: RunRecord) -> str:
    """Return how long a run took, such as "1 h 5 min", or "" when a time is absent."""
    try:
        start, end = (
            datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
            for value in (record.started_utc, record.ended_utc)
        )
    except ValueError:
        return ""
    if end < start:
        return ""
    minutes, seconds = divmod(int((end - start).total_seconds()), 60)
    if minutes < 1:
        return f"{seconds} s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} h {minutes} min" if hours else f"{minutes} min"


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
        took = duration_text(record)
        campaign = f"; campaign {record.campaign_id}" if record.campaign_id else ""
        lines.append(
            f"{record.iso3} {record.started_utc[:10]} {record.route} {record.source}: "
            f"{record.state}, {rows}{', ' + took if took else ''}"
            f"{'; ' + limits if limits else ''}{campaign}{marks}"
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
    return write_coverage_page(base / COVERAGE_PAGE, base / "countries")


def write_coverage_page(page: Path, countries: Path) -> Path:
    """Write the coverage page of the records in `countries` to `page` and return it."""
    page.parent.mkdir(parents=True, exist_ok=True)
    with page.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(render_coverage(read_run_records(countries=countries)))
    return page


def coverage_page_for(countries: Path | None) -> Path | None:
    """Return the coverage page that belongs to a countries folder, or None for another folder.

    Only the countries folder of this repository has a committed coverage page.
    """
    own = countries_dir()
    if countries is None or countries.resolve() == own.resolve():
        return own.parent / COVERAGE_PAGE
    return None
