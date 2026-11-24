"""The rule that marks the campaign songs whose dump credit does not name their roster artist."""

from datetime import date
from pathlib import Path

import pandas as pd
import pytest
from typer.testing import CliRunner

from songs.cli import app
from songs.common import manifests, paths, schemas, sync
from songs.common.paths import DATA_ROOT_ENV
from songs.stage_10_clean import uncredited_songs

RUN = "20260103T000000Z"
ROSTER = {"a1": "Anna Jóns", "a2": "Nicki Minaj", "a3": "Crosby"}
# song id, roster artist, route, source song id
SONGS = [
    ("c1", "a1", "dump_name", "d1"),
    ("c2", "a1", "dump_name", "d2"),
    ("c3", "a2", "dump_name", "d3"),
    ("c4", "a3", "dump_name", "d4"),
    ("c5", "a1", "dump_name", "d5"),
    ("c6", "a1", "dump_name", "absent"),
    ("c7", "a1", "dump_name", "d7"),
    ("o1", "a1", "old_layout", "d5"),
]
# source song id, credited name, source artist id
CREDITS = [
    ("d1", "Anna Jons", "x1"),
    ("d2", "Anna Jons feat. Bára", "x2"),
    ("d3", "KIDZ BOP Kids", "353676"),
    ("d4", "Crosby Stills Nash", "x4"),
    ("d5", "Someone Else", "x5"),
    ("d7", "AJ", "x7"),
]
NAMES = [
    *(("353676", name, "primary") for name in ("Nicki Minaj", "KIDZ BOP Kids", "Kygo")),
    ("x7", "AJ", "primary"),
    ("x7", "Anna Jóns", "alias"),
]
EXPECTED = [("TGO", "c3", "merged_artist_id"), ("TGO", "c5", "no_credit")]


def write(table: schemas.Table, folder: Path, rows: list[dict]) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    names = [column.name for column in table.all_columns]
    frame = pd.DataFrame(rows).reindex(columns=names)
    schemas.write_table(table, schemas.cast_to_schema(table, frame), folder)
    (folder / paths.MANIFEST_NAME).write_text("{}\n", encoding="utf-8")


def make_data(data: Path) -> Path:
    country = paths.country_songs_dir(data, "TGO", RUN)
    write(
        schemas.COUNTRY_ARTISTS,
        country,
        [
            {"country_iso3": "TGO", "artist_id": key, "artist_name": name}
            | {"attempted": True, "songs": 1}
            for key, name in ROSTER.items()
        ],
    )
    write(
        schemas.COUNTRY_SONGS,
        country,
        [
            {"country_iso3": "TGO", "song_id": song_id, "artist_id": artist_id}
            | {"source": "example", "source_song_id": source_id, "route": route, "run_id": RUN}
            | {"artist_name": "Invented", "lyrics": "invented line", "lyrics_sha256": song_id}
            for song_id, artist_id, route, source_id in SONGS
        ],
    )
    dump = paths.clean_dump_dir(data, "example", "20260102")
    write(
        schemas.DUMP_SONGS,
        dump,
        [
            {"source": "example", "source_song_id": song_id, "artist_name": name}
            | {"source_artist_id": artist_id, "credit_position": 1, "song_name": "Title"}
            | {"lyrics": "invented line", "lyrics_sha256": song_id}
            for song_id, name, artist_id in CREDITS
        ],
    )
    write(
        schemas.DUMP_ARTIST_NAMES,
        dump,
        [
            {"source": "example", "source_artist_id": key, "artist_name": name, "name_type": kind}
            for key, name, kind in NAMES
        ],
    )
    return country


COUNTS = {
    "campaign_songs": 7,
    "not_in_dump": 1,
    "credited": 3,
    "credited_by_split": 1,
    "merged_artist_id": 1,
    "no_credit": 1,
    "uncredited": 2,
    "countries": 1,
}


def test_a_dry_check_writes_nothing_and_a_write_makes_one_folder(tmp_path):
    country = make_data(tmp_path)
    result = uncredited_songs.check_credits(tmp_path)
    by_country = {"campaign_songs": 7, "merged_artist_id": 1, "no_credit": 1}
    assert result == {"counts": COUNTS, "by_country": {"TGO": by_country}, "folder": None}
    assert not (tmp_path / "clean" / "quality").exists()

    result = uncredited_songs.check_credits(tmp_path, write=True, today=date(2026, 1, 4))
    out = paths.clean_uncredited_songs_dir(tmp_path, "20260104")
    assert result["folder"] == out == paths.latest_clean_uncredited_songs_dir(tmp_path)
    manifest = manifests.read_manifest(out)
    assert (manifest.kind, manifest.counts) == ("clean_uncredited_songs", COUNTS)
    assert paths.data_relative(tmp_path, country) in manifest.inputs
    assert sorted(schemas.read_table(schemas.UNCREDITED_SONGS, out).fetchall()) == EXPECTED
    assert out.parent in sync._parents(tmp_path)
    with pytest.raises(FileExistsError, match="never written over"):
        uncredited_songs.check_credits(tmp_path, write=True, today=date(2026, 1, 4))


def test_the_command_is_dry_without_write(tmp_path, monkeypatch):
    make_data(tmp_path)
    monkeypatch.setenv(DATA_ROOT_ENV, str(tmp_path))
    result = CliRunner().invoke(app, ["lyrics", "credit-check"])
    assert result.exit_code == 0, result.output
    assert "credited: 3, by a split name: 1" in result.output
    assert "uncredited (rows out): 2" in result.output
    assert "left out, not in the newest dump: 1" in result.output
    assert "TGO\t2\t7\t1\t1" in result.output
    assert "dry run: nothing written" in result.output
    assert paths.latest_clean_uncredited_songs_dir(tmp_path) is None
