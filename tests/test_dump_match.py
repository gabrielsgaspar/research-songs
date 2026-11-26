"""The comparison of a dump with the songs of a country, on small invented tables."""

import os
import unicodedata
from pathlib import Path

import duckdb
import pandas as pd
import pytest
from typer.testing import CliRunner

from songs.cli import app
from songs.common import manifests, paths, run_records, schemas
from songs.common.paths import DATA_ROOT_ENV
from songs.stage_00_ingest import dump_match
from songs.stage_00_ingest.dump_match import (
    by_decade,
    dump_keys,
    gaps,
    import_dump,
    lead_artist,
    load_reviewed_matches,
    loose_key,
    match_discogs,
    match_dump,
    name_key,
    survey,
    would_add,
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
        "lyrics": over.get("lyrics", f"an invented line of text for the tests, song {song_id}"),
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
    # Letters with no accent to drop get their plain letter.
    assert name_key("Işık Đàm Łódź Sørensen") == "isik dam lodz sorensen"
    # A vowel sign stays in its word, so two words with other vowels have two keys.
    assert name_key("कीर") == "कीर"
    assert name_key("की") != name_key("का")
    assert name_key("Night ❤️") == "night"


def test_each_dump_song_counts_once_in_one_class(tmp_path):
    result = match_dump(*make_folders(tmp_path))
    by_id = {row["source_song_id"]: row for row in result["songs"]}
    assert {song: row["class"] for song, row in by_id.items()} == {
        "d1": "held",
        "d2": "same_title",
        "d3": "roster_new",
        "d4": "roster_new",
        "d7": "roster_new",
    }
    assert by_id["d4"]["roster_artist_ids"] == ["a1"]
    assert result["credit_rows_in"] == 9
    assert result["songs_in"] == 8
    assert result["counts"] == {"held": 1, "same_title": 1, "roster_new": 3, "not_roster": 1}
    assert result["left_out"] == {"no_title_key": 1, "no_artist_key": 1, "short_lyrics": 0}
    assert result["songs_out"] + sum(result["left_out"].values()) == result["songs_in"]
    assert result["examples"]["not_roster"] == [("Unknown Band", "Far Away")]


def test_lead_artist_splits_featuring_and_joining_words():
    assert lead_artist("Anna Jons feat. Bára") == "Anna Jons"
    assert lead_artist("Anna Jons (ft. Bára)") == "Anna Jons"
    assert lead_artist("Anna Jons FEATURING Bára, Other") == "Anna Jons"
    assert lead_artist("Anna Jons x Bára") == "Anna Jons"
    assert lead_artist("Anna Jons&Bára") == "Anna Jons"
    assert lead_artist("Anna Jons na Bára") == "Anna Jons"
    assert lead_artist("Anna Jons с Bára") == ""
    assert lead_artist("Malcolm X") == "" and lead_artist("Aftermath") == ""
    assert lead_artist("& Bára") == "" and lead_artist(None) == ""


def test_a_song_of_a_merged_artist_id_reaches_only_its_credited_name(tmp_path):
    _, country = make_folders(tmp_path)
    dump = paths.clean_dump_dir(tmp_path, "example", "20260103")
    merged = ("Nicki Minaj", "Rosa Linn", "KIDZ BOP Kids", "Mura Masa", "Magic System", "Kygo")
    names = [
        {"source_artist_id": "353676", "artist_name": name, "name_type": "primary"}
        for name in (*merged, "Anna Jons")
    ] + [
        {"source_artist_id": "x4", "artist_name": "AJ", "name_type": "primary"},
        {"source_artist_id": "x4", "artist_name": "Anna Jóns", "name_type": "alias"},
    ]
    write(schemas.DUMP_ARTIST_NAMES, dump, [{"source": "example"} | name for name in names])
    write(
        schemas.DUMP_SONGS,
        dump,
        [
            credit("m1", "KIDZ BOP Kids", "Cover Song", "g1", artist_id="353676"),
            credit("m2", "Anna Jons", "Own Song", "g2", artist_id="353676"),
            credit("m3", "AJ", "Alias Song", "g3", artist_id="x4"),
        ],
    )
    result = match_dump(dump, country)
    by_id = {row["source_song_id"]: row["roster_artist_ids"] for row in result["songs"]}
    assert by_id == {"m2": ["a1"], "m3": ["a1"]}


def test_the_lead_of_a_featuring_credit_matches_and_is_counted(tmp_path):
    _, country = make_folders(tmp_path)
    dump = paths.clean_dump_dir(tmp_path, "example", "20260103")
    write(schemas.DUMP_ARTIST_NAMES, dump, [])
    write(
        schemas.DUMP_SONGS,
        dump,
        [
            credit("f1", "Anna Jons feat. Bára", "Brand New", "g1"),
            credit("f2", "Someone ft. Anna Jons", "Other", "g2"),
            credit("f3", "Anna Jons & Unknown", "Sól, sól!", "g3"),
            credit("f4", "Bára x Anna Jons", "Third", "g4"),
            credit("f5", "Anna Jons", "Plain", "g5"),
            credit("f6", "Malcolm X", "Fourth", "g6"),
        ],
    )
    result = match_dump(dump, country)
    by_id = {row["source_song_id"]: row for row in result["songs"]}
    assert {song: (row["class"], row["roster_artist_ids"]) for song, row in by_id.items()} == {
        "f1": ("roster_new", ["a1"]),
        "f3": ("same_title", []),
        "f4": ("roster_new", ["a2"]),
        "f5": ("roster_new", ["a1"]),
    }
    assert result["counts"]["not_roster"] == 2
    assert result["matched_by_split"] == 3
    assert result["roster_new_more_than_one_artist"] == 0


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


def write_discogs(folder: Path, close_title: str = "Another New Song 2") -> None:
    """Invented Discogs tables with the column names of the Discogs dump.

    `close_title` is the track that the dump song "Another New Song" matches by close
    spelling. The default holds a number that the dump title lacks.
    """
    folder.mkdir(parents=True)
    tables = {
        "release_artists": "SELECT * FROM (VALUES (100, 11), (200, 11), (900, 11)) "
        "AS t(release_id, artist_id)",
        "release_track_artists": "SELECT * FROM (VALUES (300, 2, 11)) "
        "AS t(release_id, track_index, artist_id)",
        "release_tracklist": "SELECT * FROM (VALUES (100, 1, 'Sól Sól'), "
        "(100, 2, 'Morning Light (Remix)'), (200, 1, 'Sól, sól!'), (200, 2, 'Riverside'), "
        "(300, 1, 'Other Artist Song'), (300, 2, 'Night Train'), (900, 1, 'Old Song'), "
        f"(200, 3, 'A New Song'), (100, 3, 'Duet (Radio Edit)'), (200, 4, '{close_title}'), "
        "(100, 4, 'Encore'), (100, 5, 'Encore (Live)')) "
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
    # The country holds this song with no link; a longer title of it must not enter again.
    write(schemas.COUNTRY_SONGS, country, [held("h1", "a1", "Anna Jóns", "A New Song", "kh")])
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
        song("two_artists_new", "Duet", ("a2", "a1")),
        song("held", "Sol sol", kind="held"),
        song("held_loose", "A New Song (Live)"),
        song("longer_first", "Encore (Live)"),
        song("shorter_wins", "Encore"),
    ]
    rows = {
        row["source_song_id"]: row
        for row in match_discogs(songs, country, tmp_path / "discogs", "ISL")
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
        "two_artists": "track_taken",
        "two_artists_new": "loose",
        "held_loose": "held_loose_title",
        "longer_first": "held_loose_title",
        "shorter_wins": "exact",
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
    # Of the two roster artists of the song, only a1 has a Discogs id and the track.
    assert rows["two_artists_new"]["roster_artist_id"] == "a1"


def test_a_song_with_a_short_lyric_text_is_left_out(tmp_path):
    _, country = make_folders(tmp_path)
    dump = paths.clean_dump_dir(tmp_path, "short", "20260102")
    write(schemas.DUMP_ARTIST_NAMES, dump, [])
    write(
        schemas.DUMP_SONGS,
        dump,
        [
            credit("d3", "Anna Jons", "A New Song", "h3", lyrics="  no text yet  "),
            credit("d9", "Anna Jons", "Second Song", "h9"),
            credit("d1", "Someone Else", "Any Title", "h1", lyrics="held"),
        ],
    )

    result = match_dump(dump, country)

    # A held song stays held: its hash decides, not its length.
    assert (result["counts"]["roster_new"], result["counts"]["held"]) == (1, 1)
    assert result["left_out"]["short_lyrics"] == 1
    assert result["songs_out"] + sum(result["left_out"].values()) == result["songs_in"]


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
    assert record.songs_rejected["close"] == 1


def test_import_dump_leaves_out_the_songs_of_an_artist_of_another_country(tmp_path):
    data, countries = tmp_path / "data", tmp_path / "countries"
    dump, country = make_folders(data, "kasilyrics")
    manifests.write_manifest(
        data, dump, "clean_dump", source="kasilyrics", inputs=["raw/x/20260101/"]
    )
    manifests.write_manifest(
        data, country, "country_songs", country_iso3="ISL", run_id=RUN, inputs=["lyrics/isl/"]
    )
    write_discogs(tmp_path / "discogs")
    table = paths.clean_artist_country_dir(data, "20260103")
    evidence = {"stated_country": "", "home_word": False, "releases": 0, "releases_home": 0}
    write(
        schemas.ARTIST_COUNTRY,
        table,
        [
            evidence
            | {"country_iso3": code, "artist_id": "a1", "discogs_artist_id": "11"}
            | {"top_release_country": "", "decision": decision}
            for code, decision in (("ISL", schemas.OTHER_COUNTRY), ("NOR", schemas.KEEP))
        ],
    )
    repo = tmp_path / "repo"
    (repo / dump_match.ARTIST_COUNTRIES_FILE).parent.mkdir(parents=True)
    (repo / dump_match.ARTIST_COUNTRIES_FILE).write_text(
        "artist_id,country_iso3\n", encoding="utf-8"
    )
    assert dump_match.other_country_artists(data, "ISL", repo) == (None, frozenset())
    manifests.write_manifest(data, table, "clean_artist_country", inputs=["lyrics/isl/"])
    assert dump_match.other_country_artists(data, "ISL", repo) == (table, frozenset({"a1"}))
    assert dump_match.other_country_artists(data, "NOR", repo) == (table, frozenset())

    (found,) = survey(data, "ISL", ["kasilyrics"], tmp_path / "discogs")
    assert (found["would_add"], found["rejected"]["artist_other_country"]) == (0, 2)
    assert found["would_add"] + sum(found["rejected"].values()) == found["songs_in"]
    result = import_dump(
        data, "kasilyrics", "ISL", tmp_path / "discogs", discogs_label="test", countries=countries
    )
    assert (result["songs_added"], result["songs"]) == (0, 2)
    manifest = manifests.read_manifest(result["path"])
    assert manifest.counts["dump_songs_artist_other_country"] == 2
    assert "Artist countries: clean/quality/artist_country/20260103/." in manifest.notes
    (record,) = run_records.read_run_records("ISL", countries)
    assert record.songs_rejected["artist_other_country"] == 2
    assert record.songs_accepted + sum(record.songs_rejected.values()) == record.songs_attempted


def test_the_tracked_artist_countries_win_over_the_table_in_the_import(tmp_path):
    data = tmp_path / "data"
    table = paths.clean_artist_country_dir(data, "20260103")
    evidence = {"stated_country": "", "home_word": False, "releases": 0, "releases_home": 0}
    write(
        schemas.ARTIST_COUNTRY,
        table,
        [
            evidence
            | {"country_iso3": "ISL", "artist_id": artist, "discogs_artist_id": "11"}
            | {"top_release_country": "", "decision": schemas.OTHER_COUNTRY}
            for artist in ("a1", "a2")
        ],
    )
    manifests.write_manifest(data, table, "clean_artist_country", inputs=["lyrics/isl/"])
    tracked = tmp_path / "repo" / dump_match.ARTIST_COUNTRIES_FILE
    tracked.parent.mkdir(parents=True)
    tracked.write_text("artist_id,country_iso3\na1,ISL\na3,NOR\n", encoding="utf-8")
    folder, other = dump_match.other_country_artists(data, "ISL", root=tmp_path / "repo")
    assert (folder, other) == (table, frozenset({"a2", "a3"}))
    # An artist that the list gives ISL belongs to another country for NOR.
    assert dump_match.other_country_artists(data, "NOR", root=tmp_path / "repo")[1] == {"a1"}


def import_with_review(root: Path, reviewed: dict, close_title: str = "Another New Song 2") -> dict:
    data = root / "data"
    dump, country = make_folders(data, "kasilyrics")
    manifests.write_manifest(
        data, dump, "clean_dump", source="kasilyrics", inputs=["raw/x/20260101/"]
    )
    manifests.write_manifest(
        data, country, "country_songs", country_iso3="ISL", run_id=RUN, inputs=["lyrics/isl/"]
    )
    write_discogs(root / "discogs", close_title)
    return import_dump(
        data,
        "kasilyrics",
        "ISL",
        root / "discogs",
        discogs_label="test",
        countries=root / "countries",
        reviewed=reviewed,
    )


def test_import_dump_adds_a_close_match_only_for_the_reviewed_track(tmp_path):
    other_track = import_with_review(
        tmp_path / "a", {("kasilyrics", "ISL", "d4", "200", "3"): "accept"}
    )
    assert other_track["songs_added"] == 2
    rejected = import_with_review(
        tmp_path / "b", {("kasilyrics", "ISL", "d4", "200", "4"): "reject"}
    )
    assert rejected["songs_added"] == 2
    result = import_with_review(tmp_path / "c", {("kasilyrics", "ISL", "d4", "200", "4"): "accept"})
    assert result["songs_added"] == 3
    method = duckdb.sql(
        f"SELECT match_method FROM '{(result['path'] / 'links.parquet').as_posix()}' "
        "WHERE source_song_id = 'd4'"
    ).fetchall()
    assert method == [("dump_discogs_close_title",)]
    assert manifests.read_manifest(result["path"]).counts["dump_songs_close_accepted"] == 1


def test_import_dump_adds_a_close_match_with_the_same_numbers_unless_a_person_rejects_it(
    tmp_path,
):
    result = import_with_review(tmp_path / "a", {}, close_title="Another New Sng")
    assert result["songs_added"] == 3
    method = duckdb.sql(
        f"SELECT match_method FROM '{(result['path'] / 'links.parquet').as_posix()}' "
        "WHERE source_song_id = 'd4'"
    ).fetchall()
    assert method == [("dump_discogs_close_title",)]
    (record,) = run_records.read_run_records("ISL", tmp_path / "a" / "countries")
    assert "1 close matches added: the titles hold the same numbers" in record.notes
    assert "close" not in record.songs_rejected
    rejected = import_with_review(
        tmp_path / "b",
        {("kasilyrics", "ISL", "d4", "200", "4"): "reject"},
        close_title="Another New Sng",
    )
    assert rejected["songs_added"] == 2


def test_same_numbers_compares_the_numbers_of_two_titles_in_order():
    assert dump_match.same_numbers("Las 7 AM", "Las 7 a.m.")
    assert dump_match.same_numbers("Pobre de mi", "Podre De Mi")
    assert not dump_match.same_numbers("Saludo 2010 (En Vivo)", "Saludo 2004")
    assert not dump_match.same_numbers("03 - Tormenta de mar", "Tormenta De Mar")
    assert not dump_match.same_numbers("Escena 1 y 2", "Escena 2 y 1")


def complete_folders(data: Path) -> Path:
    """Write the dump and the country of `make_folders` with their manifests."""
    dump, country = make_folders(data, "kasilyrics")
    manifests.write_manifest(
        data, dump, "clean_dump", source="kasilyrics", inputs=["raw/x/20260101/"]
    )
    manifests.write_manifest(
        data, country, "country_songs", country_iso3="ISL", run_id=RUN, inputs=["lyrics/isl/"]
    )
    return country


def write_catalog(data: Path) -> str:
    """Write the invented Discogs tables as a complete catalog folder. Return its path."""
    folder = paths.clean_catalog_dir(data, "discogs", "20260101")
    write_discogs(folder)
    manifests.write_manifest(
        data, folder, "clean_catalog", source="discogs", inputs=["raw/discogs/20260101/"]
    )
    return paths.data_relative(data, folder)


def test_the_survey_gives_what_the_import_then_adds_and_writes_nothing(tmp_path):
    data = tmp_path / "data"
    complete_folders(data)
    write_discogs(tmp_path / "discogs")

    def outside() -> list[Path]:
        return sorted(path for path in tmp_path.rglob("*") if "cache" not in path.parts)

    before = outside()

    found, absent = survey(data, "ISL", ["kasilyrics", "no_dump"], tmp_path / "discogs")

    assert outside() == before
    assert absent == {"source": "no_dump", "dump": None}
    assert (found["dump"], found["songs_in"]) == ("clean/dumps/kasilyrics/20260102/", 8)
    assert (found["by_year"], found["no_year"]) == ({1995: 1, 1997: 1}, 0)
    assert sum(found["by_year"].values()) + found["no_year"] == found["would_add"]
    assert found["would_add"] + sum(found["rejected"].values()) == found["songs_in"]
    assert found["seconds"] >= 0
    result = import_dump(
        data, "kasilyrics", "ISL", tmp_path / "discogs", countries=tmp_path / "countries"
    )
    assert result["songs_added"] == found["would_add"] == 2
    assert result["rejected"] == found["rejected"]


def test_by_decade_sums_the_years_of_each_decade():
    assert by_decade({1969: 1, 1960: 2, 1970: 4}) == {1960: 3, 1970: 4}
    assert by_decade({}) == {}


def test_gaps_counts_the_songs_held_and_the_tracks_wanted_by_year(tmp_path):
    data = tmp_path / "data"
    country = paths.country_songs_dir(data, "ISL", RUN)
    write(
        schemas.COUNTRY_SONGS,
        country,
        [
            held("s1", "a1", "Anna Jons", "Old Song", "h1") | {"year": 1990},
            held("s2", "a1", "Anna Jons", "Sol sol (Live)", "h2"),
            held("s3", "a2", "Bára", "Riverside", "h3") | {"year": 1990},
        ],
    )
    roster = [artist("a1", "Anna Jóns") | {"discogs_artist_id": "11"}, artist("a2", "Bára")]
    write(schemas.COUNTRY_ARTISTS, country, roster)
    write(schemas.COUNTRY_LINKS, country, [])
    manifests.write_manifest(
        data, country, "country_songs", country_iso3="ISL", run_id=RUN, inputs=["lyrics/isl/"]
    )
    write_catalog(data)

    found = gaps(data, "ISL")

    assert found["songs_folder"] == f"lyrics/ISL/songs/{RUN}/"
    assert (found["songs"], found["held_by_year"], found["held_no_year"]) == (3, {1990: 2}, 1)
    assert (found["artists"], found["artists_no_discogs_id"]) == (2, 1)
    assert (found["tracks_in"], found["tracks_no_title_key"], found["pairs"]) == (11, 0, 9)
    assert (found["pairs_linked"], found["pairs_held"], found["wanted"]) == (0, 2, 7)
    assert found["wanted_by_year"] == {1995: 3, 1997: 3, 2001: 1}
    assert found["pairs_linked"] + found["pairs_held"] + found["wanted"] == found["pairs"]

    later = paths.country_songs_dir(data, "ISL", "20260201T000000Z")
    for table in (schemas.COUNTRY_SONGS, schemas.COUNTRY_ARTISTS):
        (later / table.file).parent.mkdir(parents=True, exist_ok=True)
        (later / table.file).write_bytes((country / table.file).read_bytes())
    link = {"country_iso3": "ISL", "song_id": "s1", "artist_id": "a1", "source": "invented"}
    write(
        schemas.COUNTRY_LINKS,
        later,
        [link | {"discogs_release_id": "200", "discogs_track_index": "2", "run_id": RUN}],
    )
    manifests.write_manifest(
        data,
        later,
        "country_songs",
        country_iso3="ISL",
        run_id="20260201T000000Z",
        inputs=["lyrics/isl/"],
    )
    found = gaps(data, "ISL")
    assert (found["pairs_linked"], found["pairs_held"], found["wanted"]) == (1, 2, 6)
    assert found["wanted_by_year"] == {1995: 2, 1997: 3, 2001: 1}


def test_import_dump_uses_the_newest_catalog_folder_and_names_it_as_an_input(tmp_path):
    data, countries = tmp_path / "data", tmp_path / "countries"
    complete_folders(data)
    with pytest.raises(FileNotFoundError, match="no Discogs tables"):
        import_dump(data, "kasilyrics", "ISL", countries=countries)
    assert run_records.read_run_records("ISL", countries) == []

    catalog = write_catalog(data)
    result = import_dump(data, "kasilyrics", "ISL", countries=countries)

    assert result["songs_added"] == 2
    manifest = manifests.read_manifest(result["path"])
    assert manifest.inputs == [
        "clean/dumps/kasilyrics/20260102/",
        f"lyrics/ISL/songs/{RUN}/",
        catalog,
    ]
    assert f"Discogs tables: {catalog}." in manifest.notes


def test_the_tracked_review_file_loads(tmp_path):
    assert set(load_reviewed_matches().values()) <= {"accept", "reject"}
    bad = tmp_path / "resources" / "lyrics"
    bad.mkdir(parents=True)
    (bad / "reviewed_close_matches.csv").write_text(
        "source,country_iso3,source_song_id,discogs_release_id,discogs_track_index,"
        "decision,decided,reason\nx,ISL,1,2,3,maybe,2026-01-01,why\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="needs a decision"):
        load_reviewed_matches(tmp_path)


def test_songs_with_no_roster_artist_are_counted_and_have_no_row(tmp_path):
    _, country = make_folders(tmp_path)
    dump = paths.clean_dump_dir(tmp_path, "example", "20260104")
    write(schemas.DUMP_ARTIST_NAMES, dump, [])
    write(
        schemas.DUMP_SONGS,
        dump,
        [
            credit("n1", "Unknown Band", "Far Away", "k1"),
            credit("n2", "Unknown Band", "???", "k2"),
            credit("n3", "!!!", "Lost Title", "k3"),
            credit("n4", "Other Band", "Far Away", "k4", 1),
            credit("n4", "Third Band", "Far Away", "k4", 2),
            credit("n5", "Anna Jons", "A New Song", "k5"),
        ],
    )
    result = match_dump(dump, country)
    assert [row["source_song_id"] for row in result["songs"]] == ["n5"]
    assert (result["credit_rows_in"], result["songs_in"]) == (6, 5)
    assert result["counts"] == {"held": 0, "same_title": 0, "roster_new": 1, "not_roster": 2}
    assert result["left_out"] == {"no_title_key": 1, "no_artist_key": 1, "short_lyrics": 0}
    assert result["songs_out"] + sum(result["left_out"].values()) == result["songs_in"]
    assert result["examples"]["not_roster"] == [
        ("Other Band", "Far Away"),
        ("Unknown Band", "Far Away"),
    ]


def test_the_keys_of_a_dump_are_built_one_time_and_again_when_the_key_code_changes(
    tmp_path, monkeypatch
):
    dump, country = make_folders(tmp_path)
    first = match_dump(dump, country)
    folder = dump_keys(dump)
    assert folder.parent == tmp_path / "cache" / "dump_keys" / "example" / "20260102"
    stamp = (folder / "credits.parquet").stat().st_mtime_ns

    assert match_dump(dump, country) == first
    assert (folder / "credits.parquet").stat().st_mtime_ns == stamp
    assert [path.name for path in folder.parent.iterdir()] == [folder.name]
    assert sorted(path.name for path in dump.iterdir()) == ["artist_names.parquet", "songs.parquet"]

    # A change of the hashed key code gives a new version, so the keys are built again.
    # The work folder of a build that stopped more than one day ago is removed.
    stopped = folder.parent / "work-stopped"
    stopped.mkdir()
    os.utime(stopped, (0, 0))
    monkeypatch.setattr(dump_match, "_HOMONYM", dump_match._HOMONYM + "|x")
    other = dump_match._keys_version()
    assert other != folder.name
    assert match_dump(dump, country) == first
    assert sorted(path.name for path in folder.parent.iterdir()) == sorted([folder.name, other])
    assert unicodedata.unidata_version in dump_match._keys_text()
    with pytest.raises(ValueError, match="clean/dumps"):
        dump_keys(tmp_path / "elsewhere")


def test_a_country_with_no_match_and_no_discogs_id_gives_zero_counts(tmp_path):
    data = tmp_path / "data"
    dump = paths.clean_dump_dir(data, "example", "20260102")
    write(schemas.DUMP_ARTIST_NAMES, dump, [])
    write(schemas.DUMP_SONGS, dump, [credit("n1", "Unknown Band", "Far Away", "k1")])
    manifests.write_manifest(data, dump, "clean_dump", source="example", inputs=["raw/x/20260101/"])
    country = paths.country_songs_dir(data, "ISL", RUN)
    write(schemas.COUNTRY_SONGS, country, [])
    write(schemas.COUNTRY_ARTISTS, country, [artist("a2", "Bára") | {"songs": 0}])
    write(schemas.COUNTRY_LINKS, country, [])
    manifests.write_manifest(
        data, country, "country_songs", country_iso3="ISL", run_id=RUN, inputs=["lyrics/isl/"]
    )
    write_catalog(data)

    (row,) = survey(data, "ISL", ["example"])
    assert (row["songs_in"], row["would_add"], row["by_year"]) == (1, 0, {})
    assert row["rejected"]["not_roster"] == 1
    plan = would_add(dump, country, data / "clean/catalog/discogs/20260101", "example", "ISL", {})
    assert (plan["chosen"], plan["songs_in"]) == ({}, 1)
    found = gaps(data, "ISL")
    assert (found["songs"], found["wanted"], found["tracks_in"]) == (0, 0, 0)
    assert (found["artists"], found["artists_no_discogs_id"]) == (1, 1)


def write_named_discogs(folder: Path, artists: str) -> None:
    """Invented Discogs tables where artist 21 has one track, and an `artists` table."""
    folder.mkdir(parents=True)
    tables = {
        "artists": f"SELECT * FROM (VALUES {artists}) AS t(artist_id, name)",
        "release_artists": "SELECT * FROM (VALUES (500, 21), (600, 81)) "
        "AS t(release_id, artist_id)",
        "release_track_artists": "SELECT * FROM (VALUES (500, 1, 21)) "
        "AS t(release_id, track_index, artist_id) WHERE false",
        "release_tracklist": "SELECT * FROM (VALUES (500, 1, 'Night Song')) "
        "AS t(release_id, track_index, title)",
        "releases": "SELECT * FROM (VALUES (500, NULL::BIGINT, '1988', 'Iceland'), "
        "(600, NULL::BIGINT, '1990', 'US')) AS t(release_id, master_id, released, country)",
        "masters": "SELECT * FROM (VALUES (50, 1997)) AS t(master_id, year) WHERE false",
    }
    for name, sql in tables.items():
        duckdb.sql(sql).write_parquet(str(folder / f"{name}.parquet"))


def test_of_artists_with_one_name_the_only_one_with_home_releases_gets_the_id(tmp_path):
    country = tmp_path / "country"
    write(
        schemas.COUNTRY_ARTISTS,
        country,
        [
            artist("a1", "Thanh Tuyền"),
            artist("a2", "Elín"),
            artist("a3", "Finnur"),
            artist("a4", "Madonna"),
        ],
    )
    folder = tmp_path / "discogs"
    write_named_discogs(
        folder,
        "(31, 'Thanh Tuyền'), (32, 'Thanh Tuyen (2)'), (41, 'Elin'), (42, 'Elín (2)'), "
        "(51, 'Finnur'), (52, 'Finnur (2)'), (61, 'Madonna'), (62, 'Madonna (2)')",
    )
    # 31 has two releases in Iceland and 32 one elsewhere; 41 has only one home release;
    # 51 and 52 both have a home release; 61 has two home releases of 500, under 0.5%.
    credits = "(1, 31), (2, 31), (3, 32), (4, 41), (5, 51), (5, 52), (6, 52), (1, 61), (2, 61)"
    duckdb.sql(
        f"SELECT * FROM (VALUES {credits}) AS t(release_id, artist_id) "
        "UNION ALL SELECT range, 61 FROM range(100, 598)"
    ).write_parquet(str(folder / "release_artists.parquet"))
    countries = (
        "(1, 'Iceland'), (2, 'Iceland'), (3, 'US'), (4, 'Iceland'), (5, 'Iceland'), (6, 'US')"
    )
    duckdb.sql(
        f"SELECT release_id, NULL::BIGINT AS master_id, '1990' AS released, country "
        f"FROM (VALUES {countries}) AS t(release_id, country) "
        "UNION ALL SELECT range, NULL, '1990', 'US' FROM range(100, 598)"
    ).write_parquet(str(folder / "releases.parquet"))

    found = dump_match.discogs_ids(country, folder, "ISL")

    assert found["by_name"] == {"a1": (31, "Thanh Tuyền")}
    assert (found["by_home_release"], found["more_than_one"]) == (1, 3)


def test_variant_keys_add_discogs_name_variations_and_articles_of_roster_artists(tmp_path):
    country = tmp_path / "country"
    write(
        schemas.COUNTRY_ARTISTS,
        country,
        [
            artist("a1", "Los Temerarios") | {"discogs_artist_id": "11"},
            artist("a2", "Sora Ruiz") | {"discogs_artist_id": "12"},
            artist("a3", "Temerarios Band"),
            artist("a4", "Rakim y Ken-Y (Dúo)") | {"discogs_artist_id": "15"},
        ],
    )
    folder = tmp_path / "discogs"
    folder.mkdir(parents=True)
    tables = {
        "artists": "SELECT * FROM (VALUES (11, 'Los Temerarios'), (12, 'Sora Ruiz'), "
        "(14, 'Sora'), (15, 'Rakim Y Ken-Y')) AS t(artist_id, name)",
        "artist_namevariations": "SELECT * FROM (VALUES (11, 'Temerarios Band'), "
        "(12, 'Sora'), (12, 'Ruiz')) AS t(artist_id, namevariation)",
        "release_artists": "SELECT * FROM (VALUES (1, 11, 'Los Temerarios', 'Temerarios Y Su "
        "Grupo')) AS t(release_id, artist_id, artist_name, anv)",
    }
    for name, sql in tables.items():
        duckdb.sql(sql).write_parquet(str(folder / f"{name}.parquet"))

    variants = dump_match.variant_keys(country, folder, "ISL")

    # A roster name loses or gets an article. A roster key ("temerarios band") and a single
    # word that is the key of another Discogs artist ("sora", artist 14) are no variants.
    assert variants == {
        "temerarios": "a1",
        "temerarios y su grupo": "a1",
        "el sora ruiz": "a2",
        "la sora ruiz": "a2",
        "las sora ruiz": "a2",
        "los sora ruiz": "a2",
        "ruiz": "a2",
        "rakim ken y": "a4",
        "rakim y ken y": "a4",
        "el rakim y ken y duo": "a4",
        "la rakim y ken y duo": "a4",
        "las rakim y ken y duo": "a4",
        "los rakim y ken y duo": "a4",
    }


def test_a_dominant_artist_a_shared_key_and_a_stated_country_give_an_id(tmp_path):
    country = tmp_path / "country"
    write(
        schemas.COUNTRY_ARTISTS,
        country,
        [
            artist("a1", "Lola"),
            artist("a2", "Sol"),
            artist("a3", "SOL"),
            artist("a4", "Rita"),
            artist("a5", "Vera"),
        ],
    )
    folder = tmp_path / "discogs"
    folder.mkdir(parents=True)
    artists = (
        "(71, 'Lola', ''), (72, 'Lola (2)', ''), (81, 'Sol', ''), "
        "(91, 'Rita', 'Icelandic singer from Reykjavik.'), (92, 'Rita (2)', 'American singer.'), "
        "(95, 'Vera', ''), (96, 'Vera (2)', '')"
    )
    duckdb.sql(f"SELECT * FROM (VALUES {artists}) AS t(artist_id, name, profile)").write_parquet(
        str(folder / "artists.parquet")
    )
    # 71 has 10 home releases and 72 has 2: 71 has 5 times the home releases of 72.
    # 95 has 6 home releases and 96 has 2: under 5 times, so Vera gets no id.
    credits = [(n, 71) for n in range(1, 11)] + [(11, 72), (12, 72), (13, 81)]
    credits += [(n, 95) for n in range(20, 26)] + [(26, 96), (27, 96)]
    duckdb.sql(
        "SELECT * FROM (VALUES "
        + ", ".join(f"({release}, {number})" for release, number in credits)
        + ") AS t(release_id, artist_id)"
    ).write_parquet(str(folder / "release_artists.parquet"))
    duckdb.sql(
        "SELECT range AS release_id, NULL::BIGINT AS master_id, '1990' AS released, "
        "'Iceland' AS country FROM range(1, 30)"
    ).write_parquet(str(folder / "releases.parquet"))
    duckdb.sql(
        "SELECT * FROM (VALUES (1, 1, 1)) AS t(release_id, track_index, artist_id) WHERE false"
    ).write_parquet(str(folder / "release_track_artists.parquet"))

    found = dump_match.discogs_ids(country, folder, "ISL")

    assert found["ids"] == {"a1": 71, "a2": 81, "a3": 81, "a4": 91}
    assert (found["by_dominance"], found["by_same_key"], found["by_stated"]) == (1, 2, 1)
    assert found["more_than_one"] == 1


def test_a_discogs_id_is_found_by_name_only_when_one_artist_has_the_name(tmp_path):
    country = tmp_path / "country"
    write(
        schemas.COUNTRY_ARTISTS,
        country,
        [
            artist("a1", "Anna Jóns") | {"discogs_artist_id": "11"},
            artist("a2", "Bára"),
            artist("a3", "Dísa"),
            artist("a4", "Elín"),
            artist("a5", "Finnur"),
            artist("a6", "Gunnar"),
            artist("a7", "Gunnar!"),
            artist("a8", "..."),
            artist("a9", "Νίκος"),
            artist("a10", "Strasse"),
            artist("a11", "Hanna"),
        ],
    )
    # The two Greek names differ only in case and in the final sigma, and the two German
    # names only in ß against SS: `name_key` gives each pair one key, so each pair blocks.
    write_named_discogs(
        tmp_path / "discogs",
        "(21, 'BÁRA (2)'), (31, 'Disa'), (32, 'Dísa (2)'), (11, 'Elin'), (41, 'Gunnar'), "
        "(51, 'Bára Band'), (61, 'Νίκος'), (62, 'ΝΙΚΟΣ'), (71, 'Straße'), (72, 'STRASSE'), "
        "(81, 'Hanna')",
    )

    found = dump_match.discogs_ids(country, tmp_path / "discogs", "ISL")

    # One artist with the name, with or without the homonym mark: the id is used.
    assert found["by_name"] == {"a2": (21, "BÁRA (2)")}
    assert found["ids"] == {"a1": 11, "a2": 21}
    # Two homonyms with no home release block. An id of another roster artist blocks.
    assert (found["more_than_one"], found["id_taken"]) == (3, 1)
    assert (found["none_found"], found["no_name_key"]) == (1, 1)
    # The only Discogs artist with the name has no release in Iceland: the id is not used,
    # for Hanna and for the two roster artists that share the key of Gunnar.
    assert found["no_home_release"] == 3
    assert dump_match.discogs_ids(country, tmp_path / "discogs", "USA")["by_name"] == {
        "a11": (81, "Hanna")
    }

    # For a catalog folder of the data folder, the keys of Discogs are built one time in cache/.
    catalog = paths.clean_catalog_dir(tmp_path / "data", "discogs", "20260101")
    write_named_discogs(catalog, "(21, 'BÁRA (2)'), (61, 'Νίκος'), (62, 'ΝΙΚΟΣ')")
    assert dump_match.discogs_ids(country, catalog, "ISL")["by_name"] == {"a2": (21, "BÁRA (2)")}
    cache = tmp_path / "data" / "cache" / "discogs_keys" / "discogs" / "20260101"
    assert [path.name for path in cache.iterdir()] == [dump_match._keys_version()]

    write(schemas.COUNTRY_ARTISTS, tmp_path / "other", [artist("a2", "Bára")])
    write_discogs(tmp_path / "no_artists_table")
    assert (
        dump_match.discogs_ids(tmp_path / "other", tmp_path / "no_artists_table", "ISL")["ids"]
        == {}
    )


def test_a_song_of_an_artist_found_by_name_is_added_with_its_own_method_and_count(tmp_path):
    data, countries = tmp_path / "data", tmp_path / "countries"
    dump = paths.clean_dump_dir(data, "kasilyrics", "20260102")
    write(schemas.DUMP_ARTIST_NAMES, dump, [])
    write(
        schemas.DUMP_SONGS,
        dump,
        [credit("b1", "Bara", "Night Song", "kb"), credit("b2", "Bara", "No Such Track", "kc")],
    )
    manifests.write_manifest(
        data, dump, "clean_dump", source="kasilyrics", inputs=["raw/x/20260101/"]
    )
    country = paths.country_songs_dir(data, "ISL", RUN)
    write(schemas.COUNTRY_SONGS, country, [])
    write(schemas.COUNTRY_ARTISTS, country, [artist("a2", "Bára") | {"songs": 0}])
    write(schemas.COUNTRY_LINKS, country, [])
    manifests.write_manifest(
        data, country, "country_songs", country_iso3="ISL", run_id=RUN, inputs=["lyrics/isl/"]
    )
    discogs = tmp_path / "discogs"
    write_named_discogs(discogs, "(21, 'Bára')")

    plan = would_add(dump, country, discogs, "kasilyrics", "ISL", {})
    assert (len(plan["chosen"]), plan["by_name"], plan["rejected"]["no_track"]) == (1, 1, 1)
    found = gaps(data, "ISL", discogs)
    assert (found["artists_by_name"], found["artists_no_discogs_id"], found["wanted"]) == (1, 0, 1)

    result = import_dump(data, "kasilyrics", "ISL", discogs, countries=countries)

    out = result["path"]
    assert result["songs_added"] == 1
    assert duckdb.sql(
        f"SELECT match_method FROM '{(out / 'links.parquet').as_posix()}'"
    ).fetchall() == [("dump_discogs_exact_title_artist_by_name",)]
    assert manifests.read_manifest(out).counts["dump_songs_added_artist_by_name"] == 1
    (record,) = run_records.read_run_records("ISL", countries)
    assert "1 songs added for artists whose Discogs id was found by name" in record.notes
    # The roster of the new folder holds the id that the import found.
    assert duckdb.sql(
        f"SELECT discogs_artist_id FROM '{(out / 'artists.parquet').as_posix()}'"
    ).fetchall() == [("21",)]
    # The artist stays an artist found by name: its link says so, also with no `artists` table.
    (discogs / "artists.parquet").unlink()
    later = dump_match.discogs_ids(out.resolve(), discogs.resolve(), "ISL")
    assert (later["ids"], later["by_name"]) == ({"a2": 21}, {"a2": (21, "Bára")})


def test_an_import_fills_the_id_of_an_artist_that_an_earlier_import_found_by_name(tmp_path):
    data = tmp_path / "data"
    dump = paths.clean_dump_dir(data, "kasilyrics", "20260102")
    write(schemas.DUMP_ARTIST_NAMES, dump, [])
    write(schemas.DUMP_SONGS, dump, [credit("b2", "Bara", "No Such Track", "kc")])
    manifests.write_manifest(
        data, dump, "clean_dump", source="kasilyrics", inputs=["raw/x/20260101/"]
    )
    # A folder of an earlier import: a link by name, and a roster with no Discogs id.
    country = paths.country_songs_dir(data, "ISL", RUN)
    write(schemas.COUNTRY_SONGS, country, [held("s9", "a2", "Bára", "Night Song", "kz")])
    write(schemas.COUNTRY_ARTISTS, country, [artist("a2", "Bára"), artist("a3", "Dísa")])
    link = {"country_iso3": "ISL", "song_id": "s9", "artist_id": "a2", "source": "invented"}
    by_name = {"match_method": "dump_discogs_exact_title_artist_by_name", "run_id": RUN}
    track = {"discogs_release_id": "500", "discogs_track_index": "1"}
    write(schemas.COUNTRY_LINKS, country, [link | track | by_name])
    manifests.write_manifest(
        data, country, "country_songs", country_iso3="ISL", run_id=RUN, inputs=["lyrics/isl/"]
    )
    discogs = tmp_path / "discogs"
    write_named_discogs(discogs, "(21, 'Bára')")

    result = import_dump(data, "kasilyrics", "ISL", discogs, countries=tmp_path / "countries")

    assert result["songs_added"] == 0
    roster = (result["path"] / "artists.parquet").as_posix()
    assert duckdb.sql(
        f"SELECT artist_id, discogs_artist_id FROM '{roster}' ORDER BY 1"
    ).fetchall() == [("a2", "21"), ("a3", None)]


def test_the_home_countries_of_discogs_include_the_states_that_no_longer_exist():
    home = dump_match.load_home_countries()

    assert home["ISL"] == {"Iceland"}
    assert {"Ukraine", "USSR"} <= home["UKR"] and "USSR" in home["SUN"]
    assert {"Serbia", "Yugoslavia", "Serbia and Montenegro"} <= home["SRB"]
    assert "Europe" not in set().union(*home.values())


def test_held_text_finds_copies_of_held_songs_and_of_earlier_songs(tmp_path):
    long_start = "an invented verse that repeats " * 12
    dump = paths.clean_dump_dir(tmp_path, "example", "20260102")
    texts = {
        "t1": "An invented text that the country holds under another artist",
        "t2": long_start + "and an invented end",
        "t3": long_start + "and a second end",
        "t4": "a new invented text of this dump, first copy",
        "t5": "A NEW invented text of this dump -- first copy!",
        "t6": "a short text",
        "t7": "a short text",
        "t8": "another invented text, which only a copy holds before it",
    }
    rows = [credit(key, "Anna Jons", "Title", key, lyrics=text) for key, text in texts.items()]
    write(schemas.DUMP_SONGS, dump, rows)
    country = paths.country_songs_dir(tmp_path, "ISL", RUN)
    write(
        schemas.COUNTRY_SONGS,
        country,
        [
            held("s1", "a2", "Bára", "", "x1") | {"lyrics": texts["t1"].lower() + "."},
            held("s2", "a1", "Anna Jons", "", "x2") | {"lyrics": long_start + "and an old end"},
        ],
    )
    artists = dict.fromkeys(texts, "a1") | {"t3": "a2", "t8": "a2"}

    copies = dump_match.held_text(dump, country, artists)

    # t1: same text, other artist. t2: same artist, same start. t3: same start, other
    # artist, so new. t5: same text as the earlier t4. t6 and t7: too short for a key.
    assert copies == {"t1", "t2", "t5"}
    assert dump_match.held_text(dump, country, {}) == set()


def test_the_import_and_the_survey_hold_back_a_text_copy(tmp_path):
    data, countries = tmp_path / "data", tmp_path / "countries"
    dump, country = make_folders(data, "kasilyrics")
    (country / schemas.COUNTRY_SONGS.file).unlink()
    write(
        schemas.COUNTRY_SONGS,
        country,
        [
            held("s1", "a1", "Anna Jons", "Old Song", "h1"),
            held("s2", "a1", "Anna Jons", "Sol sol", "other"),
            held("s3", "a2", "Bára", "", "other")
            | {"lyrics": "An invented line of text -- for the tests; SONG D3!"},
        ],
    )
    manifests.write_manifest(
        data, dump, "clean_dump", source="kasilyrics", inputs=["raw/x/20260101/"]
    )
    manifests.write_manifest(
        data, country, "country_songs", country_iso3="ISL", run_id=RUN, inputs=["lyrics/isl/"]
    )
    write_discogs(tmp_path / "discogs")

    (found,) = survey(data, "ISL", ["kasilyrics"], tmp_path / "discogs")
    assert (found["would_add"], found["rejected"][dump_match.HELD_TEXT]) == (1, 1)
    assert found["would_add"] + sum(found["rejected"].values()) == found["songs_in"]
    result = import_dump(
        data, "kasilyrics", "ISL", tmp_path / "discogs", discogs_label="test", countries=countries
    )
    assert result["songs_added"] == 1 and result["rejected"] == found["rejected"]
    added = duckdb.sql(
        f"SELECT source_song_id FROM '{(result['path'] / 'songs.parquet').as_posix()}' "
        "WHERE route = 'dump_name'"
    ).fetchall()
    assert added == [("d7",)]
    assert manifests.read_manifest(result["path"]).counts["dump_songs_held_text"] == 1
    (record,) = run_records.read_run_records("ISL", countries)
    assert record.songs_rejected["held_text"] == 1
    assert record.songs_accepted + sum(record.songs_rejected.values()) == record.songs_attempted
