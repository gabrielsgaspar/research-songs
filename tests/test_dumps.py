"""The dump builder, on small invented files. No lyric text from a real song."""

import hashlib
import json
import re
from pathlib import Path

import duckdb
import pandas as pd
import pytest
from typer.testing import CliRunner

from songs.cli import app
from songs.common import manifests, schemas
from songs.common.paths import DATA_ROOT_ENV
from songs.stage_00_ingest import dumps

DAY = "20261118"
RAW = "raw/example/20260101/"
RUNNER = CliRunner()


def write_parquet(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(rows).convert_dtypes()
    duckdb.from_df(frame).write_parquet(str(path))


def write_lists(path: Path, rows: list[dict]) -> None:
    """Write a GeniusRU lyric table. `featured_artists` is a list, not text."""
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect()
    connection.execute(
        """
        CREATE TABLE lyric (
          source_song_key VARCHAR, artist_name VARCHAR, song_name VARCHAR, lyrics VARCHAR,
          song_url VARCHAR, source_artist_id VARCHAR, release_year INTEGER,
          verified_language VARCHAR, imported_at_utc VARCHAR, featured_artists VARCHAR[]
        )
        """
    )
    for row in rows:
        connection.execute(
            "INSERT INTO lyric VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                row["source_song_key"],
                row["artist_name"],
                row["song_name"],
                row["lyrics"],
                row["song_url"],
                row["source_artist_id"],
                row["release_year"],
                row["verified_language"],
                row["imported_at_utc"],
                row["featured_artists"],
            ],
        )
    connection.execute("COPY lyric TO ? (FORMAT parquet)", [path.as_posix()])
    connection.close()


def table(kind: schemas.Table, folder: Path, order: str) -> list[dict]:
    relation = schemas.read_table(kind, folder).order(order)
    return [dict(zip(relation.columns, row, strict=True)) for row in relation.fetchall()]


def build(data: Path, source: str, folder: Path, **kwargs) -> dict:
    return dumps.build_dump(source, folder, RAW, data, day=DAY, **kwargs)


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def song_id_from_url(url: str) -> str:
    return sha(url)[:20]


def test_each_family_is_detected_from_its_signature():
    assert (
        dumps.detect_family(
            {
                "provider_song_id",
                "text_kind",
                "language_label",
                "release_year_raw",
                "retrieved_at_utc",
                "bonus",
            }
        )
        == "site_snapshot"
    )
    assert (
        dumps.detect_family({"source_song_key", "text_kind", "fetched_at_utc", "translation_text"})
        == "balkan_engine"
    )
    assert dumps.detect_family({"track_id", "plain_lyrics", "album_name", "artist_key"}) == "lrclib"
    assert dumps.detect_family({"lyrics", "song_name"}) == ""


def test_a_raw_input_must_be_a_relative_dated_folder():
    assert dumps.check_raw_input("raw/example/20260101") == RAW
    with pytest.raises(dumps.DumpError):
        dumps.check_raw_input("C:/raw/example/20260101/")
    with pytest.raises(dumps.DumpError):
        dumps.check_raw_input("raw/example/../20260101/")


def test_held_back_sources_match_the_old_lists():
    held = dumps.load_held_back()
    skipped = sorted(source for source, row in held.items() if not row.build)
    assert skipped == ["beesona", "cuspajz", "hmpu_uy", "pesmarica"]
    assert held["geniusru"].build and "HTTP" in held["geniusru"].reason
    assert held["aghanilyrics"].reason == "mirror of SongNu"
    assert held["joinmyjam"].build and "chord" in held["joinmyjam"].reason
    assert held["hebrew_lyrics_hf"].build
    assert held["tab4u"].build and held["turkish_folk_kaggle"].build


def test_an_empty_dump_on_the_list_is_not_written(tmp_path):
    result = dumps.build_dump("beesona", tmp_path / "missing", RAW, tmp_path, day=DAY)
    assert result["skipped"] and result["reason"] == "no lyric rows"
    assert not (tmp_path / "clean").exists()


def test_site_snapshot_maps_columns_and_drops_rows(tmp_path):
    folder = tmp_path / "in"
    lyric = {
        "provider_song_id": "s1",
        "text_kind": "lyrics",
        "language_label": "en",
        "release_year_raw": "1999",
        "retrieved_at_utc": "2026-09-18T19:47:53.123456+00:00",
        "song_url": "https://songs.example/s1",
        "artist_name": "Page Printed",
        "artist_url": "https://artists.example/page",
        "song_name": "Song One",
        "lyrics": "invented line a",
        "album_name": "Album One",
        "raw_path": "raw/example/20260101/pages/a",
        "parser_error": None,
        "http_status": 200,
        "provider": "other",
        "bonus": "ignored",
    }
    write_parquet(
        folder / "example_lyrics.parquet",
        [
            lyric,
            lyric | {"lyrics": "x"},
            lyric
            | {
                "provider_song_id": "s2",
                "text_kind": "translation",
                "lyrics": "invented translation",
            },
            lyric | {"provider_song_id": "s3", "lyrics": "  "},
            lyric
            | {"provider_song_id": "s4", "parser_error": "bad page", "lyrics": "invented line b"},
            lyric | {"provider_song_id": "s5", "http_status": 404, "lyrics": "invented line c"},
            lyric | {"provider_song_id": "s6", "song_name": "  ", "lyrics": "invented line d"},
            lyric
            | {
                "provider_song_id": "s7",
                "artist_name": None,
                "lyrics": "invented line e",
            },
            lyric
            | {
                "provider_song_id": "s8",
                "artist_name": "Page Band",
                "release_year_raw": "1800",
                "retrieved_at_utc": "2026-10-01T10:00:00+02:00",
                "raw_path": "C:/nope/a",
                "lyrics": "invented line h",
                "album_name": None,
                "language_label": None,
            },
            lyric
            | {
                "provider_song_id": None,
                "song_url": "https://songs.example/z",
                "artist_name": "Url Band",
                "lyrics": "invented line z",
            },
        ],
    )
    write_parquet(
        folder / "example_artist_songs.parquet",
        [
            {
                "artist_key": "k1",
                "provider_song_id": "s1",
                "song_url": "https://songs.example/s1",
                "credit_position": 5,
                "credit_role": "performer",
                "credit_raw": "Band One raw",
                "artist_url": "https://artists.example/one",
            },
            {
                "artist_key": "k2",
                "provider_song_id": "s1",
                "song_url": "https://songs.example/s1",
                "credit_position": 9,
                "credit_role": "Performer",
                "credit_raw": "Second raw",
                "artist_url": "https://artists.example/two",
            },
            {
                "artist_key": "k3",
                "provider_song_id": "s1",
                "song_url": "https://songs.example/s1",
                "credit_position": 1,
                "credit_role": "lyricist",
                "credit_raw": "Writer",
                "artist_url": "https://artists.example/writer",
            },
        ],
    )
    write_parquet(
        folder / "example_artists.parquet",
        [
            {
                "artist_key": "k1",
                "artist_name": "Band One",
                "artist_url": "https://artists.example/one",
            },
            {
                "artist_key": "k2",
                "artist_name": "Second",
                "artist_url": "https://artists.example/two",
            },
            {
                "artist_key": "k3",
                "artist_name": "Writer",
                "artist_url": "https://artists.example/writer",
            },
        ],
    )
    write_parquet(
        folder / "example_artist_names.parquet",
        [
            {
                "artist_key": "k1",
                "artist_name": "Band One",
                "name_type": "display",
                "name_origin": "printed",
                "artist_url": "https://artists.example/one",
            },
            {
                "artist_key": "k1",
                "artist_name": "Band One Alt",
                "name_type": "alternate",
                "name_origin": "printed",
                "artist_url": "https://artists.example/one",
            },
            {
                "artist_key": "k1",
                "artist_name": "bandone",
                "name_type": "latin_matching_key",
                "name_origin": "derived",
                "artist_url": "https://artists.example/one",
            },
        ],
    )
    data = tmp_path / "data"
    result = build(data, "example", folder)
    out = data / "clean" / "dumps" / "example" / DAY
    songs = table(schemas.DUMP_SONGS, out, "source_song_id, credit_position")
    names = table(schemas.DUMP_ARTIST_NAMES, out, "source_artist_id, artist_name")
    by_id = {}
    for row in songs:
        by_id.setdefault(row["source_song_id"], []).append(row)
    assert [row["artist_name"] for row in by_id["s1"]] == ["Band One", "Second"]
    assert [row["credit_position"] for row in by_id["s1"]] == [1, 2]
    first = by_id["s1"][0]
    assert first["source"] == "example"
    assert first["song_name"] == "Song One"
    assert first["lyrics"] == "invented line a"
    assert first["lyrics_sha256"] == sha("invented line a")
    assert first["language"] == "en"
    assert first["year"] == 1999
    assert first["album"] == "Album One"
    assert first["fetched_utc"] == "2026-09-18T19:47:53Z"
    assert first["raw_ref"] == "raw/example/20260101/pages/a"
    assert first["source_artist_id"] == "k1"
    assert first["song_url"] == "https://songs.example/s1"
    assert "Page Printed" not in {row["artist_name"] for row in songs}
    assert "Writer" not in {row["artist_name"] for row in songs}
    page = by_id["s8"][0]
    assert page["artist_name"] == "Page Band"
    assert page["source_artist_id"] == "Page Band"
    assert page["year"] is None and page["fetched_utc"] is None and page["raw_ref"] is None
    url_id = song_id_from_url("https://songs.example/z")
    assert by_id[url_id][0]["artist_name"] == "Url Band"
    assert result["rows_in"] == 10
    assert result["rows_out"] == 4
    assert result["dropped"] == {
        "duplicate_song": 1,
        "not_lyrics": 1,
        "empty_lyrics": 1,
        "error_page": 2,
        "no_song_name": 1,
        "no_artist": 1,
    }
    assert result["credits_not_performer"] == 1
    assert sum(result["dropped"].values()) == result["rows_in"] - 3
    assert {(row["source_artist_id"], row["artist_name"], row["name_type"]) for row in names} >= {
        ("k1", "Band One", "primary"),
        ("k1", "Band One Alt", "alias"),
        ("k2", "Second", "primary"),
        ("Page Band", "Page Band", "primary"),
    }
    assert "bandone" not in {row["artist_name"] for row in names}
    manifest = manifests.read_manifest(out)
    assert manifest.inputs == [RAW]
    assert manifest.kind == "clean_dump"
    assert manifest.source == "example"
    assert "site_snapshot" in manifest.notes
    assert manifest.counts["rows_out"] == 4
    with pytest.raises(dumps.DumpError, match="already exists"):
        build(data, "example", folder)


def test_a_stop_file_marks_the_crawl_incomplete(tmp_path):
    folder = tmp_path / "in"
    write_parquet(folder / "example_lyrics.parquet", [_lyric("s1")])
    (folder / "STOP").write_text("stop\n", encoding="utf-8")
    data = tmp_path / "data"
    result = build(data, "example", folder)
    manifest = manifests.read_manifest(data / "clean" / "dumps" / "example" / DAY)
    assert result["incomplete"]
    assert "The crawl is incomplete." in manifest.notes


def test_final_build_false_marks_the_crawl_incomplete(tmp_path):
    folder = tmp_path / "in"
    write_parquet(folder / "example_lyrics.parquet", [_lyric("s1")])
    (folder / "latest.json").write_text(
        json.dumps({"final_build": False, "pending_urls": 0}), encoding="utf-8"
    )
    data = tmp_path / "data"
    result = build(data, "example", folder)
    assert result["incomplete"]


def test_a_result_with_no_songs_is_not_written(tmp_path):
    folder = tmp_path / "in"
    write_parquet(folder / "example_lyrics.parquet", [_lyric("s1", text_kind="translation")])
    data = tmp_path / "data"
    result = build(data, "example", folder)
    assert result["skipped"] and result["reason"] == "no lyric rows"
    assert not (data / "clean").exists()


def test_two_thousand_invented_rows_stream_through_duckdb(tmp_path):
    folder = tmp_path / "in"
    write_parquet(
        folder / "example_lyrics.parquet", [_lyric(f"s{number}") for number in range(2000)]
    )
    data = tmp_path / "data"
    result = build(data, "example", folder)
    assert result["rows_in"] == 2000
    assert result["rows_out"] == 2000
    assert result["family"] == "site_snapshot"


def test_letras_uses_the_printed_name_and_not_the_artist_key(tmp_path):
    folder = tmp_path / "in"
    write_parquet(
        folder / "letras_lyrics.parquet",
        [
            {
                "source_song_key": "L1",
                "raw_offset": 10,
                "retrieved_at_utc": "2026-01-02T03:04:05Z",
                "song_url": "https://songs.example/l1",
                "artist_name": "Letras Band",
                "song_name": "Letras Song",
                "lyrics": "invented line l",
                "source_artist_key": "normalized-key",
                "quality_status": "ok",
            },
            {
                "source_song_key": "L2",
                "raw_offset": 11,
                "retrieved_at_utc": "2026-01-02T03:04:05Z",
                "song_url": "https://songs.example/l2",
                "artist_name": "Quiet",
                "song_name": "Empty",
                "lyrics": "",
                "source_artist_key": "other-key",
            },
        ],
    )
    data = tmp_path / "data"
    result = build(data, "letras", folder)
    songs = table(schemas.DUMP_SONGS, _out(data, "letras"), "source_song_id")
    assert result["family"] == "letras"
    assert len(songs) == 1
    assert songs[0]["source_song_id"] == "L1"
    assert songs[0]["artist_name"] == "Letras Band"
    assert songs[0]["source_artist_id"] == "Letras Band"
    assert songs[0]["source_artist_id"] != "normalized-key"
    assert songs[0]["fetched_utc"] == "2026-01-02T03:04:05Z"
    assert result["dropped"]["empty_lyrics"] == 1


def test_stixoi_keeps_performers_and_one_album(tmp_path):
    folder = tmp_path / "in"
    write_parquet(
        folder / "stixoi_lyrics.parquet",
        [
            {
                "provider_song_id": "g1",
                "provider_url": "https://songs.example/g1",
                "title": "Greek Song",
                "release_year": "2001",
                "language": "el",
                "lyrics": "invented line g",
                "parsed_at_utc": "2026-03-04T05:06:07Z",
            },
            {
                "provider_song_id": "g2",
                "provider_url": "https://songs.example/g2",
                "title": "Second Song",
                "release_year": "1890",
                "language": "el",
                "lyrics": "invented line g2",
                "parsed_at_utc": "2026-03-04T05:06:07Z",
            },
        ],
    )
    write_parquet(
        folder / "stixoi_artist_songs.parquet",
        [
            {
                "provider_artist_id": "a1",
                "provider_song_id": "g1",
                "relation_role": "performer",
                "position": 2,
                "artist_name": "Ada",
            },
            {
                "provider_artist_id": "a2",
                "provider_song_id": "g1",
                "relation_role": "lyricist",
                "position": 1,
                "artist_name": "Poe",
            },
            {
                "provider_artist_id": "b1",
                "provider_song_id": "g2",
                "relation_role": "performer",
                "position": 1,
                "artist_name": "Bea",
            },
        ],
    )
    write_parquet(
        folder / "stixoi_artists.parquet",
        [
            {
                "provider_artist_id": "a1",
                "provider_url": "https://artists.example/ada",
                "name": "Ada",
            },
            {
                "provider_artist_id": "b1",
                "provider_url": "https://artists.example/bea",
                "name": "Bea",
            },
        ],
    )
    write_parquet(
        folder / "stixoi_song_albums.parquet",
        [
            {"provider_song_id": "g1", "provider_album_id": "m1"},
            {"provider_song_id": "g2", "provider_album_id": "m1"},
            {"provider_song_id": "g2", "provider_album_id": "m2"},
        ],
    )
    write_parquet(
        folder / "stixoi_albums.parquet",
        [
            {"provider_album_id": "m1", "title": "Only Album"},
            {"provider_album_id": "m2", "title": "Other Album"},
        ],
    )
    data = tmp_path / "data"
    result = build(data, "stixoi", folder)
    songs = table(schemas.DUMP_SONGS, _out(data, "stixoi"), "source_song_id")
    by_id = {row["source_song_id"]: row for row in songs}
    assert result["family"] == "stixoi"
    assert by_id["g1"]["artist_name"] == "Ada"
    assert by_id["g1"]["song_name"] == "Greek Song"
    assert by_id["g1"]["song_url"] == "https://songs.example/g1"
    assert by_id["g1"]["language"] == "el"
    assert by_id["g1"]["year"] == 2001
    assert by_id["g1"]["album"] == "Only Album"
    assert by_id["g1"]["fetched_utc"] == "2026-03-04T05:06:07Z"
    assert by_id["g1"]["source_artist_id"] == "a1"
    assert by_id["g2"]["album"] is None and by_id["g2"]["year"] is None
    assert "Poe" not in {row["artist_name"] for row in songs}
    assert result["credits_not_performer"] == 1


def test_kugeci_reads_labels_and_the_song_index(tmp_path):
    folder = tmp_path / "in"
    write_parquet(
        folder / "kugeci_lyrics.parquet",
        [
            {
                "provider": "kugeci",
                "provider_song_id": "k1",
                "provider_title": "Kugeci Song",
                "site_artist_ids_json": '["id1"]',
                "site_artist_labels_json": '["Label One"]',
                "lyrics_text": "invented line k",
                "has_lyrics": True,
                "parse_state": "parsed",
            },
            {
                "provider": "kugeci",
                "provider_song_id": "k2",
                "provider_title": "Unparsed",
                "site_artist_ids_json": '["id1"]',
                "site_artist_labels_json": '["Label One"]',
                "lyrics_text": "invented line k2",
                "has_lyrics": True,
                "parse_state": "failed",
            },
            {
                "provider": "kugeci",
                "provider_song_id": "k3",
                "provider_title": "Bad Lists",
                "site_artist_ids_json": '["id1", "id2"]',
                "site_artist_labels_json": '["Only One"]',
                "lyrics_text": "invented line k3",
                "has_lyrics": True,
                "parse_state": "parsed",
            },
        ],
    )
    write_parquet(
        folder / "kugeci_song_index.parquet",
        [
            {
                "provider_song_id": "k1",
                "song_url": "https://songs.example/k1",
                "last_attempt_at_utc": "2026-04-05T06:07:08Z",
                "provider_title": "index title",
            }
        ],
    )
    write_parquet(
        folder / "kugeci_artists.parquet",
        [{"site_artist_id": "id1", "site_artist_name": "Label One"}],
    )
    data = tmp_path / "data"
    result = build(data, "kugeci", folder)
    songs = table(schemas.DUMP_SONGS, _out(data, "kugeci"), "source_song_id")
    assert result["family"] == "kugeci"
    assert len(songs) == 1
    assert songs[0]["song_name"] == "Kugeci Song"
    assert songs[0]["artist_name"] == "Label One"
    assert songs[0]["source_artist_id"] == "id1"
    assert songs[0]["song_url"] == "https://songs.example/k1"
    assert songs[0]["fetched_utc"] == "2026-04-05T06:07:08Z"
    assert songs[0]["lyrics"] == "invented line k"
    assert result["dropped"]["not_parsed"] == 1
    assert result["dropped"]["no_artist"] == 1


def test_aama_uses_the_probed_columns_not_the_old_names(tmp_path):
    folder = tmp_path / "in"
    write_parquet(
        folder / "aama_lyrics.parquet",
        [
            {
                "provider_song_id": "a1",
                "song_url": "https://songs.example/a1",
                "song_name": "Real Title",
                "provider_title": "Alt Title",
                "lyrics": "invented line a",
                "lyrics_text": "invented other",
                "fetched_at_utc": "2026-05-06T07:08:09Z",
                "harvest_date": "20260913",
                "artist_name": "Page Name",
                "artist_heading": "Heading",
                "url": "https://wrong.example/a1",
                "title": "Wrong Title",
                "fetched_at": "1999-01-01T00:00:00Z",
                "scrape_status": "complete",
                "aama_artist_key": "page-key",
            },
            {
                "provider_song_id": "a2",
                "song_url": "https://songs.example/a2",
                "song_name": None,
                "provider_title": "From Title",
                "lyrics": None,
                "lyrics_text": "invented line b",
                "fetched_at_utc": "2026-05-06T07:08:09Z",
                "harvest_date": "20260913",
                "artist_name": None,
                "artist_heading": "Heading Band",
                "scrape_status": "complete",
            },
            {
                "provider_song_id": "a3",
                "song_url": "https://songs.example/a3",
                "song_name": "Failed",
                "lyrics": "invented line c",
                "fetched_at_utc": "2026-05-06T07:08:09Z",
                "harvest_date": "20260913",
                "artist_name": "Nobody",
                "scrape_status": "failed",
            },
        ],
    )
    write_parquet(
        folder / "aama_artist_songs.parquet",
        [
            {
                "aama_artist_key": "ka",
                "artist_name": "Band A",
                "artist_url": "https://artists.example/a",
                "song_url": "https://songs.example/a1",
                "provider_song_id": "a1",
            },
            {
                "aama_artist_key": "kb",
                "artist_name": "Band B",
                "artist_url": "https://artists.example/b",
                "song_url": "https://songs.example/a1",
                "provider_song_id": "a1",
            },
        ],
    )
    data = tmp_path / "data"
    result = build(data, "aama", folder)
    songs = table(schemas.DUMP_SONGS, _out(data, "aama"), "source_song_id, artist_name")
    grouped: dict[str, list[dict]] = {}
    for row in songs:
        grouped.setdefault(row["source_song_id"], []).append(row)
    assert result["family"] == "aama_fnanen"
    assert [row["artist_name"] for row in grouped["a1"]] == ["Band A", "Band B"]
    assert grouped["a1"][0]["song_name"] == "Real Title"
    assert grouped["a1"][0]["song_url"] == "https://songs.example/a1"
    assert grouped["a1"][0]["lyrics"] == "invented line a"
    assert grouped["a1"][0]["fetched_utc"] == "2026-05-06T07:08:09Z"
    assert grouped["a1"][0]["source_artist_id"] == "ka"
    assert grouped["a2"][0]["artist_name"] == "Heading Band"
    assert grouped["a2"][0]["song_name"] == "From Title"
    assert grouped["a2"][0]["lyrics"] == "invented line b"
    assert result["dropped"]["error_page"] == 1


def test_balkan_engine_drops_translations(tmp_path):
    folder = tmp_path / "in"
    write_parquet(
        folder / "paroles2chansons_lyrics.parquet",
        [
            {
                "provider": "paroles2chansons",
                "source_song_key": "p1",
                "song_url": "https://songs.example/p1",
                "song_name": "French Song",
                "artist_url": "https://artists.example/band",
                "artist_name": "French Band",
                "lyrics": "invented line p",
                "translation_text": "invented translation",
                "text_kind": "lyrics",
                "fetched_at_utc": "2026-06-07T08:09:10Z",
            },
            {
                "provider": "paroles2chansons",
                "source_song_key": "p2",
                "song_url": "https://songs.example/p2",
                "song_name": "Translated",
                "artist_name": "French Band",
                "lyrics": "invented translation row",
                "translation_text": "invented translation row",
                "text_kind": "translation",
                "fetched_at_utc": "2026-06-07T08:09:10Z",
            },
        ],
    )
    write_parquet(
        folder / "paroles2chansons_artists.parquet",
        [
            {
                "source_artist_key": "fk",
                "artist_url": "https://artists.example/band",
                "artist_name": "French Band",
            }
        ],
    )
    data = tmp_path / "data"
    result = build(data, "paroles2chansons", folder)
    songs = table(schemas.DUMP_SONGS, _out(data, "paroles2chansons"), "source_song_id")
    assert result["family"] == "balkan_engine"
    assert len(songs) == 1
    assert songs[0]["lyrics"] == "invented line p"
    assert songs[0]["source_song_id"] == "p1"
    assert songs[0]["source_artist_id"] == "fk"
    assert songs[0]["language"] is None and songs[0]["year"] is None
    assert result["dropped"]["not_lyrics"] == 1


def test_genius_uses_the_original_columns_and_not_a_name_key(tmp_path):
    folder = tmp_path / "in"
    write_parquet(
        folder / "songs.parquet",
        [
            {
                "song_name": "Genius Song",
                "artist_name": "Genius Band",
                "genius_artist_id": "g-1",
                "year": 1991,
                "lyrics": "invented line genius",
                "genius_song_id": 42,
                "language_cld3": "en",
                "language_ft": "xx",
                "artist_key": "not-this",
                "features": '["Feat Band"]',
            }
        ],
    )
    data = tmp_path / "data"
    result = build(data, "genius", folder)
    songs = table(schemas.DUMP_SONGS, _out(data, "genius"), "credit_position")
    assert result["family"] == "genius"
    assert len(songs) == 1
    assert songs[0]["source_song_id"] == "42"
    assert songs[0]["artist_name"] == "Genius Band"
    assert songs[0]["source_artist_id"] == "g-1"
    assert songs[0]["language"] == "en"
    assert songs[0]["year"] == 1991
    assert songs[0]["song_url"] is None
    assert songs[0]["album"] is None
    names = table(schemas.DUMP_ARTIST_NAMES, _out(data, "genius"), "artist_name")
    assert names[0]["source_artist_id"] == "g-1"
    assert "not-this" not in {row["source_artist_id"] for row in names}


@pytest.mark.parametrize(
    "updated_at",
    ["2026-08-07 12:00:00", pd.Timestamp("2026-08-07 12:00:00")],
    ids=["text", "timestamp"],
)
def test_lrclib_does_not_copy_keys(tmp_path, updated_at):
    folder = tmp_path / "in"
    write_parquet(
        folder / "lrclib_lyrics.parquet",
        [
            {
                "track_id": 7,
                "name": "Title Seven",
                "artist_name": "Ada",
                "album_name": "Album Seven",
                "plain_lyrics": "invented line lrclib",
                "updated_at": updated_at,
                "artist_key": "bad-key",
                "title_key": "bad-title",
            },
            {
                "track_id": 8,
                "name": "Blank",
                "artist_name": "Ada",
                "album_name": "Album",
                "plain_lyrics": " ",
                "updated_at": updated_at,
                "artist_key": "bad-key",
                "title_key": "bad-title",
            },
        ],
    )
    data = tmp_path / "data"
    result = build(data, "lrclib", folder)
    songs = table(schemas.DUMP_SONGS, _out(data, "lrclib"), "source_song_id")
    assert result["family"] == "lrclib"
    assert len(songs) == 1
    assert songs[0]["source_song_id"] == "7"
    assert songs[0]["song_name"] == "Title Seven"
    assert songs[0]["artist_name"] == "Ada"
    assert songs[0]["source_artist_id"] == "Ada"
    assert songs[0]["album"] == "Album Seven"
    assert songs[0]["lyrics"] == "invented line lrclib"
    assert songs[0]["fetched_utc"] == "2026-08-07T12:00:00Z"
    assert songs[0]["song_url"] is None
    assert songs[0]["source_artist_id"] != "bad-key"
    manifest = manifests.read_manifest(_out(data, "lrclib"))
    assert {entry["path"] for entry in manifest.files} == {"songs.parquet", "artist_names.parquet"}


def test_central_asia_uses_song_rows_and_credit_rows(tmp_path):
    folder = tmp_path / "in"
    write_parquet(
        folder / "uztext_lyrics.parquet",
        [
            {
                "site": "uztext",
                "provider_song_id": "u1",
                "song_url": "https://songs.example/u1",
                "artist_name": "Page",
                "artist_credits": "ignored text",
                "song_name": "Uzbek Song",
                "lyrics": "invented line u",
                "lyrics_text": "invented other",
                "fetched_at_utc": "2026-07-08T09:10:11Z",
                "is_song_page": True,
            },
            {
                "site": "uztext",
                "provider_song_id": "u2",
                "song_url": "https://songs.example/u2",
                "artist_name": "Page",
                "artist_credits": "x",
                "song_name": "Not a song",
                "lyrics": "invented line u2",
                "lyrics_text": "invented line u2",
                "fetched_at_utc": "2026-07-08T09:10:11Z",
                "is_song_page": False,
            },
        ],
    )
    write_parquet(
        folder / "uztext_artist_songs.parquet",
        [
            {
                "artist_key": "uk1",
                "provider_song_id": "u1",
                "song_url": "https://songs.example/u1",
                "artist_name": "Uzbek A",
                "credit_position": 1,
            },
            {
                "artist_key": "uk2",
                "provider_song_id": "u1",
                "song_url": "https://songs.example/u1",
                "artist_name": "Uzbek B",
                "credit_position": 2,
            },
        ],
    )
    data = tmp_path / "data"
    result = build(data, "uztext", folder)
    songs = table(schemas.DUMP_SONGS, _out(data, "uztext"), "credit_position")
    assert result["family"] == "central_asia"
    assert [row["artist_name"] for row in songs] == ["Uzbek A", "Uzbek B"]
    assert songs[0]["lyrics"] == "invented line u"
    assert songs[0]["source_artist_id"] == "uk1"
    assert result["dropped"]["not_song"] == 1


def test_corpus_import_keeps_performers_and_a_year(tmp_path):
    folder = tmp_path / "in"
    write_parquet(
        folder / "giitaayan_lyrics.parquet",
        [
            {
                "provider": "giitaayan",
                "source_record_id": "rec-1",
                "provider_song_id": "c1",
                "artist_name": "Page Singer",
                "song_name": "Corpus Song",
                "song_url": "https://songs.example/c1",
                "lyrics": "invented line c",
                "source_singer_credit": "Other Credit",
                "source_year": 1988,
                "import_eligible": True,
            },
            {
                "provider": "giitaayan",
                "source_record_id": "rec-2",
                "provider_song_id": "c2",
                "artist_name": None,
                "song_name": "Solo Song",
                "song_url": "https://songs.example/c2",
                "lyrics": "invented line c2",
                "source_singer_credit": "Solo",
                "source_year": 1970,
                "import_eligible": True,
            },
            {
                "provider": "giitaayan",
                "source_record_id": "rec-3",
                "provider_song_id": "c3",
                "artist_name": "No",
                "song_name": "Held",
                "lyrics": "invented line c3",
                "source_singer_credit": "No",
                "source_year": 1970,
                "import_eligible": False,
            },
        ],
    )
    write_parquet(
        folder / "giitaayan_artist_songs.parquet",
        [
            {
                "provider_song_id": "c1",
                "credit_role": "performer",
                "credit_order": 1,
                "artist_name": "Singer",
            },
            {
                "provider_song_id": "c1",
                "credit_role": "composer",
                "credit_order": 2,
                "artist_name": "Composer",
            },
        ],
    )
    data = tmp_path / "data"
    result = build(data, "giitaayan", folder)
    songs = table(schemas.DUMP_SONGS, _out(data, "giitaayan"), "source_song_id")
    by_id = {row["source_song_id"]: row for row in songs}
    assert result["family"] == "corpus_import"
    assert by_id["c1"]["artist_name"] == "Singer"
    assert by_id["c1"]["year"] == 1988
    assert by_id["c2"]["artist_name"] == "Solo"
    assert by_id["c2"]["source_song_id"] == "c2"
    assert "Composer" not in {row["artist_name"] for row in songs}
    assert result["dropped"]["not_eligible"] == 1
    assert result["credits_not_performer"] == 1


def test_russian_dump_uses_the_fallback_columns(tmp_path):
    folder = tmp_path / "in"
    write_parquet(
        folder / "lyrics.parquet",
        [
            {
                "source_song_id": "r1",
                "source_url": "https://songs.example/r1",
                "song_title": "Russian Song",
                "song_name": None,
                "song_url": None,
                "artist": "Russian Band",
                "artist_name": None,
                "lyrics": "invented line r",
                "fetched_at_utc": "2026-02-03T04:05:06Z",
            }
        ],
    )
    data = tmp_path / "data"
    result = build(data, "tekstpesni", folder)
    songs = table(schemas.DUMP_SONGS, _out(data, "tekstpesni"), "source_song_id")
    assert result["family"] == "russian_dump"
    assert songs[0]["song_name"] == "Russian Song"
    assert songs[0]["artist_name"] == "Russian Band"
    assert songs[0]["song_url"] == "https://songs.example/r1"
    assert songs[0]["source_artist_id"] == "Russian Band"
    assert songs[0]["fetched_utc"] == "2026-02-03T04:05:06Z"


def test_genius_ru_keeps_performers_and_featured_names(tmp_path):
    folder = tmp_path / "in"
    write_lists(
        folder / "lyrics.parquet",
        [
            {
                "source_song_key": "ru1",
                "artist_name": "Main Band",
                "song_name": "Russian Genius",
                "lyrics": "invented line ru",
                "song_url": "https://songs.example/ru1",
                "source_artist_id": "main-id",
                "release_year": 2004,
                "verified_language": "ru",
                "imported_at_utc": "2026-09-01T00:00:00Z",
                "featured_artists": ["Feat One"],
            }
        ],
    )
    write_parquet(
        folder / "song_artist.parquet",
        [
            {
                "source_song_key": "ru1",
                "source_artist_key": "m1",
                "artist_name": "Main Band",
                "credit_role": "performer",
                "credit_order": 1,
            },
            {
                "source_song_key": "ru1",
                "source_artist_key": "p1",
                "artist_name": "Poet",
                "credit_role": "lyricist",
                "credit_order": 2,
            },
        ],
    )
    data = tmp_path / "data"
    result = build(data, "geniusru", folder)
    songs = table(schemas.DUMP_SONGS, _out(data, "geniusru"), "credit_position")
    assert result["family"] == "genius_ru"
    assert [row["artist_name"] for row in songs] == ["Main Band", "Feat One"]
    assert songs[0]["source_artist_id"] == "m1"
    assert songs[1]["source_artist_id"] == "Feat One"
    assert songs[0]["language"] == "ru" and songs[0]["year"] == 2004
    assert result["credits_not_performer"] == 1
    assert dumps.load_held_back()["geniusru"].build


def test_the_command_writes_a_dump(tmp_path, monkeypatch):
    folder = tmp_path / "in"
    write_parquet(folder / "example_lyrics.parquet", [_lyric("s1")])
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv(DATA_ROOT_ENV, str(data))
    result = RUNNER.invoke(app, ["dumps", "build", "example", str(folder), RAW, "--day", DAY])
    assert result.exit_code == 0, result.output
    assert "wrote clean/dumps/example/20261118/" in result.output
    assert "invented" not in result.output
    assert manifests.read_manifest(data / "clean" / "dumps" / "example" / DAY).source == "example"


def test_balkan_engine_keeps_original_and_poem_text_and_drops_the_rest(tmp_path):
    folder = tmp_path / "in"
    row = {
        "provider": "parolesnet",
        "source_song_key": "b1",
        "song_url": "https://songs.example/b1",
        "song_name": "Original Song",
        "artist_name": "Band",
        "lyrics": "invented original line",
        "translation_text": None,
        "text_kind": "original",
        "fetched_at_utc": "2026-06-07T08:09:10Z",
    }
    write_parquet(
        folder / "parolesnet_lyrics.parquet",
        [
            row,
            row | {"source_song_key": "b4", "text_kind": "source_lyrics_or_poem"},
            row | {"source_song_key": "b2", "text_kind": "translation", "lyrics": "invented t"},
            row | {"source_song_key": "b3", "text_kind": "missing", "lyrics": "invented m"},
        ],
    )
    data = tmp_path / "data"
    result = build(data, "parolesnet", folder)
    out = _out(data, "parolesnet")
    songs = table(schemas.DUMP_SONGS, out, "source_song_id")
    assert [song["source_song_id"] for song in songs] == ["b1", "b4"]
    assert result["dropped"] == {"not_lyrics": 2}
    assert result["not_lyrics_kinds"] == {"missing": 1, "translation": 1}
    counts = manifests.read_manifest(out).counts
    assert counts["dropped_not_lyrics_missing"] == 1
    assert counts["dropped_not_lyrics_translation"] == 1


def test_lyrics_or_poem_rows_are_dropped_with_their_own_count(tmp_path):
    folder = tmp_path / "in"
    write_parquet(
        folder / "tarab_hf_lyrics.parquet",
        [
            _lyric("s1"),
            _lyric("s2", text_kind="lyrics_or_poem"),
            _lyric("s3", text_kind="Chord Sheet"),
        ],
    )
    data = tmp_path / "data"
    result = build(data, "tarab_hf", folder)
    counts = manifests.read_manifest(_out(data, "tarab_hf")).counts
    assert result["rows_out"] == 1
    assert counts["dropped_not_lyrics"] == 2
    assert counts["dropped_not_lyrics_lyrics_or_poem"] == 1
    assert counts["dropped_not_lyrics_chord_sheet"] == 1


def test_site_snapshot_year_falls_back_to_album_year_then_date(tmp_path):
    folder = tmp_path / "in"
    plain = {"release_year_raw": None, "album_release_year_raw": None, "release_date_raw": None}
    write_parquet(
        folder / "example_lyrics.parquet",
        [
            _lyric("s1") | plain | {"release_year_raw": "1999", "album_release_year_raw": "2001"},
            _lyric("s2") | plain | {"release_year_raw": "1200", "album_release_year_raw": "2001"},
            _lyric("s3") | plain | {"album_release_year_raw": "1987.0"},
            _lyric("s4") | plain | {"release_date_raw": "12 May 1975"},
            _lyric("s5") | plain | {"release_date_raw": "words: 1950, music: 1952"},
            _lyric("s6") | plain | {"release_date_raw": "3/4/19750"},
            _lyric("s7") | plain,
        ],
    )
    data = tmp_path / "data"
    build(data, "example", folder)
    songs = table(schemas.DUMP_SONGS, _out(data, "example"), "source_song_id")
    found = {song["source_song_id"]: (song["year"], song["year_source"]) for song in songs}
    assert found == {
        "s1": (1999, "release_year"),
        "s2": (2001, "album_release_year"),
        "s3": (1987, "album_release_year"),
        "s4": (1975, "release_date"),
        "s5": (None, None),
        "s6": (None, None),
        "s7": (None, None),
    }


def test_a_family_with_one_year_column_names_it(tmp_path):
    folder = tmp_path / "in"
    write_parquet(
        folder / "example_lyrics.parquet",
        [
            {
                "source_record_id": "r1",
                "provider_song_id": "c1",
                "artist_name": "Singer",
                "song_name": "Corpus Song",
                "lyrics": "invented corpus line",
                "source_year": 1970,
                "source_singer_credit": "Singer",
            }
        ],
    )
    data = tmp_path / "data"
    build(data, "example", folder)
    songs = table(schemas.DUMP_SONGS, _out(data, "example"), "source_song_id")
    assert (songs[0]["year"], songs[0]["year_source"]) == (1970, "source_year")


def test_a_stop_file_in_the_crawl_folder_marks_a_snapshot_incomplete(tmp_path):
    crawl = tmp_path / "lyrics_dump" / "20261001"
    snapshot = crawl / "snapshots" / "20261002T000000Z"
    write_parquet(snapshot / "example_lyrics.parquet", [_lyric("s1")])
    (crawl / "STOP").write_text("stop\n", encoding="utf-8")
    data = tmp_path / "data"
    result = build(data, "example", snapshot)
    assert result["incomplete"]
    assert "The crawl is incomplete." in manifests.read_manifest(_out(data, "example")).notes


def test_a_credit_with_no_song_key_joins_by_the_song_page(tmp_path):
    folder = tmp_path / "in"
    write_parquet(folder / "example_lyrics.parquet", [_lyric("s1"), _lyric("s2")])
    write_parquet(
        folder / "example_artist_songs.parquet",
        [
            {
                "artist_key": "k1",
                "provider_song_id": "s1",
                "song_url": "https://songs.example/s1",
                "credit_role": "performer",
                "credit_raw": "By Key",
            },
            {
                "artist_key": "k2",
                "provider_song_id": None,
                "song_url": "https://songs.example/s2",
                "credit_role": "performer",
                "credit_raw": "By Page",
            },
            {
                "artist_key": "k3",
                "provider_song_id": None,
                "song_url": "https://songs.example/s2",
                "credit_role": "composer",
                "credit_raw": "Writer",
            },
        ],
    )
    data = tmp_path / "data"
    result = build(data, "example", folder)
    songs = table(schemas.DUMP_SONGS, _out(data, "example"), "source_song_id")
    assert {(song["source_song_id"], song["artist_name"]) for song in songs} == {
        ("s1", "By Key"),
        ("s2", "By Page"),
    }
    assert result["credits_not_performer"] == 1


def test_no_builder_view_joins_on_a_condition_with_or(tmp_path):
    folder = tmp_path / "in"
    write_parquet(folder / "example_lyrics.parquet", [_lyric("s1")])
    write_parquet(
        folder / "example_artist_songs.parquet",
        [{"artist_key": "k1", "provider_song_id": "s1", "credit_role": "performer"}],
    )
    connection = duckdb.connect()
    lyric = folder / "example_lyrics.parquet"
    columns = set(dumps._columns(connection, lyric))
    family = dumps.FAMILY_BY_NAME[dumps.detect_family(columns)]
    dumps._prepare(connection, folder, "example", family, lyric, columns)
    views = connection.execute(
        "SELECT view_name, sql FROM duckdb_views() WHERE NOT internal"
    ).fetchall()
    on_with_or = re.compile(
        r"\bON\b(?:(?!\b(?:WHERE|JOIN|UNION|GROUP|SELECT)\b).)*?\bOR\b", re.S | re.I
    )
    assert views
    assert [name for name, sql in views if on_with_or.search(sql)] == []


def _out(data: Path, source: str) -> Path:
    return data / "clean" / "dumps" / source / DAY


def _lyric(song_id: str, **over) -> dict:
    return {
        "provider_song_id": song_id,
        "text_kind": "lyrics",
        "language_label": "en",
        "release_year_raw": "1999",
        "retrieved_at_utc": "2026-01-01T00:00:00Z",
        "song_url": f"https://songs.example/{song_id}",
        "artist_name": "Band",
        "song_name": "Song",
        "lyrics": f"invented line {song_id}",
    } | over
