"""Build one lyric dump in the uniform format.

The command reads a folder of an old dump, the folder the caller names, and writes
`clean/dumps/<source>/<YYYYMMDD>/` with `songs.parquet`, `artist_names.parquet`
and a manifest. The date is the date of the build. The manifest names the
`raw/<source>/<YYYYMMDD>/` folder the caller names. No old path is stored here.

The caller chooses the snapshot. For Genius, that is the original songs file,
not a later edit of the names. For LRCLIB, that is the Parquet tables. A
normalized name key and a normalized title key are not copied. An empty result
is not written. A crawl that did not finish is marked in the manifest notes.

DuckDB reads the Parquet files and writes the result. The builder does not
collect the lyric rows into a Python list.
"""

import csv
import json
import re
import tempfile
from dataclasses import dataclass
from datetime import UTC
from pathlib import Path

import duckdb

from songs.common import manifests, paths, schemas
from songs.common.years import MAX_SONG_YEAR, MIN_SONG_YEAR

HELD_BACK_FILE = Path("resources") / "lyrics" / "held_back_from_matching.csv"
RAW_INPUT = re.compile(r"raw/[a-z0-9][a-z0-9_]*/\d{8}/")
PERFORMER_ROLES = ("performer", "artist")
SONG_ID = "coalesce(song_key, substring(sha256(song_url), 1, 20))"
# Drop reasons, in the order a row is tested. A row counts under the first reason only.
DROP_REASONS = (
    "not_lyrics",
    "not_song",
    "not_parsed",
    "not_eligible",
    "error_page",
    "empty_lyrics",
    "no_song_name",
    "no_song_id",
    "duplicate_song",
    "no_artist",
)
_ROLE_LIST = ", ".join(f"'{role}'" for role in PERFORMER_ROLES)


class DumpError(ValueError):
    """The dump cannot be built from this folder."""


@dataclass(frozen=True)
class HeldBack:
    """One source that matching does not use, or that the builder does not write."""

    source: str
    reason: str
    origin: str
    build: bool


@dataclass(frozen=True)
class Family:
    """How one old shape maps onto the uniform columns."""

    name: str
    signature: frozenset[str]
    song_key: tuple[str, ...]
    song_name: tuple[str, ...]
    lyrics: tuple[str, ...] = ("lyrics",)
    song_url: tuple[str, ...] = ("song_url",)
    language: tuple[str, ...] = ()
    year: tuple[str, ...] = ()
    album: tuple[str, ...] = ()
    fetched: tuple[str, ...] = ()
    page_artist: tuple[str, ...] = ("artist_name",)
    page_artist_url: tuple[str, ...] = ("artist_url",)
    page_artist_id: tuple[str, ...] = ()
    text_kind: bool = False
    lyric_kinds: tuple[str, ...] = ("lyrics",)
    song_page: bool = False
    parsed: bool = False
    eligible: bool = False
    credits: str = "page"
    json_ids: str = ""
    json_labels: str = ""
    list_column: str = ""
    index_url: bool = False
    album_tables: bool = False


FAMILIES: tuple[Family, ...] = (
    Family(
        "site_snapshot",
        frozenset(
            {
                "provider_song_id",
                "text_kind",
                "language_label",
                "release_year_raw",
                "retrieved_at_utc",
            }
        ),
        song_key=("provider_song_id",),
        song_name=("song_name",),
        language=("language_label",),
        year=("release_year_raw", "album_release_year_raw", "release_date_raw"),
        album=("album_name",),
        fetched=("retrieved_at_utc",),
        text_kind=True,
        credits="roles",
    ),
    Family(
        "balkan_engine",
        frozenset({"source_song_key", "text_kind", "fetched_at_utc", "translation_text"}),
        song_key=("source_song_key",),
        song_name=("song_name",),
        fetched=("fetched_at_utc",),
        page_artist_id=("source_artist_key",),
        text_kind=True,
        lyric_kinds=("lyrics", "original", "source_lyrics_or_poem"),
        credits="page",
    ),
    Family(
        "letras",
        frozenset({"source_song_key", "raw_offset", "retrieved_at_utc"}),
        song_key=("source_song_key",),
        song_name=("song_name",),
        fetched=("retrieved_at_utc",),
        credits="page",
    ),
    Family(
        "stixoi",
        frozenset({"provider_url", "title", "parsed_at_utc"}),
        song_key=("provider_song_id",),
        song_url=("provider_url",),
        song_name=("title",),
        language=("language",),
        year=("release_year",),
        fetched=("parsed_at_utc",),
        page_artist=(),
        credits="roles",
        album_tables=True,
    ),
    Family(
        "kugeci",
        frozenset({"lyrics_text", "provider_title", "site_artist_labels_json"}),
        song_key=("provider_song_id",),
        song_url=(),
        song_name=("provider_title",),
        lyrics=("lyrics_text",),
        page_artist=(),
        credits="json",
        json_ids="site_artist_ids_json",
        json_labels="site_artist_labels_json",
        parsed=True,
        index_url=True,
    ),
    Family(
        "genius",
        frozenset({"genius_song_id", "language_cld3"}),
        song_key=("genius_song_id",),
        song_url=(),
        song_name=("song_name",),
        language=("language_cld3",),
        year=("year",),
        page_artist_id=("genius_artist_id",),
        credits="page",
    ),
    Family(
        "central_asia",
        frozenset({"site", "artist_credits", "lyrics_text", "fetched_at_utc"}),
        song_key=("provider_song_id",),
        song_name=("song_name", "provider_title"),
        lyrics=("lyrics", "lyrics_text"),
        fetched=("fetched_at_utc",),
        page_artist_id=("artist_key",),
        song_page=True,
        credits="links",
    ),
    Family(
        "corpus_import",
        frozenset({"source_record_id", "source_singer_credit"}),
        song_key=("provider_song_id", "source_record_id"),
        song_name=("song_name",),
        year=("source_year",),
        page_artist=("artist_name", "source_singer_credit"),
        eligible=True,
        credits="roles",
    ),
    Family(
        "russian_dump",
        frozenset({"source_song_id", "source_url", "song_title", "fetched_at_utc"}),
        song_key=("source_song_id",),
        song_url=("song_url", "source_url"),
        song_name=("song_name", "song_title"),
        fetched=("fetched_at_utc",),
        page_artist=("artist_name", "artist"),
        credits="page",
    ),
    Family(
        "genius_ru",
        frozenset({"source_song_key", "verified_language", "imported_at_utc"}),
        song_key=("source_song_key",),
        song_name=("song_name",),
        language=("verified_language",),
        year=("release_year",),
        fetched=("imported_at_utc",),
        page_artist_id=("source_artist_id",),
        credits="roles_or_list",
        list_column="featured_artists",
    ),
    Family(
        "aama_fnanen",
        frozenset({"provider_song_id", "song_url", "fetched_at_utc", "harvest_date"}),
        song_key=("provider_song_id",),
        song_name=("song_name", "provider_title"),
        lyrics=("lyrics", "lyrics_text"),
        language=("language",),
        fetched=("fetched_at_utc",),
        page_artist=("artist_name", "artist_heading"),
        page_artist_id=("aama_artist_key", "fnanen_artist_key", "tewle_entry_id"),
        credits="links",
    ),
    Family(
        "lrclib",
        frozenset({"track_id", "plain_lyrics", "album_name"}),
        song_key=("track_id",),
        song_url=(),
        song_name=("name",),
        lyrics=("plain_lyrics",),
        album=("album_name",),
        fetched=("updated_at",),
        credits="page",
    ),
    Family(
        "lidicity",
        frozenset({"lyrics_text", "provider_title", "site_artist_label"}),
        song_key=("provider_song_id",),
        song_name=("provider_title",),
        lyrics=("lyrics_text",),
        page_artist=("site_artist_label",),
        credits="page",
    ),
    Family(
        "lyricsmy",
        frozenset({"lyrics_text", "provider_title", "artist_names_json"}),
        song_key=("provider_song_id",),
        song_name=("provider_title", "page_title", "index_title"),
        lyrics=("lyrics_text",),
        page_artist=(),
        credits="json",
        json_ids="artist_ids_json",
        json_labels="artist_names_json",
        parsed=True,
    ),
    Family(
        "deungdutjai",
        frozenset({"song_id", "artist_text", "lyrics_text"}),
        song_key=("song_id",),
        song_url=("url",),
        song_name=("title",),
        lyrics=("lyrics_text",),
        page_artist=("artist_text",),
        credits="page",
    ),
)
FAMILY_BY_NAME = {family.name: family for family in FAMILIES}

_ARTIST_ID_COLUMNS = (
    "artist_key",
    "provider_artist_id",
    "source_artist_key",
    "source_artist_id",
    "genius_artist_id",
    "site_artist_id",
    "aama_artist_key",
    "fnanen_artist_key",
    "tewle_entry_id",
)
_ARTIST_NAME_COLUMNS = ("artist_name", "name", "display_name", "site_artist_name")
_ARTIST_URL_COLUMNS = ("artist_url", "provider_url", "genius_url", "aama_url", "site_url")
_CREDIT_KEY_COLUMNS = ("provider_song_id", "source_song_key", "song_url")
_CREDIT_ROLE_COLUMNS = ("credit_role", "relation_role", "role")
_CREDIT_POSITION_COLUMNS = ("credit_position", "position", "credit_order")
_CREDIT_NAME_COLUMNS = ("artist_name", "credit_raw", "name")
_SIDE_KINDS = {
    "artist_songs": (
        "{source}_artist_songs.parquet",
        "artist_songs.parquet",
        "source_artist_song_links.parquet",
        "song_artist.parquet",
    ),
    "artists": (
        "{source}_artists.parquet",
        "artists.parquet",
        "source_artists.parquet",
        "genius_artists.parquet",
    ),
    "artist_names": ("{source}_artist_names.parquet", "artist_names.parquet"),
    "song_index": (
        "{source}_song_index.parquet",
        "song_index.parquet",
        "source_song_index.parquet",
    ),
    "song_albums": ("{source}_song_albums.parquet", "song_albums.parquet"),
    "albums": ("{source}_albums.parquet", "albums.parquet"),
}


def load_held_back(root: Path | None = None) -> dict[str, HeldBack]:
    """Return the sources matching does not use, keyed by the source."""
    path = (root or paths.resolve_project_root()) / HELD_BACK_FILE
    rows: dict[str, HeldBack] = {}
    with path.open(encoding="utf-8", newline="") as handle:
        for record in csv.DictReader(handle):
            source = paths.check_source(record["source"])
            if source in rows:
                raise DumpError(f"{path.name} lists {source} twice")
            build = record["build"]
            if build not in ("yes", "no"):
                raise DumpError(f"{path.name} build for {source} must be yes or no")
            rows[source] = HeldBack(
                source, record["reason"].strip(), record["origin"].strip(), build == "yes"
            )
    return rows


def check_raw_input(value: str) -> str:
    """Return `raw/<source>/<YYYYMMDD>/`, or raise DumpError when the path is not that shape."""
    text = value.strip().replace("\\", "/")
    if not text.endswith("/"):
        text += "/"
    if RAW_INPUT.fullmatch(text) is None:
        raise DumpError(
            "raw input must look like raw/<source>/<YYYYMMDD>/, relative to the data folder"
        )
    return text


def detect_family(columns: set[str]) -> str:
    """Return the format family whose signature is contained in `columns`, or ''."""
    for family in FAMILIES:
        if family.signature <= columns:
            return family.name
    return ""


def build_dump(
    source: str,
    folder: Path,
    raw_input: str,
    data: Path,
    *,
    family: str | None = None,
    day: str | None = None,
    incomplete: bool = False,
) -> dict:
    """Read one old dump and write the uniform folder. Return the row counts.

    A source listed with `build` no is not written. A result with no songs is not
    written. Both return `skipped` true and do not create a version folder.
    """
    source = paths.check_source(source)
    raw_input = check_raw_input(raw_input)
    day = paths.check_day(day or _today())
    held = load_held_back().get(source)
    if held is not None and not held.build:
        return _skipped(source, held.reason)

    if not folder.is_dir():
        raise DumpError(f"the dump folder does not exist: {folder.name}")
    out = paths.clean_dump_dir(data, source, day)
    if (out / paths.MANIFEST_NAME).exists() or (out / schemas.DUMP_SONGS.file).exists():
        raise DumpError(f"{paths.data_relative(data, out)} already exists")

    lyric = _lyric_file(folder, source)
    incomplete = incomplete or _crawl_is_incomplete(folder)
    with tempfile.TemporaryDirectory(prefix="songs-dump-") as temp:
        connection = duckdb.connect()
        connection.execute("SET preserve_insertion_order = false")
        connection.execute("SET temp_directory = ?", [temp])
        try:
            result = _build(
                connection, source, folder, lyric, data, out, raw_input, family, incomplete
            )
        finally:
            connection.close()
    return result


def _today() -> str:
    from datetime import datetime

    return datetime.now(UTC).strftime("%Y%m%d")


def _skipped(source: str, reason: str, **extra: object) -> dict:
    result = {
        "skipped": True,
        "reason": reason,
        "source": source,
        "path": None,
        "family": None,
        "incomplete": False,
        "rows_in": 0,
        "rows_out": 0,
        "artists_out": 0,
        "dropped": {},
        "not_lyrics_kinds": {},
        "credits_not_performer": 0,
    }
    result.update(extra)
    return result


def _build(
    connection, source, folder, lyric, data, out, raw_input, family_name, incomplete
) -> dict:
    columns = set(_columns(connection, lyric))
    found = detect_family(columns)
    if family_name is not None and family_name not in FAMILY_BY_NAME:
        known = ", ".join(FAMILY_BY_NAME)
        raise DumpError(f"unknown format family {family_name!r}. Known families: {known}")
    if family_name is not None and family_name != found:
        raise DumpError(
            f"the lyric table looks like {found or 'an unknown shape'}, not {family_name}"
        )
    if not found:
        raise DumpError("the lyric table does not match a known format family")
    family = FAMILY_BY_NAME[found]
    _prepare(connection, folder, source, family, lyric, columns)
    rows_in = _count(connection, "SELECT count(*) FROM src")
    dropped = {
        reason: count
        for reason, count in connection.execute(
            "SELECT drop_reason, count(*) FROM lyric_fate WHERE drop_reason IS NOT NULL GROUP BY 1"
        ).fetchall()
    }
    no_artist = _count(
        connection,
        """
        SELECT count(*) FROM lyric_kept kept
        WHERE NOT EXISTS (
            SELECT 1 FROM songs_ready ready WHERE ready.source_song_id = kept.source_song_id
        )
        """,
    )
    if no_artist:
        dropped["no_artist"] = no_artist
    not_lyrics_kinds = {
        re.sub(r"[^a-z0-9]+", "_", kind).strip("_") or "other": count
        for kind, count in connection.execute(
            "SELECT lower(text_kind), count(*) FROM lyric_fate"
            " WHERE drop_reason = 'not_lyrics' GROUP BY 1 ORDER BY 1"
        ).fetchall()
    }
    credits_skipped = _count(
        connection,
        f"""
        SELECT count(*) FROM (
          SELECT credit.role FROM ({_CREDIT_BY_KEY}) credit
          JOIN lyric_kept kept ON credit.kept_key = kept.song_key
          UNION ALL
          SELECT credit.role FROM ({_CREDIT_BY_URL}) credit
          JOIN lyric_kept kept ON credit.kept_url = kept.song_url
        ) credit
        WHERE credit.role IS NOT NULL AND credit.role NOT IN ({_ROLE_LIST})
        """,
    )
    rows_out = _count(connection, "SELECT count(*) FROM songs_ready")
    artists_out = _count(connection, "SELECT count(*) FROM artists_ready")
    kept_songs = _count(connection, "SELECT count(DISTINCT source_song_id) FROM songs_ready")
    if rows_out == 0:
        return _skipped(
            source,
            "no lyric rows",
            family=family.name,
            incomplete=incomplete,
            rows_in=rows_in,
            dropped=dropped,
            not_lyrics_kinds=not_lyrics_kinds,
            credits_not_performer=credits_skipped,
        )
    out.mkdir(parents=True, exist_ok=True)
    try:
        schemas.write_table(schemas.DUMP_SONGS, connection.sql("SELECT * FROM songs_out"), out)
        schemas.write_table(
            schemas.DUMP_ARTIST_NAMES, connection.sql("SELECT * FROM artists_out"), out
        )
    except ValueError as error:
        raise DumpError(str(error)) from error
    notes = [f"Format family: {family.name}."]
    if incomplete:
        notes.append("The crawl is incomplete.")
    counts = {
        "rows_in": rows_in,
        "rows_out": rows_out,
        "rows_dropped": rows_in - kept_songs,
        "artists_out": artists_out,
    }
    for reason in DROP_REASONS:
        if dropped.get(reason):
            counts[f"dropped_{reason}"] = dropped[reason]
    for kind, count in not_lyrics_kinds.items():
        counts[f"dropped_not_lyrics_{kind}"] = count
    if credits_skipped:
        counts["credits_not_performer"] = credits_skipped
    manifests.write_manifest(
        data,
        out,
        "clean_dump",
        source=source,
        inputs=[raw_input],
        counts=counts,
        notes=" ".join(notes),
    )
    return {
        "skipped": False,
        "reason": "",
        "source": source,
        "path": paths.data_relative(data, out),
        "family": family.name,
        "incomplete": incomplete,
        "rows_in": rows_in,
        "rows_out": rows_out,
        "artists_out": artists_out,
        "dropped": dropped,
        "not_lyrics_kinds": not_lyrics_kinds,
        "credits_not_performer": credits_skipped,
    }


def _prepare(connection, folder, source, family: Family, lyric: Path, columns: set[str]) -> None:
    _empty_sides(connection)
    if family.index_url:
        _load_index(connection, folder, source)
    if family.album_tables:
        _load_albums(connection, folder, source)
    _load_artists(connection, folder, source)
    connection.execute(
        "CREATE VIEW src AS SELECT "
        + _src_select(family, columns)
        + " FROM "
        + _prepare_from(family, columns, lyric)
    )
    kinds = ", ".join(f"'{kind}'" for kind in family.lyric_kinds)
    connection.execute(
        f"""
        CREATE VIEW lyric_checked AS
        SELECT *,
          CASE
            WHEN text_kind IS NOT NULL AND lower(text_kind) NOT IN ({kinds}) THEN 'not_lyrics'
            WHEN is_not_song THEN 'not_song'
            WHEN is_not_parsed THEN 'not_parsed'
            WHEN is_not_eligible THEN 'not_eligible'
            WHEN is_error THEN 'error_page'
            WHEN lyrics IS NULL THEN 'empty_lyrics'
            WHEN song_name IS NULL THEN 'no_song_name'
            WHEN song_key IS NULL AND song_url IS NULL THEN 'no_song_id'
            ELSE NULL
          END AS step_drop
        FROM src
        """
    )
    connection.execute(
        """
        CREATE VIEW lyric_fate AS
        SELECT * EXCLUDE (step_drop),
          CASE
            WHEN step_drop IS NOT NULL THEN step_drop
            WHEN row_number() OVER (
              PARTITION BY CASE WHEN step_drop IS NULL THEN coalesce(song_key, song_url) END
              ORDER BY length(lyrics) DESC NULLS LAST, song_name
            ) > 1 THEN 'duplicate_song'
            ELSE NULL
          END AS drop_reason
        FROM lyric_checked
        """
    )
    connection.execute(
        f"""
        CREATE VIEW lyric_kept AS
        SELECT *, {SONG_ID} AS source_song_id
        FROM lyric_fate
        WHERE drop_reason IS NULL
        """
    )
    _create_credits(connection, folder, source, family)
    connection.execute(
        """
        CREATE VIEW credit_one AS
        SELECT * EXCLUDE (pick) FROM (
          SELECT *, row_number() OVER (
            PARTITION BY source_song_id, source_artist_id
            ORDER BY position_raw NULLS LAST, artist_name
          ) AS pick
          FROM credit_line
          WHERE artist_name IS NOT NULL AND source_artist_id IS NOT NULL
            AND song_name IS NOT NULL AND lyrics IS NOT NULL AND source_song_id IS NOT NULL
        ) WHERE pick = 1
        """
    )
    connection.execute(
        """
        CREATE VIEW songs_ready AS
        SELECT source_song_id, song_url, song_name, lyrics, language, year, year_source, album,
          fetched_utc,
          raw_ref, artist_name, source_artist_id, artist_url,
          CAST(row_number() OVER (
            PARTITION BY source_song_id
            ORDER BY position_raw NULLS LAST, artist_name
          ) AS INTEGER) AS credit_position
        FROM credit_one
        """
    )
    _create_artist_rows(connection, folder, source)
    quoted = "'" + source + "'"
    connection.execute(
        f"""
        CREATE VIEW songs_out AS
        SELECT {quoted} AS source,
          CAST(source_song_id AS VARCHAR) AS source_song_id,
          CAST(song_url AS VARCHAR) AS song_url,
          CAST(artist_name AS VARCHAR) AS artist_name,
          CAST(source_artist_id AS VARCHAR) AS source_artist_id,
          CAST(credit_position AS INTEGER) AS credit_position,
          CAST(song_name AS VARCHAR) AS song_name,
          CAST(lyrics AS VARCHAR) AS lyrics,
          sha256(CAST(lyrics AS VARCHAR)) AS lyrics_sha256,
          CAST(language AS VARCHAR) AS language,
          CAST(year AS INTEGER) AS year,
          CAST(year_source AS VARCHAR) AS year_source,
          CAST(album AS VARCHAR) AS album,
          CAST(fetched_utc AS VARCHAR) AS fetched_utc,
          CAST(raw_ref AS VARCHAR) AS raw_ref
        FROM songs_ready
        """
    )


def _empty_sides(connection) -> None:
    connection.execute(
        """
        CREATE VIEW index_one AS
        SELECT CAST(NULL AS VARCHAR) AS song_key, CAST(NULL AS VARCHAR) AS song_url,
               CAST(NULL AS VARCHAR) AS fetched_raw
        WHERE FALSE
        """
    )
    connection.execute(
        """
        CREATE VIEW album_one AS
        SELECT CAST(NULL AS VARCHAR) AS song_key, CAST(NULL AS VARCHAR) AS album_name
        WHERE FALSE
        """
    )
    connection.execute(
        """
        CREATE VIEW credit_raw AS
        SELECT CAST(NULL AS VARCHAR) AS song_key, CAST(NULL AS VARCHAR) AS song_url,
               CAST(NULL AS VARCHAR) AS role, CAST(NULL AS BIGINT) AS position_raw,
               CAST(NULL AS VARCHAR) AS artist_id, CAST(NULL AS VARCHAR) AS credit_name,
               CAST(NULL AS VARCHAR) AS artist_url
        WHERE FALSE
        """
    )


def _src_select(family: Family, columns: set[str]) -> str:
    song_key = _coalesce(columns, family.song_key)
    song_url = f"coalesce(idx.song_url, {_coalesce(columns, family.song_url)})"
    album = f"coalesce(alb.album_name, {_coalesce(columns, family.album)})"
    fetched_value = f"coalesce(idx.fetched_raw, {_raw_time(columns, family.fetched)})"
    ids = _string_list(columns, family.json_ids) if family.json_ids else "CAST(NULL AS VARCHAR[])"
    labels = (
        _string_list(columns, family.json_labels)
        if family.json_labels
        else "CAST(NULL AS VARCHAR[])"
    )
    featured = (
        _string_list(columns, family.list_column)
        if family.list_column
        else "CAST(NULL AS VARCHAR[])"
    )
    return ", ".join(
        [
            f"{song_key} AS song_key",
            f"{song_url} AS song_url",
            f"{_coalesce(columns, family.page_artist)} AS page_artist",
            f"{_coalesce(columns, family.page_artist_id)} AS page_artist_id",
            f"{_coalesce(columns, family.page_artist_url)} AS page_artist_url",
            f"{_coalesce(columns, family.song_name)} AS song_name",
            f"{_coalesce(columns, family.lyrics)} AS lyrics",
            f"{_coalesce(columns, family.language)} AS language",
            f"{_year(columns, family.year)} AS year",
            f"{_year_source(columns, family.year)} AS year_source",
            f"{album} AS album",
            f"{_utc(fetched_value)} AS fetched_utc",
            f"{_raw_ref(columns)} AS raw_ref",
            f"{_text_kind(family, columns)} AS text_kind",
            f"{_is_error(columns)} AS is_error",
            f"{_is_not_song(columns) if family.song_page else 'FALSE'} AS is_not_song",
            f"{_is_not_parsed(columns) if family.parsed else 'FALSE'} AS is_not_parsed",
            f"{_is_not_eligible(columns) if family.eligible else 'FALSE'} AS is_not_eligible",
            f"{ids} AS artist_ids",
            f"{labels} AS artist_labels",
            f"{featured} AS featured",
        ]
    )


def _prepare_from(family: Family, columns: set[str], lyric: Path) -> str:
    key = _coalesce(columns, family.song_key)
    return (
        f"read_parquet('{_quote(lyric)}') AS lyric "
        f"LEFT JOIN index_one AS idx ON idx.song_key = {key} "
        f"LEFT JOIN album_one AS alb ON alb.song_key = {key}"
    )


def _create_credits(connection, folder: Path, source: str, family: Family) -> None:
    credit_file = _side(folder, source, "artist_songs")
    if family.credits == "json":
        _credits_from_lists(connection, "artist_ids", "artist_labels")
        return
    if family.credits in ("roles", "links") or (family.credits == "roles_or_list" and credit_file):
        if credit_file is not None:
            _load_credit_file(connection, credit_file, force_performer=family.credits == "links")
        listed = "featured" if family.credits == "roles_or_list" else ""
        _credits_from_roles(connection, page_fallback=True, list_column=listed)
        return
    if family.credits == "roles_or_list":
        _credits_from_page(connection, list_column="featured")
        return
    _credits_from_page(connection, list_column="")


def _load_credit_file(connection, path: Path, *, force_performer: bool) -> None:
    columns = set(_columns(connection, path))
    song_key = _first(columns, _CREDIT_KEY_COLUMNS)
    song_url = "song_url" if "song_url" in columns else ""
    role = "" if force_performer else _first(columns, _CREDIT_ROLE_COLUMNS)
    position = _first(columns, _CREDIT_POSITION_COLUMNS)
    artist_id = _first(columns, _CREDIT_ARTIST_ID)
    name = _first(columns, _CREDIT_NAME_COLUMNS)
    url = _first(columns, ("artist_url",))
    role_sql = (
        "'performer'" if force_performer or not role else f"lower({_text(columns, role, '')})"
    )
    position_sql = f"TRY_CAST({_q(position)} AS BIGINT)" if position else "CAST(NULL AS BIGINT)"
    connection.execute("DROP VIEW credit_raw")
    connection.execute(
        f"""
        CREATE VIEW credit_raw AS
        SELECT {_text(columns, song_key, "") if song_key else "CAST(NULL AS VARCHAR)"} AS song_key,
          {_text(columns, song_url, "") if song_url else "CAST(NULL AS VARCHAR)"} AS song_url,
          {role_sql} AS role,
          {position_sql} AS position_raw,
          {_text(columns, artist_id, "") if artist_id else "CAST(NULL AS VARCHAR)"} AS artist_id,
          {_text(columns, name, "") if name else "CAST(NULL AS VARCHAR)"} AS credit_name,
          {_text(columns, url, "") if url else "CAST(NULL AS VARCHAR)"} AS artist_url
        FROM read_parquet('{_quote(path)}')
        """
    )


_CREDIT_ARTIST_ID = _ARTIST_ID_COLUMNS
_CREDIT_BY_KEY = "SELECT *, song_key AS kept_key FROM credit_raw WHERE song_key IS NOT NULL"
_CREDIT_BY_URL = (
    "SELECT *, song_url AS kept_url FROM credit_raw WHERE song_key IS NULL AND song_url IS NOT NULL"
)


def _credits_from_roles(connection, *, page_fallback: bool, list_column: str = "") -> None:
    connection.execute(
        f"""
        CREATE VIEW role_line AS
        SELECT kept.source_song_id, kept.song_url, kept.song_name, kept.lyrics, kept.language,
          kept.year, kept.year_source, kept.album, kept.fetched_utc, kept.raw_ref,
          coalesce(dim.artist_name, credit.credit_name) AS artist_name,
          coalesce(credit.artist_id, dim.artist_id, credit.credit_name) AS source_artist_id,
          coalesce(dim.artist_url, credit.artist_url) AS artist_url,
          credit.position_raw
        FROM lyric_kept kept
        JOIN ({_CREDIT_BY_KEY}) credit ON credit.kept_key = kept.song_key
        LEFT JOIN artist_dim dim ON dim.artist_id = credit.artist_id
        WHERE credit.role IN ({_ROLE_LIST})
        UNION ALL
        SELECT kept.source_song_id, kept.song_url, kept.song_name, kept.lyrics, kept.language,
          kept.year, kept.year_source, kept.album, kept.fetched_utc, kept.raw_ref,
          coalesce(dim.artist_name, credit.credit_name) AS artist_name,
          coalesce(credit.artist_id, dim.artist_id, credit.credit_name) AS source_artist_id,
          coalesce(dim.artist_url, credit.artist_url) AS artist_url,
          credit.position_raw
        FROM lyric_kept kept
        JOIN ({_CREDIT_BY_URL}) credit ON credit.kept_url = kept.song_url
        LEFT JOIN artist_dim dim ON dim.artist_id = credit.artist_id
        WHERE credit.role IN ({_ROLE_LIST})
        """
    )
    page = ""
    if page_fallback:
        page = """
        UNION ALL
        SELECT kept.source_song_id, kept.song_url, kept.song_name, kept.lyrics, kept.language,
          kept.year, kept.year_source, kept.album, kept.fetched_utc, kept.raw_ref,
          kept.page_artist AS artist_name,
          coalesce(kept.page_artist_id, by_url.artist_id, kept.page_artist) AS source_artist_id,
          coalesce(by_url.artist_url, kept.page_artist_url) AS artist_url,
          CAST(1 AS BIGINT) AS position_raw
        FROM lyric_kept kept
        LEFT JOIN artist_by_url by_url ON by_url.artist_url = kept.page_artist_url
        WHERE kept.page_artist IS NOT NULL
          AND NOT EXISTS (
            SELECT 1 FROM role_line role WHERE role.source_song_id = kept.source_song_id
          )
        """
    listed = ""
    if list_column:
        listed = f"""
        UNION ALL
        SELECT kept.source_song_id, kept.song_url, kept.song_name, kept.lyrics, kept.language,
          kept.year, kept.year_source, kept.album, kept.fetched_utc, kept.raw_ref,
          names.name AS artist_name,
          names.name AS source_artist_id,
          CAST(NULL AS VARCHAR) AS artist_url,
          1000 + names.pos AS position_raw
        FROM lyric_kept kept, LATERAL (
          SELECT kept.{list_column}[pos] AS name, pos
          FROM range(1, len(kept.{list_column}) + 1) AS list_pos(pos)
        ) names
        WHERE kept.{list_column} IS NOT NULL AND len(kept.{list_column}) > 0
          AND names.name IS NOT NULL
          AND names.name IS DISTINCT FROM kept.page_artist
          AND NOT EXISTS (
            SELECT 1 FROM role_line role
            WHERE role.source_song_id = kept.source_song_id AND role.artist_name = names.name
          )
        """
    connection.execute(f"CREATE VIEW credit_line AS SELECT * FROM role_line {page} {listed}")


def _page_select() -> str:
    """SQL of one credit from the printed artist on the lyric row."""
    return """
        SELECT kept.source_song_id, kept.song_url, kept.song_name, kept.lyrics, kept.language,
          kept.year, kept.year_source, kept.album, kept.fetched_utc, kept.raw_ref,
          kept.page_artist AS artist_name,
          coalesce(kept.page_artist_id, by_url.artist_id, kept.page_artist) AS source_artist_id,
          coalesce(by_url.artist_url, kept.page_artist_url) AS artist_url,
          CAST(1 AS BIGINT) AS position_raw
        FROM lyric_kept kept
        LEFT JOIN artist_by_url by_url ON by_url.artist_url = kept.page_artist_url
        WHERE kept.page_artist IS NOT NULL
    """


def _credits_from_page(connection, *, list_column: str) -> None:
    extra = ""
    if list_column:
        extra = f"""
        UNION ALL
        SELECT kept.source_song_id, kept.song_url, kept.song_name, kept.lyrics, kept.language,
          kept.year, kept.year_source, kept.album, kept.fetched_utc, kept.raw_ref,
          names.name AS artist_name,
          names.name AS source_artist_id,
          CAST(NULL AS VARCHAR) AS artist_url,
          names.pos + 1 AS position_raw
        FROM lyric_kept kept, LATERAL (
          SELECT kept.{list_column}[pos] AS name, pos
          FROM range(1, len(kept.{list_column}) + 1) AS list_pos(pos)
        ) names
        WHERE kept.{list_column} IS NOT NULL AND len(kept.{list_column}) > 0
          AND names.name IS NOT NULL AND names.name <> kept.page_artist
        """
    connection.execute(
        f"""
        CREATE VIEW credit_line AS
        SELECT source_song_id, song_url, song_name, lyrics, language, year, year_source, album,
          fetched_utc,
          raw_ref, artist_name, source_artist_id, artist_url, position_raw
        FROM (
          {_page_select()}
        ) page_credit
        {extra}
        """
    )


def _credits_from_lists(connection, ids: str, labels: str) -> None:
    connection.execute(
        f"""
        CREATE VIEW credit_line AS
        SELECT kept.source_song_id, kept.song_url, kept.song_name, kept.lyrics, kept.language,
          kept.year, kept.year_source, kept.album, kept.fetched_utc, kept.raw_ref,
          pair.label AS artist_name,
          coalesce(nullif(trim(pair.artist_id), ''), pair.label) AS source_artist_id,
          dim.artist_url AS artist_url,
          pair.pos AS position_raw
        FROM lyric_kept kept, LATERAL (
          SELECT {ids}[pos] AS artist_id, {labels}[pos] AS label, pos
          FROM range(1, len({ids}) + 1) AS list_pos(pos)
        ) pair
        LEFT JOIN artist_dim dim ON dim.artist_id = pair.artist_id
        WHERE {ids} IS NOT NULL AND {labels} IS NOT NULL
          AND len({ids}) = len({labels}) AND len({ids}) > 0
          AND pair.label IS NOT NULL
        """
    )


def _create_artist_rows(connection, folder: Path, source: str) -> None:
    names = _side(folder, source, "artist_names")
    parts = [
        """
        SELECT source_artist_id, artist_name, 'primary' AS name_type, artist_url
        FROM songs_ready
        """
    ]
    if names is not None:
        parts.append(_names_from_file(connection, names))
    elif _view_has_rows(connection, "artist_dim"):
        parts.append(
            """
            SELECT artist_id AS source_artist_id, artist_name, 'primary' AS name_type, artist_url
            FROM artist_dim
            WHERE artist_id IS NOT NULL AND artist_name IS NOT NULL
            """
        )
    union = " UNION ALL ".join(parts)
    quoted = "'" + source + "'"
    connection.execute(
        f"""
        CREATE VIEW artists_ready AS
        SELECT source_artist_id, artist_name, name_type, artist_url FROM (
          SELECT source_artist_id, artist_name,
            CASE WHEN count(*) FILTER (WHERE name_type = 'primary') > 0 THEN 'primary'
                 ELSE 'alias' END AS name_type,
            max(artist_url) AS artist_url
          FROM ({union}) named
          WHERE source_artist_id IS NOT NULL AND artist_name IS NOT NULL
          GROUP BY source_artist_id, artist_name
        )
        """
    )
    connection.execute(
        f"""
        CREATE VIEW artists_out AS
        SELECT {quoted} AS source,
          CAST(source_artist_id AS VARCHAR) AS source_artist_id,
          CAST(artist_name AS VARCHAR) AS artist_name,
          CAST(name_type AS VARCHAR) AS name_type,
          CAST(artist_url AS VARCHAR) AS artist_url
        FROM artists_ready
        """
    )


def _names_from_file(connection, path: Path) -> str:
    columns = set(_columns(connection, path))
    artist_id = _first(columns, _ARTIST_ID_COLUMNS)
    name = _first(columns, _ARTIST_NAME_COLUMNS)
    url = _first(columns, _ARTIST_URL_COLUMNS)
    if not artist_id or not name:
        return (
            "SELECT CAST(NULL AS VARCHAR) AS source_artist_id, "
            "CAST(NULL AS VARCHAR) AS artist_name, 'primary' AS name_type, "
            "CAST(NULL AS VARCHAR) AS artist_url WHERE FALSE"
        )
    origin = (
        _text(columns, "name_origin", "") if "name_origin" in columns else "CAST(NULL AS VARCHAR)"
    )
    kind = (
        _text(columns, "name_type", "") if "name_type" in columns else "CAST('primary' AS VARCHAR)"
    )
    url_sql = _text(columns, url, "") if url else "CAST(NULL AS VARCHAR)"
    name_type = f"CASE WHEN lower({kind}) IN ('alias', 'alternate') THEN 'alias' ELSE 'primary' END"
    return f"""
        SELECT {_text(columns, artist_id, "")} AS source_artist_id,
          {_text(columns, name, "")} AS artist_name,
          {name_type} AS name_type,
          {url_sql} AS artist_url
        FROM read_parquet('{_quote(path)}')
        WHERE {_text(columns, name, "")} IS NOT NULL
          AND lower(coalesce({origin}, '')) <> 'derived'
          AND lower(coalesce({kind}, '')) <> 'latin_matching_key'
    """


def _load_artists(connection, folder: Path, source: str) -> None:
    path = _side(folder, source, "artists")
    columns: set[str] = set()
    artist_id = name = url = ""
    if path is not None:
        columns = set(_columns(connection, path))
        artist_id = _first(columns, _ARTIST_ID_COLUMNS)
        name = _first(columns, _ARTIST_NAME_COLUMNS)
        url = _first(columns, _ARTIST_URL_COLUMNS)
    if path is not None and artist_id and name:
        connection.execute(
            f"""
            CREATE VIEW artist_dim AS
            SELECT {_text(columns, artist_id, "")} AS artist_id,
              {_text(columns, name, "")} AS artist_name,
              {_text(columns, url, "") if url else "CAST(NULL AS VARCHAR)"} AS artist_url
            FROM read_parquet('{_quote(path)}')
            """
        )
    else:
        connection.execute(
            """
            CREATE VIEW artist_dim AS
            SELECT CAST(NULL AS VARCHAR) AS artist_id, CAST(NULL AS VARCHAR) AS artist_name,
                   CAST(NULL AS VARCHAR) AS artist_url
            WHERE FALSE
            """
        )
    connection.execute(
        """
        CREATE VIEW artist_by_url AS
        SELECT artist_url, artist_id FROM (
          SELECT artist_url, artist_id,
            row_number() OVER (PARTITION BY artist_url ORDER BY artist_id) AS pick
          FROM artist_dim
          WHERE artist_url IS NOT NULL AND artist_id IS NOT NULL
        ) WHERE pick = 1
        """
    )


def _load_index(connection, folder: Path, source: str) -> None:
    path = _side(folder, source, "song_index")
    if path is None:
        return
    columns = set(_columns(connection, path))
    if "provider_song_id" not in columns:
        return
    url = _text(columns, "song_url", "") if "song_url" in columns else "CAST(NULL AS VARCHAR)"
    fetched = (
        _text(columns, "last_attempt_at_utc", "")
        if "last_attempt_at_utc" in columns
        else "CAST(NULL AS VARCHAR)"
    )
    connection.execute("DROP VIEW index_one")
    connection.execute(
        f"""
        CREATE VIEW index_one AS
        SELECT song_key, song_url, fetched_raw FROM (
          SELECT {_text(columns, "provider_song_id", "")} AS song_key, {url} AS song_url,
            {fetched} AS fetched_raw,
            row_number() OVER (
              PARTITION BY {_text(columns, "provider_song_id", "")} ORDER BY {url}
            ) AS pick
          FROM read_parquet('{_quote(path)}')
        ) WHERE pick = 1 AND song_key IS NOT NULL
        """
    )


def _load_albums(connection, folder: Path, source: str) -> None:
    songs = _side(folder, source, "song_albums")
    albums = _side(folder, source, "albums")
    if songs is None or albums is None:
        return
    song_columns = set(_columns(connection, songs))
    album_columns = set(_columns(connection, albums))
    if "provider_song_id" not in song_columns or "provider_album_id" not in song_columns:
        return
    if "provider_album_id" not in album_columns:
        return
    title = (
        "title"
        if "title" in album_columns
        else "album_name"
        if "album_name" in album_columns
        else ""
    )
    if not title:
        return
    connection.execute("DROP VIEW album_one")
    connection.execute(
        f"""
        CREATE VIEW album_one AS
        SELECT song_key, album_name FROM (
          SELECT song_key, album_name, count(*) OVER (PARTITION BY song_key) AS copies
          FROM (
            SELECT {_text(song_columns, "provider_song_id", "song_album")} AS song_key,
              {_text(album_columns, title, "album")} AS album_name
            FROM read_parquet('{_quote(songs)}') song_album
            JOIN read_parquet('{_quote(albums)}') album
              ON song_album.provider_album_id = album.provider_album_id
          )
          WHERE song_key IS NOT NULL AND album_name IS NOT NULL
        ) WHERE copies = 1
        """
    )


def _lyric_file(folder: Path, source: str) -> Path:
    named = folder / f"{source}_lyrics.parquet"
    if named.is_file():
        return named
    lyrics = sorted(folder.glob("*_lyrics.parquet"))
    if len(lyrics) == 1:
        return lyrics[0]
    if len(lyrics) > 1:
        found = ", ".join(path.name for path in lyrics)
        raise DumpError(f"the folder has more than one lyric table: {found}")
    for name in ("lyrics.parquet", "songs.parquet"):
        path = folder / name
        if path.is_file():
            return path
    found = ", ".join(path.name for path in sorted(folder.glob("*.parquet"))) or "none"
    raise DumpError(f"the folder has no lyric table. Parquet files: {found}")


def _side(folder: Path, source: str, kind: str) -> Path | None:
    names = [name.format(source=source) for name in _SIDE_KINDS[kind]]
    found = [folder / name for name in names if (folder / name).is_file()]
    if not found:
        found = sorted(folder.glob(f"*_{kind}.parquet"))
    prefixed = [path for path in found if path.name.startswith(f"{source}_")]
    if len(prefixed) == 1:
        return prefixed[0]
    if len(found) == 1:
        return found[0]
    if len(found) > 1:
        listed = ", ".join(path.name for path in found)
        raise DumpError(f"the folder has more than one {kind} table: {listed}")
    return None


def _crawl_is_incomplete(folder: Path) -> bool:
    """True when the folder, or the crawl folder above a `snapshots/<stamp>/` folder, says so."""
    folders = [folder]
    if folder.parent.name == "snapshots":
        folders.append(folder.parent.parent)
    return any(_folder_is_incomplete(item) for item in folders)


def _folder_is_incomplete(folder: Path) -> bool:
    if (folder / "STOP").is_file():
        return True
    for name in ("latest.json", "manifest.json"):
        path = folder / name
        if not path.is_file() or path.stat().st_size > 1_000_000:
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except OSError, UnicodeError, json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        if payload.get("final_build") is False:
            return True
        pending = payload.get("pending_urls")
        if isinstance(pending, int) and not isinstance(pending, bool) and pending > 0:
            return True
    return False


def _columns(connection, path: Path) -> list[str]:
    rows = connection.execute(
        "DESCRIBE SELECT * FROM read_parquet(?)", [path.as_posix()]
    ).fetchall()
    return [row[0] for row in rows]


def _count(connection, query: str) -> int:
    return int(connection.execute(query).fetchall()[0][0])


def _view_has_rows(connection, view: str) -> bool:
    return _count(connection, f"SELECT count(*) FROM {view}") > 0


def _q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _quote(path: Path) -> str:
    return path.as_posix().replace("'", "''")


def _text_kind(family: Family, columns: set[str]) -> str:
    if family.text_kind:
        return _text(columns, "text_kind")
    return "CAST(NULL AS VARCHAR)"


def _text(columns: set[str], name: str, qualifier: str = "lyric") -> str:
    if name not in columns:
        return "CAST(NULL AS VARCHAR)"
    prefix = f"{qualifier}." if qualifier else ""
    return f"nullif(trim(CAST({prefix}{_q(name)} AS VARCHAR)), '')"


def _coalesce(columns: set[str], names: tuple[str, ...]) -> str:
    present = [_text(columns, name) for name in names if name in columns]
    if not present:
        return "CAST(NULL AS VARCHAR)"
    if len(present) == 1:
        return present[0]
    return "coalesce(" + ", ".join(present) + ")"


def _raw_time(columns: set[str], names: tuple[str, ...]) -> str:
    for name in names:
        if name in columns:
            return f"CAST(lyric.{_q(name)} AS VARCHAR)"
    return "CAST(NULL AS VARCHAR)"


def _one_year(columns: set[str], name: str) -> str:
    """SQL of an admissible year from one column, or NULL.

    A number is rounded. A date text gives a year only when it holds exactly one
    four-digit number, so a text with two years gives none.
    """
    text = _text(columns, name)
    if "date" in name:
        found = f"regexp_extract_all({text}, '(?:^|[^0-9])([0-9]{{4}})(?:[^0-9]|$)', 1)"
        value = f"CASE WHEN len({found}) = 1 THEN TRY_CAST({found}[1] AS DOUBLE) END"
    else:
        value = f"TRY_CAST({text} AS DOUBLE)"
    return (
        f"CASE WHEN {value} IS NOT NULL AND round({value}) BETWEEN {MIN_SONG_YEAR} "
        f"AND {MAX_SONG_YEAR} THEN CAST(round({value}) AS INTEGER) ELSE NULL END"
    )


def _year(columns: set[str], names: tuple[str, ...]) -> str:
    """SQL of the first admissible year of the columns, in the order of the family."""
    present = [_one_year(columns, name) for name in names if name in columns]
    if not present:
        return "CAST(NULL AS INTEGER)"
    if len(present) == 1:
        return present[0]
    return "coalesce(" + ", ".join(present) + ")"


def year_label(name: str) -> str:
    """Return the `year_source` value of a year that comes from the old column `name`."""
    return name.removesuffix("_raw")


def _year_source(columns: set[str], names: tuple[str, ...]) -> str:
    cases = [
        f"WHEN {_one_year(columns, name)} IS NOT NULL THEN '{year_label(name)}'"
        for name in names
        if name in columns
    ]
    if not cases:
        return "CAST(NULL AS VARCHAR)"
    return "CASE " + " ".join(cases) + " END"


def _utc(value: str) -> str:
    text = f"CAST({value} AS VARCHAR)"
    return (
        f"CASE WHEN regexp_matches({text}, '[+-]\\d\\d:?\\d\\d$') "
        f"AND NOT regexp_matches({text}, '[+-]00:?00$') THEN NULL "
        f"ELSE strftime(TRY_CAST({value} AS TIMESTAMP), '%Y-%m-%dT%H:%M:%SZ') END"
    )


def _raw_ref(columns: set[str]) -> str:
    for name in ("raw_path", "raw_html_path"):
        if name in columns:
            value = _text(columns, name)
            return (
                f"CASE WHEN {value} LIKE 'raw/%' AND {value} NOT LIKE '%..%' "
                f"AND NOT regexp_matches({value}, '[A-Za-z]:|[\\\\]') THEN {value} ELSE NULL END"
            )
    return "CAST(NULL AS VARCHAR)"


def _is_error(columns: set[str]) -> str:
    parts = []
    if "parser_error" in columns:
        parts.append(f"{_text(columns, 'parser_error')} IS NOT NULL")
    if "http_status" in columns:
        parts.append(f"TRY_CAST(lyric.{_q('http_status')} AS INTEGER) >= 400")
    if "scrape_status" in columns:
        parts.append(f"lower({_text(columns, 'scrape_status')}) IN ('failed', 'error', 'blocked')")
    if not parts:
        return "FALSE"
    return "(" + " OR ".join(parts) + ")"


def _is_not_song(columns: set[str]) -> str:
    if "is_song_page" not in columns:
        return "FALSE"
    return f"TRY_CAST(lyric.{_q('is_song_page')} AS BOOLEAN) IS FALSE"


def _is_not_parsed(columns: set[str]) -> str:
    if "parse_state" not in columns:
        return "FALSE"
    value = _text(columns, "parse_state")
    return f"{value} IS NOT NULL AND lower({value}) <> 'parsed'"


def _is_not_eligible(columns: set[str]) -> str:
    if "import_eligible" not in columns:
        return "FALSE"
    return f"TRY_CAST(lyric.{_q('import_eligible')} AS BOOLEAN) IS FALSE"


def _string_list(columns: set[str], name: str) -> str:
    if name not in columns:
        return "CAST(NULL AS VARCHAR[])"
    column = f"lyric.{_q(name)}"
    return (
        f"CASE WHEN typeof({column}) LIKE '%[]' THEN CAST({column} AS VARCHAR[]) "
        f"WHEN json_valid(CAST({column} AS VARCHAR)) THEN from_json(CAST({column} AS VARCHAR), "
        f"'[\"VARCHAR\"]') ELSE NULL END"
    )


def _first(columns: set[str], names: tuple[str, ...]) -> str:
    for name in names:
        if name in columns:
            return name
    return ""
