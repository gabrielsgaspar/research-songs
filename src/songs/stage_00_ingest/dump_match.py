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

`match_discogs` then looks for each roster_new song in the Discogs tracks of its
artist:

    in   <Discogs folder>   release_artists, release_track_artists, release_tracklist,
                            releases, masters (Parquet, the column names of the Discogs dump)

Only a song with exactly one roster artist, and a Discogs id for that artist, is
in scope. The tracks of an artist are the tracks of the releases that credit it,
and the tracks that credit it. The first title step that finds a track wins:

    exact           the title keys are the same
    loose           the keys are the same without parts in brackets and featuring parts
    close           the loose keys are similar (`CLOSE_CUTOFF` or more); a person reviews these

A song is `already_linked` when a track with its title already has a link in the
country, and `track_taken` when an earlier song of the dump took the same track.
Of the releases that hold the track, the one with the earliest year wins, then the
lowest release id. The year is the earlier of the release date and the year of
its master.

`import_dump` adds the `exact` and `loose` songs to the country, with the route
`dump_name`:

    out  lyrics/<ISO3>/songs/<run id>/   artists.parquet, songs.parquet, links.parquet,
                                         _MANIFEST.json

The new folder holds the earlier rows and the added songs, each with one link to
its Discogs track. Its run record counts every other song of the dump by class.
The import reads the lyric text of the added songs from the dump; lyric text never
goes to Git, to a manifest or to a run record.
"""

import difflib
import hashlib
import re
import unicodedata
from collections import Counter
from pathlib import Path

import duckdb
import pandas as pd

from songs.common import manifests, paths, run_records, schemas
from songs.common.years import is_admissible_year
from songs.stage_00_ingest import review_workbooks

CLASSES = ("held", "same_title", "roster_new", "not_roster")
NEW_CLASSES = CLASSES[1:]
LEFT_OUT = ("no_title_key", "no_artist_key")
DISCOGS_CLASSES = (
    "exact",
    "loose",
    "close",
    "already_linked",
    "track_taken",
    "no_track",
    "out_of_scope",
)
# match_method and match_score of a link, for each title step that adds a song.
DISCOGS_METHODS = {
    "exact": ("dump_discogs_exact_title", 100.0),
    "loose": ("dump_discogs_loose_title", 95.0),
}
CLOSE_CUTOFF = 0.9
# The Discogs classes that the import adds, and the route of its run.
ADDED = ("exact", "loose")
ROUTE = "dump_name"
DISCOGS_TABLES = (
    "release_artists",
    "release_track_artists",
    "release_tracklist",
    "releases",
    "masters",
)
_BRACKETS = re.compile(r"[(\[][^)\]]*[)\]]")
_FEATURING = re.compile(r"\b(?:ft|feat|featuring)\b.*$", re.IGNORECASE)


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


def loose_key(title: str | None) -> str:
    """Return the title key without parts in brackets and without a featuring part.

    A title that is only such parts keeps its full key.
    """
    text = _FEATURING.sub("", _BRACKETS.sub(" ", title or ""))
    return name_key(text) or name_key(title)


def _discogs_tracks(discogs: Path, artist_ids: list[int]) -> dict[int, list[tuple]]:
    """Return, for each Discogs artist id, its tracks: (title, release id, track index, year)."""
    missing = [name for name in DISCOGS_TABLES if not (discogs / f"{name}.parquet").is_file()]
    if missing:
        raise FileNotFoundError(f"the Discogs folder lacks {', '.join(missing)}")
    table = {
        name: (discogs / f"{name}.parquet").as_posix().replace("'", "''") for name in DISCOGS_TABLES
    }
    with duckdb.connect() as connection:
        connection.execute("CREATE TABLE ids (artist_id BIGINT)")
        connection.executemany("INSERT INTO ids VALUES (?)", [[number] for number in artist_ids])
        rows = connection.sql(
            f"""
            WITH credited AS (
                SELECT artist_id, release_id, CAST(NULL AS BIGINT) AS track_index
                FROM '{table["release_artists"]}' JOIN ids USING (artist_id)
                UNION
                SELECT artist_id, release_id, track_index
                FROM '{table["release_track_artists"]}' JOIN ids USING (artist_id)
            )
            SELECT DISTINCT c.artist_id, t.title, t.release_id, t.track_index,
                least(
                    nullif(TRY_CAST(left(r.released, 4) AS INTEGER), 0),
                    nullif(CAST(m.year AS INTEGER), 0)
                ) AS year
            FROM credited AS c
            JOIN '{table["release_tracklist"]}' AS t
                ON t.release_id = c.release_id
                AND (c.track_index IS NULL OR c.track_index = t.track_index)
            LEFT JOIN '{table["releases"]}' AS r ON r.release_id = t.release_id
            LEFT JOIN '{table["masters"]}' AS m ON m.master_id = r.master_id
            WHERE t.title IS NOT NULL
            """
        ).fetchall()
    tracks: dict[int, list[tuple]] = {}
    for artist_id, title, release_id, index, year in rows:
        year = year if year is not None and is_admissible_year(year) else None
        tracks.setdefault(artist_id, []).append((title, release_id, index, year))
    return tracks


def _earliest(hits: list[tuple]) -> tuple:
    return min(hits, key=lambda hit: (hit[3] is None, hit[3] or 0, hit[1], hit[2]))


def match_discogs(songs: list[dict], country: Path, discogs: Path) -> list[dict]:
    """Look for each roster_new song of `match_dump` in the Discogs tracks of its artist.

    `songs` is the `songs` list of `match_dump`. Return one row for each roster_new
    song, in the order of `songs`, with its Discogs class and, for a found track,
    the release id, track index, Discogs title, year, match method and score.
    """
    with duckdb.connect() as connection:
        discogs_of = dict(
            schemas.read_table(schemas.COUNTRY_ARTISTS, country, connection)
            .project("artist_id, discogs_artist_id")
            .fetchall()
        )
        linked = set(
            schemas.read_table(schemas.COUNTRY_LINKS, country, connection)
            .filter("discogs_release_id IS NOT NULL")
            .project("discogs_release_id, discogs_track_index")
            .fetchall()
        )
    candidates = [song for song in songs if song["class"] == "roster_new"]
    artist_of = {
        song["source_song_id"]: int(discogs_of[song["roster_artist_ids"][0]])
        for song in candidates
        if len(song["roster_artist_ids"]) == 1 and discogs_of.get(song["roster_artist_ids"][0])
    }
    tracks = _discogs_tracks(discogs, sorted(set(artist_of.values())))
    taken: set[tuple] = set()
    rows = []
    for song in candidates:
        row = {"source_song_id": song["source_song_id"], "discogs_class": "out_of_scope"}
        rows.append(row)
        artist = artist_of.get(song["source_song_id"])
        if artist is None:
            continue
        row["discogs_artist_id"] = str(artist)
        found = tracks.get(artist, [])
        exact, loose = name_key(song["song_name"]), loose_key(song["song_name"])
        kind, hits, score = "exact", [hit for hit in found if name_key(hit[0]) == exact], None
        if not hits:
            kind, hits = "loose", [hit for hit in found if loose_key(hit[0]) == loose]
        if not hits:
            keys = sorted({loose_key(hit[0]) for hit in found})
            close = difflib.get_close_matches(loose, keys, n=1, cutoff=CLOSE_CUTOFF)
            kind, hits = "close", [hit for hit in found if close and loose_key(hit[0]) == close[0]]
            if close:
                score = round(100 * difflib.SequenceMatcher(None, loose, close[0]).ratio(), 1)
        if not hits:
            row["discogs_class"] = "no_track"
            continue
        if any((str(hit[1]), str(hit[2])) in linked for hit in hits):
            row["discogs_class"] = "already_linked"
            continue
        title, release_id, index, year = _earliest(hits)
        method, fixed = DISCOGS_METHODS.get(kind, ("dump_discogs_close_title", None))
        row |= {
            "discogs_class": "track_taken" if (release_id, index) in taken else kind,
            "discogs_release_id": str(release_id),
            "discogs_track_index": str(index),
            "discogs_title": title,
            "year": year,
            "match_method": method,
            "match_score": fixed if fixed is not None else score,
        }
        taken.add((release_id, index))
    return rows


def _added_frames(
    dump: Path, country: Path, iso3: str, source: str, chosen: dict[str, dict], songs: dict
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return the rows of `songs.parquet` and of `links.parquet` for the chosen dump songs."""
    with duckdb.connect() as connection:
        roster = {
            row[0]: row[1:]
            for row in schemas.read_table(schemas.COUNTRY_ARTISTS, country, connection)
            .project("artist_id, artist_name, discogs_artist_id, country_tag")
            .fetchall()
        }
        connection.execute("CREATE TABLE chosen (source_song_id VARCHAR)")
        connection.executemany("INSERT INTO chosen VALUES (?)", [[key] for key in sorted(chosen)])
        dumped = (
            schemas.read_table(schemas.DUMP_SONGS, dump, connection)
            .filter("credit_position = 1")
            .join(connection.table("chosen"), "source_song_id")
            .project("source_song_id, song_url, song_name, lyrics, lyrics_sha256, language")
            .fetchall()
        )
    song_rows, link_rows = [], []
    for song_id, url, title, lyrics, sha, language in dumped:
        match, artist_id = chosen[song_id], songs[song_id]["roster_artist_ids"][0]
        roster_name, discogs_id, tag = roster[artist_id]
        key = "dp_" + hashlib.sha256(f"{source}/{song_id}".encode()).hexdigest()[:20]
        shared = {
            "country_iso3": iso3,
            "song_id": key,
            "artist_id": artist_id,
            "source": source,
            "source_song_id": song_id,
            "song_url": url,
        }
        song_rows.append(
            shared
            | {
                "artist_name": roster_name,
                "song_name": title,
                "lyrics": lyrics,
                "lyrics_sha256": sha,
                "language": language,
                "year": match["year"],
                "year_source": "discogs" if match["year"] else None,
                "year_basis": "discogs_earliest_release" if match["year"] else None,
                "route": ROUTE,
                "discogs_artist_id": discogs_id,
                "country_tag": tag,
            }
        )
        link_rows.append(
            shared
            | {
                "discogs_release_id": match["discogs_release_id"],
                "discogs_track_index": match["discogs_track_index"],
                "discogs_title": match["discogs_title"],
                "source_title": title,
                "match_method": match["match_method"],
                "match_score": match["match_score"],
            }
        )
    song_columns = [*(c.name for c in schemas.COUNTRY_SONGS.columns), "discogs_artist_id"]
    song_columns.append("country_tag")
    added = pd.DataFrame(song_rows, columns=song_columns).drop(columns=["run_id", "collected_utc"])
    links = pd.DataFrame(link_rows, columns=[c.name for c in schemas.COUNTRY_LINKS.columns])
    return added.astype({"year": "Int64"}), links.drop(columns=["run_id"])


def import_dump(
    data: Path,
    source: str,
    iso3: str,
    discogs: Path,
    *,
    discogs_label: str,
    countries: Path | None = None,
) -> dict:
    """Add the songs of the newest dump that match a Discogs track of their roster artist.

    Only the `exact` and `loose` songs of `match_discogs` are added. The command
    writes a new folder `lyrics/<ISO3>/songs/<run id>/` with the earlier rows and
    the added songs and links, its manifest, and the run record. `discogs_label`
    names the Discogs folder in the manifest notes, since that folder is outside
    the data folder. Every other song of the dump is counted in the run record with
    its class.
    """
    paths.check_iso3(iso3)
    dump = paths.latest_clean_dump_dir(data, source)
    earlier = paths.latest_country_songs_dir(data, iso3)
    if dump is None or earlier is None:
        raise FileNotFoundError(f"no dump of {source} or no songs folder of {iso3}")
    bulk_file = paths.data_relative(data, dump)
    with run_records.record_run(
        iso3, ROUTE, source, countries=countries, bulk_file=bulk_file
    ) as record:
        if earlier.name >= record.run_id:
            raise ValueError(f"{earlier} is not older than this run ({record.run_id})")
        manifests.read_manifest(dump)
        manifests.read_manifest(earlier)
        result = match_dump(dump, earlier)
        found = match_discogs(result["songs"], earlier, discogs)
        chosen = {row["source_song_id"]: row for row in found if row["discogs_class"] in ADDED}
        songs = {song["source_song_id"]: song for song in result["songs"]}
        added, links = _added_frames(dump, earlier, iso3, source, chosen, songs)
        out = paths.country_songs_dir(data, iso3, record.run_id)
        out.mkdir(parents=True, exist_ok=False)
        counts = review_workbooks.write_country_songs(
            added, earlier, out, record.run_id, record.started_utc, links
        )
        discogs_counts = Counter(row["discogs_class"] for row in found)
        rejected = {
            **{name: result["counts"][name] for name in CLASSES if name != "roster_new"},
            **result["left_out"],
            **{name: discogs_counts[name] for name in DISCOGS_CLASSES if name not in ADDED},
        }
        manifests.write_manifest(
            data,
            out,
            "country_songs",
            country_iso3=iso3,
            run_id=record.run_id,
            inputs=[bulk_file, paths.data_relative(data, earlier)],
            counts=counts | {f"dump_songs_{name}": value for name, value in rejected.items()},
            notes=(
                f"Songs of {bulk_file} that match a Discogs track of their roster artist. "
                f"Discogs tables: {discogs_label}."
            ),
        )
        record.rows_added = counts["songs_added"]
        record.requests_sent, record.limits_hit = 0, {}
        record.songs_attempted = result["songs_in"]
        record.songs_accepted = len(added)
        record.songs_rejected = {name: value for name, value in rejected.items() if value}
        record.artists_attempted = int(added["artist_id"].nunique())
        if discogs_counts["close"]:
            record.known_gaps.append(
                f"close: {discogs_counts['close']} songs match a Discogs title by close "
                "spelling and wait for review"
            )
    return {"path": out, "songs_attempted": result["songs_in"], "rejected": rejected, **counts}
