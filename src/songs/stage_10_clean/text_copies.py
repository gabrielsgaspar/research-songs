"""Mark the campaign songs whose lyric text is a copy of another song of the same country.

    in   lyrics/<ISO3>/songs/<run id>/            songs.parquet of the newest complete
                                                  folder of each country
    out  clean/quality/text_copies/<YYYYMMDD>/    text_copies.parquet, _MANIFEST.json

A song B is a text copy of a song A of the same country when one of two conditions
holds (the keys are those of `songs.common.lyric_hash`):

1. `same_text`: A and B have the same `text_key`, for any two artists.
2. `same_artist_start`: A and B have the same `artist_id` and the same `start_key`.

A text with no key is never a copy. Only a campaign song (route `dump_name`) can
be marked. An older song keeps the duplicate decisions of the old pipeline
(`canonical_song_id`, `duplicate_decision`) and is never marked here.

The songs of one key are a group, and one song represents the group: an older song
when the group has one, else the campaign song with the smallest `run_id`, then the
smallest `song_id` (`ORDER`). Every other campaign song of the group gets one row,
with that song as `kept_song_id`. The reason is `same_text` when the song is not the
first of its `same_text` group, else `same_artist_start`. The first song in `ORDER`
of a set of linked groups is never marked, so each text keeps one song.

The rule reads each text one time, on two threads, one country at a time. The data
folders are write-once, so the rule marks the copies and deletes nothing; the rule
for eligible songs leaves the marked songs out.
"""

import tempfile
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd

from songs.common import lyric_hash, manifests, paths, schemas
from songs.common.schemas import SAME_ARTIST_START, SAME_TEXT

ROUTE = "dump_name"
# The order of the songs of a group; `campaign` is true for the route `ROUTE`.
ORDER = "campaign, run_id, song_id"


def country_copies(folder: Path, iso3: str) -> tuple[list[tuple], dict[str, int]]:
    """Return the rows of the table for one songs folder, and its counts.

    A row is (country, song id, kept song id, reason). The counts are the songs read
    (`songs_in`), the campaign songs, the songs whose text has no key, and the rows by reason.
    """
    with duckdb.connect() as connection, tempfile.TemporaryDirectory() as spill:
        connection.execute(f"SET temp_directory = '{Path(spill).as_posix()}'")
        connection.execute("SET memory_limit = '4GB'")
        connection.execute("SET threads = 2")
        connection.execute("SET preserve_insertion_order = false")
        schemas.read_table(schemas.COUNTRY_SONGS, folder, connection, fill_absent=True).create_view(
            "songs"
        )
        connection.execute(
            "CREATE TEMP TABLE keyed AS SELECT song_id, artist_id, run_id, "
            f"coalesce(route = '{ROUTE}', false) AS campaign, {lyric_hash.text_keys_sql()} "
            "FROM songs"
        )
        songs_in, campaign, no_key = connection.execute(
            "SELECT count(*), coalesce(count_if(campaign), 0), "
            "coalesce(count_if(text_key IS NULL), 0) FROM keyed"
        ).fetchall()[0]
        rows = connection.execute(
            f"""
            SELECT '{paths.check_iso3(iso3)}', song_id,
                CASE WHEN text_first <> song_id THEN text_first ELSE start_first END,
                CASE WHEN text_first <> song_id THEN '{SAME_TEXT}' ELSE '{SAME_ARTIST_START}' END
            FROM (
                SELECT song_id, campaign,
                    first_value(song_id) OVER (PARTITION BY text_key ORDER BY {ORDER})
                        AS text_first,
                    first_value(song_id) OVER (PARTITION BY artist_id, start_key ORDER BY {ORDER})
                        AS start_first
                FROM keyed WHERE text_key IS NOT NULL
            )
            WHERE campaign AND (text_first <> song_id OR start_first <> song_id)
            ORDER BY song_id
            """
        ).fetchall()
    counts = {
        "songs_in": songs_in,
        "campaign_songs": campaign,
        "songs_no_key": no_key,
        SAME_TEXT: sum(row[3] == SAME_TEXT for row in rows),
        SAME_ARTIST_START: sum(row[3] == SAME_ARTIST_START for row in rows),
    }
    return rows, counts


def check_copies(data: Path, *, write: bool = False, today: date | None = None) -> dict:
    """Apply the rule to the newest complete songs folder of every country. Return the counts.

    With `write`, write the folder of the day with the table and its manifest, and
    return it as `folder`. Raise FileExistsError when the folder of the day exists.
    `counts` holds the songs read (`songs_in`), the campaign songs, the songs with no
    key, the rows out (`copies`) and the rows by reason. `by_country` gives, for each
    country with a copy, the copies, the campaign songs and all songs.
    """
    out = paths.clean_text_copies_dir(data, today or date.today())
    if write and out.exists():
        raise FileExistsError(f"{out} exists; a version folder is never written over")
    names = ("songs_in", "campaign_songs", "songs_no_key", SAME_TEXT, SAME_ARTIST_START)
    counts = dict.fromkeys(("countries", *names, "copies"), 0)
    rows, inputs, by_country = [], [], {}
    for parent in sorted((data / "lyrics").glob("*")):
        folder = (
            paths.latest_country_songs_dir(data, parent.name)
            if paths.ISO3.fullmatch(parent.name)
            else None
        )
        if folder is None:
            continue
        found, one = country_copies(folder, parent.name)
        counts["countries"] += 1
        for name in names:
            counts[name] += one[name]
        counts["copies"] += len(found)
        if found:
            by_country[parent.name] = (len(found), one["campaign_songs"], one["songs_in"])
        rows += found
        inputs.append(paths.data_relative(data, folder))
    result = {"counts": counts, "by_country": by_country, "folder": None}
    if write:
        columns = [column.name for column in schemas.TEXT_COPIES.columns]
        out.mkdir(parents=True)
        with duckdb.connect() as connection:
            frame = pd.DataFrame(rows, columns=columns)
            schemas.write_table(
                schemas.TEXT_COPIES,
                schemas.cast_to_schema(schemas.TEXT_COPIES, frame, connection),
                out,
            )
        manifests.write_manifest(
            data,
            out,
            "clean_text_copies",
            inputs=inputs,
            counts=counts,
            notes="The rule of songs.stage_10_clean.text_copies, with the text keys of "
            "songs.common.lyric_hash.",
        )
        result["folder"] = out
    return result
