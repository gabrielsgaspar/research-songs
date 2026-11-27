"""Mark the campaign songs whose dump credit does not name their roster artist.

    in   lyrics/<ISO3>/songs/<run id>/                  songs.parquet, artists.parquet of the
                                                        newest complete folder of each country
    in   clean/dumps/<source>/<YYYYMMDD>/               songs.parquet, artist_names.parquet of
                                                        the newest complete dump of each source
    out  clean/quality/uncredited_songs/<YYYYMMDD>/     uncredited_songs.parquet, _MANIFEST.json

Before 2026-11-24, an import of a dump (`songs.stage_00_ingest.dump_match`) could give
a song a roster artist that the song does not credit. A song is credited when the
`name_key` of its roster artist is one of the keys that the match now gives the song
(`dump_match.credited_keys`). A campaign song (route `dump_name`) gets one row, with
the first reason that fits:

1. `merged_artist_id`: a name of the artist id of the credit has the key, but the id
   holds the primary names of unrelated artists.
2. `no_credit`: no credited name has the key, and no credited name starts with it.

A credited name that starts with the key at a place where `dump_match.lead_artist`
does not split it, such as "Crosby Stills Nash" for "Crosby", is a band name or a
joint credit with no joining word. Such a song gets no row; it is counted as
`credited_by_split`. A song that the newest dump of its source lacks is not checked,
and is counted as `not_in_dump`. The data folders are write-once, so the rule marks
the songs and deletes nothing; the rule for eligible songs leaves the marked songs out.
"""

from datetime import date
from pathlib import Path

import duckdb
import pandas as pd

from songs.common import manifests, paths, schemas
from songs.common.schemas import MERGED_ARTIST_ID, NO_CREDIT
from songs.stage_00_ingest import dump_match

ROUTE = dump_match.ROUTE
REASONS = (MERGED_ARTIST_ID, NO_CREDIT)
# The classes of a checked song with no row.
CREDITED, BY_SPLIT = "credited", "credited_by_split"


def _campaign_songs(folder: Path) -> list[tuple]:
    """Return the campaign songs of a songs folder: song id, source, source song id, roster name."""
    with duckdb.connect() as connection:
        songs = schemas.read_table(schemas.COUNTRY_SONGS, folder, connection, fill_absent=True)
        artists = schemas.read_table(schemas.COUNTRY_ARTISTS, folder, connection)
        return (
            songs.filter(f"route = '{ROUTE}'")
            .join(artists.project("artist_id, artist_name AS roster_name"), "artist_id", how="left")
            .project("song_id, source, source_song_id, roster_name")
            .order("song_id")
            .fetchall()
        )


def _class(key: str, credit: dict[str, set[str]]) -> str:
    """Return the class of a song with the roster key `key`: a reason, or a class with no row."""
    if key in credit["keys"]:
        return CREDITED
    if key in credit["merged"]:
        return MERGED_ARTIST_ID
    if key and any(name.startswith(key + " ") for name in credit["names"]):
        return BY_SPLIT
    return NO_CREDIT


def check_credits(data: Path, *, write: bool = False, today: date | None = None) -> dict:
    """Apply the rule to the newest complete songs folder of every country. Return the counts.

    With `write`, write the folder of the day with the table and its manifest, and
    return it as `folder`. Raise FileExistsError when the folder of the day exists.
    `counts` holds the campaign songs read, the songs left out as `not_in_dump`, the
    credited songs (`credited`, `credited_by_split`), the rows out (`uncredited`) and
    the rows by reason. `by_country`
    gives, for each country with a row, the rows by reason and the campaign songs.
    """
    out = paths.clean_uncredited_songs_dir(data, today or date.today())
    if write and out.exists():
        raise FileExistsError(f"{out} exists; a version folder is never written over")
    wanted: dict[str, list[tuple]] = {}
    inputs, campaign = [], {}
    for parent in sorted((data / "lyrics").glob("*")):
        folder = (
            paths.latest_country_songs_dir(data, parent.name)
            if paths.ISO3.fullmatch(parent.name)
            else None
        )
        if folder is None:
            continue
        songs = _campaign_songs(folder)
        campaign[parent.name] = len(songs)
        inputs.append(paths.data_relative(data, folder))
        for song_id, source, *rest in songs:
            wanted.setdefault(source, []).append((parent.name, song_id, *rest))
    counts = dict.fromkeys(("campaign_songs", "not_in_dump", CREDITED, BY_SPLIT, *REASONS), 0)
    counts["campaign_songs"] = sum(campaign.values())
    rows, by_country = [], {}
    for source, songs in sorted(wanted.items()):
        dump = paths.latest_clean_dump_dir(data, source)
        credits = dump_match.credited_keys(dump, [song[2] for song in songs]) if dump else {}
        if dump:
            inputs.append(paths.data_relative(data, dump))
        for iso3, song_id, source_song_id, roster_name in songs:
            credit = credits.get(source_song_id)
            reason = (
                "not_in_dump"
                if credit is None
                else _class(dump_match.roster_key(roster_name), credit)
            )
            counts[reason] += 1
            if reason in REASONS:
                rows.append((iso3, song_id, reason))
                country = by_country.setdefault(iso3, {"campaign_songs": campaign[iso3]})
                country[reason] = country.get(reason, 0) + 1
    counts["uncredited"] = len(rows)
    counts["countries"] = len(campaign)
    classes = ("not_in_dump", CREDITED, BY_SPLIT, *REASONS)
    if sum(counts[name] for name in classes) != counts["campaign_songs"]:
        raise ValueError("the rows out and the songs left out do not add up to the songs in")
    result = {"counts": counts, "by_country": by_country, "folder": None}
    if write:
        columns = [column.name for column in schemas.UNCREDITED_SONGS.columns]
        out.mkdir(parents=True)
        with duckdb.connect() as connection:
            frame = pd.DataFrame(sorted(rows), columns=columns)
            schemas.write_table(
                schemas.UNCREDITED_SONGS,
                schemas.cast_to_schema(schemas.UNCREDITED_SONGS, frame, connection),
                out,
            )
        manifests.write_manifest(
            data,
            out,
            "clean_uncredited_songs",
            inputs=inputs,
            counts=counts,
            notes="The rule of songs.stage_10_clean.uncredited_songs, with the keys of "
            "songs.stage_00_ingest.dump_match.credited_keys.",
        )
        result["folder"] = out
    return result
