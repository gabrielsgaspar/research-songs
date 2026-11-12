"""The import of a country review workbook, on a small invented workbook."""

import duckdb
import pandas as pd
import pytest
from typer.testing import CliRunner

from songs.cli import app
from songs.common import run_records
from songs.common.paths import DATA_ROOT_ENV
from songs.stage_00_ingest import review_workbooks as r

ADDED, OLD = r.ADDED, "Link in our files"
# Artist, title, year, lyrics, link, link check, review status. All text is invented.
SONGS = [
    ("Band One", "Already here", "1990", "la la", "https://a.example/1", OLD, "Checked"),
    ("Band One", "New song", "2001", "invented line", "https://www.a.example/2", ADDED, "Checked"),
    ("Two Lands", "Far away", "", "invented line", "https://b.example/3", ADDED, "Done"),
    ("Nobody", "Unknown act", "3001", "invented line", "https://b.example/4", ADDED, "Checked"),
    ("Band One", "Not checked", "2002", "invented line", "https://a.example/5", ADDED, ""),
    ("Band One", "No words", "2003", "", "https://a.example/6", ADDED, "Checked"),
    ("Band One", "No link", "2004", "invented line", "not sure", ADDED, "Checked"),
    ("Band One", "Twice", "2005", "invented line", "https://www.a.example/2", ADDED, "Checked"),
]
ARTISTS = [("Band One", "123", "Togo"), ("Two Lands", "", "Togo / France")]


def make_workbook(data, name="TGO_Togo_reviewed.xlsx", day="20261101"):
    folder = data / "raw" / "manual_review" / "TGO" / day
    folder.mkdir(parents=True)
    songs = pd.DataFrame(
        [
            (a, t, y, "French", text, url, check, status)
            for a, t, y, text, url, check, status in SONGS
        ],
        columns=list(r.SONG_COLUMNS),
    )
    with pd.ExcelWriter(folder / name) as writer:
        songs.to_excel(writer, sheet_name="Songs", index=False)
        pd.DataFrame(ARTISTS, columns=list(r.ARTIST_COLUMNS)).to_excel(
            writer, sheet_name="Artists", index=False
        )
    return folder / name


def test_only_added_and_checked_songs_are_imported(tmp_path):
    songs, gaps = r.read_added_songs(make_workbook(tmp_path), "TGO")
    assert list(songs.columns) == list(r.OUTPUT_COLUMNS)
    assert list(songs["song_name"]) == ["New song", "Far away", "Unknown act"]
    assert songs["year"].fillna(0).tolist() == [2001, 0, 0]  # 3001 is outside the window
    assert songs["discogs_artist_id"].fillna("").tolist() == ["123", "", ""]
    assert list(songs["source_host"]) == ["a.example", "b.example", "b.example"]
    assert set(songs["origin"]) == {"manual_review"}
    assert songs["song_id"].is_unique
    assert gaps == [
        "1 added songs left out: review status is not Checked or Done",
        "1 added songs left out: no lyrics",
        "1 added songs left out: no source link",
        "1 added songs left out: source link appears twice",
        "2 songs have no usable year",
        "1 songs name an artist absent from Artists",
        "2 songs are by an artist with no Discogs id",
        "1 songs are by an artist tagged with more than one country",
    ]


def test_the_command_writes_the_songs_and_one_run_record(tmp_path, monkeypatch):
    data, countries = tmp_path / "data", tmp_path / "countries"
    make_workbook(data)
    monkeypatch.setenv(DATA_ROOT_ENV, str(data))
    monkeypatch.setattr(run_records, "countries_dir", lambda: countries)
    result = CliRunner().invoke(app, ["lyrics", "import-review", "tgo"])
    assert result.exit_code == 0, result.output
    (record,) = run_records.read_run_records("TGO", countries)
    assert (record.route, record.source, record.state) == (
        "manual_review",
        "review_workbook",
        "complete",
    )
    assert (record.rows_added, record.artists_attempted) == (3, 3)
    assert record.bulk_file == "raw/manual_review/TGO/20261101/TGO_Togo_reviewed.xlsx"
    assert "invented line" not in (countries / "TGO" / "runs" / record.file_name).read_text(
        encoding="utf-8"
    )
    out = data / "lyrics" / "TGO" / "manual_review" / record.run_id / "songs.parquet"
    stored = duckdb.read_parquet(str(out))
    assert stored.columns == list(r.OUTPUT_COLUMNS)
    assert stored.fetchall()[0][6:8] == (2001, "manual_review")
    # The same download is never imported twice.
    with pytest.raises(FileExistsError, match="was imported"):
        r.import_workbook(data, "TGO", countries=countries)


def test_a_workbook_that_is_not_reviewed_is_refused(tmp_path):
    make_workbook(tmp_path, name="TGO_Togo_ongoing.xlsx")
    with pytest.raises(ValueError, match="not marked _reviewed"):
        r.find_workbook(tmp_path, "TGO")
    make_workbook(tmp_path, name="BEN_Benin_reviewed.xlsx", day="20261102")
    with pytest.raises(ValueError, match="does not start with TGO_"):
        r.find_workbook(tmp_path, "TGO")
    with pytest.raises(FileNotFoundError):
        r.find_workbook(tmp_path, "KEN")
