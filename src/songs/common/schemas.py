"""The tables of the data layout: their columns, their keys, and one check for all of them.

Each table that the layout names is declared here once. A writer calls
`write_table`, which checks the table against its schema before it writes. The
column tables in `docs/standards/data_layout.md` are generated from this module.

    python -m songs.common.schemas            # print the generated parts of the page
    python -m songs.common.schemas --write    # write them into docs/standards/data_layout.md
"""

import re
import sys
from dataclasses import dataclass, replace
from pathlib import Path

import duckdb
import pandas as pd

from songs.common.paths import resolve_project_root
from songs.stage_30_topics.topic_ids import TOPIC_IDS

LAYOUT_PAGE = Path("docs") / "standards" / "data_layout.md"
WRITE_COMMAND = "python -m songs.common.schemas --write"
# Type name in the standard -> type in DuckDB and in the Parquet file.
TYPES = {
    "string": "VARCHAR",
    "boolean": "BOOLEAN",
    "int16": "SMALLINT",
    "int32": "INTEGER",
    "int64": "BIGINT",
    "float64": "DOUBLE",
}


@dataclass(frozen=True)
class Column:
    """One column of a table. `required` means that no row may be null."""

    name: str
    type: str
    required: bool
    meaning: str


@dataclass(frozen=True)
class Table:
    """One Parquet file of a version folder.

    `planned` marks a table that the standard specifies and no code writes yet.
    `per_topic` is the pattern of the score columns; the table has one such column
    for each topic id. `other_columns` names another table whose columns this table
    also holds; the check then accepts columns that the schema does not name.
    """

    file: str
    folder: str
    rows: str
    key: tuple[str, ...]
    columns: tuple[Column, ...]
    planned: bool = False
    per_topic: Column | None = None
    other_columns: str = ""

    @property
    def all_columns(self) -> tuple[Column, ...]:
        """Every column of the file, in order."""
        if self.per_topic is None:
            return self.columns
        return (*self.columns, *(replace(self.per_topic, name=topic) for topic in TOPIC_IDS))


RAW_FOLDER = "raw/<source>/<YYYYMMDD>/"
COUNTRY_FOLDER = "lyrics/<ISO3>/songs/<run id>/"
SCORES_FOLDER = "lyrics/<ISO3>/scores/<run id>/"
DUMP_FOLDER = "clean/dumps/<source>/<YYYYMMDD>/"
ANALYSIS_FOLDER = "analysis/<YYYYMMDD>/"
ARTIST_COUNTRY_FOLDER = "clean/quality/artist_country/<YYYYMMDD>/"
TEXT_COPIES_FOLDER = "clean/quality/text_copies/<YYYYMMDD>/"
UNCREDITED_SONGS_FOLDER = "clean/quality/uncredited_songs/<YYYYMMDD>/"

RAW_MEMBERS = Table(
    file="members.parquet",
    folder=RAW_FOLDER,
    rows="one row per file in the parts of a packed source",
    key=("member",),
    columns=(
        Column("part", "string", True, "The part that holds the file: `pages-00001.tar.gz`"),
        Column(
            "member",
            "string",
            True,
            "Name of the file in the part: its path as received, with forward slashes",
        ),
        Column("bytes", "int64", True, "Size of the file"),
        Column("sha256", "string", True, "SHA-256 of the bytes of the file, hex"),
        Column(
            "modified_utc",
            "string",
            True,
            "Last change of the source file when it was packed",
        ),
    ),
)

COUNTRY_ARTISTS = Table(
    file="artists.parquet",
    folder=COUNTRY_FOLDER,
    rows="one row per artist of the country",
    key=("artist_id",),
    columns=(
        Column("country_iso3", "string", True, "Country of the folder, upper case"),
        Column(
            "artist_id",
            "string",
            True,
            "Project id of the artist. For an artist with a Discogs id it is "
            '`uuid5(NAMESPACE_URL, "https://www.discogs.com/artist/<id>")`, the same value as '
            "in the old data. For an artist with no Discogs id it is `uuid5(NAMESPACE_URL, "
            '"https://research-songs.invalid/artist/<ISO3>/<artist_name>")`',
        ),
        Column("artist_name", "string", True, "Name as the roster has it"),
        Column("discogs_artist_id", "string", False, "Discogs id"),
        Column(
            "country_tag",
            "string",
            False,
            "Why the artist belongs to the country, as recorded (the old `country_basis`, "
            'the "Nationality / country in our file" value of a review workbook, or '
            "`discogs_home_releases` for an artist that a campaign added from Discogs)",
        ),
        Column("attempted", "boolean", True, "True when a collection run tried this artist"),
        Column("last_attempt_utc", "string", False, "Time of the last attempt"),
        Column(
            "songs",
            "int32",
            True,
            "Number of rows of this artist in `songs.parquet` of the same folder",
        ),
    ),
)

COUNTRY_SONGS = Table(
    file="songs.parquet",
    folder=COUNTRY_FOLDER,
    rows="one row per song with lyrics",
    key=("song_id",),
    columns=(
        Column("country_iso3", "string", True, "Country of the folder"),
        Column("song_id", "string", True, "Id of the song row, unique in the country"),
        Column("artist_id", "string", True, "Joins to `artists.parquet`"),
        Column("artist_name", "string", True, "Name of the artist as collected"),
        Column(
            "song_name",
            "string",
            False,
            "Title as the source prints it. The old lyric files have no title column; "
            "an importer takes it from the links",
        ),
        Column(
            "title_key",
            "string",
            False,
            "Normalized title used in matching (the old `canonical_title_key`)",
        ),
        Column(
            "source",
            "string",
            True,
            "Where the lyrics come from: a source key (`genius`, `letras`, `lrclib`), "
            "or the host of the page for a hand-collected song",
        ),
        Column("source_song_id", "string", False, "Id of the song at the source"),
        Column("song_url", "string", False, "Page of the song at the source"),
        Column("lyrics", "string", True, "The lyric text"),
        Column("lyrics_sha256", "string", True, "SHA-256 of `lyrics` as UTF-8, hex"),
        Column(
            "lyrics_text_hash",
            "string",
            False,
            "Hash by which the lyric-hash lists of the rule for eligible songs name the text "
            "(`songs.common.lyric_hash`): the hash that the old files store, or the SHA-256 "
            "of the text after whitespace normalization. Empty when the text is blank",
        ),
        Column("language", "string", False, "Language as recorded; no fixed code list yet"),
        Column("year", "int32", False, "Release year used in analysis"),
        Column(
            "year_source",
            "string",
            False,
            "Where `year` comes from (`discogs`, `genius`, `musicbrainz`, `manual_review`, ...)",
        ),
        Column(
            "year_basis",
            "string",
            False,
            "How sure the year is (for example `source_printed_unverified`)",
        ),
        Column(
            "first_release_year",
            "int32",
            False,
            "Year of first release when the row is a re-release",
        ),
        Column(
            "re_release",
            "boolean",
            False,
            "Verdict of the re-release check: true when the row is a re-release (the old "
            "`tag_re_release`). Empty when no check ran",
        ),
        Column(
            "canonical_song_id",
            "string",
            False,
            "`song_id` of the row that represents this song when it is a duplicate or a re-release",
        ),
        Column(
            "duplicate_decision",
            "string",
            False,
            "Decision of the duplicate check (for example `suppress_duplicate`)",
        ),
        Column(
            "quality_status",
            "string",
            False,
            "Decision of the quality check (for example `quarantine`)",
        ),
        Column(
            "route",
            "string",
            True,
            "Route of the run that added the row; one of `ROUTES` in `run_records.py`",
        ),
        Column("run_id", "string", True, "Run that added or last replaced the row"),
        Column("collected_utc", "string", False, "When the lyrics were fetched or imported"),
    ),
)

COUNTRY_LINKS = Table(
    file="links.parquet",
    folder=COUNTRY_FOLDER,
    rows="one row per link from a song to a source page",
    key=("song_id", "discogs_release_id", "discogs_track_index"),
    columns=(
        Column("country_iso3", "string", True, "Country of the folder"),
        Column("song_id", "string", True, "Joins to `songs.parquet`"),
        Column("artist_id", "string", True, "Joins to `artists.parquet`"),
        Column(
            "discogs_release_id",
            "string",
            False,
            "Release on the catalog side. Empty when the link has no catalog track",
        ),
        Column(
            "discogs_track_index",
            "string",
            False,
            "Position of the track in the release. Empty when the link has no catalog track",
        ),
        Column("discogs_title", "string", False, "Track title in the catalog"),
        Column("source", "string", True, "Same meaning as in `songs.parquet`"),
        Column("source_song_id", "string", False, "Id of the song at the source"),
        Column("source_title", "string", False, "Title at the source (the old `provider_title`)"),
        Column("song_url", "string", False, "Page of the song at the source"),
        Column("match_method", "string", False, "How the match was made"),
        Column(
            "match_score",
            "float64",
            False,
            "Strength of the match; the old files store it as text",
        ),
        Column("run_id", "string", True, "Run that added the link"),
    ),
)

SCORE_TOPICS = Table(
    file="topics.parquet",
    folder=SCORES_FOLDER,
    rows="one row per scored song",
    key=("song_id",),
    columns=(
        Column("country_iso3", "string", True, "Country of the folder"),
        Column("song_id", "string", True, "Joins to `songs.parquet` of the country"),
        Column("lyrics_sha256", "string", True, "SHA-256 of the lyric text that was scored"),
    ),
    per_topic=Column(
        "",
        "int16",
        False,
        "One column per topic id: the score of the song on that topic. Null when the run "
        "gave no score. The names come from `songs.stage_30_topics.topic_ids`; "
        "[topics](topics.md) lists them",
    ),
)

SCORE_PROVENANCE = Table(
    file="provenance.parquet",
    folder=SCORES_FOLDER,
    rows="one row per scored song",
    key=("song_id",),
    columns=(
        Column("country_iso3", "string", True, "Country of the folder"),
        Column("song_id", "string", True, "Joins to `songs.parquet` of the country"),
        Column("lyrics_sha256", "string", True, "SHA-256 of the lyric text that was scored"),
        Column("prompt_sha256", "string", True, "SHA-256 of the prompt that scored the song"),
        Column("model", "string", True, "Model that scored the song"),
        Column("text_kind", "string", True, "What the model says the text is"),
        Column(
            "status",
            "string",
            True,
            "Result of the scoring request: `complete`, or `reused` when `songs score prepare` "
            "copied the score of a song with the same text and decade",
        ),
        Column("scored_utc", "string", False, "When the song was scored"),
    ),
)

DUMP_SONGS = Table(
    file="songs.parquet",
    folder=DUMP_FOLDER,
    rows="one row per song and credited performer",
    key=("source_song_id", "credit_position"),
    columns=(
        Column("source", "string", True, "Source key, the same in every row"),
        Column(
            "source_song_id",
            "string",
            True,
            "Id of the song at the source. When the source has none, the first 20 hex "
            "characters of the SHA-256 of `song_url`",
        ),
        Column(
            "song_url",
            "string",
            False,
            "Page of the song. Null for LRCLIB and Genius rows that have no page",
        ),
        Column("artist_name", "string", True, "Name of the performer as the source prints it"),
        Column(
            "source_artist_id",
            "string",
            False,
            "Id or key of the artist at the source; joins to `artist_names.parquet`",
        ),
        Column(
            "credit_position",
            "int32",
            True,
            "1 for the first credited performer, 2 for the next",
        ),
        Column("song_name", "string", True, "Title as the source prints it"),
        Column("lyrics", "string", True, "The lyric text"),
        Column("lyrics_sha256", "string", True, "SHA-256 of `lyrics` as UTF-8, hex"),
        Column("language", "string", False, "Language as the source states it"),
        Column(
            "year",
            "int32",
            False,
            "Release year as the source states it, when it is a plausible year "
            "(`songs.common.years.is_admissible_year`)",
        ),
        Column(
            "year_source",
            "string",
            False,
            "Old column that gave `year`, without `_raw`: `release_year` is the song, "
            "`album_release_year` is the album of the song (a fallback), `release_date` is a "
            "printed date. Null when `year` is null",
        ),
        Column("album", "string", False, "Album name"),
        Column("fetched_utc", "string", False, "When the page or the record was fetched"),
        Column(
            "raw_ref",
            "string",
            False,
            "Where the raw page is under `raw/`, relative to the data folder",
        ),
    ),
)

DUMP_ARTIST_NAMES = Table(
    file="artist_names.parquet",
    folder=DUMP_FOLDER,
    rows="one row per name of an artist at the source",
    key=("source_artist_id", "artist_name"),
    columns=(
        Column("source", "string", True, "Source key"),
        Column("source_artist_id", "string", True, "Id or key of the artist at the source"),
        Column("artist_name", "string", True, "One name of the artist"),
        Column("name_type", "string", True, "`primary` or `alias`"),
        Column("artist_url", "string", False, "Page of the artist"),
    ),
)

ANALYSIS_COUNTRY_YEAR = Table(
    file="country_year.parquet",
    folder=ANALYSIS_FOLDER,
    rows="one row per country and year of the country-year table",
    key=("country_iso3", "year"),
    columns=(
        Column("country_iso3", "string", True, "Country"),
        Column("year", "int32", True, "Year"),
        Column(
            "num_songs",
            "int64",
            False,
            "Eligible songs of the country and year. Null when the release has no songs "
            "folder for the country",
        ),
        Column("num_artists", "int64", False, "Distinct artists of those songs"),
        Column(
            "num_songs_by_exception",
            "int64",
            False,
            "Those songs that entered by exception (`resources/lyrics/eligibility_exceptions.csv`)",
        ),
        Column("num_songs_scored", "int64", False, "Those songs that have topic scores"),
    ),
    per_topic=Column(
        "",
        "float64",
        False,
        "One column per topic id: the mean of the scores on that topic that are not null. "
        "Null when no song of the country and year has a score on the topic",
    ),
    other_columns="every column of `countries.parquet` (`COUNTRY_COLUMNS` in "
    "`countries_panel.py`), except `num_songs`, `num_artists` and `artist_count_method`, "
    "which the release counts again",
)

ANALYSIS_SONGS = Table(
    file="songs.parquet",
    folder=ANALYSIS_FOLDER,
    rows="one row per eligible song; no lyric text",
    key=("country_iso3", "song_id"),
    columns=(
        Column("country_iso3", "string", True, "Country"),
        Column("song_id", "string", True, "Id of the song in the country tables"),
        Column("artist_id", "string", True, "Joins to `artists.parquet` of the country"),
        Column(
            "year",
            "int32",
            False,
            "Release year. Empty when the song has no year; such a song is not in "
            "`country_year.parquet`",
        ),
        Column("source", "string", True, "Where the lyrics come from"),
        Column("route", "string", True, "Route of the run that added the song"),
        Column(
            "by_exception",
            "boolean",
            True,
            "True when the song entered by exception "
            "(`resources/lyrics/eligibility_exceptions.csv`)",
        ),
        Column(
            "scored",
            "boolean",
            True,
            "True when a score of the newest scoring run has the same `song_id` and "
            "`lyrics_sha256`",
        ),
    ),
    per_topic=Column(
        "",
        "int16",
        False,
        "One column per topic id: the score of the song. Null when the song has no score",
    ),
)

# The decisions of `artist_country.parquet`.
KEEP, OTHER_COUNTRY = "keep", "other_country"

ARTIST_COUNTRY = Table(
    file="artist_country.parquet",
    folder=ARTIST_COUNTRY_FOLDER,
    rows="one row per roster artist with a Discogs id",
    key=("country_iso3", "artist_id"),
    columns=(
        Column("country_iso3", "string", True, "Country of the roster"),
        Column("artist_id", "string", True, "Joins to `artists.parquet` of the country"),
        Column(
            "discogs_artist_id",
            "string",
            True,
            "Discogs id of the roster, or the id that `dump_match.discogs_ids` found by name",
        ),
        Column(
            "stated_country",
            "string",
            True,
            "Country that the start of the Discogs profile states for the artist, as a code. "
            "Empty text when it states none",
        ),
        Column(
            "home_word",
            "boolean",
            True,
            "True when the start of the profile holds a word of a home country",
        ),
        Column("releases", "int64", True, "Releases that credit the artist and have a country"),
        Column("releases_home", "int64", True, "Those releases in a home release country"),
        Column(
            "top_release_country",
            "string",
            True,
            "Release country of Discogs with the most of those releases. Empty text when "
            "`releases` is 0",
        ),
        Column(
            "decision",
            "string",
            True,
            f"`{OTHER_COUNTRY}` when the artist belongs to another country, or `{KEEP}`",
        ),
    ),
)

# The reasons of `text_copies.parquet`.
SAME_TEXT, SAME_ARTIST_START = "same_text", "same_artist_start"

TEXT_COPIES = Table(
    file="text_copies.parquet",
    folder=TEXT_COPIES_FOLDER,
    rows="one row per campaign song that is a text copy of another song of its country",
    key=("country_iso3", "song_id"),
    columns=(
        Column("country_iso3", "string", True, "Country of the song"),
        Column(
            "song_id",
            "string",
            True,
            "The copy: a song with the route `dump_name` in `songs.parquet` of the country",
        ),
        Column(
            "kept_song_id",
            "string",
            True,
            "The song of the same country that represents the group: an older song when "
            "the group has one, else the campaign song with the smallest `run_id`, then "
            "the smallest `song_id`",
        ),
        Column(
            "reason",
            "string",
            True,
            f"`{SAME_TEXT}`: the same `text_key` as the kept song (`songs.common.lyric_hash`). "
            f"`{SAME_ARTIST_START}`: the same artist and the same `start_key`",
        ),
    ),
)

# The reasons of `uncredited_songs.parquet`.
MERGED_ARTIST_ID, NO_CREDIT = "merged_artist_id", "no_credit"

UNCREDITED_SONGS = Table(
    file="uncredited_songs.parquet",
    folder=UNCREDITED_SONGS_FOLDER,
    rows="one row per campaign song whose dump credit does not name its roster artist",
    key=("country_iso3", "song_id"),
    columns=(
        Column("country_iso3", "string", True, "Country of the song"),
        Column(
            "song_id",
            "string",
            True,
            "A song with the route `dump_name` in `songs.parquet` of the country",
        ),
        Column(
            "reason",
            "string",
            True,
            f"`{MERGED_ARTIST_ID}`: a name of the artist id of the credit has the key of the "
            "roster artist, and the id holds unrelated artists. "
            f"`{NO_CREDIT}`: no credited name has that key or starts with it",
        ),
    ),
)

# Name of a generated part of the standard -> the tables that it shows.
GROUPS: dict[str, tuple[Table, ...]] = {
    "raw_tables": (RAW_MEMBERS,),
    "country_tables": (COUNTRY_ARTISTS, COUNTRY_SONGS, COUNTRY_LINKS),
    "score_tables": (SCORE_TOPICS, SCORE_PROVENANCE),
    "dump_tables": (DUMP_SONGS, DUMP_ARTIST_NAMES),
    "analysis_tables": (ANALYSIS_COUNTRY_YEAR, ANALYSIS_SONGS),
    "quality_tables": (ARTIST_COUNTRY, TEXT_COPIES, UNCREDITED_SONGS),
}
TABLES: tuple[Table, ...] = tuple(table for tables in GROUPS.values() for table in tables)


def _quoted(names: tuple[str, ...] | list[str]) -> str:
    return ", ".join(f'"{name}"' for name in names)


def check_table(table: Table, relation: duckdb.DuckDBPyRelation) -> list[str]:
    """Return one line for each way a relation breaks the schema of a table. Empty means it fits.

    The check names every missing column, extra column, wrong type, null in a
    required column, and duplicate key. The order of the columns does not matter.
    """
    expected = {column.name: column for column in table.all_columns}
    found = dict(zip(relation.columns, (str(kind) for kind in relation.types), strict=True))
    problems = [f"missing column {name}" for name in expected if name not in found]
    if not table.other_columns:
        problems += [f"extra column {name}" for name in found if name not in expected]
    present = [column for column in expected.values() if column.name in found]
    problems += [
        f"wrong type in {column.name}: {found[column.name]}, "
        f"must be {TYPES[column.type]} ({column.type})"
        for column in present
        if found[column.name] != TYPES[column.type]
    ]
    required = [column.name for column in present if column.required]
    if required:
        nulls = relation.aggregate(
            ", ".join(f'count(*) - count("{name}")' for name in required)
        ).fetchall()[0]
        problems += [
            f"null in required column {name} ({count} rows)"
            for name, count in zip(required, nulls, strict=True)
            if count
        ]
    if all(name in found for name in table.key):
        key = _quoted(table.key)
        repeated = len(relation.aggregate(f"{key}, count(*) AS n", key).filter("n > 1"))
        if repeated:
            problems.append(
                f"duplicate key ({', '.join(table.key)}): {repeated} keys have more than one row"
            )
    return problems


def cast_to_schema(
    table: Table,
    frame: pd.DataFrame | duckdb.DuckDBPyRelation,
    connection: duckdb.DuckDBPyConnection | None = None,
) -> duckdb.DuckDBPyRelation:
    """Return a frame or a relation with the column types and the column order of a table.

    A column that the table does not have stays as it is, and a column that the
    input lacks stays absent, so that `check_table` names both.
    """
    known = [column for column in table.all_columns if column.name in frame.columns]
    select = [
        f'CAST("{column.name}" AS {TYPES[column.type]}) AS "{column.name}"' for column in known
    ]
    names = {column.name for column in known}
    select += [f'"{name}"' for name in frame.columns if name not in names]
    if isinstance(frame, pd.DataFrame):
        frame = (connection or duckdb).from_df(frame)
    return frame.project(", ".join(select))


def empty_table(
    table: Table, connection: duckdb.DuckDBPyConnection | None = None
) -> duckdb.DuckDBPyRelation:
    """Return a relation with the columns of a table and no rows."""
    select = ", ".join(
        f'CAST(NULL AS {TYPES[column.type]}) AS "{column.name}"' for column in table.all_columns
    )
    return (connection or duckdb).sql(f"SELECT {select} LIMIT 0")


def _fail(table: Table, where: Path, problems: list[str]) -> None:
    if problems:
        raise ValueError(f"{where} breaks the schema of {table.file}: " + "; ".join(problems))


def write_table(table: Table, relation: duckdb.DuckDBPyRelation, folder: Path) -> Path:
    """Check a relation against its schema, then write it to `folder` as Parquet with zstd.

    Raise ValueError with every problem when the relation does not fit, and
    FileExistsError when the file exists: a version folder is write-once.
    """
    path = folder / table.file
    if path.exists():
        raise FileExistsError(f"{path} exists; a version folder is never written over")
    _fail(table, path, check_table(table, relation))
    names = [column.name for column in table.all_columns]
    names += [name for name in relation.columns if name not in names]
    relation.project(_quoted(names)).write_parquet(str(path), compression="zstd")
    return path


def read_table(
    table: Table,
    folder: Path,
    connection: duckdb.DuckDBPyConnection | None = None,
    *,
    fill_absent: bool = False,
) -> duckdb.DuckDBPyRelation:
    """Open the file of a table in `folder`, and raise ValueError when it breaks the schema.

    With `fill_absent`, an optional column that the file lacks is read as empty. An
    importer uses it to read a folder written before the column existed. An analysis
    does not: for it, an absent column is an error.
    """
    path = folder / table.file
    relation = (connection or duckdb).read_parquet(str(path))
    absent = [
        f'CAST(NULL AS {TYPES[column.type]}) AS "{column.name}"'
        for column in table.all_columns
        if fill_absent and not column.required and column.name not in relation.columns
    ]
    if absent:
        relation = relation.project(", ".join(["*", *absent]))
    _fail(table, path, check_table(table, relation))
    return relation


def _marker(group: str, edge: str) -> str:
    return f"<!-- generated:{group}:{edge} -->"


def render_group(group: str) -> str:
    """Return the Markdown of one generated part of the standard: the tables of a group."""
    blocks = []
    for table in GROUPS[group]:
        keys = ", ".join(f"`{name}`" for name in table.key)
        state = " Planned: no code writes this table yet." if table.planned else ""
        lines = [
            f"### `{table.file}`: {table.rows}",
            "",
            f"Folder: `{table.folder}`. Key: {keys}.{state}",
            "",
            "| Column | Type | Required | Meaning |",
            "| --- | --- | --- | --- |",
        ]
        lines += [
            f"| `{column.name}` | {column.type} | {'yes' if column.required else 'no'} "
            f"| {column.meaning} |"
            for column in table.columns
        ]
        if table.per_topic is not None:
            column = table.per_topic
            lines.append(
                f"| `{TOPIC_IDS[0]}` to `{TOPIC_IDS[-1]}` | {column.type} "
                f"| {'yes' if column.required else 'no'} | {column.meaning} |"
            )
        if table.other_columns:
            lines += ["", f"The file also holds {table.other_columns}."]
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def render_page(text: str) -> str:
    """Return the text of the standard with every generated part made new.

    A generated part stands between two marker lines. The text outside the
    markers is written by hand and stays as it is.
    """
    for group in GROUPS:
        start, end = _marker(group, "start"), _marker(group, "end")
        pattern = re.compile(re.escape(start) + r".*?" + re.escape(end), flags=re.DOTALL)
        if len(pattern.findall(text)) != 1:
            raise ValueError(f"{LAYOUT_PAGE.as_posix()} must hold {start} and {end} one time each")
        note = f"<!-- Do not edit by hand. To rebuild, run: {WRITE_COMMAND} -->"
        block = f"{start}\n{note}\n\n{render_group(group)}\n\n{end}"
        text = pattern.sub(lambda _match, block=block: block, text)
    return text


def main(argv: list[str]) -> int:
    """Print the generated parts, or write them into the standard with --write."""
    if argv == ["--write"]:
        page = resolve_project_root() / LAYOUT_PAGE
        text = render_page(page.read_text(encoding="utf-8"))
        with page.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
    else:
        sys.stdout.write("\n\n".join(render_group(group) for group in GROUPS) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
