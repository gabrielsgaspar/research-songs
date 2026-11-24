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
4. `excluded_artist`: the artist is on the list of excluded artists
   (`resources/lyrics/excluded_artists.csv`): a poet or a spoken-word artist, a
   second entry of an artist, or a wrong Discogs artist.
5. `artist_country`: the artist belongs to another country than the country of the
   song. Two sources say so. The list of artist countries
   (`resources/lyrics/artist_countries.csv`) gives the country of an artist. The
   table of artist countries (`clean/quality/artist_country/<YYYYMMDD>/` in the data
   folder, the newest complete folder) gives the decision `other_country` for an
   artist on the roster of the country of the song. The list wins: only the list
   decides for an artist that it names. An artist that neither source names passes,
   and with no such folder only the list decides.
6. `suppressed_duplicate`: the duplicate check suppressed the song
   (`duplicate_decision` is `suppress_duplicate`).
7. `not_canonical`: another row represents the song (`canonical_song_id` is set and
   is not the `song_id` of the row): a duplicate or a re-release.
8. `re_release`: the re-release check of the old pipeline says that the row is a
   re-release (`re_release` is true). A row that no check saw is not left out.
9. `entered_by_hand`: a person collected the song (route `manual_review`), and its
   country has no group in the exceptions file.
10. `year_out_of_range`: the year is outside `MIN_SONG_YEAR` to `MAX_SONG_YEAR`.

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

The two artist lists come from the master artist table of the old pipeline. The
list of excluded artists holds the artists with `include` 0 and a short reason code.
The list of artist countries holds the country of each artist that the old data
put in the folder of another country. Both are tracked, with ids and codes and no
names. `load_artist_lists` reads them, and the table of artist countries, which
`songs.stage_10_clean.artist_country` writes from Discogs evidence.
"""

import csv
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd

from songs.common import manifests, schemas
from songs.common.paths import (
    check_iso3,
    clean_song_quarantine_dir,
    data_root,
    latest_clean_artist_country_dir,
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
EXCLUDED_ARTISTS_FILE = Path("resources") / "lyrics" / "excluded_artists.csv"
EXCLUDED_ARTIST_COLUMNS = ["artist_id", "reason"]
ARTIST_COUNTRIES_FILE = Path("resources") / "lyrics" / "artist_countries.csv"
ARTIST_COUNTRY_COLUMNS = ["artist_id", "country_iso3"]
# List -> the condition that puts a song (alias s) on a row of the list (alias q).
MATCHES = {
    "suspect_text": "q.lyrics_text_hash = s.lyrics_text_hash "
    "AND q.source IN ('*', lower(s.source))",
    "quarantined_song": "q.song_id = s.song_id AND q.artist_id = s.artist_id "
    "AND q.source = lower(s.source) AND q.lyrics_text_hash = s.lyrics_text_hash",
    "excluded_artist": "q.artist_id = s.artist_id",
    "artist_country": "q.artist_id = s.artist_id "
    "AND (q.country_iso3 = s.country_iso3) = q.other_country",
}
# Reason -> the condition on a song row that leaves it out. The order is the order of the check.
RULES = {
    "quality_quarantine": "quality_status = 'quarantine'",
    **{name: f"on_{name}" for name in MATCHES},
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
    """Read a list of the rule; all columns but the last are its key.

    Raise ValueError on a bad row or a row named twice.
    """
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != columns:
            raise ValueError(f"{path}: the columns must be {columns}")
        rows = list(reader)
    for number, row in enumerate(rows, start=2):
        try:
            if not all(row[name] for name in columns):
                raise ValueError("a cell is empty")
            if "lyrics_text_hash" in row and not re.fullmatch(
                "[0-9a-f]{64}", row["lyrics_text_hash"]
            ):
                raise ValueError("the hash is not 64 lower-case hex characters")
            if "source" in row and row["source"] != row["source"].lower():
                raise ValueError("the source is not lower case")
            if "country_iso3" in row:
                check_iso3(row["country_iso3"])
        except ValueError as error:
            raise ValueError(f"{path}:{number}: {error}") from error
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
    return _load(
        connection,
        ("suspect_text", suspect or resolve_project_root() / SUSPECT_FILE, SUSPECT_COLUMNS),
        ("quarantined_song", quarantine or quarantine_file(data_root()), QUARANTINE_COLUMNS),
    )


def load_artist_lists(
    connection: duckdb.DuckDBPyConnection,
    excluded: Path | None = None,
    countries: Path | None = None,
    data: Path | None = None,
) -> dict[str, duckdb.DuckDBPyRelation]:
    """Read the list of excluded artists and the artist countries into `connection`.

    The defaults are the tracked files and the data folder of `data_root`. The
    artist countries have the column `other_country`. It is false for a row of the
    list: `country_iso3` is the country of the artist. It is true for a row of the
    newest complete table of artist countries in `data` with the decision
    `other_country`: the artist does not belong to `country_iso3`. An artist that
    the list names has no row of the table.
    """
    root = resolve_project_root()
    lists = _load(
        connection,
        ("excluded_artist", excluded or root / EXCLUDED_ARTISTS_FILE, EXCLUDED_ARTIST_COLUMNS),
        ("artist_country", countries or root / ARTIST_COUNTRIES_FILE, ARTIST_COUNTRY_COLUMNS),
    )
    tracked = lists["artist_country"]
    lists["artist_country"] = tracked.project("*, false AS other_country")
    folder = latest_clean_artist_country_dir(data or data_root())
    if folder is not None:
        checked = (
            schemas.read_table(schemas.ARTIST_COUNTRY, folder, connection)
            .filter(f"decision = '{schemas.OTHER_COUNTRY}'")
            .project("artist_id, country_iso3, true AS other_country")
            .set_alias("checked")
            .join(tracked.set_alias("tracked"), "checked.artist_id = tracked.artist_id", how="anti")
        )
        lists["artist_country"] = lists["artist_country"].union(checked)
    return lists


def _load(
    connection: duckdb.DuckDBPyConnection, *lists: tuple[str, Path, list[str]]
) -> dict[str, duckdb.DuckDBPyRelation]:
    loaded = {}
    for name, path, columns in lists:
        text = ", ".join(f'CAST("{column}" AS VARCHAR) AS "{column}"' for column in columns)
        loaded[name] = connection.from_df(_read_list(path, columns)).project(text)
    return loaded


def load_rule(
    connection: duckdb.DuckDBPyConnection,
    data: Path,
    *,
    exceptions: Path | None = None,
    suspect: Path | None = None,
    quarantine: Path | None = None,
    excluded_artists: Path | None = None,
    artist_countries: Path | None = None,
) -> tuple[list[NamedGroup], dict[str, duckdb.DuckDBPyRelation]]:
    """Return the exceptions and the lists that `classify` takes, read into `connection`.

    Each file defaults to the tracked file in `resources/lyrics/`, and the list of songs
    in quarantine to the newest complete quarantine folder of `data`. The table of
    artist countries is the newest complete one of `data`, when `data` has one.
    """
    lists = load_hash_lists(
        connection, suspect, quarantine or quarantine_file(data)
    ) | load_artist_lists(connection, excluded_artists, artist_countries, data)
    return load_exceptions(exceptions), lists


def classify(
    songs: duckdb.DuckDBPyRelation,
    exceptions: list[NamedGroup],
    lists: dict[str, duckdb.DuckDBPyRelation],
) -> duckdb.DuckDBPyRelation:
    """Return the songs with two more columns.

    `ineligible_reason` is the first rule that leaves the song out, or null when the
    song is eligible. `by_exception` is true for an eligible song that entered
    through a group of the exceptions file. The songs need `country_iso3` and the
    columns in `COLUMNS`. `lists` joins the results of `load_hash_lists` and
    `load_artist_lists` on the connection of the songs.
    """
    for name, condition in MATCHES.items():
        hits = songs.set_alias("s").join(lists[name].set_alias("q"), condition, how="semi")
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
