"""The comparison of a dump with the songs of a country, on small invented tables."""

from pathlib import Path

import pandas as pd
from typer.testing import CliRunner

from songs.cli import app
from songs.common import paths, schemas
from songs.common.paths import DATA_ROOT_ENV
from songs.stage_00_ingest.dump_match import match_dump, name_key

RUN = "20260101T000000Z"


def write(table: schemas.Table, folder: Path, rows: list[dict]) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    names = [column.name for column in table.all_columns]
    schemas.write_table(
        table, schemas.cast_to_schema(table, pd.DataFrame(rows).reindex(columns=names)), folder
    )


def credit(song_id: str, artist: str, title: str, sha: str, position: int = 1, **over) -> dict:
    return {
        "source": "example",
        "source_song_id": song_id,
        "artist_name": artist,
        "source_artist_id": over.get("artist_id", artist),
        "credit_position": position,
        "song_name": title,
        "lyrics": "invented line",
        "lyrics_sha256": sha,
    }


def held(song_id: str, artist_id: str, artist: str, title: str, sha: str) -> dict:
    return {
        "country_iso3": "ISL",
        "song_id": song_id,
        "artist_id": artist_id,
        "artist_name": artist,
        "song_name": title,
        "source": "invented",
        "lyrics": "invented line",
        "lyrics_sha256": sha,
        "route": "old_layout",
        "run_id": RUN,
    }


def artist(artist_id: str, name: str) -> dict:
    return {
        "country_iso3": "ISL",
        "artist_id": artist_id,
        "artist_name": name,
        "attempted": True,
        "songs": 1,
    }


def make_folders(data: Path) -> tuple[Path, Path]:
    dump = paths.clean_dump_dir(data, "example", "20260102")
    country = paths.country_songs_dir(data, "ISL", RUN)
    write(
        schemas.DUMP_SONGS,
        dump,
        [
            credit("d1", "Someone Else", "Any Title", "h1"),
            credit("d2", "ÁNNA Jóns", "Sól, sól!", "h2"),
            credit("d3", "Anna Jons", "A New Song", "h3"),
            credit("d4", "AJ", "Another New Song", "h4", artist_id="x4"),
            credit("d5", "Unknown Band", "Far Away", "h5"),
            credit("d6", "Anna Jons", "!!!", "h6"),
            credit("d7", "Unknown Band", "Duet", "h7", 1),
            credit("d7", "Anna Jons", "Duet", "h7", 2),
            credit("d8", "...", "Lost Title", "h8"),
        ],
    )
    write(
        schemas.DUMP_ARTIST_NAMES,
        dump,
        [
            {
                "source": "example",
                "source_artist_id": "x4",
                "artist_name": "AJ",
                "name_type": "primary",
            },
            {
                "source": "example",
                "source_artist_id": "x4",
                "artist_name": "Anna Jóns",
                "name_type": "alias",
            },
        ],
    )
    write(
        schemas.COUNTRY_SONGS,
        country,
        [
            held("s1", "a1", "Anna Jons", "Old Song", "h1"),
            held("s2", "a1", "Anna Jons", "Sol sol", "other"),
        ],
    )
    write(schemas.COUNTRY_ARTISTS, country, [artist("a1", "Anna Jóns"), artist("a2", "Bára")])
    return dump, country


def test_name_key_folds_case_accents_and_marks():
    assert name_key("  ÁNNA  Jóns!! ") == "anna jons"
    assert name_key("Sól, sól!") == "sol sol"
    assert name_key("Þór & Æsa") == "þor æsa"
    assert name_key(None) == "" and name_key("...") == ""


def test_each_dump_song_counts_once_in_one_class(tmp_path):
    result = match_dump(*make_folders(tmp_path))
    by_id = {row["source_song_id"]: row for row in result["songs"]}
    assert {song: row["class"] for song, row in by_id.items()} == {
        "d1": "held",
        "d2": "same_title",
        "d3": "roster_new",
        "d4": "roster_new",
        "d5": "not_roster",
        "d7": "roster_new",
    }
    assert by_id["d4"]["roster_artist_ids"] == ["a1"]
    assert result["credit_rows_in"] == 9
    assert result["songs_in"] == 8
    assert result["counts"] == {"held": 1, "same_title": 1, "roster_new": 3, "not_roster": 1}
    assert result["left_out"] == {"no_title_key": 1, "no_artist_key": 1}
    assert result["songs_out"] + sum(result["left_out"].values()) == result["songs_in"]
    assert result["examples"]["not_roster"] == [("Unknown Band", "Far Away")]


def test_cli_prints_counts_and_no_lyrics(tmp_path, monkeypatch):
    dump, country = make_folders(tmp_path)
    for folder in (dump, country):
        (folder / paths.MANIFEST_NAME).write_text("{}", encoding="utf-8")
    monkeypatch.setenv(DATA_ROOT_ENV, str(tmp_path))
    result = CliRunner().invoke(app, ["dumps", "match", "example", "ISL"])
    assert result.exit_code == 0, result.output
    assert "roster_new: 3" in result.output
    assert "left out, no_title_key: 1" in result.output
    assert "invented line" not in result.output
