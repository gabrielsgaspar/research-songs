"""The rule that marks the songs whose text another song of the country has."""

from datetime import date
from pathlib import Path

import pandas as pd
import pytest
from typer.testing import CliRunner

from songs.cli import app
from songs.common import manifests, paths, schemas, sync
from songs.common.paths import DATA_ROOT_ENV
from songs.stage_10_clean import text_copies
from songs.stage_50_analysis import eligible_songs

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
    ("TGO", "o2", "o1", "same_text"),
    ("TGO", "o4", "o3", "same_text"),
]


def make_country(data: Path, iso3: str, rows: list[dict]) -> Path:
    folder = paths.country_songs_dir(data, iso3, LATER)
    folder.mkdir(parents=True)
    table = schemas.COUNTRY_SONGS
    names = [column.name for column in table.all_columns]
    frame = pd.DataFrame([row | {"country_iso3": iso3} for row in rows]).reindex(columns=names)
    schemas.write_table(table, schemas.cast_to_schema(table, frame), folder)
    (folder / paths.MANIFEST_NAME).write_text("{}\n", encoding="utf-8")
    if paths.latest_clean_song_quarantine_dir(data) is None:
        quarantine = paths.clean_song_quarantine_dir(data, "20260101")
        quarantine.mkdir(parents=True)
        columns = ",".join(eligible_songs.QUARANTINE_COLUMNS)
        (quarantine / manifests.SONG_QUARANTINE_FILE).write_text(f"{columns}\n", encoding="utf-8")
        manifests.write_manifest(data, quarantine, "clean_song_quarantine", inputs=["z"])
    return folder


def test_a_song_that_another_rule_leaves_out_does_not_represent_the_group(tmp_path):
    rows = [
        song("o1", "a1", ONE, OLD) | {"year": 1899},
        song("o2", "a1", ONE, OLD) | {"year": 1950, "quality_status": "quarantine"},
        song("o3", "a1", ONE, OLD) | {"year": 1970},
        song("o4", "a1", ONE, OLD) | {"year": 1980},
        # Every older song is left out, so the campaign song represents the group.
        song("o5", "a2", TWO, OLD) | {"re_release": True, "year": 1990},
        song("c1", "a2", TWO, FIRST) | {"year": 1995},
        # Two campaign songs: the one that the rule lets in represents the group.
        song("c2", "a3", THREE, FIRST) | {"quality_status": "quarantine"},
        song("c3", "a3", THREE, LATER),
    ]
    folder = make_country(tmp_path, "TGO", rows)
    found, _ = text_copies.country_copies(folder, "TGO", tmp_path)
    assert {song_id: kept for _, song_id, kept, _ in found} == {
        "o1": "o3",
        "o2": "o3",
        "o4": "o3",
        "o5": "c1",
        "c2": "c3",
    }


def test_a_song_of_any_route_is_marked_and_the_order_chooses_the_kept_song(tmp_path):
    folder = make_country(tmp_path, "TGO", SONGS)
    rows, counts = text_copies.country_copies(folder, "TGO", tmp_path)
    assert rows == EXPECTED
    assert counts == {
        "songs_in": 13,
        "campaign_songs": 9,
        "songs_no_key": 2,
        "same_text": 5,
        "same_artist_start": 1,
        "campaign_copies": 4,
    }


def test_an_older_song_with_no_flag_and_the_earliest_year_represents_the_group(tmp_path):
    rows = [
        song("o1", "a1", ONE, OLD) | {"duplicate_decision": "suppress_duplicate", "year": 1990},
        song("o2", "a1", ONE, OLD) | {"canonical_song_id": "o9", "year": 1990},
        song("o3", "a1", ONE, OLD) | {"re_release": True, "year": 1990},
        song("o4", "a1", ONE, OLD),
        song("o5", "a1", ONE, OLD) | {"year": 1985},
        song("o6", "a1", ONE, OLD) | {"year": 1980, "canonical_song_id": "o6"},
        # A campaign song with a year never takes the place of an eligible older song.
        song("c1", "a1", ONE, FIRST) | {"year": 1970},
        song("o7", "a2", TWO, OLD) | {"duplicate_decision": "suppress_duplicate", "year": 1990},
        song("o8", "a2", TWO, OLD),
        # Of two campaign songs, the year does not decide: the run and the id do.
        song("c3", "a3", THREE, FIRST),
        song("c2", "a3", THREE, FIRST) | {"year": 1990},
    ]
    found, _ = text_copies.country_copies(make_country(tmp_path, "TGO", rows), "TGO", tmp_path)
    kept = {song_id: kept for _, song_id, kept, _ in found}
    assert kept == {
        "o1": "o6",
        "o2": "o6",
        "o3": "o6",
        "o4": "o6",
        "o5": "o6",
        "c1": "o6",
        "o7": "o8",
        "c3": "c2",
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
    rows, _ = text_copies.country_copies(folder, "TGO", tmp_path)
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
        "same_text": 5,
        "same_artist_start": 1,
        "campaign_copies": 4,
        "copies": 6,
    }
    assert result == {"counts": counts, "by_country": {"TGO": (6, 13)}, "folder": None}
    assert not (tmp_path / "clean" / "quality" / "text_copies").exists()

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
    assert "copies (rows out): 6" in result.output
    assert "  same_artist_start: 1" in result.output
    assert "  campaign songs: 4\n  older songs: 2" in result.output
    assert "TGO\t6\t13\t46.2%" in result.output
    assert "dry run: nothing written" in result.output
    assert "invented" not in result.output
    assert paths.latest_clean_text_copies_dir(tmp_path) is None
    result = CliRunner().invoke(app, ["lyrics", "copy-check", "--write"])
    assert result.exit_code == 0, result.output
    assert paths.latest_clean_text_copies_dir(tmp_path) is not None
