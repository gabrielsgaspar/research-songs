"""The analysis release: the files that every table and regression of the paper reads.

`build` writes `analysis/<YYYYMMDD>/` with `country_year.parquet`, `songs.parquet` and
the manifest (`docs/standards/data_layout.md`, "Analysis release"). It reads the
newest complete songs folder and scores folder of each country and the newest
country-year table. `eligible_songs.classify` decides which songs enter. A score
joins a song on `song_id` and `lyrics_sha256`, so a score of other lyric text does
not count. The manifest counts the songs read, the songs that enter, and the songs
left out for each reason.
"""

import hashlib
from datetime import date
from pathlib import Path

import duckdb

from songs.common import manifests, paths, schemas
from songs.stage_30_topics.topic_ids import TOPIC_IDS
from songs.stage_50_analysis import eligible_songs
from songs.stage_50_analysis.countries_panel import COUNTRY_COLUMNS
from songs.stage_50_analysis.eligible_songs import country_folders

# Columns of the country-year table that the release counts again from the eligible songs.
REPLACED_PANEL_COLUMNS = ("num_songs", "num_artists", "artist_count_method")
TOPICS = ", ".join(f'"{topic}"' for topic in TOPIC_IDS)


def _one(connection: duckdb.DuckDBPyConnection, query: str) -> int:
    return connection.sql(query).fetchall()[0][0]


def _read_inputs(
    connection: duckdb.DuckDBPyConnection, countries: list[tuple[str, Path, Path | None]]
) -> None:
    """Load the songs (no lyric text) and the scores of every country into two tables."""
    eligible_songs.read_country_tables(
        connection,
        "songs",
        schemas.COUNTRY_SONGS,
        [(code, folder) for code, folder, _ in countries],
        ", ".join(eligible_songs.SONG_COLUMNS),
    )
    eligible_songs.read_country_tables(
        connection,
        "scores",
        schemas.SCORE_TOPICS,
        [(code, folder) for code, _, folder in countries if folder is not None],
    )


def _release_songs(connection: duckdb.DuckDBPyConnection) -> duckdb.DuckDBPyRelation:
    """Return one row per eligible song with its scores, in the columns of the release."""
    return connection.sql(
        f"""
        SELECT c.country_iso3, c.song_id, c.artist_id, c.year, c.source, c.route,
            c.by_exception, s.song_id IS NOT NULL AS scored,
            {", ".join(f's."{topic}"' for topic in TOPIC_IDS)}
        FROM classified AS c
        LEFT JOIN scores AS s
            ON c.country_iso3 = s.country_iso3
            AND c.song_id = s.song_id
            AND c.lyrics_sha256 = s.lyrics_sha256
        WHERE c.ineligible_reason IS NULL
        ORDER BY c.country_iso3, c.song_id
        """
    )


def _country_year(connection: duckdb.DuckDBPyConnection) -> duckdb.DuckDBPyRelation:
    """Return the country-year table with the counts and the mean scores of the eligible songs.

    A country with no songs folder has empty counts; a covered country has 0 in a
    year with no eligible song.
    """
    eligible_songs.year_counts(connection.table("release_songs")).create("year_counts")
    means = ", ".join(f'avg("{topic}") AS "{topic}"' for topic in TOPIC_IDS)
    counts = ("num_songs", "num_artists", "num_songs_by_exception", "num_songs_scored")
    covered = ", ".join(
        f"CASE WHEN p.country_iso3 IN (SELECT country_iso3 FROM covered) "
        f"THEN coalesce(a.{name}, 0) END AS {name}"
        for name in counts
    )
    return connection.sql(
        f"""
        WITH a AS (
            SELECT country_iso3, year, any_value(num_songs) AS num_songs,
                any_value(num_artists) AS num_artists,
                count(*) FILTER (WHERE by_exception) AS num_songs_by_exception,
                count(*) FILTER (WHERE scored) AS num_songs_scored, {means}
            FROM release_songs JOIN year_counts USING (country_iso3, year)
            GROUP BY country_iso3, year
        )
        SELECT p.country_iso3, CAST(p.year AS INTEGER) AS year, {covered},
            {", ".join(f'a."{topic}"' for topic in TOPIC_IDS)},
            p.* EXCLUDE (country_iso3, year, {", ".join(REPLACED_PANEL_COLUMNS)})
        FROM panel AS p LEFT JOIN a USING (country_iso3, year)
        ORDER BY p.country_iso3, p.year
        """
    )


def _counts(connection: duckdb.DuckDBPyConnection) -> dict[str, int]:
    """Count the songs in, the songs out, the songs left out for each reason, and the scores."""
    rule = eligible_songs.reason_counts(connection.table("classified"))
    counts = {
        "songs": rule["songs"],
        "eligible_songs": rule["eligible_songs"],
        "songs_by_exception": _one(connection, "SELECT count_if(by_exception) FROM release_songs"),
        "songs_scored": _one(connection, "SELECT count_if(scored) FROM release_songs"),
        "country_year_left_out_no_year": rule["eligible_songs_no_year"],
        "songs_outside_panel": _one(
            connection,
            "SELECT count(*) FROM release_songs ANTI JOIN panel USING (country_iso3, year) "
            "WHERE year IS NOT NULL",
        ),
        "scores": _one(connection, "SELECT count(*) FROM scores"),
        "scores_other_lyrics": _one(
            connection,
            "SELECT count(*) FROM scores AS s JOIN songs AS c USING (country_iso3, song_id) "
            "WHERE s.lyrics_sha256 <> c.lyrics_sha256",
        ),
        "scores_no_song": _one(
            connection, "SELECT count(*) FROM scores ANTI JOIN songs USING (country_iso3, song_id)"
        ),
        "scores_ineligible_song": _one(
            connection,
            "SELECT count(*) FROM scores AS s JOIN classified AS c USING (country_iso3, song_id) "
            "WHERE s.lyrics_sha256 = c.lyrics_sha256 AND c.ineligible_reason IS NOT NULL",
        ),
    }
    counts |= {
        f"left_out_{reason}": rule[f"left_out_{reason}"] for reason in eligible_songs.REASONS
    }
    by_country = connection.sql(
        "SELECT country_iso3, count(*) FROM release_songs WHERE by_exception GROUP BY ALL"
    ).fetchall()
    counts |= {f"songs_by_exception_{code}": number for code, number in sorted(by_country)}
    parts = ("songs_scored", "scores_other_lyrics", "scores_no_song", "scores_ineligible_song")
    if sum(counts[name] for name in parts) != counts["scores"]:
        raise ValueError(f"the scores do not add up: {parts} must sum to the scores read")
    return counts


def build(
    data: Path,
    *,
    today: date | None = None,
    exceptions_file: Path | None = None,
    suspect_file: Path | None = None,
    quarantine_file: Path | None = None,
    excluded_artists_file: Path | None = None,
    artist_countries_file: Path | None = None,
) -> dict:
    """Build the release and write it, with its manifest, to `analysis/<YYYYMMDD>/`.

    The exceptions file, the list of suspect texts and the two artist lists default to
    the tracked files in `resources/lyrics/`, and the list of songs in quarantine to
    the newest complete quarantine folder of `data`. The rule also reads the newest
    complete table of artist countries of `data`, when `data` has one.

    Raise FileNotFoundError when there is no complete country-year table or no
    complete songs folder, and FileExistsError when the folder of the day exists.
    """
    folder = paths.analysis_dir(data, today or date.today())
    if folder.exists():
        raise FileExistsError(
            f"{folder} exists; a release is never written over. "
            f"A folder without {paths.MANIFEST_NAME} is a build that did not end."
        )
    panel_folder = paths.latest_clean_countries_dir(data)
    if panel_folder is None:
        raise FileNotFoundError("no complete clean/countries/<YYYYMMDD>/ folder")
    countries = country_folders(data)
    if not countries:
        raise FileNotFoundError("no country has a complete lyrics/<ISO3>/songs/<run id>/ folder")
    exceptions_file = (
        exceptions_file or paths.resolve_project_root() / eligible_songs.EXCEPTIONS_FILE
    )
    exceptions = eligible_songs.load_exceptions(exceptions_file)
    root = paths.resolve_project_root()
    suspect_file = suspect_file or root / eligible_songs.SUSPECT_FILE
    quarantine_file = quarantine_file or eligible_songs.quarantine_file(data)
    excluded_artists_file = excluded_artists_file or root / eligible_songs.EXCLUDED_ARTISTS_FILE
    artist_countries_file = artist_countries_file or root / eligible_songs.ARTIST_COUNTRIES_FILE

    connection = duckdb.connect()
    panel = connection.read_parquet(str(panel_folder / manifests.COUNTRIES_FILE))
    if tuple(panel.columns) != COUNTRY_COLUMNS:
        raise ValueError(f"{panel_folder} has other columns than COUNTRY_COLUMNS")
    panel.create("panel")
    _read_inputs(connection, countries)
    connection.sql("CREATE TABLE covered (country_iso3 VARCHAR)")
    connection.executemany("INSERT INTO covered VALUES (?)", [(code,) for code, _, _ in countries])
    lists = (
        eligible_songs.load_hash_lists(connection, suspect_file, quarantine_file)
        | eligible_songs.load_artist_lists(
            connection, excluded_artists_file, artist_countries_file, data
        )
        | eligible_songs.load_text_copies(connection, data)
    )
    eligible_songs.classify(connection.table("songs"), exceptions, lists).create("classified")
    _release_songs(connection).create("release_songs")
    counts = _counts(connection)
    country_year = _country_year(connection)
    declared = [column.name for column in schemas.ANALYSIS_COUNTRY_YEAR.all_columns]
    passed = [name for name in COUNTRY_COLUMNS if name not in (*declared, *REPLACED_PANEL_COLUMNS)]
    if country_year.columns != declared + passed:
        raise ValueError("the columns of country_year.parquet differ from the contract")
    counts |= {
        "countries": len(countries),
        "country_years": len(country_year),
        "songs_in_country_year": int(
            country_year.aggregate("coalesce(sum(num_songs), 0)").fetchall()[0][0]
        ),
    }
    parts = ("songs_in_country_year", "country_year_left_out_no_year", "songs_outside_panel")
    if sum(counts[name] for name in parts) != counts["eligible_songs"]:
        raise ValueError(f"the eligible songs do not add up: {parts} must sum to them")

    folder.mkdir(parents=True)
    schemas.write_table(schemas.ANALYSIS_SONGS, connection.table("release_songs"), folder)
    schemas.write_table(schemas.ANALYSIS_COUNTRY_YEAR, country_year, folder)
    inputs = [paths.data_relative(data, panel_folder)]
    if quarantine_file.parent.is_relative_to(data):
        inputs.append(paths.data_relative(data, quarantine_file.parent))
    for table in (
        paths.latest_clean_artist_country_dir(data),
        paths.latest_clean_text_copies_dir(data),
        paths.latest_clean_uncredited_songs_dir(data),
    ):
        if table is not None:
            inputs.append(paths.data_relative(data, table))
    for _, songs, scores in countries:
        inputs += [paths.data_relative(data, songs)]
        inputs += [paths.data_relative(data, scores)] if scores is not None else []
    manifests.write_manifest(
        data,
        folder,
        "analysis",
        inputs=inputs,
        counts=counts,
        notes=f"Exception groups: {len(exceptions)}. The files of the rule are inputs too: "
        + "; ".join(
            f"{name.as_posix()} with SHA-256 {hashlib.sha256(path.read_bytes()).hexdigest()}"
            for name, path in (
                (eligible_songs.EXCEPTIONS_FILE, exceptions_file),
                (eligible_songs.SUSPECT_FILE, suspect_file),
                (Path(manifests.SONG_QUARANTINE_FILE), quarantine_file),
                (eligible_songs.EXCLUDED_ARTISTS_FILE, excluded_artists_file),
                (eligible_songs.ARTIST_COUNTRIES_FILE, artist_countries_file),
            )
        )
        + ".",
    )
    return {"folder": folder, "counts": counts}
