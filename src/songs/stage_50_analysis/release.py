"""The analysis release: the files that every table and regression of the paper reads.

`build` writes `analysis/<YYYYMMDD>/` with `country_year.parquet`, `songs.parquet` and
the manifest (`docs/standards/data_layout.md`, "Analysis release"). It reads the
newest complete songs folder and scores folder of each country and the newest
country-year table. `eligible_songs.classify` decides which songs enter. A score
joins a song on `song_id` and `lyrics_sha256`, so a score of other lyric text does
not count. The manifest counts the songs read, the songs that enter, and the songs
left out for each reason.
"""

from datetime import date
from pathlib import Path

import duckdb

from songs.common import manifests, paths, schemas
from songs.stage_30_topics.topic_ids import TOPIC_IDS
from songs.stage_50_analysis import eligible_songs
from songs.stage_50_analysis.countries_panel import COUNTRY_COLUMNS

# Columns of the country-year table that the release counts again from the eligible songs.
REPLACED_PANEL_COLUMNS = ("num_songs", "num_artists", "artist_count_method")
SONG_COLUMNS = ("country_iso3", "artist_id", "source", "lyrics_sha256", *eligible_songs.COLUMNS)
TOPICS = ", ".join(f'"{topic}"' for topic in TOPIC_IDS)


def country_folders(data: Path) -> list[tuple[str, Path, Path | None]]:
    """Return each country that has a complete songs folder.

    Each item is the country code, the newest complete songs folder, and the newest
    complete scores folder or None.
    """
    found = []
    for folder in sorted((data / "lyrics").glob("*")):
        try:
            code = paths.check_iso3(folder.name)
        except ValueError:
            continue
        songs = paths.latest_country_songs_dir(data, code)
        if songs is not None:
            found.append((code, songs, paths.latest_country_scores_dir(data, code)))
    return found


def _stack(connection: duckdb.DuckDBPyConnection, name: str, parts: list) -> None:
    """Create one table from relations that have the same columns in the same order."""
    first, *rest = parts
    first.create(name)
    for part in rest:
        part.insert_into(name)


def _one(connection: duckdb.DuckDBPyConnection, query: str) -> int:
    return connection.sql(query).fetchall()[0][0]


def _read_inputs(
    connection: duckdb.DuckDBPyConnection, countries: list[tuple[str, Path, Path | None]]
) -> None:
    """Load the songs (no lyric text) and the scores of every country into two tables."""
    songs = [
        schemas.read_table(schemas.COUNTRY_SONGS, folder, connection).project(
            ", ".join(SONG_COLUMNS)
        )
        for _, folder, _ in countries
    ]
    _stack(connection, "songs", songs)
    scores = [
        schemas.read_table(schemas.SCORE_TOPICS, folder, connection)
        for _, _, folder in countries
        if folder is not None
    ]
    _stack(connection, "scores", scores or [schemas.empty_table(schemas.SCORE_TOPICS, connection)])


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
            SELECT country_iso3, year, count(*) AS num_songs,
                count(DISTINCT artist_id) AS num_artists,
                count(*) FILTER (WHERE by_exception) AS num_songs_by_exception,
                count(*) FILTER (WHERE scored) AS num_songs_scored, {means}
            FROM release_songs GROUP BY country_iso3, year
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
    counts = {
        "songs": _one(connection, "SELECT count(*) FROM classified"),
        "eligible_songs": _one(connection, "SELECT count(*) FROM release_songs"),
        "songs_by_exception": _one(connection, "SELECT count_if(by_exception) FROM release_songs"),
        "songs_scored": _one(connection, "SELECT count_if(scored) FROM release_songs"),
        "songs_outside_panel": _one(
            connection,
            "SELECT count(*) FROM release_songs ANTI JOIN panel USING (country_iso3, year)",
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
    }
    left_out = dict(
        connection.sql(
            "SELECT ineligible_reason, count(*) FROM classified "
            "WHERE ineligible_reason IS NOT NULL GROUP BY ALL"
        ).fetchall()
    )
    counts |= {f"left_out_{reason}": left_out.get(reason, 0) for reason in eligible_songs.REASONS}
    by_country = connection.sql(
        "SELECT country_iso3, count(*) FROM release_songs WHERE by_exception GROUP BY ALL"
    ).fetchall()
    counts |= {f"songs_by_exception_{code}": number for code, number in sorted(by_country)}
    left = sum(counts[f"left_out_{reason}"] for reason in eligible_songs.REASONS)
    if counts["eligible_songs"] + left != counts["songs"]:
        raise ValueError("the eligible songs and the songs left out do not add up to the songs")
    return counts


def build(data: Path, *, today: date | None = None, exceptions_file: Path | None = None) -> dict:
    """Build the release and write it, with its manifest, to `analysis/<YYYYMMDD>/`.

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
    exceptions = eligible_songs.load_exceptions(exceptions_file)

    connection = duckdb.connect()
    panel = connection.read_parquet(str(panel_folder / manifests.COUNTRIES_FILE))
    if tuple(panel.columns) != COUNTRY_COLUMNS:
        raise ValueError(f"{panel_folder} has other columns than COUNTRY_COLUMNS")
    panel.create("panel")
    _read_inputs(connection, countries)
    connection.sql("CREATE TABLE covered (country_iso3 VARCHAR)")
    connection.executemany("INSERT INTO covered VALUES (?)", [(code,) for code, _, _ in countries])
    eligible_songs.classify(connection.table("songs"), exceptions).create("classified")
    _release_songs(connection).create("release_songs")
    counts = _counts(connection)
    country_year = _country_year(connection)
    counts |= {
        "countries": len(countries),
        "country_years": len(country_year),
    }

    folder.mkdir(parents=True)
    schemas.write_table(schemas.ANALYSIS_SONGS, connection.table("release_songs"), folder)
    schemas.write_table(schemas.ANALYSIS_COUNTRY_YEAR, country_year, folder)
    inputs = [paths.data_relative(data, panel_folder)]
    for _, songs, scores in countries:
        inputs += [paths.data_relative(data, songs)]
        inputs += [paths.data_relative(data, scores)] if scores is not None else []
    manifests.write_manifest(
        data,
        folder,
        "analysis",
        inputs=inputs,
        counts=counts,
        notes=f"Exception groups: {len(exceptions)}. "
        "The tracked file resources/lyrics/eligibility_exceptions.csv is an input too; "
        "code_commit names its version.",
    )
    return {"folder": folder, "counts": counts}
