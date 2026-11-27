from pathlib import Path

import duckdb
import pytest

from songs.common.schemas import Column, Table
from songs.stage_00_ingest.reviewed_fields import write_reviewed_table


def test_review_updates_only_the_named_row_and_accepts_null(tmp_path: Path):
    table = Table(
        "links.parquet",
        "",
        "",
        ("song_id",),
        (Column("song_id", "string", True, ""), Column("score", "int32", False, "")),
    )
    output = tmp_path / "new"
    output.mkdir()
    with duckdb.connect() as db:
        db.sql("SELECT * FROM (VALUES ('a', 1), ('b', 2)) t(song_id, score)").write_parquet(
            str(tmp_path / table.file)
        )
        with pytest.raises(ValueError, match="missing"):
            write_reviewed_table(db, table, tmp_path, output, {"x": {"score": 3}}, ("score",))
        assert not (output / table.file).exists()
        write_reviewed_table(db, table, tmp_path, output, {"b": {"score": None}}, ("score",))
        assert db.read_parquet(str(output / table.file)).order("song_id").fetchall() == [
            ("a", 1),
            ("b", None),
        ]
        assert db.read_parquet(str(tmp_path / table.file)).order("song_id").fetchall() == [
            ("a", 1),
            ("b", 2),
        ]
