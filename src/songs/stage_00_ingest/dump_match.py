"""Compare one lyric dump with the songs of one country, and find the songs the country lacks.

    in   clean/dumps/<source>/<YYYYMMDD>/   songs.parquet, artist_names.parquet
    in   lyrics/<ISO3>/songs/<run id>/      songs.parquet, artists.parquet of the newest folder

Each song of the dump counts once, in the first class that it fits:

    held        the country holds a song with the same `lyrics_sha256`
    same_title  the country holds a song with the same artist key and title key, other text
    roster_new  an artist of the song is on the roster of the country
    not_roster  no artist of the song is on the roster

A song of the dump is one `source_song_id`; it can have more than one credited
artist. The artists of a song are its credited names and the other names of
those artists in `artist_names.parquet`. A song that is not held, and whose title
or whose every artist name has no key, is left out with its reason. The
comparison reads no lyric text, only its hash.
"""

import unicodedata
from collections import Counter
from pathlib import Path

import duckdb

from songs.common import schemas

CLASSES = ("held", "same_title", "roster_new", "not_roster")
NEW_CLASSES = CLASSES[1:]
LEFT_OUT = ("no_title_key", "no_artist_key")


def name_key(text: str | None) -> str:
    """Return the matching key of an artist name or a title: folded case, no accents, no marks.

    Letters and digits of every script stay. Every other character is a space, and
    runs of spaces become one.
    """
    if not text:
        return ""
    folded = unicodedata.normalize("NFKD", unicodedata.normalize("NFKC", text).casefold())
    kept = "".join(
        char if char.isalnum() else " " for char in folded if not unicodedata.combining(char)
    )
    return " ".join(kept.split())


def _rows(relation: duckdb.DuckDBPyRelation, columns: str) -> list[tuple]:
    return relation.project(columns).fetchall()


def match_dump(dump: Path, country: Path, *, examples: int = 10) -> dict:
    """Classify each song of the dump folder `dump` against the country folder `country`.

    Return the counts, the songs left out with their reasons, up to `examples`
    artist and title pairs of each new class, and one row for each classified song.
    """
    with duckdb.connect() as connection:
        credits = _rows(
            schemas.read_table(schemas.DUMP_SONGS, dump, connection),
            "source_song_id, credit_position, artist_name, source_artist_id, song_name, "
            "lyrics_sha256",
        )
        aliases = _rows(
            schemas.read_table(schemas.DUMP_ARTIST_NAMES, dump, connection),
            "source_artist_id, artist_name",
        )
        held = _rows(
            schemas.read_table(schemas.COUNTRY_SONGS, country, connection),
            "artist_id, artist_name, song_name, lyrics_sha256",
        )
        roster = _rows(
            schemas.read_table(schemas.COUNTRY_ARTISTS, country, connection),
            "artist_id, artist_name",
        )

    names_of: dict[str, set[str]] = {}
    for artist_id, name in aliases:
        names_of.setdefault(artist_id, set()).add(name_key(name))
    roster_ids: dict[str, set[str]] = {}
    roster_name: dict[str, str] = {}
    for artist_id, name in roster:
        roster_ids.setdefault(name_key(name), set()).add(artist_id)
        roster_name[artist_id] = name
    held_hashes = {row[3] for row in held}
    held_pairs = set()
    for artist_id, artist, title, _ in held:
        for key in (name_key(artist), name_key(roster_name.get(artist_id))):
            held_pairs.add((key, name_key(title)))

    songs: dict[str, dict] = {}
    for song_id, _position, artist, artist_id, title, sha in sorted(credits):
        song = songs.setdefault(
            song_id,
            {"artist_name": artist, "song_name": title, "lyrics_sha256": sha, "keys": set()},
        )
        song["keys"] |= {name_key(artist), *names_of.get(artist_id, ())}

    counts = Counter({name: 0 for name in CLASSES})
    left_out = Counter({name: 0 for name in LEFT_OUT})
    ambiguous = 0
    rows = []
    for song_id, song in songs.items():
        keys = song["keys"] - {""}
        title = name_key(song["song_name"])
        artist_ids: set[str] = set()
        if song["lyrics_sha256"] in held_hashes:
            kind = "held"
        elif not title:
            left_out["no_title_key"] += 1
            continue
        elif not keys:
            left_out["no_artist_key"] += 1
            continue
        elif any((key, title) in held_pairs for key in keys):
            kind = "same_title"
        else:
            artist_ids = set().union(*(roster_ids.get(key, set()) for key in keys))
            kind = "roster_new" if artist_ids else "not_roster"
            ambiguous += len(artist_ids) > 1
        counts[kind] += 1
        rows.append(
            {
                "source_song_id": song_id,
                "class": kind,
                "artist_name": song["artist_name"],
                "song_name": song["song_name"],
                "roster_artist_ids": sorted(artist_ids),
            }
        )
    return {
        "credit_rows_in": len(credits),
        "songs_in": len(songs),
        "songs_out": sum(counts.values()),
        "counts": dict(counts),
        "left_out": dict(left_out),
        "roster_new_more_than_one_artist": ambiguous,
        "examples": {
            kind: [
                (row["artist_name"], row["song_name"])
                for row in sorted(rows, key=lambda row: (row["artist_name"], row["song_name"]))
                if row["class"] == kind
            ][:examples]
            for kind in NEW_CLASSES
        },
        "songs": rows,
    }
