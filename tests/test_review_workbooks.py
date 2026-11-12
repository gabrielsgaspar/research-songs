"""The import of a country review workbook, on a small invented workbook."""

import hashlib
import uuid

import pandas as pd
import pytest
from typer.testing import CliRunner

from songs.cli import app
from songs.common import manifests, paths, run_records, schemas
from songs.common.paths import DATA_ROOT_ENV
from songs.stage_00_ingest import review_workbooks as r

ADDED, OLD = "Added by review", r.ALREADY_IN_DATA
# Artist, title, year, lyrics, link, link check, review status. All text is invented.
SONGS = [
    ("Band One", "Already here", "1990", "la la", "https://a.example/1", OLD, "Checked"),
    ("Band One", "New song", "2001", "invented line", "https://www.a.example/2", ADDED, "Checked"),
    (
        "Two Lands",
        "Far away",
        "",
        "invented line",
        "https://b.example/3",
        "Verified online",
        "Added",
    ),
    ("Nobody", "Unknown act", "3001", "invented line", "https://b.example/4", ADDED, "Checked"),
    (
        "Band One",
        "Not checked",
        "2002",
        "invented line",
        "https://a.example/5",
        ADDED,
        "Not checked",
    ),
    ("Band One", "No words", "2003", "", "https://a.example/6", ADDED, "Checked"),
    ("Band One", "No link", "2004", "invented line", "not sure", ADDED, "Checked"),
    ("Band One", "Twice", "2005", "invented line", "https://www.a.example/2", ADDED, "Checked"),
]
ARTISTS = [("Band One", "123", "Togo"), ("Two Lands", "", "Togo / France")]
BAND_ONE = str(uuid.uuid5(uuid.NAMESPACE_URL, "https://www.discogs.com/artist/123"))
TWO_LANDS = str(
    uuid.uuid5(uuid.NAMESPACE_URL, "https://research-songs.invalid/artist/TGO/Two Lands")
)
NEW_SONG = "mr_" + hashlib.sha256(b"https://www.a.example/2").hexdigest()[:20]
EARLIER_RUN = "20200102T030405Z"


def make_workbook(
    data, name="TGO_Togo_reviewed.xlsx", day="20261101", songs=SONGS, artists=ARTISTS
):
    folder = paths.raw_manual_review_dir(data, "TGO", day)
    folder.mkdir(parents=True)
    frame = pd.DataFrame(
        [
            (a, t, y, "French", text, url, check, status)
            for a, t, y, text, url, check, status in songs
        ],
        columns=list(r.SONG_COLUMNS),
    )
    with pd.ExcelWriter(folder / name) as writer:
        frame.to_excel(writer, sheet_name="Songs", index=False)
        pd.DataFrame(artists, columns=list(r.ARTIST_COLUMNS)).to_excel(
            writer, sheet_name="Artists", index=False
        )
    return folder / name


def rows(table: schemas.Table, values: list[dict]) -> pd.DataFrame:
    """Return invented rows of a table; a column that is not given is empty."""
    names = [column.name for column in table.columns]
    return pd.DataFrame([dict.fromkeys(names) | row for row in values], columns=names)


def make_earlier_folder(data, run_id=EARLIER_RUN):
    """Make a songs folder that an earlier run wrote: one artist, two songs, one link."""
    folder = paths.country_songs_dir(data, "TGO", run_id)
    folder.mkdir(parents=True)
    song = {
        "country_iso3": "TGO",
        "artist_id": BAND_ONE,
        "artist_name": "Band One",
        "lyrics": "an earlier invented line",
        "lyrics_sha256": "0" * 64,
        "run_id": run_id,
    }
    tables = {
        schemas.COUNTRY_ARTISTS: [
            {
                "country_iso3": "TGO",
                "artist_id": BAND_ONE,
                "artist_name": "Band One (roster)",
                "discogs_artist_id": "123",
                "attempted": False,
                "songs": 2,
            }
        ],
        schemas.COUNTRY_SONGS: [
            song | {"song_id": "site_1", "source": "example_site", "route": "live", "year": 1990},
            song | {"song_id": NEW_SONG, "source": "a.example", "route": "manual_review"},
        ],
        schemas.COUNTRY_LINKS: [
            {
                "country_iso3": "TGO",
                "song_id": "site_1",
                "artist_id": BAND_ONE,
                "discogs_release_id": "9",
                "discogs_track_index": "A1",
                "source": "example_site",
                "match_score": 0.5,
                "run_id": run_id,
            }
        ],
    }
    for table, values in tables.items():
        schemas.write_table(table, schemas.cast_to_schema(table, rows(table, values)), folder)
    manifests.write_manifest(
        data,
        folder,
        "country_songs",
        country_iso3="TGO",
        run_id=run_id,
        inputs=["raw/example_site/20200101/"],
    )
    return folder


def test_only_added_and_finished_songs_are_imported(tmp_path):
    songs, gaps = r.read_added_songs(make_workbook(tmp_path), "TGO")
    assert list(songs["song_name"]) == ["New song", "Far away", "Unknown act"]
    assert songs["year"].fillna(0).tolist() == [2001, 0, 0]  # 3001 is outside the window
    assert songs["discogs_artist_id"].fillna("").tolist() == ["123", "", ""]
    assert songs["country_tag"].fillna("").tolist() == ["Togo", "Togo / France", ""]
    assert list(songs["source"]) == ["a.example", "b.example", "b.example"]
    assert set(songs["route"]) == {"manual_review"}
    assert songs["song_id"].is_unique and songs["song_id"][0] == NEW_SONG
    # The Discogs id decides the artist id; without one, the country and the name do.
    assert list(songs["artist_id"][:2]) == [BAND_ONE, TWO_LANDS]
    assert set(songs["lyrics_sha256"]) == {hashlib.sha256(b"invented line").hexdigest()}
    assert gaps == [
        "1 added songs left out: the review is not finished",
        "1 added songs left out: no lyrics",
        "1 added songs left out: no source link",
        "1 added songs left out: source link appears twice",
        "2 songs have no usable year",
        "1 songs name an artist absent from Artists",
        "2 songs are by an artist with no Discogs id",
        "1 songs are by an artist tagged with more than one country",
    ]


def test_the_command_writes_the_country_tables_a_manifest_and_one_run_record(tmp_path, monkeypatch):
    data, countries = tmp_path / "data", tmp_path / "countries"
    make_workbook(data)
    monkeypatch.setenv(DATA_ROOT_ENV, str(data))
    monkeypatch.setattr(run_records, "countries_dir", lambda: countries)
    result = CliRunner().invoke(app, ["lyrics", "import-review", "tgo"])
    assert result.exit_code == 0, result.output
    assert "3 songs added" in result.output and "invented line" not in result.output
    (record,) = run_records.read_run_records("TGO", countries)
    assert (record.route, record.source, record.state) == (
        "manual_review",
        "review_workbook",
        "complete",
    )
    assert (record.rows_added, record.artists_attempted) == (3, 3)
    assert record.bulk_file == "raw/manual_review/TGO/20261101/TGO_Togo_reviewed.xlsx"

    # With no earlier folder, the new folder holds only the reviewed songs and no links.
    out = paths.latest_country_songs_dir(data, "TGO")
    assert out == data / "lyrics" / "TGO" / "songs" / record.run_id
    songs = schemas.read_table(schemas.COUNTRY_SONGS, out)
    assert songs.project("song_name, year, source, route, run_id").order(
        "song_name"
    ).fetchall() == [
        ("Far away", None, "b.example", "manual_review", record.run_id),
        ("New song", 2001, "a.example", "manual_review", record.run_id),
        ("Unknown act", None, "b.example", "manual_review", record.run_id),
    ]
    assert songs.project("collected_utc, year_source").distinct().fetchall() == [
        (record.started_utc, "manual_review")
    ]
    artists = schemas.read_table(schemas.COUNTRY_ARTISTS, out)
    assert artists.project(
        "artist_name, artist_id, discogs_artist_id, country_tag, attempted, songs"
    ).fetchall() == [
        ("Band One", BAND_ONE, "123", "Togo", True, 1),
        ("Nobody", r.artist_id("TGO", "Nobody", ""), None, None, True, 1),
        ("Two Lands", TWO_LANDS, None, "Togo / France", True, 1),
    ]
    assert len(schemas.read_table(schemas.COUNTRY_LINKS, out)) == 0

    manifest = manifests.read_manifest(out)
    assert (manifest.kind, manifest.country_iso3, manifest.run_id) == (
        "country_songs",
        "TGO",
        record.run_id,
    )
    assert manifest.inputs == ["raw/manual_review/TGO/20261101/"]
    assert manifest.counts == {
        "songs": 3,
        "artists": 3,
        "links": 0,
        "songs_added": 3,
        "songs_replaced": 0,
    }
    # Lyric text stays in the Parquet file.
    for path in (countries / "TGO" / "runs" / record.file_name, out / paths.MANIFEST_NAME):
        assert "invented line" not in path.read_text(encoding="utf-8")
    # The same download is never imported twice.
    with pytest.raises(FileExistsError, match="was imported"):
        r.import_workbook(data, "TGO", countries=countries)


def test_an_import_adds_to_the_newest_songs_folder_of_the_country(tmp_path):
    data, countries = tmp_path / "data", tmp_path / "countries"
    earlier = make_earlier_folder(data)
    before = (earlier / paths.MANIFEST_NAME).read_bytes()
    make_workbook(data)
    result = r.import_workbook(data, "TGO", countries=countries)
    (record,) = run_records.read_run_records("TGO", countries)
    out = paths.latest_country_songs_dir(data, "TGO")
    assert out == result["path"] and out.name == record.run_id and out != earlier

    # One reviewed song replaces an earlier row with the same id; the other two are new.
    assert (result["songs_added"], result["songs_replaced"], result["songs"]) == (2, 1, 4)
    assert record.rows_added == 2
    songs = schemas.read_table(schemas.COUNTRY_SONGS, out)
    assert sorted(songs.project("coalesce(song_name, song_id), route, run_id").fetchall()) == [
        ("Far away", "manual_review", record.run_id),
        ("New song", "manual_review", record.run_id),
        ("Unknown act", "manual_review", record.run_id),
        ("site_1", "live", EARLIER_RUN),
    ]
    assert songs.filter(f"song_id = '{NEW_SONG}'").project("run_id, lyrics, year").fetchall() == [
        (record.run_id, "invented line", 2001)
    ]
    # The earlier artist keeps its roster name, is now attempted, and counts its songs again.
    artists = schemas.read_table(schemas.COUNTRY_ARTISTS, out)
    assert artists.filter(f"artist_id = '{BAND_ONE}'").project(
        "artist_name, country_tag, attempted, last_attempt_utc, songs"
    ).fetchall() == [("Band One (roster)", "Togo", True, record.started_utc, 2)]
    assert len(artists) == 3
    # The links are carried over.
    links = schemas.read_table(schemas.COUNTRY_LINKS, out)
    assert links.project("song_id, discogs_track_index, match_score").fetchall() == [
        ("site_1", "A1", 0.5)
    ]
    manifest = manifests.read_manifest(out)
    assert manifest.inputs == [
        "raw/manual_review/TGO/20261101/",
        f"lyrics/TGO/songs/{EARLIER_RUN}/",
    ]
    assert manifest.counts["links"] == 1 and manifest.counts["songs_replaced"] == 1
    # A version folder is never changed.
    assert (earlier / paths.MANIFEST_NAME).read_bytes() == before
    assert len(schemas.read_table(schemas.COUNTRY_SONGS, earlier)) == 2


def test_an_import_stops_when_the_earlier_folder_is_not_usable(tmp_path):
    data, countries = tmp_path / "data", tmp_path / "countries"
    make_workbook(data)
    later = make_earlier_folder(data, run_id="29990101T000000Z")
    with pytest.raises(ValueError, match="is not older than this run"):
        r.import_workbook(data, "TGO", countries=countries)
    (record,) = run_records.read_run_records("TGO", countries)
    assert record.state == "failed" and record.rows_added is None
    assert paths.latest_country_songs_dir(data, "TGO") == later


def test_a_folder_without_a_manifest_is_not_the_state_of_the_country(tmp_path):
    data, countries = tmp_path / "data", tmp_path / "countries"
    make_workbook(data)
    paths.country_songs_dir(data, "TGO", EARLIER_RUN).mkdir(parents=True)  # a run that stopped
    result = r.import_workbook(data, "TGO", countries=countries)
    assert (result["songs"], result["songs_added"]) == (3, 3)
    assert manifests.read_manifest(result["path"]).inputs == ["raw/manual_review/TGO/20261101/"]


def test_two_names_with_one_discogs_id_are_one_artist(tmp_path):
    songs = [
        ("Band One", "First", "2001", "invented line", "https://a.example/1", ADDED, "Checked"),
        ("B. One", "Second", "2002", "invented line", "https://a.example/2", ADDED, "Checked"),
    ]
    artists = [("Band One", "123", "Togo"), ("B. One", "123", "Togo")]
    make_workbook(tmp_path / "data", songs=songs, artists=artists)
    result = r.import_workbook(tmp_path / "data", "TGO", countries=tmp_path / "countries")
    stored = schemas.read_table(schemas.COUNTRY_ARTISTS, result["path"])
    assert stored.project("artist_name, artist_id, songs").fetchall() == [("Band One", BAND_ONE, 2)]
    names = schemas.read_table(schemas.COUNTRY_SONGS, result["path"]).project("artist_name")
    assert sorted(names.fetchall()) == [("B. One",), ("Band One",)]  # the name as collected stays


def test_a_workbook_with_no_added_song_writes_empty_tables(tmp_path):
    make_workbook(tmp_path / "data", songs=SONGS[:1])
    result = r.import_workbook(tmp_path / "data", "TGO", countries=tmp_path / "countries")
    assert (result["songs"], result["artists"], result["links"], result["songs_added"]) == (
        0,
        0,
        0,
        0,
    )
    assert manifests.read_manifest(result["path"]).counts["songs"] == 0


def test_a_discogs_id_that_is_not_a_number_stops_the_import(tmp_path):
    book = make_workbook(tmp_path, artists=[("Band One", "about 123", "Togo")])
    with pytest.raises(ValueError, match="Discogs artist ID is not a number"):
        r.read_added_songs(book, "TGO")


def test_a_workbook_that_is_not_reviewed_is_refused(tmp_path):
    make_workbook(tmp_path, name="TGO_Togo_ongoing.xlsx")
    with pytest.raises(ValueError, match="not marked _reviewed"):
        r.find_workbook(tmp_path, "TGO")
    make_workbook(tmp_path, name="BEN_Benin_reviewed.xlsx", day="20261102")
    with pytest.raises(ValueError, match="does not start with TGO_"):
        r.find_workbook(tmp_path, "TGO")
    with pytest.raises(FileNotFoundError):
        r.find_workbook(tmp_path, "KEN")
