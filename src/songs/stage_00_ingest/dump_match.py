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
those artists in `artist_names.parquet`. When no artist of a song gives
same_title or roster_new, the lead part of each credited name is tried next
(`lead_artist`: "A feat. B", "A x B" and "A & B" give A). A featured part alone
never makes a match. `matched_by_split` counts the songs that the lead parts
matched. A song that is not held, and whose title
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

A song is `held_loose_title` when the country holds a song of the same roster
artist with the same loose key. A song is `already_linked` when a track with its
title already has a link in the
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

`would_add` decides which songs an import adds; `import_dump` and `survey` both use
it. `survey` and `gaps` only read:

    survey   for each source, what an import of its newest dump would add, by year
    gaps     for each year, the songs that the country holds and the Discogs tracks of
             its roster artists that have no song yet
"""

import csv
import difflib
import functools
import hashlib
import inspect
import re
import shutil
import tempfile
import time
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
    "held_loose_title",
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
# Added to the match method of a song whose artist got its Discogs id by name.
BY_NAME = "_artist_by_name"
# Discogs marks the second artist of one name as "Name (2)".
_HOMONYM = r"\s\(\d+\)$"
# The Discogs classes that the import adds, and the route of its run.
ADDED = ("exact", "loose")
ROUTE = "dump_name"
# A person's decision on each close match: accept adds the song, reject leaves it out.
REVIEWED_FILE = Path("resources") / "lyrics" / "reviewed_close_matches.csv"
REVIEW_COLUMNS = (
    "source",
    "country_iso3",
    "source_song_id",
    "discogs_release_id",
    "discogs_track_index",
    "decision",
    "decided",
    "reason",
)
DECISIONS = ("accept", "reject")
# The release countries of Discogs that count as the home of each country.
HOME_FILE = Path("resources") / "lyrics" / "discogs_countries.csv"
HOME_COLUMNS = ("discogs_country", "country_iso3")
DISCOGS_TABLES = (
    "release_artists",
    "release_track_artists",
    "release_tracklist",
    "releases",
    "masters",
)
_BRACKETS = re.compile(r"[(\[][^)\]]*[)\]]")
_FEATURING = re.compile(r"\b(?:ft|feat|featuring)\b.*$", re.IGNORECASE)
# Words that join a lead performer to other performers, in the languages of the dumps.
_JOINERS = r"x|and|with|vs\.?|e|y|i|et|con|avec|mit|und|og|ja|en|na|le|ve|va|и|і|та|و|/|\+"
_CREDIT_SPLIT = re.compile(
    rf"\s*(?:\(?(?<!\w)(?:feat|ft|featuring)(?!\w)\.?|[,&]|(?<=\s)(?:{_JOINERS})(?=\s))\s*",
    re.IGNORECASE,
)


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


def lead_artist(name: str | None) -> str:
    """Return the lead performer of a credit such as "A feat. B" or "A & B", or "" for no split.

    A name with no featuring or joining word, or with nothing on one side of it, has no split.
    """
    parts = _CREDIT_SPLIT.split(name or "", maxsplit=1)
    return parts[0].strip() if len(parts) == 2 and name_key(parts[0]) and name_key(parts[1]) else ""


def _rows(relation: duckdb.DuckDBPyRelation, columns: str) -> list[tuple]:
    return relation.project(columns).fetchall()


def _table(connection: duckdb.DuckDBPyConnection, name: str, kind: str, values: list) -> None:
    """Create the one-column table `name` (column `value`) from a list, which can be empty."""
    frame = pd.DataFrame({"value": pd.Series(values, dtype=kind)})
    connection.register("frame", frame)
    connection.execute(f"CREATE TEMP TABLE {name} AS SELECT value FROM frame")
    connection.unregister("frame")


def _keys_text() -> str:
    """Return everything that decides the content of a key cache, as one text."""
    builders = (name_key, lead_artist, dump_keys, _discogs_keys)
    return "".join(inspect.getsource(part) for part in builders) + repr(
        (_CREDIT_SPLIT.pattern, _CREDIT_SPLIT.flags, _HOMONYM, unicodedata.unidata_version)
    )


def _keys_version() -> str:
    """Return a short hash of `_keys_text`; a change of the key code gives a new key cache."""
    return hashlib.sha256(_keys_text().encode()).hexdigest()[:12]


def _work_folder(parent: Path) -> Path:
    """Return a new work folder in a cache folder, and remove the work folders of stopped builds.

    A work folder that is older than one day belongs to no build that still runs.
    """
    parent.mkdir(parents=True, exist_ok=True)
    for old in parent.glob("work-*"):
        if time.time() - old.stat().st_mtime > 86400:
            shutil.rmtree(old, ignore_errors=True)
    return Path(tempfile.mkdtemp(dir=parent, prefix="work-"))


def _keep(work: Path, folder: Path) -> None:
    """Give a finished work folder its final name. A stopped build leaves no such name."""
    try:
        work.rename(folder)
    except OSError:
        # Another process built the same folder first; its result is the same.
        shutil.rmtree(work, ignore_errors=True)
        if not folder.is_dir():
            raise


def _quoted(path: Path) -> str:
    return "'" + path.as_posix().replace("'", "''") + "'"


def dump_keys(dump: Path) -> Path:
    """Return the folder of the key tables of a dump, and build it when it is absent.

    The dump stores no key, so the keys of `name_key` and `lead_artist` are computed
    one time for each dump folder and kept under `cache/dump_keys/` of the data folder,
    which is never uploaded. The folder name is `_keys_version`, so a change of the
    key code gives a new folder. The build writes to a work folder and renames it
    last. DuckDB reads and writes Parquet in streams, so no table is held in Python.

        credits.parquet     one row per credit: song id, source artist id, artist key, lead key
        alias_keys.parquet  one row per source artist id and key of one of its names
        songs.parquet       one row per song: artist, title and hash of its first credit,
                            its title key, and `has_key` (an artist name of it has a key)
    """
    dump = dump.resolve()
    if dump.parent.parent.name != "dumps" or dump.parents[2].name != "clean":
        raise ValueError(f"{dump} is not a clean/dumps/<source>/<YYYYMMDD>/ folder")
    folder = dump.parents[3] / "cache" / "dump_keys" / dump.parent.name / dump.name
    folder = folder / _keys_version()
    if folder.is_dir():
        return folder
    work = _work_folder(folder.parent)
    with duckdb.connect() as connection:
        connection.execute(f"SET temp_directory = {_quoted(work / 'spill')}")
        connection.execute("SET memory_limit = '4GB'")
        connection.execute("SET preserve_insertion_order = false")
        connection.create_function(
            "name_key", name_key, ["VARCHAR"], "VARCHAR", null_handling="special"
        )
        connection.create_function(
            "lead_key",
            lambda name: name_key(lead_artist(name)),
            ["VARCHAR"],
            "VARCHAR",
            null_handling="special",
        )
        schemas.read_table(schemas.DUMP_SONGS, dump, connection).create_view("d")
        schemas.read_table(schemas.DUMP_ARTIST_NAMES, dump, connection).create_view("a")
        connection.execute(
            "CREATE TEMP TABLE nk AS SELECT name, name_key(name) AS key, lead_key(name) AS lead "
            "FROM (SELECT artist_name AS name FROM d UNION SELECT artist_name FROM a)"
        )
        connection.execute(
            "CREATE TEMP TABLE tk AS SELECT title, name_key(title) AS key "
            "FROM (SELECT DISTINCT song_name AS title FROM d)"
        )
        connection.execute(
            "CREATE TEMP TABLE alias AS SELECT DISTINCT a.source_artist_id, nk.key "
            "FROM a JOIN nk ON a.artist_name = nk.name WHERE nk.key <> ''"
        )
        connection.execute(f"COPY alias TO {_quoted(work / 'alias_keys.parquet')}")
        connection.execute(
            "COPY (SELECT d.source_song_id, d.source_artist_id, nk.key AS artist_key, "
            "nk.lead AS lead_key FROM d JOIN nk ON d.artist_name = nk.name) "
            f"TO {_quoted(work / 'credits.parquet')}"
        )
        connection.execute(
            "COPY (SELECT d.source_song_id, "
            "arg_min(d.artist_name, d.credit_position) AS artist_name, "
            "arg_min(d.song_name, d.credit_position) AS song_name, "
            "arg_min(d.lyrics_sha256, d.credit_position) AS lyrics_sha256, "
            "arg_min(tk.key, d.credit_position) AS title_key, "
            "bool_or(nk.key <> '' OR k.source_artist_id IS NOT NULL) AS has_key "
            "FROM d JOIN nk ON d.artist_name = nk.name JOIN tk ON d.song_name = tk.title "
            "LEFT JOIN (SELECT DISTINCT source_artist_id FROM alias) AS k "
            "ON d.source_artist_id = k.source_artist_id GROUP BY d.source_song_id) "
            f"TO {_quoted(work / 'songs.parquet')}"
        )
    shutil.rmtree(work / "spill", ignore_errors=True)
    _keep(work, folder)
    return folder


def _discogs_keys(connection: duckdb.DuckDBPyConnection, discogs: Path) -> str:
    """Return the SQL source of the Discogs artists with their name key: artist_id, name, key.

    The key is `name_key` of the name without the homonym mark, computed by `name_key`
    itself, so two Discogs names with one key are always seen as two. For a
    `clean/catalog/<source>/<YYYYMMDD>/` folder the table is built one time under
    `cache/discogs_keys/` of the data folder, like `dump_keys`. For any other folder
    it is computed in the query.
    """
    connection.create_function(
        "bare_key",
        lambda name: name_key(re.sub(_HOMONYM, "", name or "")),
        ["VARCHAR"],
        "VARCHAR",
        null_handling="special",
    )
    select = (
        f"SELECT artist_id, name, bare_key(name) AS key FROM {_quoted(discogs / 'artists.parquet')}"
    )
    if discogs.parent.parent.name != "catalog" or discogs.parents[2].name != "clean":
        return f"({select})"
    folder = discogs.parents[3] / "cache" / "discogs_keys" / discogs.parent.name / discogs.name
    folder = folder / _keys_version()
    if not folder.is_dir():
        work = _work_folder(folder.parent)
        connection.execute(f"COPY ({select}) TO {_quoted(work / 'artist_keys.parquet')}")
        _keep(work, folder)
    return _quoted(folder / "artist_keys.parquet")


def match_dump(dump: Path, country: Path, *, examples: int = 10) -> dict:
    """Classify each song of the dump folder `dump` against the country folder `country`.

    Return the counts, the songs left out with their reasons, up to `examples`
    artist and title pairs of each new class, and one row for each candidate song.
    A candidate is a song whose hash the country holds, or with an artist key or a
    lead key that is the key of a roster artist or of the artist of a held song.
    Only the candidates are read into Python. Every other song is counted in SQL as
    not_roster, no_title_key or no_artist_key, and has no row in `songs`.
    """
    keys = dump_keys(dump)
    credits_file, alias_file, songs_file = (
        _quoted(keys / name) for name in ("credits.parquet", "alias_keys.parquet", "songs.parquet")
    )
    with duckdb.connect() as connection:
        held_songs = schemas.read_table(
            schemas.COUNTRY_SONGS, country, connection, fill_absent=True
        )
        held = _rows(held_songs, "artist_id, artist_name, song_name")
        held_songs.project("lyrics_sha256").create_view("held_hashes")
        roster = _rows(
            schemas.read_table(schemas.COUNTRY_ARTISTS, country, connection),
            "artist_id, artist_name",
        )
        roster_ids: dict[str, set[str]] = {}
        roster_name: dict[str, str] = {}
        for artist_id, name in roster:
            roster_ids.setdefault(name_key(name), set()).add(artist_id)
            roster_name[artist_id] = name
        held_pairs = set()
        for artist_id, artist, title in held:
            for key in (name_key(artist), name_key(roster_name.get(artist_id))):
                held_pairs.add((key, name_key(title)))
        wanted = sorted(({*roster_ids} | {key for key, _ in held_pairs}) - {""})
        _table(connection, "wanted", "str", wanted)
        connection.execute(
            f"""
            CREATE TEMP TABLE candidates AS
            SELECT source_song_id FROM {credits_file}
            WHERE artist_key IN (SELECT value FROM wanted)
                OR lead_key IN (SELECT value FROM wanted)
                OR source_artist_id IN (
                    SELECT source_artist_id FROM {alias_file}
                    WHERE key IN (SELECT value FROM wanted)
                )
            UNION
            SELECT source_song_id FROM {songs_file}
            WHERE lyrics_sha256 IN (SELECT lyrics_sha256 FROM held_hashes)
            """
        )
        credit_rows_in = connection.sql(f"SELECT count(*) FROM {credits_file}").fetchall()[0][0]
        songs_in, no_title, no_artist, not_roster = connection.sql(
            f"""
            SELECT (SELECT count(*) FROM {songs_file}),
                coalesce(count_if(title_key = ''), 0),
                coalesce(count_if(title_key <> '' AND NOT has_key), 0),
                coalesce(count_if(title_key <> '' AND has_key), 0)
            FROM {songs_file} ANTI JOIN candidates USING (source_song_id)
            """
        ).fetchall()[0]
        other_examples = connection.sql(
            f"""
            SELECT artist_name, song_name
            FROM {songs_file} ANTI JOIN candidates USING (source_song_id)
            WHERE title_key <> '' AND has_key ORDER BY ALL LIMIT {int(examples)}
            """
        ).fetchall()
        songs = {
            row[0]: {
                "artist_name": row[1],
                "song_name": row[2],
                "held": row[3],
                "title": row[4],
                "keys": set(),
                "leads": set(),
            }
            for row in connection.sql(
                f"""
                SELECT source_song_id, artist_name, song_name,
                    lyrics_sha256 IN (SELECT lyrics_sha256 FROM held_hashes), title_key
                FROM {songs_file} SEMI JOIN candidates USING (source_song_id)
                ORDER BY source_song_id
                """
            ).fetchall()
        }
        connection.execute(
            f"CREATE TEMP TABLE chosen AS SELECT * FROM {credits_file} "
            "SEMI JOIN candidates USING (source_song_id)"
        )
        names_of: dict[str, set[str]] = {}
        for artist_id, key in connection.sql(
            f"SELECT source_artist_id, key FROM {alias_file} "
            "WHERE source_artist_id IN (SELECT source_artist_id FROM chosen)"
        ).fetchall():
            names_of.setdefault(artist_id, set()).add(key)
        for song_id, artist_id, artist_key, lead_key in connection.sql(
            "SELECT source_song_id, source_artist_id, artist_key, lead_key FROM chosen"
        ).fetchall():
            songs[song_id]["keys"] |= {artist_key, *names_of.get(artist_id, ())}
            songs[song_id]["leads"].add(lead_key)

    def on_roster(keys: set[str]) -> set[str]:
        return set().union(*(roster_ids.get(key, set()) for key in keys))

    counts = Counter({name: 0 for name in CLASSES})
    counts["not_roster"] = not_roster
    left_out = Counter({"no_title_key": no_title, "no_artist_key": no_artist})
    ambiguous = split = 0
    rows = []
    for song_id, song in songs.items():
        keys = song["keys"] - {""}
        leads = song["leads"] - keys - {""}
        title = song["title"]
        artist_ids: set[str] = set()
        if song["held"]:
            kind = "held"
        elif not title:
            left_out["no_title_key"] += 1
            continue
        elif not keys:
            left_out["no_artist_key"] += 1
            continue
        elif any((key, title) in held_pairs for key in keys):
            kind = "same_title"
        elif artist_ids := on_roster(keys):
            kind = "roster_new"
        elif any((key, title) in held_pairs for key in leads):
            kind, split = "same_title", split + 1
        else:
            artist_ids = on_roster(leads)
            kind = "roster_new" if artist_ids else "not_roster"
            split += bool(artist_ids)
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
    pairs = {
        kind: sorted((row["artist_name"], row["song_name"]) for row in rows if row["class"] == kind)
        for kind in NEW_CLASSES
    }
    pairs["not_roster"] = sorted(pairs["not_roster"] + other_examples)
    return {
        "credit_rows_in": credit_rows_in,
        "songs_in": songs_in,
        "songs_out": sum(counts.values()),
        "counts": dict(counts),
        "left_out": dict(left_out),
        "roster_new_more_than_one_artist": ambiguous,
        "matched_by_split": split,
        "examples": {kind: pairs[kind][:examples] for kind in NEW_CLASSES},
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
    if not artist_ids:
        return {}
    with duckdb.connect() as connection:
        # Each step is a small table, so DuckDB never builds a hash table of a whole Discogs table.
        connection.execute("SET memory_limit = '4GB'")
        _table(connection, "ids", "int64", artist_ids)
        connection.execute(
            f"""
            CREATE TEMP TABLE credited AS
            SELECT artist_id, release_id, CAST(NULL AS BIGINT) AS track_index
            FROM '{table["release_artists"]}' WHERE artist_id IN (SELECT value FROM ids)
            UNION
            SELECT artist_id, release_id, track_index
            FROM '{table["release_track_artists"]}' WHERE artist_id IN (SELECT value FROM ids)
            """
        )
        connection.execute(
            f"""
            CREATE TEMP TABLE found AS
            SELECT DISTINCT c.artist_id, t.title, t.release_id, t.track_index
            FROM '{table["release_tracklist"]}' AS t
            JOIN credited AS c
                ON t.release_id = c.release_id
                AND (c.track_index IS NULL OR c.track_index = t.track_index)
            WHERE t.title IS NOT NULL
                AND t.release_id IN (SELECT release_id FROM credited)
            """
        )
        connection.execute(
            f"""
            CREATE TEMP TABLE dated AS
            SELECT release_id, released, master_id FROM '{table["releases"]}'
            WHERE release_id IN (SELECT release_id FROM found)
            """
        )
        rows = connection.sql(
            f"""
            SELECT f.artist_id, f.title, f.release_id, f.track_index,
                least(
                    nullif(TRY_CAST(left(r.released, 4) AS INTEGER), 0),
                    nullif(CAST(m.year AS INTEGER), 0)
                ) AS year
            FROM found AS f
            LEFT JOIN dated AS r ON r.release_id = f.release_id
            LEFT JOIN (
                SELECT master_id, year FROM '{table["masters"]}'
                WHERE master_id IN (SELECT master_id FROM dated)
            ) AS m ON m.master_id = r.master_id
            """
        ).fetchall()
    tracks: dict[int, list[tuple]] = {}
    for artist_id, title, release_id, index, year in rows:
        year = year if year is not None and is_admissible_year(year) else None
        tracks.setdefault(artist_id, []).append((title, release_id, index, year))
    return tracks


def _earliest(hits: list[tuple]) -> tuple:
    return min(hits, key=lambda hit: (hit[3] is None, hit[3] or 0, hit[1], hit[2]))


@functools.cache
def load_home_countries(root: Path | None = None) -> dict[str, frozenset[str]]:
    """Return, for each country code, the release countries of Discogs that are its home.

    `HOME_FILE` has one row for each pair. A state that no longer exists, such as
    the USSR, is a home of each country that followed it.
    """
    path = (root or paths.resolve_project_root()) / HOME_FILE
    home: dict[str, set[str]] = {}
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != HOME_COLUMNS:
            raise ValueError(f"{path.name} must have the columns {', '.join(HOME_COLUMNS)}")
        for line in reader:
            paths.check_iso3(line["country_iso3"])
            if line["discogs_country"] in home.setdefault(line["country_iso3"], set()):
                raise ValueError(f"{path.name} lists {tuple(line.values())} twice")
            home[line["country_iso3"]].add(line["discogs_country"])
    return {iso3: frozenset(names) for iso3, names in home.items()}


def _with_home_release(discogs: Path, artist_ids: list[int], home: frozenset[str]) -> set[int]:
    """Return the Discogs artists that a release of a country in `home` credits.

    The credit is on the release or on one of its tracks.
    """
    if not artist_ids or not home:
        return set()
    table = {
        name: _quoted(discogs / f"{name}.parquet")
        for name in ("release_artists", "release_track_artists", "releases")
    }
    with duckdb.connect() as connection:
        connection.execute("SET memory_limit = '4GB'")
        _table(connection, "ids", "int64", artist_ids)
        _table(connection, "home", "str", sorted(home))
        connection.execute(
            f"""
            CREATE TEMP TABLE credited AS
            SELECT artist_id, release_id FROM {table["release_artists"]}
            WHERE artist_id IN (SELECT value FROM ids)
            UNION
            SELECT artist_id, release_id FROM {table["release_track_artists"]}
            WHERE artist_id IN (SELECT value FROM ids)
            """
        )
        rows = connection.sql(
            f"""
            SELECT DISTINCT artist_id FROM credited WHERE release_id IN (
                SELECT release_id FROM {table["releases"]}
                WHERE release_id IN (SELECT release_id FROM credited)
                    AND country IN (SELECT value FROM home)
            )
            """
        ).fetchall()
    return {row[0] for row in rows}


@functools.lru_cache(maxsize=8)
def discogs_ids(country: Path, discogs: Path, iso3: str) -> dict:
    """Return the Discogs id of each roster artist of a country folder, also found by name.

    A roster artist with no Discogs id gets the id of a Discogs artist by name when
    four things hold: exactly one artist in `artists.parquet` of the Discogs folder
    has the same `name_key` (without the homonym mark " (2)"), no other roster artist
    has that id, no other roster artist without an id has that key, and a release
    of a home country of `iso3` credits that artist (`load_home_countries`). The
    last rule keeps out an artist of another country with the same name. The roster
    of the folder is not changed. Return `ids` (roster artist id -> Discogs id),
    `by_name` (roster artist id -> Discogs id and Discogs name, for the ids found by
    name), and the roster artists that stay without an id, counted by reason:
    `none_found`, `more_than_one`, `id_taken`, `no_home_release` and `no_name_key`.
    A Discogs folder with no `artists.parquet` finds no id by name. A folder is
    write-once, so the result of a folder is kept.
    """
    with duckdb.connect() as connection:
        roster = _rows(
            schemas.read_table(schemas.COUNTRY_ARTISTS, country, connection),
            "artist_id, artist_name, discogs_artist_id",
        )
        ids = {artist_id: int(number) for artist_id, _, number in roster if number}
        missing = {artist_id: name_key(name) for artist_id, name, number in roster if not number}
        keys = sorted(set(missing.values()) - {""})
        found: dict[str, dict[int, str]] = {}
        if keys and (discogs / "artists.parquet").is_file():
            _table(connection, "names", "str", keys)
            for number, name, key in connection.sql(
                f"SELECT artist_id, name, key FROM {_discogs_keys(connection, discogs)} "
                "WHERE key IN (SELECT value FROM names)"
            ).fetchall():
                found.setdefault(key, {})[number] = name
    result = {"none_found": 0, "more_than_one": 0, "id_taken": 0}
    result["no_name_key"] = sum(not key for key in missing.values())
    shared = Counter(missing.values())
    taken = set(ids.values())
    alone = {}
    for artist_id, key in missing.items():
        hits = found.get(key, {})
        if not key:
            continue
        if not hits:
            result["none_found"] += 1
        elif len(hits) > 1:
            result["more_than_one"] += 1
        elif shared[key] > 1 or next(iter(hits)) in taken:
            result["id_taken"] += 1
        else:
            alone[artist_id] = next(iter(hits.items()))
    home = load_home_countries().get(iso3, frozenset())
    at_home = _with_home_release(discogs, sorted(pair[0] for pair in alone.values()), home)
    result["by_name"] = {key: pair for key, pair in alone.items() if pair[0] in at_home}
    result["no_home_release"] = len(alone) - len(result["by_name"])
    result["ids"] = ids | {artist_id: pair[0] for artist_id, pair in result["by_name"].items()}
    return result


def match_discogs(songs: list[dict], country: Path, discogs: Path, iso3: str) -> list[dict]:
    """Look for each roster_new song of `match_dump` in the Discogs tracks of its artist.

    `songs` is the `songs` list of `match_dump`. Return one row for each roster_new
    song, in the order of `songs`, with its Discogs class and, for a found track,
    the release id, track index, Discogs title, year, match method and score.
    The Discogs id of an artist is the id of the roster, or the id that `discogs_ids`
    finds by name for the country `iso3`. For such an id the row has `artist_by_name`
    true, and its match method ends with `BY_NAME`. A song is `held_loose_title` when
    the country holds a
    song of the same roster artist with the same loose title key, with or without a
    link, so one track never gets a second song under a longer title. The same holds
    inside one dump: of the songs of an artist with one loose title key, only the song
    with the shortest title is added, and the first one when two are equally short.
    """
    resolved = discogs_ids(country.resolve(), discogs.resolve(), iso3)
    discogs_of, by_name = resolved["ids"], resolved["by_name"]
    with duckdb.connect() as connection:
        held_loose = {
            (artist_id, loose_key(title))
            for artist_id, title in schemas.read_table(
                schemas.COUNTRY_SONGS, country, connection, fill_absent=True
            )
            .project("artist_id, song_name")
            .fetchall()
        }
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
    indexes: dict[int, tuple[dict, dict, list[str]]] = {}

    def tracks_of(artist: int) -> tuple[dict, dict, list[str]]:
        """Return the tracks of an artist by exact key and by loose key, and the loose keys."""
        if artist not in indexes:
            by_exact: dict[str, list[tuple]] = {}
            by_loose: dict[str, list[tuple]] = {}
            for hit in tracks.get(artist, []):
                by_exact.setdefault(name_key(hit[0]), []).append(hit)
                by_loose.setdefault(loose_key(hit[0]), []).append(hit)
            indexes[artist] = (by_exact, by_loose, sorted(by_loose))
        return indexes[artist]

    rows = [
        {"source_song_id": song["source_song_id"], "discogs_class": "out_of_scope"}
        for song in candidates
    ]
    added_loose: set[tuple] = set()
    pairs = zip(candidates, rows, strict=True)
    for song, row in sorted(pairs, key=lambda pair: len(pair[0]["song_name"])):
        artist = artist_of.get(song["source_song_id"])
        if artist is None:
            continue
        row["discogs_artist_id"] = str(artist)
        named = song["roster_artist_ids"][0] in by_name
        by_exact, by_loose, keys = tracks_of(artist)
        exact, loose = name_key(song["song_name"]), loose_key(song["song_name"])
        if (song["roster_artist_ids"][0], loose) in held_loose:
            row["discogs_class"] = "held_loose_title"
            continue
        kind, hits, score = "exact", by_exact.get(exact, []), None
        if not hits:
            kind, hits = "loose", by_loose.get(loose, [])
        if not hits:
            close = difflib.get_close_matches(loose, keys, n=1, cutoff=CLOSE_CUTOFF)
            kind, hits = "close", by_loose[close[0]] if close else []
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
        held_key = (song["roster_artist_ids"][0], loose)
        if (release_id, index) in taken:
            kind = "track_taken"
        elif kind in ADDED and held_key in added_loose:
            kind = "held_loose_title"
        elif kind in ADDED:
            added_loose.add(held_key)
        row |= {
            "discogs_class": kind,
            "discogs_release_id": str(release_id),
            "discogs_track_index": str(index),
            "discogs_title": title,
            "year": year,
            "match_method": method + BY_NAME * named,
            "match_score": fixed if fixed is not None else score,
            "artist_by_name": named,
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
        _table(connection, "chosen_ids", "str", sorted(chosen))
        connection.execute(
            "CREATE TEMP TABLE chosen AS SELECT value AS source_song_id FROM chosen_ids"
        )
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


def load_reviewed_matches(root: Path | None = None) -> dict[tuple[str, ...], str]:
    """Return the decision on each reviewed close match.

    The key is source, country, source song id, Discogs release id and track index,
    so a decision holds only for the track that the person saw.
    """
    path = (root or paths.resolve_project_root()) / REVIEWED_FILE
    decisions: dict[tuple[str, ...], str] = {}
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != REVIEW_COLUMNS:
            raise ValueError(f"{path.name} must have the columns {', '.join(REVIEW_COLUMNS)}")
        for line in reader:
            key = tuple(line[name].strip() for name in REVIEW_COLUMNS[:5])
            if line["decision"] not in DECISIONS or not line["decided"] or not line["reason"]:
                raise ValueError(f"{path.name}: {key} needs a decision, a date and a reason")
            if key in decisions:
                raise ValueError(f"{path.name} lists {key} twice")
            decisions[key] = line["decision"]
    return decisions


def would_add(
    dump: Path,
    country: Path,
    discogs: Path,
    source: str,
    iso3: str,
    reviewed: dict[tuple[str, ...], str] | None = None,
) -> dict:
    """Decide which songs of the dump folder `dump` an import adds to the folder `country`.

    A song is added when `match_discogs` gives it the class `exact` or `loose`, or
    the class `close` and `REVIEWED_FILE` accepts it for the same Discogs track.
    `reviewed` replaces the decisions of that file (for tests). Return the songs
    read (`songs_in`), the chosen songs with their Discogs rows (`chosen`), every
    other song counted by class (`rejected`), and the chosen songs counted by
    year (`by_year`, and `no_year` for a song with no year). `by_name` counts the
    chosen songs whose artist got its Discogs id by name (`discogs_ids`). The chosen
    songs and the rejected songs add up to `songs_in`.
    """
    result = match_dump(dump, country)
    found = match_discogs(result["songs"], country, discogs, iso3)
    reviewed = load_reviewed_matches() if reviewed is None else reviewed

    def accepted(row: dict) -> bool:
        key = (source, iso3, row["source_song_id"], row.get("discogs_release_id", ""))
        return reviewed.get((*key, row.get("discogs_track_index", ""))) == "accept"

    chosen = {
        row["source_song_id"]: row
        for row in found
        if row["discogs_class"] in ADDED or (row["discogs_class"] == "close" and accepted(row))
    }
    close_accepted = sum(row["discogs_class"] == "close" for row in chosen.values())
    discogs_counts = Counter(row["discogs_class"] for row in found)
    discogs_counts["close"] -= close_accepted
    years = Counter(row["year"] for row in chosen.values())
    no_year = years.pop(None, 0)
    return {
        "songs_in": result["songs_in"],
        "songs": {song["source_song_id"]: song for song in result["songs"]},
        "chosen": chosen,
        "close_accepted": close_accepted,
        "by_name": sum(row["artist_by_name"] for row in chosen.values()),
        "rejected": {
            **{name: result["counts"][name] for name in CLASSES if name != "roster_new"},
            **result["left_out"],
            **{name: discogs_counts[name] for name in DISCOGS_CLASSES if name not in ADDED},
        },
        "by_year": dict(sorted(years.items())),
        "no_year": no_year,
    }


def by_decade(by_year: dict[int, int]) -> dict[int, int]:
    """Return counts by decade from counts by year. The key is the first year of the decade."""
    decades: Counter = Counter()
    for year, number in by_year.items():
        decades[year // 10 * 10] += number
    return dict(sorted(decades.items()))


def _discogs_folder(data: Path, discogs: Path | None) -> Path:
    """Return the Discogs folder: the one given, or the newest complete catalog folder."""
    found = discogs or paths.latest_clean_catalog_dir(data, "discogs")
    if found is None:
        raise FileNotFoundError(
            "no Discogs tables: name a folder, or put a complete "
            "clean/catalog/discogs/<YYYYMMDD>/ in the data folder"
        )
    return found


def survey(data: Path, iso3: str, sources: list[str], discogs: Path | None = None) -> list[dict]:
    """Estimate, for each source, what an import of its newest dump adds to a country.

    The function only reads: it writes no folder and no run record. Return one row
    for each source, in the order given. A source with no complete dump in the data
    folder has `dump` None and no counts. Every other row has the dump folder, the
    songs read (`songs_in`), the songs that `import_dump` would add (`would_add`),
    how many of them have an artist whose Discogs id was found by name
    (`would_add_by_name`), those songs by year (`by_year`, `no_year`), every other song by class
    (`rejected`), and the seconds that the estimate took. `discogs` defaults to the
    newest complete `clean/catalog/discogs/<YYYYMMDD>/`.
    """
    country = paths.latest_country_songs_dir(data, iso3)
    if country is None:
        raise FileNotFoundError(f"no songs folder of {iso3}")
    discogs = _discogs_folder(data, discogs)
    rows = []
    for source in sources:
        dump = paths.latest_clean_dump_dir(data, source)
        if dump is None:
            rows.append({"source": source, "dump": None})
            continue
        start = time.monotonic()
        plan = would_add(dump, country, discogs, source, iso3)
        rows.append(
            {
                "source": source,
                "dump": paths.data_relative(data, dump),
                "songs_in": plan["songs_in"],
                "would_add": len(plan["chosen"]),
                "would_add_by_name": plan["by_name"],
                "by_year": plan["by_year"],
                "no_year": plan["no_year"],
                "rejected": plan["rejected"],
                "seconds": round(time.monotonic() - start, 1),
            }
        )
    return rows


def gaps(data: Path, iso3: str, discogs: Path | None = None) -> dict:
    """Count, for each year, the songs that a country holds and the tracks that it lacks.

    The function only reads the newest songs folder of the country and the Discogs
    tables. A wanted pair is one roster artist with a Discogs id and one loose title
    key of a Discogs track of that artist. A pair is left out as `pairs_linked` when
    a track of the pair has a link in the country, and as `pairs_held` when the
    country holds a song of the artist with that title key. The year of a pair is
    the earliest year of its tracks. Two roster rows with one Discogs id are one
    artist. The Discogs ids are those of `discogs_ids`: `artists_by_name` counts the
    roster artists whose id was found by name. `artists_no_discogs_id` counts the
    artists that stay without an id, which the dump route cannot serve, and
    `artists_no_id_reasons` counts them by reason. A track whose title has no key
    is counted in `tracks_no_title_key`.
    """
    country = paths.latest_country_songs_dir(data, iso3)
    if country is None:
        raise FileNotFoundError(f"no songs folder of {iso3}")
    discogs = _discogs_folder(data, discogs)
    with duckdb.connect() as connection:
        songs = schemas.read_table(schemas.COUNTRY_SONGS, country, connection, fill_absent=True)
        held_years = dict(songs.aggregate("year, count(*)").fetchall())
        held_titles = songs.project("artist_id, song_name").fetchall()
        artists = len(schemas.read_table(schemas.COUNTRY_ARTISTS, country, connection))
        linked = set(
            schemas.read_table(schemas.COUNTRY_LINKS, country, connection)
            .filter("discogs_release_id IS NOT NULL")
            .project("discogs_release_id, discogs_track_index")
            .fetchall()
        )
    resolved = discogs_ids(country.resolve(), discogs.resolve(), iso3)
    discogs_of = resolved["ids"]
    held = {
        (discogs_of[artist_id], loose_key(title))
        for artist_id, title in held_titles
        if artist_id in discogs_of
    }
    tracks = _discogs_tracks(discogs, sorted(set(discogs_of.values())))
    earliest: dict[tuple[int, str], int | None] = {}
    with_link: set[tuple[int, str]] = set()
    tracks_in = no_key = 0
    for artist, found in tracks.items():
        for title, release_id, index, year in found:
            tracks_in += 1
            pair = (artist, loose_key(title))
            if not pair[1]:
                no_key += 1
                continue
            years = [value for value in (earliest.get(pair), year) if value is not None]
            earliest[pair] = min(years, default=None)
            if (str(release_id), str(index)) in linked:
                with_link.add(pair)
    held_pairs = (held & set(earliest)) - with_link
    wanted = Counter(
        year for pair, year in earliest.items() if pair not in with_link and pair not in held_pairs
    )
    held_no_year = held_years.pop(None, 0)
    wanted_no_year = wanted.pop(None, 0)
    return {
        "songs_folder": paths.data_relative(data, country),
        "songs": sum(held_years.values()) + held_no_year,
        "held_by_year": dict(sorted(held_years.items())),
        "held_no_year": held_no_year,
        "artists": artists,
        "artists_by_name": len(resolved["by_name"]),
        "artists_no_discogs_id": artists - len(discogs_of),
        "artists_no_id_reasons": {
            name: resolved[name]
            for name in (
                "none_found",
                "more_than_one",
                "id_taken",
                "no_home_release",
                "no_name_key",
            )
        },
        "tracks_in": tracks_in,
        "tracks_no_title_key": no_key,
        "pairs": len(earliest),
        "pairs_linked": len(with_link),
        "pairs_held": len(held_pairs),
        "wanted": sum(wanted.values()) + wanted_no_year,
        "wanted_by_year": dict(sorted(wanted.items())),
        "wanted_no_year": wanted_no_year,
    }


def import_dump(
    data: Path,
    source: str,
    iso3: str,
    discogs: Path | None = None,
    *,
    discogs_label: str | None = None,
    countries: Path | None = None,
    reviewed: dict[tuple[str, ...], str] | None = None,
    repeat_reason: str | None = None,
) -> dict:
    """Add the songs of the newest dump that match a Discogs track of their roster artist.

    `would_add` chooses the songs. The command writes a new folder
    `lyrics/<ISO3>/songs/<run id>/` with the earlier rows and the added songs and
    links, its manifest, and the run record. `discogs` defaults to the newest
    complete `clean/catalog/discogs/<YYYYMMDD>/`. A Discogs folder inside the data
    folder is an input of the manifest. For a folder outside the data folder,
    `discogs_label` names it in the manifest notes. `reviewed` replaces the
    decisions of `REVIEWED_FILE` (for tests). Every other song of the dump is
    counted in the run record with its class. A second run of the same dump for the
    same country needs `repeat_reason`; the reason goes to the notes of the record.
    """
    paths.check_iso3(iso3)
    dump = paths.latest_clean_dump_dir(data, source)
    earlier = paths.latest_country_songs_dir(data, iso3)
    if dump is None or earlier is None:
        raise FileNotFoundError(f"no dump of {source} or no songs folder of {iso3}")
    discogs = _discogs_folder(data, discogs).resolve()
    catalog = (
        [paths.data_relative(data.resolve(), discogs)]
        if discogs.is_relative_to(data.resolve())
        else []
    )
    discogs_label = catalog[0] if catalog else discogs_label or discogs.name
    bulk_file = paths.data_relative(data, dump)
    with run_records.record_run(
        iso3,
        ROUTE,
        source,
        countries=countries,
        bulk_file=bulk_file,
        repeat_reason=repeat_reason,
    ) as record:
        if earlier.name >= record.run_id:
            raise ValueError(f"{earlier} is not older than this run ({record.run_id})")
        manifests.read_manifest(dump)
        manifests.read_manifest(earlier)
        plan = would_add(dump, earlier, discogs, source, iso3, reviewed)
        rejected, close_accepted, by_name = (
            plan["rejected"],
            plan["close_accepted"],
            plan["by_name"],
        )
        added, links = _added_frames(dump, earlier, iso3, source, plan["chosen"], plan["songs"])
        out = paths.country_songs_dir(data, iso3, record.run_id)
        out.mkdir(parents=True, exist_ok=False)
        counts = review_workbooks.write_country_songs(
            added, earlier, out, record.run_id, record.started_utc, links
        )
        manifests.write_manifest(
            data,
            out,
            "country_songs",
            country_iso3=iso3,
            run_id=record.run_id,
            inputs=[bulk_file, paths.data_relative(data, earlier), *catalog],
            counts=counts
            | {f"dump_songs_{name}": value for name, value in rejected.items()}
            | {"dump_songs_close_accepted": close_accepted}
            | {"dump_songs_added_artist_by_name": by_name},
            notes=(
                f"Songs of {bulk_file} that match a Discogs track of their roster artist. "
                f"Discogs tables: {discogs_label}."
            ),
        )
        record.rows_added = counts["songs_added"]
        record.requests_sent, record.limits_hit = 0, {}
        record.songs_attempted = plan["songs_in"]
        record.songs_accepted = len(added)
        record.songs_rejected = {name: value for name, value in rejected.items() if value}
        record.artists_attempted = int(added["artist_id"].nunique())
        if rejected["close"]:
            record.known_gaps.append(
                f"close: {rejected['close']} songs match a Discogs title by close "
                "spelling and wait for review"
            )
        if by_name:
            record.notes = (
                f"{record.notes} {by_name} songs added for artists whose Discogs id was "
                f"found by name (their match method ends with {BY_NAME})."
            ).strip()
        if close_accepted:
            record.notes = (
                f"{record.notes} {close_accepted} close matches added after review "
                f"({REVIEWED_FILE.as_posix()})."
            ).strip()
    return {"path": out, "songs_attempted": plan["songs_in"], "rejected": rejected, **counts}
