"""Import the topic scores of one country from the files of the old layout.

The old pipeline keeps the topic scores of a country in one folder. This module
reads that folder and writes the score tables of the layout in
`docs/standards/data_layout.md`.

    in   <old data folder>/lyrics/<iso3>/scores/topics.parquet
    in   <old data folder>/lyrics/<iso3>/scores/topic_provenance.parquet
         or provenance.parquet, when the first file is absent
    in   lyrics/<ISO3>/songs/<run id>/   the newest songs folder with a manifest
    out  lyrics/<ISO3>/scores/<run id>/  topics.parquet, provenance.parquet,
                                         _MANIFEST.json

The old data folder is read only. The command calls no model. It reads no value
scores and no lyric text. `lyrics_sha256` is the hash stored in the old
provenance: the SHA-256 of the lyric text that was scored. A score whose song
now has another hash stays, with the stored hash.
"""

from pathlib import Path

import duckdb

from songs.common import manifests, paths, run_records, schemas
from songs.stage_30_topics.topic_ids import TOPIC_IDS

OLD_DATA_ENV = "SONGS_OLD_DATA_ROOT"
# The topic-only refresh writes topic_provenance.parquet for the rows in topics.parquet.
# provenance.parquet is the older file. It is the source only when the newer file is absent.
PROVENANCE_FILES = ("topic_provenance.parquet", "provenance.parquet")
# These columns are required in the new tables. A blank cell stops the import.
REQUIRED = ("lyrics_sha256", "prompt_sha256", "model", "text_kind", "measurement_status")
OLD_TOPIC_COLUMNS = tuple(f"t{index}" for index in range(1, len(TOPIC_IDS) + 1))
COUNT_NAMES = (
    "scores",
    "scores_no_song",
    "scores_text_changed",
    "scores_null_topics",
    "scores_country_differs",
    "scores_song_lyrics",
    "scores_non_song",
    "scores_uncertain",
    "scores_other_text_kind",
)


def _sql_path(path: Path) -> str:
    return path.resolve().as_posix().replace("'", "''")


def _stamp(path: Path) -> tuple[int, int]:
    stat = path.stat()
    return (stat.st_size, stat.st_mtime_ns)


def _require_unchanged(path: Path, stamp: tuple[int, int]) -> None:
    """Raise when a source file changed size or change time after it was read."""
    if _stamp(path) != stamp:
        raise ValueError(f"{path.name} changed while it was read")


def _scalar(connection: duckdb.DuckDBPyConnection, query: str) -> int:
    return connection.sql(query).fetchall()[0][0]


def _columns(connection: duckdb.DuckDBPyConnection, path: Path) -> set[str]:
    rows = connection.execute(
        f"DESCRIBE SELECT * FROM read_parquet('{_sql_path(path)}')"
    ).fetchall()
    return {str(row[0]) for row in rows}


def _text(name: str) -> str:
    """A text column with blank cells read as empty."""
    return f'nullif(trim(CAST("{name}" AS VARCHAR)), \'\') AS "{name}"'


def _provenance_file(folder: Path) -> Path:
    for name in PROVENANCE_FILES:
        path = folder / name
        if path.is_file():
            return path
    raise FileNotFoundError(
        "no topic_provenance.parquet or provenance.parquet in the old scores folder"
    )


def _quoted(names: tuple[str, ...] | list[str]) -> str:
    return ", ".join(f'"{name}"' for name in names)


def _problems(connection: duckdb.DuckDBPyConnection) -> list[str]:
    """Return one line for each reason the old scores cannot be written."""
    problems = []
    for view in ("topics", "provenance"):
        blanks = _scalar(connection, f"SELECT count(*) FROM {view} WHERE song_id IS NULL")
        if blanks:
            problems.append(f"no song_id in {view}: {blanks} rows")
        extra = _scalar(
            connection,
            f"SELECT count(*) - count(DISTINCT song_id) FROM {view} WHERE song_id IS NOT NULL",
        )
        if extra:
            problems.append(f"duplicate song_id in {view}: {extra} extra rows")
    topics_only = _scalar(
        connection,
        "SELECT count(*) FROM (SELECT song_id FROM topics WHERE song_id IS NOT NULL) AS t "
        "ANTI JOIN (SELECT song_id FROM provenance WHERE song_id IS NOT NULL) AS p "
        "USING (song_id)",
    )
    provenance_only = _scalar(
        connection,
        "SELECT count(*) FROM (SELECT song_id FROM provenance WHERE song_id IS NOT NULL) AS p "
        "ANTI JOIN (SELECT song_id FROM topics WHERE song_id IS NOT NULL) AS t "
        "USING (song_id)",
    )
    if topics_only:
        problems.append(f"topic rows with no provenance: {topics_only}")
    if provenance_only:
        problems.append(f"provenance rows with no topic row: {provenance_only}")
    missing = connection.sql(
        "SELECT "
        + ", ".join(f'count(*) FILTER (WHERE "{name}" IS NULL)' for name in REQUIRED)
        + " FROM provenance WHERE song_id IS NOT NULL"
    ).fetchall()[0]
    problems += [
        f"no {name}: {count} rows" for name, count in zip(REQUIRED, missing, strict=True) if count
    ]
    return problems


def _counts(connection: duckdb.DuckDBPyConnection) -> dict[str, int]:
    topic_list = _quoted(TOPIC_IDS)
    row = connection.sql(
        f"""
        SELECT
            count(*),
            count(*) FILTER (WHERE no_song),
            count(*) FILTER (WHERE text_changed),
            count(*) FILTER (WHERE coalesce({topic_list}) IS NULL),
            count(*) FILTER (WHERE country_differs),
            count(*) FILTER (WHERE text_kind = 'song_lyrics'),
            count(*) FILTER (WHERE text_kind = 'non_song'),
            count(*) FILTER (WHERE text_kind = 'uncertain'),
            count(*) FILTER (
                WHERE text_kind NOT IN ('song_lyrics', 'non_song', 'uncertain')
            )
        FROM scored
        """
    ).fetchall()[0]
    return dict(zip(COUNT_NAMES, row, strict=True))


def import_scores(
    old_data: Path,
    data: Path,
    iso3: str,
    *,
    run_id: str | None = None,
) -> dict:
    """Import the topic scores of one country and write the score folder and its manifest.

    `old_data` is the old data folder. Nothing is written there. `data` is the
    data folder of the new layout. The scores join the newest songs folder of
    the country that has a manifest. `run_id` names the new folder; the default
    is the current UTC second.
    """
    iso3 = paths.check_iso3(iso3)
    run_id = paths.check_run_id(run_id) if run_id else run_records.new_run_id()
    if old_data.resolve() == data.resolve():
        raise ValueError(
            "the old data folder and the data folder are the same folder; "
            "the old data folder is read only"
        )
    folder = old_data / "lyrics" / iso3.lower() / "scores"
    topics_path = folder / "topics.parquet"
    if not topics_path.is_file():
        raise FileNotFoundError(f"no file lyrics/{iso3.lower()}/scores/topics.parquet")
    provenance_path = _provenance_file(folder)
    songs = paths.latest_country_songs_dir(data, iso3)
    if songs is None:
        raise FileNotFoundError(
            f"{iso3} has no songs folder with a manifest. Import the songs of the country first."
        )
    manifests.read_manifest(songs)
    stamps = {path: _stamp(path) for path in (topics_path, provenance_path)}

    with duckdb.connect() as connection:
        topic_names = _columns(connection, topics_path)
        provenance_names = _columns(connection, provenance_path)
        absent = [name for name in ("song_id", *OLD_TOPIC_COLUMNS) if name not in topic_names]
        absent += [name for name in ("song_id", *REQUIRED) if name not in provenance_names]
        if absent:
            raise ValueError("the old scores have no column " + ", ".join(absent))
        topic_cells = ", ".join(
            f'CAST("{name}" AS SMALLINT) AS "{name}"' for name in OLD_TOPIC_COLUMNS
        )
        if "country" in provenance_names:
            country_cell = _text("country")
            country_differs = f"p.country IS NULL OR upper(p.country) <> '{iso3}'"
        else:
            country_cell = 'CAST(NULL AS VARCHAR) AS "country"'
            country_differs = "false"
        connection.sql(
            f"CREATE VIEW topics AS SELECT {_text('song_id')}, {topic_cells} "
            f"FROM read_parquet('{_sql_path(topics_path)}')"
        )
        provenance_cells = ", ".join(_text(name) for name in ("song_id", *REQUIRED))
        connection.sql(
            f"CREATE VIEW provenance AS SELECT {provenance_cells}, {country_cell} "
            f"FROM read_parquet('{_sql_path(provenance_path)}')"
        )
        problems = _problems(connection)
        if problems:
            raise ValueError("the old scores cannot be imported: " + "; ".join(problems))
        connection.sql(
            f"""
            CREATE VIEW current_songs AS
            SELECT {_text("song_id")}, {_text("lyrics_sha256")}
            FROM read_parquet('{_sql_path(songs / "songs.parquet")}')
            """
        )
        topic_as = ", ".join(
            f't."{old}" AS "{topic_id}"'
            for old, topic_id in zip(OLD_TOPIC_COLUMNS, TOPIC_IDS, strict=True)
        )
        connection.sql(
            f"""
            CREATE VIEW scored AS
            SELECT
                '{iso3}' AS country_iso3,
                t.song_id,
                p.lyrics_sha256,
                {topic_as},
                p.prompt_sha256,
                p.model,
                p.text_kind,
                p.measurement_status AS status,
                CAST(NULL AS VARCHAR) AS scored_utc,
                s.song_id IS NULL AS no_song,
                s.song_id IS NOT NULL
                    AND s.lyrics_sha256 IS DISTINCT FROM p.lyrics_sha256 AS text_changed,
                {country_differs} AS country_differs
            FROM topics AS t
            JOIN provenance AS p USING (song_id)
            LEFT JOIN current_songs AS s USING (song_id)
            """
        )
        counts = _counts(connection)
        for path, stamp in stamps.items():
            _require_unchanged(path, stamp)
        out = paths.country_scores_dir(data, iso3, run_id)
        out.mkdir(parents=True, exist_ok=False)
        topic_columns = _quoted(("country_iso3", "song_id", "lyrics_sha256", *TOPIC_IDS))
        provenance_columns = _quoted(
            (
                "country_iso3",
                "song_id",
                "lyrics_sha256",
                "prompt_sha256",
                "model",
                "text_kind",
                "status",
                "scored_utc",
            )
        )
        schemas.write_table(
            schemas.SCORE_TOPICS,
            connection.sql(f"SELECT {topic_columns} FROM scored ORDER BY song_id"),
            out,
        )
        schemas.write_table(
            schemas.SCORE_PROVENANCE,
            connection.sql(f"SELECT {provenance_columns} FROM scored ORDER BY song_id"),
            out,
        )
        for path, stamp in stamps.items():
            _require_unchanged(path, stamp)
        manifests.write_manifest(
            data,
            out,
            "country_scores",
            country_iso3=iso3,
            run_id=run_id,
            inputs=[f"lyrics/{iso3.lower()}/scores/", paths.data_relative(data, songs)],
            counts=counts,
            notes=(
                f"Topic scores from the old layout. The input lyrics/{iso3.lower()}/scores/ "
                "is relative to the old data folder. "
                f"The provenance file is {provenance_path.name}. "
                "lyrics_sha256 is the hash stored when the song was scored. "
                "A score whose current song text has another hash is kept, with that hash. "
                "scored_utc is empty: the old files have no time of the score. "
                "Value scores are not imported."
            ),
        )
    return {"path": out, "songs": paths.data_relative(data, songs), **counts}
