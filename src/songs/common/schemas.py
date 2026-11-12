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
    for each topic id.
    """

    file: str
    folder: str
    rows: str
    key: tuple[str, ...]
    columns: tuple[Column, ...]
    planned: bool = False
    per_topic: Column | None = None

    @property
    def all_columns(self) -> tuple[Column, ...]:
        """Every column of the file, in order."""
        if self.per_topic is None:
            return self.columns
        return (*self.columns, *(replace(self.per_topic, name=topic) for topic in TOPIC_IDS))


COUNTRY_FOLDER = "lyrics/<ISO3>/songs/<run id>/"
SCORES_FOLDER = "lyrics/<ISO3>/scores/<run id>/"
DUMP_FOLDER = "clean/dumps/<source>/<YYYYMMDD>/"

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
            "Why the artist belongs to the country, as recorded (the old `country_basis`, or "
            'the "Nationality / country in our file" value of a review workbook)',
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
    rows="one row per match between a catalog track and a song",
    key=("song_id", "discogs_release_id", "discogs_track_index"),
    columns=(
        Column("country_iso3", "string", True, "Country of the folder"),
        Column("song_id", "string", True, "Joins to `songs.parquet`"),
        Column("artist_id", "string", True, "Joins to `artists.parquet`"),
        Column("discogs_release_id", "string", True, "Release on the catalog side"),
        Column("discogs_track_index", "string", True, "Position of the track in the release"),
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
    planned=True,
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
    planned=True,
    columns=(
        Column("country_iso3", "string", True, "Country of the folder"),
        Column("song_id", "string", True, "Joins to `songs.parquet` of the country"),
        Column("lyrics_sha256", "string", True, "SHA-256 of the lyric text that was scored"),
        Column("prompt_sha256", "string", True, "SHA-256 of the prompt that scored the song"),
        Column("model", "string", True, "Model that scored the song"),
        Column("text_kind", "string", True, "What the model says the text is"),
        Column("status", "string", True, "Result of the scoring request"),
        Column("scored_utc", "string", False, "When the song was scored"),
    ),
)

DUMP_SONGS = Table(
    file="songs.parquet",
    folder=DUMP_FOLDER,
    rows="one row per song and credited performer",
    key=("source_song_id", "credit_position"),
    planned=True,
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
    planned=True,
    columns=(
        Column("source", "string", True, "Source key"),
        Column("source_artist_id", "string", True, "Id or key of the artist at the source"),
        Column("artist_name", "string", True, "One name of the artist"),
        Column("name_type", "string", True, "`primary` or `alias`"),
        Column("artist_url", "string", False, "Page of the artist"),
    ),
)

# Name of a generated part of the standard -> the tables that it shows.
GROUPS: dict[str, tuple[Table, ...]] = {
    "country_tables": (COUNTRY_ARTISTS, COUNTRY_SONGS, COUNTRY_LINKS),
    "score_tables": (SCORE_TOPICS, SCORE_PROVENANCE),
    "dump_tables": (DUMP_SONGS, DUMP_ARTIST_NAMES),
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
    relation.project(_quoted(names)).write_parquet(str(path), compression="zstd")
    return path


def read_table(
    table: Table, folder: Path, connection: duckdb.DuckDBPyConnection | None = None
) -> duckdb.DuckDBPyRelation:
    """Open the file of a table in `folder`, and raise ValueError when it breaks the schema."""
    path = folder / table.file
    relation = (connection or duckdb).read_parquet(str(path))
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
