"""Import the songs that a person added to a country review workbook.

A review workbook is a spreadsheet for one country. A reviewer checks the
artists and songs in the data and adds songs that are missing, each with its
lyrics, year and source link. This module reads a downloaded copy and adds
those songs to the songs of the country, with the route `manual_review`.

    in   raw/manual_review/<ISO3>/<YYYYMMDD>/<ISO3>_<name>_reviewed.xlsx
    in   lyrics/<ISO3>/songs/<run id>/   the newest folder of the country, when one exists
    out  lyrics/<ISO3>/songs/<run id>/   artists.parquet, songs.parquet, links.parquet,
                                         _MANIFEST.json

The new folder holds the full state of the country after the import: the rows
of the earlier folder, and the reviewed songs. A reviewed song replaces an
earlier row with the same `song_id`. When the country has no earlier folder,
the new folder holds only the reviewed songs, and `links.parquet` is empty. The
tables and the manifest follow `docs/standards/data_layout.md`.

Only a workbook whose file name ends in `_reviewed` is imported. Lyric text
stays in the data folder; it never goes to Git, to a manifest or to a run record.
"""

import hashlib
import uuid
from pathlib import Path
from urllib.parse import urlsplit

import duckdb
import pandas as pd

from songs.common import manifests, paths, run_records, schemas
from songs.common.years import is_admissible_year

ROUTE = paths.MANUAL_REVIEW
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
# The columns of `artists.parquet` that a workbook gives for the artist of each added song.
ARTIST_FIELDS = ("country_iso3", "artist_id", "artist_name", "discogs_artist_id", "country_tag")


def find_workbook(data: Path, iso3: str) -> Path:
    """Return the reviewed workbook in the newest dated folder of a country."""
    dated = paths.raw_manual_review_dirs(data, iso3)
    if not dated:
        raise FileNotFoundError(f"no dated folder under raw/{ROUTE}/{iso3}/ in {data}")
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


def artist_id(iso3: str, artist_name: str, discogs_artist_id: str) -> str:
    """Return the project id of an artist: a UUID made from the Discogs artist page.

    An artist with no Discogs id gets a UUID made from the country and the name.
    """
    if discogs_artist_id:
        page = f"https://www.discogs.com/artist/{discogs_artist_id}"
    else:
        page = f"https://research-songs.invalid/artist/{iso3}/{artist_name}"
    return str(uuid.uuid5(uuid.NAMESPACE_URL, page))


def _host(url: str) -> str:
    return (urlsplit(url).hostname or "").removeprefix("www.")


def read_added_songs(book: Path, iso3: str) -> tuple[pd.DataFrame, list[str]]:
    """Return the added songs of a workbook and one line for each thing left out or missing.

    The frame has one row per song, with the columns of `songs.parquet` that a
    workbook gives, and the Discogs id and the country tag of the artist.
    """
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
    leave_out(
        ~added["Lyric source URL"].str.startswith(("http://", "https://"))
        | (added["Lyric source URL"].map(_host) == ""),
        "no source link",
    )
    leave_out(added.duplicated("Lyric source URL"), "source link appears twice")

    added = added.merge(artists, how="left", left_on="Artist", right_on="Artist name").fillna("")
    discogs, tag = added["Discogs artist ID"], added["Nationality / country in our file"]
    # The Discogs id decides the artist id, so a value that is not an id stops the import.
    not_an_id = sorted(set(discogs[(discogs != "") & ~discogs.str.fullmatch(r"\d+")]))
    if not_an_id:
        raise ValueError(
            f"{book.name}, tab Artists: Discogs artist ID is not a number: {not_an_id}"
        )
    year = pd.to_numeric(added["Year"], errors="coerce")
    year = year.where(year.map(is_admissible_year)).astype("Int64")
    url, lyrics = added["Lyric source URL"], added["Lyrics currently in file"]
    out = pd.DataFrame(
        {
            "country_iso3": iso3,
            "song_id": [f"mr_{hashlib.sha256(u.encode('utf-8')).hexdigest()[:20]}" for u in url],
            "artist_id": [
                artist_id(iso3, name, number)
                for name, number in zip(added["Artist"], discogs, strict=True)
            ],
            "artist_name": added["Artist"],
            "song_name": added["Song title"].replace("", pd.NA),
            "source": url.map(_host),
            "song_url": url,
            "lyrics": lyrics,
            "lyrics_sha256": [hashlib.sha256(text.encode("utf-8")).hexdigest() for text in lyrics],
            "language": added["Language / script"].replace("", pd.NA),
            "year": year,
            "year_source": ROUTE,
            "route": ROUTE,
            "discogs_artist_id": discogs.replace("", pd.NA),
            "country_tag": tag.replace("", pd.NA),
        }
    )
    for count, text in (
        (int(out["year"].isna().sum()), "songs have no usable year"),
        (int((tag == "").sum()), "songs name an artist absent from Artists"),
        (int((discogs == "").sum()), "songs are by an artist with no Discogs id"),
        (
            int(tag.str.contains("/").sum()),
            "songs are by an artist tagged with more than one country",
        ),
    ):
        if count:
            gaps.append(f"{count} {text}")
    return out, gaps


def write_country_songs(
    reviewed: pd.DataFrame, earlier: Path | None, out: Path, run_id: str, collected_utc: str
) -> dict[str, int]:
    """Write the three tables of a country after the import to `out`. Return the counts.

    `earlier` is the newest songs folder of the country, or None. Its rows stay,
    except a song that the review gives again. The artists of the reviewed songs
    count as attempted at `collected_utc`. The links are carried over as they are:
    a hand-collected song has no catalog track, so it has no link.
    """
    with duckdb.connect() as connection:
        return _write_country_songs(connection, reviewed, earlier, out, run_id, collected_utc)


def _write_country_songs(
    connection: duckdb.DuckDBPyConnection,
    reviewed: pd.DataFrame,
    earlier: Path | None,
    out: Path,
    run_id: str,
    collected_utc: str,
) -> dict[str, int]:
    for name, table in (
        ("old_artists", schemas.COUNTRY_ARTISTS),
        ("old_songs", schemas.COUNTRY_SONGS),
        ("old_links", schemas.COUNTRY_LINKS),
    ):
        relation = (
            schemas.read_table(table, earlier, connection)
            if earlier
            else schemas.empty_table(table, connection)
        )
        relation.create_view(name)

    absent = [
        column.name
        for column in schemas.COUNTRY_SONGS.columns
        if column.name not in (*reviewed.columns, "run_id", "collected_utc")
    ]
    rows = reviewed.drop(columns=["discogs_artist_id", "country_tag"]).assign(
        run_id=run_id, collected_utc=collected_utc, **dict.fromkeys(absent)
    )
    schemas.cast_to_schema(schemas.COUNTRY_SONGS, rows, connection).create_view("added_songs")
    # Two names with one Discogs id are one artist; the first name in the workbook stays.
    review_artists = reviewed.drop_duplicates("artist_id")[list(ARTIST_FIELDS)].assign(
        attempt_utc=collected_utc
    )
    # A frame with no rows has no column types, so each column is cast to text.
    text = ", ".join(f"CAST({name} AS VARCHAR) AS {name}" for name in review_artists.columns)
    connection.from_df(review_artists).project(text).create_view("review_artists")
    connection.sql(
        "SELECT * FROM old_songs ANTI JOIN added_songs USING (song_id) "
        "UNION ALL BY NAME SELECT * FROM added_songs"
    ).create_view("new_songs")
    artists = connection.sql(
        """
        SELECT
            coalesce(old.country_iso3, new.country_iso3) AS country_iso3,
            artist_id,
            coalesce(old.artist_name, new.artist_name) AS artist_name,
            coalesce(old.discogs_artist_id, new.discogs_artist_id) AS discogs_artist_id,
            coalesce(old.country_tag, new.country_tag) AS country_tag,
            coalesce(old.attempted, false) OR new.attempt_utc IS NOT NULL AS attempted,
            coalesce(new.attempt_utc, old.last_attempt_utc) AS last_attempt_utc,
            coalesce(counted.songs, 0) AS songs
        FROM old_artists AS old
        FULL JOIN review_artists AS new USING (artist_id)
        LEFT JOIN (
            SELECT artist_id, count(*) AS songs FROM new_songs GROUP BY artist_id
        ) AS counted USING (artist_id)
        ORDER BY artist_name, artist_id
        """
    )
    schemas.write_table(
        schemas.COUNTRY_ARTISTS,
        schemas.cast_to_schema(schemas.COUNTRY_ARTISTS, artists),
        out,
    )
    schemas.write_table(schemas.COUNTRY_SONGS, connection.sql("SELECT * FROM new_songs"), out)
    schemas.write_table(schemas.COUNTRY_LINKS, connection.sql("SELECT * FROM old_links"), out)
    replaced = len(connection.sql("SELECT 1 FROM old_songs SEMI JOIN added_songs USING (song_id)"))
    return {
        "songs": len(connection.sql("SELECT 1 FROM new_songs")),
        "artists": len(artists),
        "links": len(connection.sql("SELECT 1 FROM old_links")),
        "songs_added": len(reviewed) - replaced,
        "songs_replaced": replaced,
    }


def import_workbook(data: Path, iso3: str, *, countries: Path | None = None) -> dict:
    """Import the reviewed workbook of one country, and write its manifest and its run record.

    `rows_added` in the run record is the number of songs that are new to the
    country. A song that replaces an earlier row is counted in the manifest
    (`songs_replaced`), not in `rows_added`.
    """
    book = find_workbook(data, iso3)
    bulk_file = paths.data_relative(data, book)
    for past in run_records.read_run_records(iso3, countries):
        if past.route == ROUTE and past.bulk_file == bulk_file and past.state != "failed":
            raise FileExistsError(
                f"{bulk_file} was imported in run {past.run_id}. "
                "Put a new download in a new dated folder to import again."
            )
    with run_records.record_run(
        iso3, ROUTE, SOURCE, countries=countries, bulk_file=bulk_file
    ) as record:
        reviewed, gaps = read_added_songs(book, iso3)
        earlier = paths.latest_country_songs_dir(data, iso3)
        inputs = [paths.data_relative(data, book.parent)]
        if earlier:
            if earlier.name >= record.run_id:
                raise ValueError(f"{earlier} is not older than this run ({record.run_id})")
            manifests.read_manifest(earlier)
            inputs.append(paths.data_relative(data, earlier))
        out = paths.country_songs_dir(data, iso3, record.run_id)
        out.mkdir(parents=True, exist_ok=False)
        counts = write_country_songs(reviewed, earlier, out, record.run_id, record.started_utc)
        manifests.write_manifest(
            data,
            out,
            "country_songs",
            country_iso3=iso3,
            run_id=record.run_id,
            inputs=inputs,
            counts=counts,
            notes=f"Songs that a person added to the review workbook {bulk_file}.",
        )
        record.rows_added = counts["songs_added"]
        record.artists_attempted = int(reviewed["artist_id"].nunique())
        record.known_gaps = gaps
    return {"path": out, "gaps": gaps, **counts}
