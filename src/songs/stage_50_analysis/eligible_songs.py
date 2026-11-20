"""The one rule that decides which songs enter an analysis (decision 0007).

`classify` gives each song of a country table one reason when it is left out, or
no reason when it is eligible. Every analysis calls it; no analysis writes its own
filter. The rules, in the order that they are checked:

1. `quality_quarantine`: the quality check put the song in quarantine
   (`quality_status` is `quarantine`).
2. `suppressed_duplicate`: the duplicate check suppressed the song
   (`duplicate_decision` is `suppress_duplicate`).
3. `not_canonical`: another row represents the song (`canonical_song_id` is set and
   is not the `song_id` of the row): a duplicate or a re-release.
4. `re_release`: the re-release check of the old pipeline says that the row is a
   re-release (`re_release` is true). A row that no check saw is not left out.
5. `entered_by_hand`: a person collected the song (route `manual_review`), and its
   country has no group in the exceptions file.
6. `year_out_of_range`: the year is outside `MIN_SONG_YEAR` to `MAX_SONG_YEAR`.

A song with no year is eligible. An analysis by year cannot use it, and reports
how many such songs it leaves out.

A song collected by hand whose country has a group in the exceptions file is
eligible by exception (`by_exception` is true). The file is
`resources/lyrics/eligibility_exceptions.csv`: one row per country, with the
reason and the date of the decision. The file has no rows while no country has a
`manual_review` run; a test fails when a run record names that route and the file
has no row for its country.
"""

import csv
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import duckdb

from songs.common.paths import check_iso3, resolve_project_root
from songs.common.years import MAX_SONG_YEAR, MIN_SONG_YEAR

EXCEPTIONS_FILE = Path("resources") / "lyrics" / "eligibility_exceptions.csv"
EXCEPTION_COLUMNS = ["country_iso3", "reason", "decided"]
MANUAL_ROUTE = "manual_review"
# Reason -> the condition on a song row that leaves it out. The order is the order of the check.
RULES = {
    "quality_quarantine": "quality_status = 'quarantine'",
    "suppressed_duplicate": "duplicate_decision = 'suppress_duplicate'",
    "not_canonical": "canonical_song_id IS NOT NULL AND canonical_song_id <> song_id",
    "re_release": "re_release",
    "entered_by_hand": "{manual} AND NOT {named}",
    "year_out_of_range": f"year NOT BETWEEN {MIN_SONG_YEAR} AND {MAX_SONG_YEAR}",
}
REASONS = tuple(RULES)
COLUMNS = (
    "song_id",
    "route",
    "quality_status",
    "duplicate_decision",
    "canonical_song_id",
    "re_release",
    "year",
)


@dataclass(frozen=True)
class NamedGroup:
    """One named group of songs that enter by exception: the hand-collected songs of a country."""

    country_iso3: str
    reason: str
    decided: str


def load_exceptions(path: Path | None = None) -> list[NamedGroup]:
    """Read the exceptions file. Raise ValueError on a bad row or a country named twice."""
    path = path or resolve_project_root() / EXCEPTIONS_FILE
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != EXCEPTION_COLUMNS:
            raise ValueError(f"{path}: the columns must be {EXCEPTION_COLUMNS}")
        groups = []
        for number, row in enumerate(reader, start=2):
            try:
                check_iso3(row["country_iso3"])
                date.fromisoformat(row["decided"])
            except ValueError as error:
                raise ValueError(f"{path}:{number}: {error}") from error
            if not row["reason"].strip():
                raise ValueError(f"{path}:{number}: the reason is empty")
            groups.append(NamedGroup(row["country_iso3"], row["reason"], row["decided"]))
    codes = [group.country_iso3 for group in groups]
    if len(set(codes)) != len(codes):
        raise ValueError(f"{path}: a country has more than one group")
    return groups


def classify(
    songs: duckdb.DuckDBPyRelation, exceptions: list[NamedGroup]
) -> duckdb.DuckDBPyRelation:
    """Return the songs with two more columns.

    `ineligible_reason` is the first rule that leaves the song out, or null when the
    song is eligible. `by_exception` is true for an eligible song that entered
    through a group of the exceptions file. The songs need `country_iso3` and the
    columns in `COLUMNS`.
    """
    manual = f"coalesce(route = '{MANUAL_ROUTE}', false)"
    codes = ", ".join(f"'{check_iso3(group.country_iso3)}'" for group in exceptions)
    named = f"country_iso3 IN ({codes})" if codes else "false"
    cases = " ".join(
        f"WHEN coalesce({condition.format(manual=manual, named=named)}, false) THEN '{reason}'"
        for reason, condition in RULES.items()
    )
    reason = f"CASE {cases} END"
    return songs.project(
        f"*, {reason} AS ineligible_reason, "
        f"({reason}) IS NULL AND {manual} AND {named} AS by_exception"
    )
