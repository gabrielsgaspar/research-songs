"""The rule that marks the campaign songs whose text another song of the country has."""

from datetime import date
from pathlib import Path

import pandas as pd
import pytest
from typer.testing import CliRunner

from songs.cli import app
from songs.common import manifests, paths, schemas, sync
from songs.common.paths import DATA_ROOT_ENV
from songs.stage_10_clean import text_copies

OLD, FIRST, LATER = "20260101T000000Z", "20260102T000000Z", "20260103T000000Z"
START = "an invented verse that comes back again " * 10
ONE = "The first invented text of these tests, with its words"
TWO = "A second invented text, which only campaigns hold"
THREE = "a third invented text, two times in one campaign"


def song(song_id: str, artist_id: str, lyrics: str, run_id: str) -> dict:
    return {
        "country_iso3": "TGO",
        "song_id": song_id,
        "artist_id": artist_id,
        "artist_name": "Invented Artist",
        "source": "invented",
        "lyrics_sha256": song_id,
        "lyrics": lyrics,
        "route": "old_layout" if run_id == OLD else "dump_name",
        "run_id": run_id,
    }


SONGS = [
    song("o2", "a2", ONE.upper() + "!", OLD),
    song("o1", "a1", ONE, OLD),
    song("o3", "a1", START + "and an old end", OLD),
    song("o4", "a1", START + "and an old end", OLD),
    # Any artist, the same text: an older song represents the group.
    song("c1", "a3", ONE.lower() + " ...", FIRST),
    # The same artist and the same start.
    song("c2", "a1", START + "and a new end", FIRST),
    # The same start, another artist: no copy.
    song("c3", "a4", START + "and a third end", FIRST),
    song("c4", "a5", TWO, LATER),
    song("c5", "a6", TWO + "?", FIRST),
    song("c7", "a7", THREE, FIRST),
    song("c6", "a7", THREE.title(), FIRST),
    song("c8", "a8", "a short text", FIRST),
    song("c9", "a8", "a short text", FIRST),
]
EXPECTED = [
    ("TGO", "c1", "o1", "same_text"),
    ("TGO", "c2", "o3", "same_artist_start"),
    ("TGO", "c4", "c5", "same_text"),
    ("TGO", "c7", "c6", "same_text"),
]


def make_country(data: Path, iso3: str, rows: list[dict]) -> Path:
    folder = paths.country_songs_dir(data, iso3, LATER)
    folder.mkdir(parents=True)
    table = schemas.COUNTRY_SONGS
    names = [column.name for column in table.all_columns]
    frame = pd.DataFrame([row | {"country_iso3": iso3} for row in rows]).reindex(columns=names)
    schemas.write_table(table, schemas.cast_to_schema(table, frame), folder)
    (folder / paths.MANIFEST_NAME).write_text("{}\n", encoding="utf-8")
    return folder


def test_only_a_campaign_song_is_marked_and_the_order_chooses_the_kept_song(tmp_path):
    folder = make_country(tmp_path, "TGO", SONGS)
    rows, counts = text_copies.country_copies(folder, "TGO")
    assert rows == EXPECTED
    assert counts == {
        "songs_in": 13,
        "campaign_songs": 9,
        "songs_no_key": 2,
        "same_text": 3,
        "same_artist_start": 1,
    }


def test_each_linked_set_of_groups_keeps_one_song(tmp_path):
    # c2 has the text of c1 and the start of c3, of the same artist: c1 stays.
    folder = make_country(
        tmp_path,
        "TGO",
        [
            song("c1", "a1", START + "and one end", FIRST),
            song("c2", "a1", START + "and one end!", FIRST),
            song("c3", "a1", START + "and another end", LATER),
        ],
    )
    rows, _ = text_copies.country_copies(folder, "TGO")
    assert rows == [("TGO", "c2", "c1", "same_text"), ("TGO", "c3", "c1", "same_artist_start")]


def test_a_dry_check_writes_nothing_and_a_write_makes_one_folder(tmp_path):
    folder = make_country(tmp_path, "TGO", SONGS)
    make_country(tmp_path, "BEN", [song("b1", "a1", ONE, FIRST)])
    result = text_copies.check_copies(tmp_path)
    counts = {
        "countries": 2,
        "songs_in": 14,
        "campaign_songs": 10,
        "songs_no_key": 2,
        "same_text": 3,
        "same_artist_start": 1,
        "copies": 4,
    }
    assert result == {"counts": counts, "by_country": {"TGO": (4, 9, 13)}, "folder": None}
    assert not (tmp_path / "clean").exists()

    result = text_copies.check_copies(tmp_path, write=True, today=date(2026, 1, 4))
    out = paths.clean_text_copies_dir(tmp_path, "20260104")
    assert result["folder"] == out == paths.latest_clean_text_copies_dir(tmp_path)
    manifest = manifests.read_manifest(out)
    assert (manifest.kind, manifest.counts) == ("clean_text_copies", counts)
    assert paths.data_relative(tmp_path, folder) in manifest.inputs
    table = schemas.read_table(schemas.TEXT_COPIES, out)
    assert sorted(table.fetchall()) == EXPECTED
    assert out.parent in sync._parents(tmp_path)
    with pytest.raises(FileExistsError, match="never written over"):
        text_copies.check_copies(tmp_path, write=True, today=date(2026, 1, 4))


def test_the_command_is_dry_without_write_and_prints_no_lyrics(tmp_path, monkeypatch):
    make_country(tmp_path, "TGO", SONGS)
    monkeypatch.setenv(DATA_ROOT_ENV, str(tmp_path))
    result = CliRunner().invoke(app, ["lyrics", "copy-check"])
    assert result.exit_code == 0, result.output
    assert "songs in: 13, campaign songs: 9" in result.output
    assert "copies (rows out): 4" in result.output
    assert "  same_artist_start: 1" in result.output
    assert "TGO\t4\t9\t13\t44.4%" in result.output
    assert "dry run: nothing written" in result.output
    assert "invented" not in result.output
    assert paths.latest_clean_text_copies_dir(tmp_path) is None
    result = CliRunner().invoke(app, ["lyrics", "copy-check", "--write"])
    assert result.exit_code == 0, result.output
    assert paths.latest_clean_text_copies_dir(tmp_path) is not None
