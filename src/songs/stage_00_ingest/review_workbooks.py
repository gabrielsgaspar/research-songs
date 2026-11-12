"""Import the songs that a person added to a country review workbook.

A review workbook is a spreadsheet for one country. A reviewer checks the
artists and songs in the data and adds songs that are missing, each with its
lyrics, year and source link. This module reads a downloaded copy and writes
the added songs to the data folder, with the origin `manual_review`.

    in   raw/manual_review/<ISO3>/<YYYYMMDD>/<ISO3>_<name>_reviewed.xlsx
    out  lyrics/<ISO3>/manual_review/<run id>/songs.parquet

Only a workbook whose file name ends in `_reviewed` is imported. Lyric text
stays in the data folder; it never goes to Git or to a run record.
"""

import hashlib
import re
from pathlib import Path
from urllib.parse import urlsplit

import duckdb
import pandas as pd

from songs.common import run_records
from songs.common.years import is_admissible_year

ROUTE = "manual_review"
SOURCE = "review_workbook"
# The workbook marks a song that was already in the data with this text. Reviewers mark
# the songs they add in their own words, so every other row counts as added.
ALREADY_IN_DATA = "Link in our files"
# A review status that says the reviewer did not finish the row.
OPEN_STATUS = ("", "not checked", "needs gabriel", "not sure")
SONG_COLUMNS = (
    "Artist",
    "Song title",
    "Year",
    "Language / script",
    "Lyrics currently in file",
    "Lyric source URL",
    "Source link check",
    "Review status",
)
ARTIST_COLUMNS = ("Artist name", "Discogs artist ID", "Nationality / country in our file")
OUTPUT_COLUMNS = (
    "country_iso3",
    "song_id",
    "artist_name",
    "discogs_artist_id",
    "artist_country_tag",
    "song_name",
    "year",
    "year_source",
    "language",
    "lyrics",
    "song_url",
    "source_host",
    "origin",
)


def find_workbook(data: Path, iso3: str) -> Path:
    """Return the reviewed workbook in the newest dated folder of a country."""
    base = data / "raw" / ROUTE / iso3
    dated = sorted(path for path in base.glob("*") if re.fullmatch(r"\d{8}", path.name))
    if not dated:
        raise FileNotFoundError(f"no dated folder under {base}")
    books = sorted(dated[-1].glob("*.xlsx"))
    if len(books) != 1:
        raise ValueError(f"{dated[-1]} must hold exactly one .xlsx file, found {len(books)}")
    book = books[0]
    if not book.stem.startswith(f"{iso3}_"):
        raise ValueError(f"{book.name} does not start with {iso3}_")
    if not book.stem.endswith("_reviewed"):
        raise ValueError(f"{book.name} is not marked _reviewed; the review is not finished")
    return book


def _sheet(book: Path, name: str, required: tuple[str, ...]) -> pd.DataFrame:
    frame = pd.read_excel(book, sheet_name=name, dtype=str).fillna("")
    frame.columns = [str(column).strip() for column in frame.columns]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"{book.name}, tab {name}: missing columns {missing}")
    return frame.apply(lambda column: column.str.strip())


def read_added_songs(book: Path, iso3: str) -> tuple[pd.DataFrame, list[str]]:
    """Return the added songs of a workbook and one line for each thing left out or missing."""
    songs = _sheet(book, "Songs", SONG_COLUMNS)
    artists = _sheet(book, "Artists", ARTIST_COLUMNS).drop_duplicates("Artist name")
    added = songs[songs["Source link check"] != ALREADY_IN_DATA]
    gaps = []

    def leave_out(mask: pd.Series, reason: str) -> None:
        nonlocal added
        if mask.any():
            gaps.append(f"{int(mask.sum())} added songs left out: {reason}")
            added = added[~mask]

    leave_out(added["Review status"].str.lower().isin(OPEN_STATUS), "the review is not finished")
    leave_out(added["Lyrics currently in file"] == "", "no lyrics")
    leave_out(~added["Lyric source URL"].str.startswith(("http://", "https://")), "no source link")
    leave_out(added.duplicated("Lyric source URL"), "source link appears twice")

    added = added.merge(artists, how="left", left_on="Artist", right_on="Artist name").fillna("")
    year = pd.to_numeric(added["Year"], errors="coerce")
    year = year.where(year.map(is_admissible_year)).astype("Int64")
    url = added["Lyric source URL"]
    out = pd.DataFrame(
        {
            "country_iso3": iso3,
            "song_id": [f"mr_{hashlib.sha256(u.encode('utf-8')).hexdigest()[:20]}" for u in url],
            "artist_name": added["Artist"],
            "discogs_artist_id": added["Discogs artist ID"].replace("", pd.NA),
            "artist_country_tag": added["Nationality / country in our file"],
            "song_name": added["Song title"],
            "year": year,
            "year_source": ROUTE,
            "language": added["Language / script"],
            "lyrics": added["Lyrics currently in file"],
            "song_url": url,
            "source_host": [urlsplit(u).hostname.removeprefix("www.") for u in url],
            "origin": ROUTE,
        },
        columns=list(OUTPUT_COLUMNS),
    )
    for count, text in (
        (int(out["year"].isna().sum()), "songs have no usable year"),
        (int((out["artist_country_tag"] == "").sum()), "songs name an artist absent from Artists"),
        (int(out["discogs_artist_id"].isna().sum()), "songs are by an artist with no Discogs id"),
        (
            int(out["artist_country_tag"].str.contains("/").sum()),
            "songs are by an artist tagged with more than one country",
        ),
    ):
        if count:
            gaps.append(f"{count} {text}")
    return out, gaps


def import_workbook(data: Path, iso3: str, *, countries: Path | None = None) -> dict:
    """Import the reviewed workbook of one country and write its run record."""
    book = find_workbook(data, iso3)
    bulk_file = book.relative_to(data).as_posix()
    for earlier in run_records.read_run_records(iso3, countries):
        if earlier.route == ROUTE and earlier.bulk_file == bulk_file and earlier.state != "failed":
            raise FileExistsError(
                f"{bulk_file} was imported in run {earlier.run_id}. "
                "Put a new download in a new dated folder to import again."
            )
    with run_records.record_run(
        iso3, ROUTE, SOURCE, countries=countries, bulk_file=bulk_file
    ) as record:
        songs, gaps = read_added_songs(book, iso3)
        out = data / "lyrics" / iso3 / ROUTE / record.run_id / "songs.parquet"
        out.parent.mkdir(parents=True, exist_ok=False)
        duckdb.from_df(songs).write_parquet(str(out), compression="zstd")
        record.rows_added = len(songs)
        record.artists_attempted = int(songs["artist_name"].nunique())
        record.known_gaps = gaps
    return {"path": out, "rows": len(songs), "gaps": gaps}
