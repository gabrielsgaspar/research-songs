"""The comparison of a dump with the songs of a country, on small invented tables."""

from pathlib import Path

import duckdb
import pandas as pd
from typer.testing import CliRunner

from songs.cli import app
from songs.common import manifests, paths, run_records, schemas
from songs.common.paths import DATA_ROOT_ENV
from songs.stage_00_ingest.dump_match import (
    import_dump,
    loose_key,
    match_discogs,
    match_dump,
    name_key,
)

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


def make_folders(data: Path, source: str = "example") -> tuple[Path, Path]:
    dump = paths.clean_dump_dir(data, source, "20260102")
    country = paths.country_songs_dir(data, "ISL", RUN)
    write(
        schemas.DUMP_SONGS,
        dump,
        [
            row | {"source": source}
            for row in [
                credit("d1", "Someone Else", "Any Title", "h1"),
                credit("d2", "ÁNNA Jóns", "Sól, sól!", "h2"),
                credit("d3", "Anna Jons", "A New Song", "h3"),
                credit("d4", "AJ", "Another New Song", "h4", artist_id="x4"),
                credit("d5", "Unknown Band", "Far Away", "h5"),
                credit("d6", "Anna Jons", "!!!", "h6"),
                credit("d7", "Unknown Band", "Duet", "h7", 1),
                credit("d7", "Anna Jons", "Duet", "h7", 2),
                credit("d8", "...", "Lost Title", "h8"),
            ]
        ],
    )
    write(
        schemas.DUMP_ARTIST_NAMES,
        dump,
        [
            {
                "source": source,
                "source_artist_id": "x4",
                "artist_name": "AJ",
                "name_type": "primary",
            },
            {
                "source": source,
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
    write(
        schemas.COUNTRY_ARTISTS,
        country,
        [artist("a1", "Anna Jóns") | {"discogs_artist_id": "11"}, artist("a2", "Bára")],
    )
    write(schemas.COUNTRY_LINKS, country, [])
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


def write_discogs(folder: Path) -> None:
    """Invented Discogs tables with the column names of the Discogs dump."""
    folder.mkdir(parents=True)
    tables = {
        "release_artists": "SELECT * FROM (VALUES (100, 11), (200, 11), (900, 11)) "
        "AS t(release_id, artist_id)",
        "release_track_artists": "SELECT * FROM (VALUES (300, 2, 11)) "
        "AS t(release_id, track_index, artist_id)",
        "release_tracklist": "SELECT * FROM (VALUES (100, 1, 'Sól Sól'), "
        "(100, 2, 'Morning Light (Remix)'), (200, 1, 'Sól, sól!'), (200, 2, 'Riverside'), "
        "(300, 1, 'Other Artist Song'), (300, 2, 'Night Train'), (900, 1, 'Old Song'), "
        "(200, 3, 'A New Song'), (100, 3, 'Duet (Radio Edit)')) "
        "AS t(release_id, track_index, title)",
        "releases": "SELECT * FROM (VALUES (100, 50, '1999-05-00'), (200, NULL, '1995'), "
        "(300, NULL, '2001'), (900, NULL, '1990')) AS t(release_id, master_id, released)",
        "masters": "SELECT * FROM (VALUES (50, 1997)) AS t(master_id, year)",
    }
    for name, sql in tables.items():
        duckdb.sql(sql).write_parquet(str(folder / f"{name}.parquet"))


def test_match_discogs_finds_the_earliest_track_of_each_step(tmp_path):
    country = tmp_path / "country"
    write(
        schemas.COUNTRY_ARTISTS,
        country,
        [artist("a1", "Anna Jóns") | {"discogs_artist_id": "11"}, artist("a2", "Bára")],
    )
    link = {"country_iso3": "ISL", "song_id": "s1", "artist_id": "a1", "source": "invented"}
    write(
        schemas.COUNTRY_LINKS,
        country,
        [link | {"discogs_release_id": "900", "discogs_track_index": "1", "run_id": RUN}],
    )
    write_discogs(tmp_path / "discogs")

    def song(song_id, title, artists=("a1",), kind="roster_new"):
        return {
            "source_song_id": song_id,
            "class": kind,
            "song_name": title,
            "roster_artist_ids": list(artists),
        }

    songs = [
        song("exact", "Sol sol"),
        song("loose", "Morning Light"),
        song("close", "Riversde"),
        song("track_credit", "Night Train (feat. Someone)"),
        song("linked", "Old Song"),
        song("taken", "SOL SOL"),
        song("none", "Other Artist Song"),
        song("no_discogs_id", "Sol sol", ("a2",)),
        song("two_artists", "Sol sol", ("a1", "a2")),
        song("held", "Sol sol", kind="held"),
    ]
    rows = {
        row["source_song_id"]: row for row in match_discogs(songs, country, tmp_path / "discogs")
    }
    assert {key: row["discogs_class"] for key, row in rows.items()} == {
        "exact": "exact",
        "loose": "loose",
        "close": "close",
        "track_credit": "loose",
        "linked": "already_linked",
        "taken": "track_taken",
        "none": "no_track",
        "no_discogs_id": "out_of_scope",
        "two_artists": "out_of_scope",
    }
    assert (rows["exact"]["discogs_release_id"], rows["exact"]["year"]) == ("200", 1995)
    assert rows["exact"]["match_method"] == "dump_discogs_exact_title"
    assert (rows["loose"]["discogs_title"], rows["loose"]["year"]) == (
        "Morning Light (Remix)",
        1997,
    )
    assert rows["loose"]["match_score"] == 95.0
    assert rows["close"]["discogs_title"] == "Riverside"
    assert rows["close"]["match_score"] == 94.1
    assert rows["track_credit"]["discogs_release_id"] == "300"


def test_loose_key_drops_brackets_and_featuring():
    assert loose_key("Night Train (feat. Someone)") == "night train"
    assert loose_key("Song ft Other") == "song"
    assert loose_key("(Intro)") == "intro"


def test_cli_prints_discogs_matches(tmp_path, monkeypatch):
    dump, country = make_folders(tmp_path)
    for folder in (dump, country):
        (folder / paths.MANIFEST_NAME).write_text("{}", encoding="utf-8")
    write_discogs(tmp_path / "discogs")
    monkeypatch.setenv(DATA_ROOT_ENV, str(tmp_path))
    result = CliRunner().invoke(
        app, ["dumps", "match", "example", "ISL", "--discogs", str(tmp_path / "discogs")]
    )
    assert result.exit_code == 0, result.output
    assert "roster_new songs looked up in Discogs: 3" in result.output
    assert "invented line" not in result.output


def test_import_dump_adds_exact_and_loose_matches_with_links_and_a_run_record(tmp_path):
    data, countries = tmp_path / "data", tmp_path / "countries"
    dump, country = make_folders(data, "kasilyrics")
    manifests.write_manifest(
        data, dump, "clean_dump", source="kasilyrics", inputs=["raw/x/20260101/"]
    )
    manifests.write_manifest(
        data, country, "country_songs", country_iso3="ISL", run_id=RUN, inputs=["lyrics/isl/"]
    )
    write_discogs(tmp_path / "discogs")

    result = import_dump(
        data, "kasilyrics", "ISL", tmp_path / "discogs", discogs_label="test", countries=countries
    )

    out = result["path"]
    assert (result["songs_added"], result["songs"], result["links"]) == (2, 4, 2)
    added = duckdb.sql(
        f"SELECT source_song_id, artist_id, artist_name, year, year_source, route "
        f"FROM '{(out / 'songs.parquet').as_posix()}' WHERE route = 'dump_name' ORDER BY 1"
    ).fetchall()
    assert added == [
        ("d3", "a1", "Anna Jóns", 1995, "discogs", "dump_name"),
        ("d7", "a1", "Anna Jóns", 1997, "discogs", "dump_name"),
    ]
    links = duckdb.sql(
        f"SELECT source_song_id, discogs_release_id, discogs_track_index, match_method "
        f"FROM '{(out / 'links.parquet').as_posix()}' ORDER BY 1"
    ).fetchall()
    assert links == [
        ("d3", "200", "3", "dump_discogs_exact_title"),
        ("d7", "100", "3", "dump_discogs_loose_title"),
    ]
    manifests.read_manifest(out)
    (record,) = run_records.read_run_records("ISL", countries)
    assert (record.route, record.source, record.rows_added) == ("dump_name", "kasilyrics", 2)
    assert record.bulk_file == "clean/dumps/kasilyrics/20260102/"
    assert record.songs_attempted == 8
    assert record.songs_accepted + sum(record.songs_rejected.values()) == record.songs_attempted
    assert record.songs_rejected["no_track"] == 1
