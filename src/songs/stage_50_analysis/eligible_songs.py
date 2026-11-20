"""The one rule that decides which songs enter an analysis (decision 0007).

`classify` gives each song of a country table one reason when it is left out, or
no reason when it is eligible. Every analysis calls it; no analysis writes its own
filter. The rules, in the order that they are checked:

1. `quality_quarantine`: the quality check put the song in quarantine
   (`quality_status` is `quarantine`).
2. `suspect_text`: the text is on the list of suspect texts
   (`resources/lyrics/suspect_text_hashes.csv`): a text that a source shows on many
   pages, which is not a lyric. A row of the list names a source and a text hash
   (`lyrics_text_hash`); the source `*` is any source.
3. `quarantined_song`: the song is on the list of songs in quarantine
   (`clean/quality/song_quarantine/<YYYYMMDD>/` in the data folder), with the same
   `artist_id`, `source` and `lyrics_text_hash`. A song whose text changed after the
   check is not left out.
4. `suppressed_duplicate`: the duplicate check suppressed the song
   (`duplicate_decision` is `suppress_duplicate`).
5. `not_canonical`: another row represents the song (`canonical_song_id` is set and
   is not the `song_id` of the row): a duplicate or a re-release.
6. `re_release`: the re-release check of the old pipeline says that the row is a
   re-release (`re_release` is true). A row that no check saw is not left out.
7. `entered_by_hand`: a person collected the song (route `manual_review`), and its
   country has no group in the exceptions file.
8. `year_out_of_range`: the year is outside `MIN_SONG_YEAR` to `MAX_SONG_YEAR`.

A song with no year is eligible. An analysis by year cannot use it, and reports
how many such songs it leaves out.

A song collected by hand whose country has a group in the exceptions file is
eligible by exception (`by_exception` is true). The file is
`resources/lyrics/eligibility_exceptions.csv`: one row per country, with the
reason and the date of the decision. The file has no rows while no country has a
`manual_review` run; a test fails when a run record names that route and the file
has no row for its country.

The two lists come from the old pipeline. They hold hashes, ids and the id of the
check that put each row on the list, and no lyric text. The list of suspect texts is
tracked; the list of songs in quarantine is too large for Git and is a version
folder of the data folder, written by `import_old_song_quarantine`. `load_hash_lists`
reads them into the connection of the songs.
"""

import csv
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd

from songs.common import manifests
from songs.common.paths import (
    check_iso3,
    clean_song_quarantine_dir,
    data_root,
    latest_clean_song_quarantine_dir,
    resolve_project_root,
)
from songs.common.years import MAX_SONG_YEAR, MIN_SONG_YEAR

EXCEPTIONS_FILE = Path("resources") / "lyrics" / "eligibility_exceptions.csv"
EXCEPTION_COLUMNS = ["country_iso3", "reason", "decided"]
MANUAL_ROUTE = "manual_review"
SUSPECT_FILE = Path("resources") / "lyrics" / "suspect_text_hashes.csv"
SUSPECT_COLUMNS = ["source", "lyrics_text_hash", "check_id"]
QUARANTINE_COLUMNS = ["song_id", "artist_id", "source", "lyrics_text_hash", "check_id"]
# List -> the condition that puts a song (alias s) on a row of the list (alias q).
MATCHES = {
    "suspect_text": "q.lyrics_text_hash = s.lyrics_text_hash "
    "AND q.source IN ('*', lower(s.source))",
    "quarantined_song": "q.song_id = s.song_id AND q.artist_id = s.artist_id "
    "AND q.source = lower(s.source) AND q.lyrics_text_hash = s.lyrics_text_hash",
}
# Reason -> the condition on a song row that leaves it out. The order is the order of the check.
RULES = {
    "quality_quarantine": "quality_status = 'quarantine'",
    "suspect_text": "on_suspect_text",
    "quarantined_song": "on_quarantined_song",
    "suppressed_duplicate": "duplicate_decision = 'suppress_duplicate'",
    "not_canonical": "canonical_song_id IS NOT NULL AND canonical_song_id <> song_id",
    "re_release": "re_release",
    "entered_by_hand": "{manual} AND NOT {named}",
    "year_out_of_range": f"year NOT BETWEEN {MIN_SONG_YEAR} AND {MAX_SONG_YEAR}",
}
REASONS = tuple(RULES)
COLUMNS = (
    "song_id",
    "artist_id",
    "source",
    "lyrics_text_hash",
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


def _read_list(path: Path, columns: list[str]) -> pd.DataFrame:
    """Read a lyric-hash list. Raise ValueError on a bad row or a row named twice."""
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != columns:
            raise ValueError(f"{path}: the columns must be {columns}")
        rows = list(reader)
    for number, row in enumerate(rows, start=2):
        if not all(row[name] for name in columns):
            raise ValueError(f"{path}:{number}: a cell is empty")
        if not re.fullmatch("[0-9a-f]{64}", row["lyrics_text_hash"]):
            raise ValueError(f"{path}:{number}: the hash is not 64 lower-case hex characters")
        if row["source"] != row["source"].lower():
            raise ValueError(f"{path}:{number}: the source is not lower case")
    frame = pd.DataFrame(rows, columns=columns, dtype="string")
    if frame.duplicated(columns[:-1]).any():
        raise ValueError(f"{path}: a row is named twice")
    return frame


def quarantine_file(data: Path) -> Path:
    """Return the list of songs in quarantine of the newest complete folder.

    Raise FileNotFoundError when the data folder has none.
    """
    folder = latest_clean_song_quarantine_dir(data)
    if folder is None:
        raise FileNotFoundError("no complete clean/quality/song_quarantine/<YYYYMMDD>/ folder")
    return folder / manifests.SONG_QUARANTINE_FILE


def load_hash_lists(
    connection: duckdb.DuckDBPyConnection,
    suspect: Path | None = None,
    quarantine: Path | None = None,
) -> dict[str, duckdb.DuckDBPyRelation]:
    """Read the list of suspect texts and the list of songs in quarantine into `connection`.

    The defaults are the tracked list of suspect texts and the list in the newest
    complete quarantine folder of the data folder (`quarantine_file`).
    """
    lists = {}
    for name, path, columns in (
        ("suspect_text", suspect or resolve_project_root() / SUSPECT_FILE, SUSPECT_COLUMNS),
        ("quarantined_song", quarantine or quarantine_file(data_root()), QUARANTINE_COLUMNS),
    ):
        text = ", ".join(f'CAST("{column}" AS VARCHAR) AS "{column}"' for column in columns)
        lists[name] = connection.from_df(_read_list(path, columns)).project(text)
    return lists


def classify(
    songs: duckdb.DuckDBPyRelation,
    exceptions: list[NamedGroup],
    hash_lists: dict[str, duckdb.DuckDBPyRelation],
) -> duckdb.DuckDBPyRelation:
    """Return the songs with two more columns.

    `ineligible_reason` is the first rule that leaves the song out, or null when the
    song is eligible. `by_exception` is true for an eligible song that entered
    through a group of the exceptions file. The songs need `country_iso3` and the
    columns in `COLUMNS`. `hash_lists` comes from `load_hash_lists` on the
    connection of the songs.
    """
    for name, condition in MATCHES.items():
        hits = songs.set_alias("s").join(hash_lists[name].set_alias("q"), condition, how="semi")
        flags = hits.project(f"country_iso3, song_id, true AS on_{name}").distinct()
        songs = songs.join(flags, ["country_iso3", "song_id"], how="left")
    manual = f"coalesce(route = '{MANUAL_ROUTE}', false)"
    codes = ", ".join(f"'{check_iso3(group.country_iso3)}'" for group in exceptions)
    named = f"country_iso3 IN ({codes})" if codes else "false"
    cases = " ".join(
        f"WHEN coalesce({condition.format(manual=manual, named=named)}, false) THEN '{reason}'"
        for reason, condition in RULES.items()
    )
    reason = f"CASE {cases} END"
    flags = ", ".join(f"on_{name}" for name in MATCHES)
    return songs.project(
        f"* EXCLUDE ({flags}), {reason} AS ineligible_reason, "
        f"({reason}) IS NULL AND {manual} AND {named} AS by_exception"
    )


def import_old_song_quarantine(old_list: Path, data: Path, today: date | None = None) -> dict:
    """Write the quarantine folder of the day from the old list. Return the folder and the counts.

    The old list is `resources/lyrics/song_quarantine.csv` of the old project; it is
    read only. The new list keeps the rows with the decision `quarantine`, and only
    the columns of the rule: the old `provider` becomes `source` and the old
    `source_check_id` becomes `check_id`. The old `reason` is free text and
    `reviewed_by` names people, so neither is kept. A row with an empty key cell is
    left out, and a key that comes again keeps its first row. Raise FileExistsError
    when the folder of the day exists.
    """
    folder = clean_song_quarantine_dir(data, today or date.today())
    if folder.exists():
        raise FileExistsError(f"{folder} exists; a version folder is never written over")
    with old_list.open(encoding="utf-8-sig", newline="") as handle:
        old = list(csv.DictReader(handle))
    kept: dict[tuple[str, ...], dict[str, str]] = {}
    counts = {
        "rows_read": len(old),
        "left_out_not_quarantine": 0,
        "left_out_empty_key": 0,
        "left_out_repeated_key": 0,
    }
    for row in old:
        cells = {name: (value or "").strip() for name, value in row.items()}
        new = {
            "song_id": cells.get("song_id", ""),
            "artist_id": cells.get("artist_id", ""),
            "source": cells.get("provider", "").casefold(),
            "lyrics_text_hash": cells.get("lyrics_text_hash", "").lower(),
            "check_id": cells.get("source_check_id", "") or "unrecorded",
        }
        key = tuple(new[name] for name in QUARANTINE_COLUMNS[:-1])
        if cells.get("decision", "").casefold() != "quarantine":
            counts["left_out_not_quarantine"] += 1
        elif not all(key):
            counts["left_out_empty_key"] += 1
        elif key in kept:
            counts["left_out_repeated_key"] += 1
        else:
            kept[key] = new
    counts["rows_written"] = len(kept)
    left = sum(value for name, value in counts.items() if name.startswith("left_out_"))
    if counts["rows_written"] + left != counts["rows_read"]:
        raise ValueError("the rows written and the rows left out do not add up to the rows read")
    folder.mkdir(parents=True)
    with (folder / manifests.SONG_QUARANTINE_FILE).open("w", encoding="utf-8", newline="") as out:
        writer = csv.DictWriter(out, fieldnames=QUARANTINE_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(kept[key] for key in sorted(kept))
    manifests.write_manifest(
        data,
        folder,
        "clean_song_quarantine",
        inputs=["resources/lyrics/song_quarantine.csv"],
        counts=counts,
        notes="The input is relative to the old project, not to the data folder. "
        "The old reason and reviewer columns are not kept.",
    )
    return {"folder": folder, "counts": counts}
