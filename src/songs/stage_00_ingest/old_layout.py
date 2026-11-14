"""Import the state of one country from the files of the old layout.

The old pipeline keeps one lyric file and one link file for each artist. This
module reads the files of one country and writes the full tables of the country
in the layout of `docs/standards/data_layout.md`.

    in   <old data folder>/lyrics/<iso3>/lyrics/*.parquet         one file for each artist
    in   <old data folder>/lyrics/<iso3>/lyrics_links/*.parquet   one file for each artist
    in   <old data folder>/lyrics/<iso3>/artists.csv              the roster
    in   <old data folder>/lyrics/<iso3>/discogs_cache/artists.parquet   Discogs ids
    in   lyrics/<ISO3>/songs/<run id>/   the newest folder of the country, when one exists
    out  lyrics/<ISO3>/songs/<run id>/   artists.parquet, songs.parquet, links.parquet,
                                         _MANIFEST.json

The old data folder is read only, and it is not the data folder of the new
layout. Every row gets the route `old_layout`: the old files do not record the
route of the first collection of a row, so the importer does not guess one.

An import can run again, because the old pipeline still writes. The new folder
then holds the old files as they are now, and the rows that a run with another
route added to the earlier folder. Lyric text never goes to Git, to a manifest
or to a run record.
"""

import csv
import uuid
from pathlib import Path

import duckdb
import pandas as pd

from songs.common import manifests, paths, run_records, schemas

ROUTE = "old_layout"
SOURCE = "old_pipeline"
OLD_DATA_ENV = "SONGS_OLD_DATA_ROOT"
TEXT = "VARCHAR"
# Old column -> the type that the importer reads it as. A column that the files lack is empty.
SONG_COLUMNS = {
    "song_id": TEXT,
    "artist_id": TEXT,
    "artist_name": TEXT,
    "provider": TEXT,
    "provider_song_id": TEXT,
    "song_url": TEXT,
    "lyrics": TEXT,
    "year": "INTEGER",
    "year_source": TEXT,
    "year_basis": TEXT,
    "first_release_year": "INTEGER",
    "canonical_song_id": TEXT,
    "duplicate_decision": TEXT,
    "quality_status": TEXT,
    "scraped_at_utc": TEXT,
}
LINK_COLUMNS = {
    "song_id": TEXT,
    "discogs_release_id": TEXT,
    "discogs_track_index": TEXT,
    "discogs_title": TEXT,
    "provider": TEXT,
    "provider_song_id": TEXT,
    "provider_title": TEXT,
    "song_url": TEXT,
    "match_method": TEXT,
    "match_score": "DOUBLE",
}
ROSTER_COLUMNS = ("artist_id", "name", "scraped", "scrapped", "scraped_at_utc", "country_basis")
# The only rules that drop a row, in the order in which a row is tested.
SONG_DROPS = (
    "no_song_id",
    "no_lyrics",
    "no_source",
    "no_artist",
    "held_by_other_route",
    "duplicate_song_id",
)
LINK_DROPS = ("no_catalog_track", "no_song", "duplicate_key")
# An old time is UTC text with the offset +00:00, and can have a fraction of a second. The
# layout wants a UTC second. The cast ignores an offset, so a time with another offset is
# read as empty, and never as a wrong UTC time.
UTC_SECOND = (
    "CASE WHEN regexp_matches({0}, '[+-]\\d\\d:?\\d\\d$') "
    "AND NOT regexp_matches({0}, '[+-]00:?00$') THEN NULL "
    "ELSE strftime(TRY_CAST({0} AS TIMESTAMP), '%Y-%m-%dT%H:%M:%SZ') END"
)


def _old_view(
    connection: duckdb.DuckDBPyConnection, folder: Path, columns: dict[str, str], view: str
) -> int:
    """Make a view of all Parquet files of an old folder, with exactly `columns`.

    Return the number of files. The old files do not all have the same columns.
    Blank text is read as empty. A number that does not fit its type is read as empty.
    """
    files = len(list(folder.glob("*.parquet"))) if folder.is_dir() else 0
    if files:
        pattern = (folder / "*.parquet").as_posix().replace("'", "''")
        source = (
            f"read_parquet('{pattern}', union_by_name=true, filename=true, file_row_number=true)"
        )
        found = set(connection.sql(f"SELECT * FROM {source} LIMIT 0").columns)
    else:
        source = "(SELECT NULL AS filename, NULL AS file_row_number LIMIT 0)"
        found = set()

    def field(name: str, kind: str) -> str:
        if name not in found:
            return f'CAST(NULL AS {kind}) AS "{name}"'
        if kind == TEXT:
            text = f'CAST("{name}" AS {TEXT})'
            return f"CASE WHEN trim({text}) = '' THEN NULL ELSE {text} END AS \"{name}\""
        return f'TRY_CAST("{name}" AS {kind}) AS "{name}"'

    select = ", ".join(field(name, kind) for name, kind in columns.items())
    connection.sql(
        f"CREATE VIEW {view} AS SELECT filename, file_row_number, {select} FROM {source}"
    )
    return files


def read_roster(country: Path) -> tuple[pd.DataFrame, dict[str, int]]:
    """Return the roster of an old country folder, one row per artist, and the rows left out.

    A row with no artist id or no name is left out. When an artist id appears
    again, the first row stays: two names with one id are one artist.
    """
    path = country / "artists.csv"
    rows = []
    if path.is_file():
        with path.open(encoding="utf-8-sig", newline="") as handle:
            rows = [
                {name: (row.get(name) or "").strip() for name in ROSTER_COLUMNS}
                for row in csv.DictReader(handle)
            ]
    frame = pd.DataFrame(rows, columns=list(ROSTER_COLUMNS), dtype="string")
    named = frame[(frame["artist_id"] != "") & (frame["name"] != "")]
    roster = named.drop_duplicates("artist_id")
    return roster, {
        "roster_rows_dropped_no_id_or_name": len(frame) - len(named),
        "roster_rows_dropped_repeated_artist_id": len(named) - len(roster),
    }


def read_discogs_ids(country: Path) -> pd.DataFrame:
    """Return the Discogs id of each artist id that the Discogs cache of the country proves.

    The old artist id is a UUID made from the Discogs artist page, and the roster
    does not hold the Discogs id. The cache lists Discogs ids, so the importer
    makes the UUID of each one and joins on it. An artist that the cache does not
    hold keeps its old artist id and has no Discogs id.
    """
    cache = country / "discogs_cache" / "artists.parquet"
    ids = []
    if cache.is_file():
        ids = [
            str(row[0])
            for row in duckdb.read_parquet(str(cache))
            .filter("artist_id IS NOT NULL")
            .project("artist_id")
            .distinct()
            .fetchall()
        ]
    made = [
        str(uuid.uuid5(uuid.NAMESPACE_URL, f"https://www.discogs.com/artist/{number}"))
        for number in ids
    ]
    return pd.DataFrame({"artist_id": made, "discogs_artist_id": ids}, dtype="string")


def write_country(country: Path, earlier: Path | None, out: Path, iso3: str, run_id: str) -> dict:
    """Write the three tables of a country to `out` from an old country folder. Return the counts.

    `earlier` is the newest songs folder of the country, or None. Its rows with
    another route stay. Its rows with the route `old_layout` are replaced by the
    old files as they are now.
    """
    with duckdb.connect() as connection:
        return _write_country(connection, country, earlier, out, iso3, run_id)


def _count(connection: duckdb.DuckDBPyConnection, query: str) -> int:
    return connection.sql(f"SELECT count(*) FROM {query}").fetchall()[0][0]


def _write_country(
    connection: duckdb.DuckDBPyConnection,
    country: Path,
    earlier: Path | None,
    out: Path,
    iso3: str,
    run_id: str,
) -> dict:
    for name, table in (
        ("earlier_artists", schemas.COUNTRY_ARTISTS),
        ("earlier_songs", schemas.COUNTRY_SONGS),
        ("earlier_links", schemas.COUNTRY_LINKS),
    ):
        relation = (
            schemas.read_table(table, earlier, connection)
            if earlier
            else schemas.empty_table(table, connection)
        )
        relation.create_view(name)
    connection.sql(
        f"CREATE VIEW kept_songs AS SELECT * FROM earlier_songs WHERE route <> '{ROUTE}'"
    )

    counts = {
        "old_lyric_files": _old_view(connection, country / "lyrics", SONG_COLUMNS, "old_songs"),
        "old_link_files": _old_view(
            connection, country / "lyrics_links", LINK_COLUMNS, "old_links"
        ),
    }
    roster, roster_drops = read_roster(country)
    connection.register("roster_frame", roster)
    connection.register("discogs_frame", read_discogs_ids(country))
    # A frame with no rows has no column types, so each column is cast to text.
    connection.sql(
        f"""
        CREATE VIEW roster AS
        SELECT
            CAST(artist_id AS {TEXT}) AS artist_id,
            CAST(name AS {TEXT}) AS artist_name,
            nullif(CAST(country_basis AS {TEXT}), '') AS country_tag,
            {UTC_SECOND.format("nullif(CAST(scraped_at_utc AS VARCHAR), '')")} AS last_attempt_utc,
            lower(CAST(scraped AS {TEXT})) IN ('true', '1')
                OR lower(CAST(scrapped AS {TEXT})) IN ('true', '1')
                OR CAST(scraped_at_utc AS {TEXT}) <> '' AS attempted
        FROM roster_frame
        """
    )
    connection.sql(
        f"CREATE VIEW discogs AS SELECT CAST(artist_id AS {TEXT}) AS artist_id, "
        f"CAST(discogs_artist_id AS {TEXT}) AS discogs_artist_id FROM discogs_frame"
    )

    # One narrow row for each old song row says whether the row stays, and why not.
    connection.sql(
        f"""
        CREATE TEMP TABLE picked AS
        WITH read AS (
            SELECT
                s.filename,
                s.file_row_number,
                s.song_id,
                s.artist_id,
                coalesce(s.artist_name, r.artist_name) AS artist_name,
                s.provider AS source,
                s.song_url,
                sha256(s.lyrics) AS lyrics_sha256,
                {UTC_SECOND.format("s.scraped_at_utc")} AS collected_utc,
                s.scraped_at_utc IS NOT NULL AS has_time,
                CASE
                    WHEN s.song_id IS NULL THEN 'no_song_id'
                    WHEN s.lyrics IS NULL THEN 'no_lyrics'
                    WHEN s.provider IS NULL THEN 'no_source'
                    WHEN s.artist_id IS NULL OR coalesce(s.artist_name, r.artist_name) IS NULL
                        THEN 'no_artist'
                    WHEN s.song_id IN (SELECT song_id FROM kept_songs) THEN 'held_by_other_route'
                END AS fault
            FROM old_songs AS s
            LEFT JOIN roster AS r ON r.artist_id = s.artist_id
        )
        SELECT
            * EXCLUDE (fault),
            coalesce(
                fault,
                CASE WHEN row_number() OVER (
                    PARTITION BY song_id, fault IS NULL
                    ORDER BY collected_utc DESC NULLS LAST, lyrics_sha256, filename,
                        file_row_number
                ) > 1 THEN 'duplicate_song_id' END,
                'keep'
            ) AS status
        FROM read
        """
    )
    connection.sql(
        """
        CREATE TEMP TABLE links_picked AS
        WITH read AS (
            SELECT
                l.*,
                p.artist_id,
                p.source AS song_source,
                p.song_url AS song_page,
                CASE
                    WHEN l.discogs_release_id IS NULL OR l.discogs_track_index IS NULL
                        THEN 'no_catalog_track'
                    WHEN p.song_id IS NULL THEN 'no_song'
                END AS fault
            FROM old_links AS l
            LEFT JOIN (SELECT * FROM picked WHERE status = 'keep') AS p ON p.song_id = l.song_id
        )
        SELECT
            * EXCLUDE (fault),
            coalesce(
                fault,
                CASE WHEN row_number() OVER (
                    PARTITION BY song_id, discogs_release_id, discogs_track_index, fault IS NULL
                    ORDER BY match_score DESC NULLS LAST, provider_title, match_method, song_url,
                        discogs_title, provider_song_id, filename, file_row_number
                ) > 1 THEN 'duplicate_key' END,
                'keep'
            ) AS status
        FROM read
        """
    )
    # The old lyric files have no title. Every link of a song gives one, also a link with
    # no catalog track. The link to the page of the song comes first, then the best match.
    connection.sql(
        """
        CREATE TEMP TABLE titles AS
        SELECT
            song_id,
            first(provider_title ORDER BY
                (song_url = song_page) DESC NULLS LAST, match_score DESC NULLS LAST,
                provider_title) AS song_name
        FROM links_picked
        WHERE provider_title IS NOT NULL AND artist_id IS NOT NULL
        GROUP BY song_id
        """
    )
    imported = connection.sql(
        f"""
        SELECT
            '{iso3}' AS country_iso3, p.song_id, p.artist_id, p.artist_name, t.song_name,
            NULL AS title_key, p.source, s.provider_song_id AS source_song_id, s.song_url,
            s.lyrics, p.lyrics_sha256, NULL AS language, s.year, s.year_source, s.year_basis,
            s.first_release_year, s.canonical_song_id, s.duplicate_decision, s.quality_status,
            '{ROUTE}' AS route, '{run_id}' AS run_id, p.collected_utc
        FROM old_songs AS s
        JOIN picked AS p ON p.filename = s.filename AND p.file_row_number = s.file_row_number
        LEFT JOIN titles AS t ON t.song_id = p.song_id
        WHERE p.status = 'keep'
        """
    )
    schemas.cast_to_schema(schemas.COUNTRY_SONGS, imported).create_view("imported_songs")
    connection.sql(
        "CREATE VIEW new_songs AS SELECT * FROM imported_songs "
        "UNION ALL BY NAME SELECT * FROM kept_songs"
    )
    schemas.write_table(schemas.COUNTRY_SONGS, connection.sql("SELECT * FROM new_songs"), out)
    # The artists and the counts read the file just written, so the old lyric files are not
    # read one more time.
    connection.read_parquet(str(out / schemas.COUNTRY_SONGS.file)).create_view("written_songs")

    links = connection.sql(
        f"""
        SELECT
            '{iso3}' AS country_iso3, song_id, artist_id, discogs_release_id,
            discogs_track_index, discogs_title, coalesce(provider, song_source) AS source,
            provider_song_id AS source_song_id, provider_title AS source_title, song_url,
            match_method, match_score, '{run_id}' AS run_id
        FROM links_picked
        WHERE status = 'keep'
        """
    )
    schemas.cast_to_schema(schemas.COUNTRY_LINKS, links).create_view("imported_links")
    connection.sql(
        "CREATE VIEW new_links AS SELECT * FROM imported_links UNION ALL BY NAME "
        "SELECT * FROM earlier_links SEMI JOIN kept_songs USING (song_id)"
    )
    schemas.write_table(schemas.COUNTRY_LINKS, connection.sql("SELECT * FROM new_links"), out)

    # An artist of the earlier folder stays when the roster has it or when it has a song.
    artists = connection.sql(
        f"""
        WITH counted AS (
            SELECT artist_id, count(*) AS songs, min(artist_name) AS artist_name
            FROM written_songs GROUP BY artist_id
        ),
        listed AS (
            SELECT
                artist_id, r.artist_name AS roster_name, r.country_tag, r.last_attempt_utc,
                r.attempted, c.artist_name AS song_name, c.songs
            FROM roster AS r FULL JOIN counted AS c USING (artist_id)
        )
        SELECT
            '{iso3}' AS country_iso3,
            artist_id,
            coalesce(l.roster_name, e.artist_name, l.song_name) AS artist_name,
            coalesce(d.discogs_artist_id, e.discogs_artist_id) AS discogs_artist_id,
            coalesce(l.country_tag, e.country_tag) AS country_tag,
            coalesce(l.attempted OR coalesce(e.attempted, false), e.attempted, true) AS attempted,
            CASE
                WHEN e.last_attempt_utc > coalesce(l.last_attempt_utc, '') THEN e.last_attempt_utc
                ELSE l.last_attempt_utc
            END AS last_attempt_utc,
            coalesce(l.songs, 0) AS songs
        FROM listed AS l
        LEFT JOIN earlier_artists AS e USING (artist_id)
        LEFT JOIN discogs AS d USING (artist_id)
        ORDER BY artist_name, artist_id
        """
    )
    schemas.cast_to_schema(schemas.COUNTRY_ARTISTS, artists).create_view("new_artists")
    schemas.write_table(schemas.COUNTRY_ARTISTS, connection.sql("SELECT * FROM new_artists"), out)

    song_status = dict(connection.sql("SELECT status, count(*) FROM picked GROUP BY 1").fetchall())
    link_status = dict(
        connection.sql("SELECT status, count(*) FROM links_picked GROUP BY 1").fetchall()
    )
    return {
        "songs": _count(connection, "written_songs"),
        "artists": _count(connection, "new_artists"),
        "links": _count(connection, "new_links"),
        "songs_added": _count(connection, "written_songs ANTI JOIN earlier_songs USING (song_id)"),
        "songs_removed": _count(
            connection, "earlier_songs ANTI JOIN written_songs USING (song_id)"
        ),
        "songs_from_other_routes": _count(connection, "kept_songs"),
        **counts,
        **{f"songs_dropped_{reason}": song_status.get(reason, 0) for reason in SONG_DROPS},
        **{f"links_dropped_{reason}": link_status.get(reason, 0) for reason in LINK_DROPS},
        **roster_drops,
        "songs_without_title": _count(connection, "written_songs WHERE song_name IS NULL"),
        "songs_time_not_read": _count(
            connection, "picked WHERE status = 'keep' AND has_time AND collected_utc IS NULL"
        ),
        "artists_absent_from_roster": _count(
            connection, "new_artists ANTI JOIN roster USING (artist_id)"
        ),
        "artists_without_discogs_id": _count(
            connection, "new_artists WHERE discogs_artist_id IS NULL"
        ),
    }


def import_country(
    old_data: Path,
    data: Path,
    iso3: str,
    *,
    reason: str | None = None,
    countries: Path | None = None,
) -> dict:
    """Import one country from the old data folder, and write its manifest and its run record.

    `old_data` is the old data folder; nothing is written there. `data` is the
    data folder of the new layout. A second import of a country needs a `reason`,
    which goes to the notes of the run record.
    """
    paths.check_iso3(iso3)
    if old_data.resolve() == data.resolve():
        raise ValueError(
            "the old data folder and the data folder are the same folder; "
            "the old data folder is read only"
        )
    country = old_data / "lyrics" / iso3.lower()
    if not country.is_dir():
        raise FileNotFoundError(f"no folder lyrics/{iso3.lower()}/ in the old data folder")
    for past in run_records.read_run_records(iso3, countries):
        if past.route == ROUTE and past.state != "failed" and not reason:
            raise FileExistsError(
                f"{iso3} was imported from the old layout in run {past.run_id}. "
                "Give a reason to import it again."
            )
    with run_records.record_run(
        iso3, ROUTE, SOURCE, countries=countries, notes=reason or ""
    ) as record:
        earlier = paths.latest_country_songs_dir(data, iso3)
        # The first input is relative to the old data folder; no path of that folder is recorded.
        inputs = [f"lyrics/{iso3.lower()}/"]
        if earlier:
            if earlier.name >= record.run_id:
                raise ValueError(f"{earlier} is not older than this run ({record.run_id})")
            manifests.read_manifest(earlier)
            inputs.append(paths.data_relative(data, earlier))
        out = paths.country_songs_dir(data, iso3, record.run_id)
        out.mkdir(parents=True, exist_ok=False)
        counts = write_country(country, earlier, out, iso3, record.run_id)
        manifests.write_manifest(
            data,
            out,
            "country_songs",
            country_iso3=iso3,
            run_id=record.run_id,
            inputs=inputs,
            counts=counts,
            notes=(
                f"State of the country in the old layout. The input lyrics/{iso3.lower()}/ is "
                "relative to the old data folder. The route of the first collection of a row "
                "is not recorded in the old files."
            ),
        )
        record.rows_added = counts["songs_added"]
        record.known_gaps = [
            f"{name}: {value} rows"
            for name, value in counts.items()
            if "_dropped_" in name and value
        ]
    return {"path": out, **counts}
