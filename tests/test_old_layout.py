"""The import of a country from the old layout, on small invented files."""

import csv
import hashlib
import uuid

import duckdb
import pandas as pd
import pytest
from typer.testing import CliRunner

from songs.cli import app
from songs.common import manifests, paths, run_records, schemas
from songs.common.paths import DATA_ROOT_ENV
from songs.stage_00_ingest import old_layout as o


def discogs_uuid(number: int) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"https://www.discogs.com/artist/{number}"))


# Band One and The Twins have a Discogs id in the cache. Quiet One has none and no song.
# Late Arrival has a lyric file and is absent from the roster.
BAND_ONE, TWINS = discogs_uuid(123), discogs_uuid(456)
QUIET, LATE = str(uuid.uuid4()), str(uuid.uuid4())
ROSTER = [
    (BAND_ONE, "Band One", "true", "2026-09-18T19:47:53+00:00", "source_profile_unverified"),
    (TWINS, "The Twins", "false", "2026-09-19T00:00:00.5+00:00", ""),
    (TWINS, "Twins, The", "true", "", ""),  # a second name with the same Discogs id
    (QUIET, "Quiet One", "false", "", ""),
    ("", "No Id", "true", "", ""),
]
LATER_RUN = "20990101T000000Z"


def song(song_id, artist, **over) -> dict:
    """Return one row of an old lyric file. All text is invented."""
    return {
        "song_id": song_id,
        "artist_id": artist,
        "artist_name": "Band One",
        "lyrics_text_hash": "stale",
        "provider": "example_site",
        "provider_song_id": f"p-{song_id}",
        "song_url": f"https://a.example/{song_id}",
        "year": 1990,
        "lyrics": f"invented line {song_id}",
        "scraped_at_utc": "2026-09-18T19:47:53.123456+00:00",
        "check": "a dropped column",
    } | over


def link(song_id, release, track, **over) -> dict:
    """Return one row of an old link file."""
    return {
        "song_id": song_id,
        "artist_id": BAND_ONE,
        "discogs_release_id": release,
        "discogs_track_index": track,
        "discogs_title": "One",
        "provider": "example_site",
        "provider_song_id": f"p-{song_id}",
        "provider_title": "Line One",
        "song_url": f"https://a.example/{song_id}",
        "match_method": "exact",
        "match_score": "0.9",
        "dedupe_guardrail": "a dropped column",
    } | over


SONGS = {
    BAND_ONE: [
        song("s1", BAND_ONE),
        song("s1", BAND_ONE, lyrics="an older line", scraped_at_utc="2026-01-01T00:00:00+00:00"),
        song("s2", BAND_ONE, lyrics="  "),
        song("s3", BAND_ONE, provider=""),
        song(None, BAND_ONE),
    ],
    # This file has the columns that the newer old files have.
    TWINS: [
        song(
            "s4",
            TWINS,
            artist_name="Twins, The",
            year=2001,
            year_source="discogs",
            year_basis="source_printed_unverified",
            first_release_year=1980,
            canonical_song_id="s1",
            duplicate_decision="suppress_duplicate",
            quality_status="quarantine",
            quality_reason="a dropped column",
            scraped_at_utc="2026-10-01T10:00:00+02:00",
        )
    ],
    LATE: [
        song("s5", LATE, artist_name="Late Arrival", scraped_at_utc="not a time"),
        song("s6", LATE, artist_name=""),
    ],
}
LINKS = {
    BAND_ONE: [
        link("s1", "9", "A1"),
        link("s1", "9", "A1", match_score="0.5", provider_title="Line One (live)"),
        link("s1", "", "", match_score="0.1", provider_title="Zed"),
        link("s2", "9", "A2"),
        link("s1", "10", "2", match_score=""),
    ]
}


def write_parquet(path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(rows).convert_dtypes()
    duckdb.from_df(frame).write_parquet(str(path))


def make_old(old, songs=SONGS, links=LINKS, roster=ROSTER, discogs=(123, 456, 999)):
    """Make the folder of Togo in the old layout and return it."""
    country = old / "lyrics" / "tgo"
    country.mkdir(parents=True)
    for artist, rows in songs.items():
        write_parquet(country / "lyrics" / f"{artist}.parquet", rows)
    for artist, rows in links.items():
        write_parquet(country / "lyrics_links" / f"{artist}.parquet", rows)
    if roster:
        with (country / "artists.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["artist_id", "name", "scraped", "scraped_at_utc", "country_basis"])
            writer.writerows(roster)
    if discogs:
        write_parquet(
            country / "discogs_cache" / "artists.parquet",
            [{"artist_id": number, "name": "a cache name"} for number in discogs],
        )
    return country


def snapshot(folder) -> dict:
    """Return the SHA-256 of every file under a folder."""
    return {
        path.relative_to(folder).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(folder.rglob("*"))
        if path.is_file()
    }


def table(kind: schemas.Table, folder, order: str) -> list[dict]:
    relation = schemas.read_table(kind, folder).order(order)
    return [dict(zip(relation.columns, row, strict=True)) for row in relation.fetchall()]


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_the_command_maps_each_column_and_writes_a_manifest_and_one_run_record(
    tmp_path, monkeypatch
):
    old, data, countries = tmp_path / "old", tmp_path / "data", tmp_path / "countries"
    make_old(old)
    before = snapshot(old)
    data.mkdir()
    monkeypatch.setenv(DATA_ROOT_ENV, str(data))
    monkeypatch.setenv(o.OLD_DATA_ENV, str(old))
    monkeypatch.setattr(run_records, "countries_dir", lambda: countries)
    result = CliRunner().invoke(app, ["lyrics", "import-old", "tgo"])
    assert result.exit_code == 0, result.output
    assert "3 songs, 4 artists, 2 links" in result.output
    assert "invented line" not in result.output
    assert snapshot(old) == before  # the old data folder is read only

    (record,) = run_records.read_run_records("TGO", countries)
    assert (record.route, record.source, record.state) == ("old_layout", "old_pipeline", "complete")
    assert (record.rows_added, record.artists_attempted, record.bulk_file) == (3, None, None)
    out = paths.latest_country_songs_dir(data, "TGO")
    assert out == data / "lyrics" / "TGO" / "songs" / record.run_id

    empty = dict.fromkeys(column.name for column in schemas.COUNTRY_SONGS.columns)
    same = {"country_iso3": "TGO", "source": "example_site", "route": "old_layout"}
    same["run_id"] = record.run_id
    assert table(schemas.COUNTRY_SONGS, out, "song_id") == [
        empty
        | same
        | {
            # The newest of the two rows with this id stays. The title comes from the links.
            "song_id": "s1",
            "artist_id": BAND_ONE,
            "artist_name": "Band One",
            "song_name": "Line One",
            "source_song_id": "p-s1",
            "song_url": "https://a.example/s1",
            "lyrics": "invented line s1",
            "lyrics_sha256": sha("invented line s1"),  # computed again, not the old hash
            "year": 1990,
            "collected_utc": "2026-09-18T19:47:53Z",
        },
        empty
        | same
        | {
            "song_id": "s4",
            "artist_id": TWINS,
            "artist_name": "Twins, The",  # the name as collected
            "source_song_id": "p-s4",
            "song_url": "https://a.example/s4",
            "lyrics": "invented line s4",
            "lyrics_sha256": sha("invented line s4"),
            "year": 2001,
            "year_source": "discogs",
            "year_basis": "source_printed_unverified",
            "first_release_year": 1980,
            "canonical_song_id": "s1",
            "duplicate_decision": "suppress_duplicate",
            "quality_status": "quarantine",
            # The time has the offset +02:00. It is not read, so it is not a wrong UTC time.
        },
        empty
        | same
        | {
            "song_id": "s5",
            "artist_id": LATE,
            "artist_name": "Late Arrival",
            "source_song_id": "p-s5",
            "song_url": "https://a.example/s5",
            "lyrics": "invented line s5",
            "lyrics_sha256": sha("invented line s5"),
            "year": 1990,
        },
    ]

    artists = schemas.read_table(schemas.COUNTRY_ARTISTS, out)
    assert artists.project(
        "artist_name, artist_id, discogs_artist_id, country_tag, attempted, last_attempt_utc, songs"
    ).fetchall() == [
        ("Band One", BAND_ONE, "123", "source_profile_unverified", True, "2026-09-18T19:47:53Z", 1),
        ("Late Arrival", LATE, None, None, True, None, 1),
        ("Quiet One", QUIET, None, None, False, None, 0),
        # Two names with one Discogs id are one artist; the first name of the roster stays.
        ("The Twins", TWINS, "456", None, True, "2026-09-19T00:00:00Z", 1),
    ]

    link_row = {
        "country_iso3": "TGO",
        "song_id": "s1",
        "artist_id": BAND_ONE,
        "discogs_title": "One",
        "source": "example_site",
        "source_song_id": "p-s1",
        "source_title": "Line One",
        "song_url": "https://a.example/s1",
        "match_method": "exact",
        "run_id": record.run_id,
    }
    assert table(schemas.COUNTRY_LINKS, out, "discogs_release_id") == [
        link_row | {"discogs_release_id": "10", "discogs_track_index": "2", "match_score": None},
        link_row | {"discogs_release_id": "9", "discogs_track_index": "A1", "match_score": 0.9},
    ]

    manifest = manifests.read_manifest(out)
    assert (manifest.kind, manifest.country_iso3, manifest.run_id) == (
        "country_songs",
        "TGO",
        record.run_id,
    )
    assert manifest.inputs == ["lyrics/tgo/"]
    assert manifest.counts == {
        "songs": 3,
        "artists": 4,
        "links": 2,
        "songs_added": 3,
        "songs_removed": 0,
        "songs_from_other_routes": 0,
        "old_lyric_files": 3,
        "old_link_files": 1,
        "songs_dropped_no_song_id": 1,
        "songs_dropped_no_lyrics": 1,
        "songs_dropped_no_source": 1,
        "songs_dropped_no_artist": 1,
        "songs_dropped_held_by_other_route": 0,
        "songs_dropped_duplicate_song_id": 1,
        "links_dropped_no_catalog_track": 1,
        "links_dropped_no_song": 1,
        "links_dropped_duplicate_key": 1,
        "roster_rows_dropped_no_id_or_name": 1,
        "roster_rows_dropped_repeated_artist_id": 1,
        "songs_without_title": 2,
        "songs_time_not_read": 2,
        "artists_absent_from_roster": 1,
        "artists_without_discogs_id": 2,
    }
    assert sorted(record.known_gaps) == [
        f"{name}: 1 rows" for name in manifest.counts if "_dropped_" in name and "held" not in name
    ]
    # Lyric text stays in the Parquet file, and no path of the old data folder is recorded.
    for path in (countries / "TGO" / "runs" / record.file_name, out / paths.MANIFEST_NAME):
        text = path.read_text(encoding="utf-8")
        assert "invented line" not in text and tmp_path.name not in text


def test_a_country_with_no_links_no_roster_and_no_discogs_cache(tmp_path):
    old, data, countries = tmp_path / "old", tmp_path / "data", tmp_path / "countries"
    make_old(old, songs={LATE: [song("s5", LATE, artist_name="Late Arrival")]}, links={}, roster=[])
    make_old_empty = old / "lyrics" / "tgo" / "discogs_cache" / "artists.parquet"
    make_old_empty.unlink()
    result = o.import_country(old, data, "TGO", countries=countries)
    out = result["path"]
    assert (result["songs"], result["artists"], result["links"]) == (1, 1, 0)
    assert len(schemas.read_table(schemas.COUNTRY_LINKS, out)) == 0
    assert schemas.read_table(schemas.COUNTRY_SONGS, out).project("song_name").fetchall() == [
        (None,)
    ]
    assert schemas.read_table(schemas.COUNTRY_ARTISTS, out).project(
        "artist_name, artist_id, discogs_artist_id, attempted, songs"
    ).fetchall() == [("Late Arrival", LATE, None, True, 1)]
    manifests.read_manifest(out)


def test_a_second_import_writes_a_new_folder_and_names_the_earlier_one(tmp_path, monkeypatch):
    old, data, countries = tmp_path / "old", tmp_path / "data", tmp_path / "countries"
    country = make_old(old)
    first = o.import_country(old, data, "TGO", countries=countries)["path"]
    before = snapshot(first)

    # The old pipeline wrote in the meantime: one artist file is new, and one is gone.
    write_parquet(
        country / "lyrics" / f"{QUIET}.parquet", [song("s7", QUIET, artist_name="Quiet One")]
    )
    (country / "lyrics" / f"{LATE}.parquet").unlink()
    with pytest.raises(FileExistsError, match="Give a reason"):
        o.import_country(old, data, "TGO", countries=countries)
    assert paths.latest_country_songs_dir(data, "TGO") == first  # the refusal wrote nothing

    monkeypatch.setattr(run_records, "new_run_id", lambda: LATER_RUN)
    result = o.import_country(
        old, data, "TGO", reason="The old files changed.", countries=countries
    )
    second = result["path"]
    assert second.name == LATER_RUN and second != first and snapshot(first) == before
    assert manifests.read_manifest(second).inputs == [
        "lyrics/tgo/",
        f"lyrics/TGO/songs/{first.name}/",
    ]
    assert (result["songs"], result["songs_added"], result["songs_removed"]) == (3, 1, 1)
    songs = schemas.read_table(schemas.COUNTRY_SONGS, second)
    assert songs.project("song_id, run_id").order("song_id").fetchall() == [
        ("s1", LATER_RUN),
        ("s4", LATER_RUN),
        ("s7", LATER_RUN),
    ]
    records = run_records.read_run_records("TGO", countries)
    assert [record.run_id for record in records] == [first.name, LATER_RUN]
    assert (records[1].notes, records[1].rows_added) == ("The old files changed.", 1)


def test_an_import_keeps_the_rows_that_another_route_added(tmp_path):
    old, data, countries = tmp_path / "old", tmp_path / "data", tmp_path / "countries"
    make_old(old)
    # An earlier folder: one row from an earlier import that the old files no longer have,
    # one song that a review added under an id of the old files, and one live song with a link.
    earlier = paths.country_songs_dir(data, "TGO", "20200102T030405Z")
    earlier.mkdir(parents=True)
    reviewer = str(uuid.uuid4())
    row = {
        "country_iso3": "TGO",
        "artist_id": reviewer,
        "artist_name": "Hand Collected",
        "source": "b.example",
        "lyrics": "a reviewed invented line",
        "lyrics_sha256": "0" * 64,
        "run_id": earlier.name,
    }
    tables = {
        schemas.COUNTRY_ARTISTS: [
            row | {"attempted": True, "songs": 3, "country_tag": "Togo"},
            row
            | {
                "artist_id": BAND_ONE,
                "artist_name": "An earlier name",
                "attempted": False,
                "songs": 0,
            },
        ],
        schemas.COUNTRY_SONGS: [
            row | {"song_id": "gone", "route": "old_layout"},
            row | {"song_id": "s4", "route": "manual_review"},
            row | {"song_id": "live_1", "route": "live"},
        ],
        schemas.COUNTRY_LINKS: [
            row | {"song_id": "live_1", "discogs_release_id": "7", "discogs_track_index": "1"},
            row | {"song_id": "gone", "discogs_release_id": "7", "discogs_track_index": "2"},
        ],
    }
    for kind, values in tables.items():
        names = [column.name for column in kind.columns]
        frame = pd.DataFrame(
            [
                dict.fromkeys(names) | {k: v for k, v in value.items() if k in names}
                for value in values
            ],
            columns=names,
        )
        schemas.write_table(kind, schemas.cast_to_schema(kind, frame), earlier)
    manifests.write_manifest(
        data,
        earlier,
        "country_songs",
        country_iso3="TGO",
        run_id=earlier.name,
        inputs=["raw/example_site/20200101/"],
    )

    result = o.import_country(old, data, "TGO", countries=countries)
    out = result["path"]
    songs = schemas.read_table(schemas.COUNTRY_SONGS, out)
    assert songs.project("song_id, route, run_id, artist_id").order("song_id").fetchall() == [
        ("live_1", "live", earlier.name, reviewer),
        ("s1", "old_layout", out.name, BAND_ONE),
        ("s4", "manual_review", earlier.name, reviewer),  # the row of the review stays
        ("s5", "old_layout", out.name, LATE),
    ]
    assert (
        result["songs_from_other_routes"],
        result["songs_dropped_held_by_other_route"],
        result["songs_added"],
        result["songs_removed"],
    ) == (2, 1, 2, 1)
    links = schemas.read_table(schemas.COUNTRY_LINKS, out)
    assert sorted(links.project("song_id, discogs_release_id").fetchall()) == [
        ("live_1", "7"),
        ("s1", "10"),
        ("s1", "9"),
    ]
    artists = schemas.read_table(schemas.COUNTRY_ARTISTS, out)
    assert artists.project("artist_name, country_tag, attempted, songs").fetchall() == [
        ("Band One", "source_profile_unverified", True, 1),  # the roster name
        ("Hand Collected", "Togo", True, 2),
        ("Late Arrival", None, True, 1),
        ("Quiet One", None, False, 0),
        ("The Twins", None, True, 0),
    ]
    assert manifests.read_manifest(out).inputs == [
        "lyrics/tgo/",
        f"lyrics/TGO/songs/{earlier.name}/",
    ]


def test_an_import_stops_before_it_writes(tmp_path):
    old, data, countries = tmp_path / "old", tmp_path / "data", tmp_path / "countries"
    make_old(old)
    with pytest.raises(FileNotFoundError, match="lyrics/ben/"):
        o.import_country(old, data, "BEN", countries=countries)
    # On a file system that ignores case, lyrics/TGO/ would be the old folder lyrics/tgo/.
    with pytest.raises(ValueError, match="read only"):
        o.import_country(old, old, "TGO", countries=countries)
    with pytest.raises(ValueError, match="three capital letters"):
        o.import_country(old, data, "tgo", countries=countries)
    assert not data.exists() and not countries.exists()


def test_the_route_of_the_import_is_a_known_route():
    assert o.ROUTE in run_records.ROUTES
