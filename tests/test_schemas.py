"""The table schemas of the data layout, on small invented tables."""

import duckdb
import pandas as pd
import pytest

from songs.common import schemas as s
from songs.stage_30_topics.topic_ids import TOPIC_IDS

ROOT = s.resolve_project_root()
# One invented value per type; the row number keeps the keys apart.
VALUES = {
    "string": lambda row: f"invented {row}",
    "boolean": lambda row: row % 2 == 0,
    "int16": lambda row: row,
    "int32": lambda row: 1990 + row,
    "float64": lambda row: row / 2,
}
ALL_TABLES = pytest.mark.parametrize("table", s.TABLES, ids=lambda table: table.folder + table.file)


def sample(table: s.Table, rows: int = 2) -> pd.DataFrame:
    """Return an invented table that fits the schema."""
    return pd.DataFrame(
        {
            column.name: [VALUES[column.type](row) for row in range(rows)]
            for column in table.all_columns
        }
    )


@ALL_TABLES
def test_a_table_that_fits_its_schema_passes(table):
    assert s.check_table(table, s.cast_to_schema(table, sample(table))) == []
    assert s.check_table(table, s.empty_table(table)) == []
    # Every column that is not required may be empty.
    frame = sample(table)
    for column in table.all_columns:
        if not column.required:
            frame[column.name] = None
    assert s.check_table(table, s.cast_to_schema(table, frame)) == []


@ALL_TABLES
def test_a_missing_column_is_named(table):
    last = table.all_columns[-1].name
    relation = s.cast_to_schema(table, sample(table).drop(columns=last))
    assert s.check_table(table, relation) == [f"missing column {last}"]


@ALL_TABLES
def test_an_extra_column_is_named(table):
    relation = s.cast_to_schema(table, sample(table).assign(scratch="x"))
    assert s.check_table(table, relation) == ["extra column scratch"]


@ALL_TABLES
def test_a_wrong_type_is_named(table):
    last = table.all_columns[-1]
    relation = s.cast_to_schema(table, sample(table)).project(
        f"* REPLACE (DATE '2026-01-01' AS \"{last.name}\")"
    )
    assert s.check_table(table, relation) == [
        f"wrong type in {last.name}: DATE, must be {s.TYPES[last.type]} ({last.type})"
    ]


@ALL_TABLES
def test_a_null_in_a_required_column_is_named(table):
    first = table.all_columns[0]
    assert first.required and first.name not in table.key
    frame = sample(table)
    frame.loc[0, first.name] = None
    assert s.check_table(table, s.cast_to_schema(table, frame)) == [
        f"null in required column {first.name} (1 rows)"
    ]


@ALL_TABLES
def test_a_duplicate_key_is_named(table):
    frame = pd.concat([sample(table), sample(table)], ignore_index=True)
    assert s.check_table(table, s.cast_to_schema(table, frame)) == [
        f"duplicate key ({', '.join(table.key)}): 2 keys have more than one row"
    ]


def test_the_check_names_every_problem_at_once():
    frame = pd.concat([sample(s.COUNTRY_LINKS)] * 2, ignore_index=True)
    frame = frame.drop(columns="match_method").assign(scratch=1)
    frame.loc[0, "source"] = None
    relation = duckdb.from_df(frame)  # not cast: the float column is right, no other is wrong
    problems = s.check_table(s.COUNTRY_LINKS, relation.project("* REPLACE (1 AS match_score)"))
    assert problems == [
        "missing column match_method",
        "extra column scratch",
        "wrong type in match_score: INTEGER, must be DOUBLE (float64)",
        "null in required column source (1 rows)",
        "duplicate key (song_id, discogs_release_id, discogs_track_index): "
        "2 keys have more than one row",
    ]


def test_a_writer_checks_before_it_writes_and_never_writes_over_a_file(tmp_path):
    table = s.COUNTRY_SONGS
    bad = s.cast_to_schema(table, sample(table).drop(columns="lyrics"))
    with pytest.raises(ValueError, match="missing column lyrics"):
        s.write_table(table, bad, tmp_path)
    assert not list(tmp_path.iterdir())
    # The columns of the frame are in another order; the file has the order of the schema.
    frame = sample(table)
    path = s.write_table(table, s.cast_to_schema(table, frame[sorted(frame.columns)]), tmp_path)
    assert path == tmp_path / "songs.parquet"
    stored = s.read_table(table, tmp_path)
    assert stored.columns == [column.name for column in table.all_columns]
    assert stored.project("song_id, year, lyrics").fetchall() == [
        ("invented 0", 1990, "invented 0"),
        ("invented 1", 1991, "invented 1"),
    ]
    with pytest.raises(FileExistsError, match="never written over"):
        s.write_table(table, s.cast_to_schema(table, frame), tmp_path)


def test_an_empty_table_keeps_its_columns_and_types(tmp_path):
    s.write_table(s.COUNTRY_LINKS, s.empty_table(s.COUNTRY_LINKS), tmp_path)
    stored = s.read_table(s.COUNTRY_LINKS, tmp_path)
    assert len(stored) == 0
    assert stored.columns == [column.name for column in s.COUNTRY_LINKS.columns]
    assert str(stored.types[stored.columns.index("match_score")]) == "DOUBLE"


def test_reading_refuses_a_file_that_breaks_the_schema(tmp_path):
    frame = sample(s.COUNTRY_ARTISTS).drop(columns="attempted")
    duckdb.from_df(frame).write_parquet(str(tmp_path / s.COUNTRY_ARTISTS.file))
    with pytest.raises(ValueError, match=r"missing column attempted; wrong type in songs: BIGINT"):
        s.read_table(s.COUNTRY_ARTISTS, tmp_path)


def test_the_score_table_has_one_column_per_topic_id():
    names = [column.name for column in s.SCORE_TOPICS.all_columns]
    assert names == ["country_iso3", "song_id", "lyrics_sha256", *TOPIC_IDS]
    assert {column.type for column in s.SCORE_TOPICS.all_columns[3:]} == {"int16"}


def test_every_table_has_a_key_of_required_columns_and_known_types():
    for table in s.TABLES:
        columns = {column.name: column for column in table.all_columns}
        assert len(columns) == len(table.all_columns), table.file
        assert table.key and all(columns[name].required for name in table.key), table.file
        assert all(column.type in s.TYPES and column.meaning for column in columns.values())
    assert [table.file for table in s.TABLES if not table.planned] == [
        "artists.parquet",
        "songs.parquet",
        "links.parquet",
    ]


def test_the_generated_parts_keep_the_text_around_them():
    page = "\n".join(
        ["by hand, before"]
        + [
            f"<!-- generated:{group}:start -->\nSTALE\n<!-- generated:{group}:end -->"
            for group in s.GROUPS
        ]
        + ["by hand, after", ""]
    )
    new = s.render_page(page)
    assert new.startswith("by hand, before\n") and new.endswith("\nby hand, after\n")
    assert "STALE" not in new and "| `lyrics_sha256` | string | yes |" in new
    assert s.render_page(new) == new
    with pytest.raises(ValueError, match="one time each"):
        s.render_page("no markers")


def test_generated_page_is_current():
    on_disk = (ROOT / s.LAYOUT_PAGE).read_text(encoding="utf-8")
    assert on_disk == s.render_page(on_disk), (
        f"docs/standards/data_layout.md is out of date. Run: {s.WRITE_COMMAND}"
    )
