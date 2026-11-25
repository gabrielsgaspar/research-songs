"""The page parser of cuspajz, on invented pages. No test reads real data or the network.

The fixtures in `tests/fixtures/cuspajz/` copy the tags and classes of the site.
Every name and every lyric line is invented. The packed folder copies the receipt
fields of the Balkan crawl: `http_status`, `response_headers`, gzipped bodies in
dated folders.
"""

import gzip
import json
from pathlib import Path

import duckdb
import pytest

from songs.common import tar_parts as t
from songs.stage_00_ingest import cuspajz as site
from songs.stage_00_ingest import dumps, site_pages

PAGES = Path(__file__).parent / "fixtures" / "cuspajz"
SONG = f"{site.BASE}/tekstovi-pjesama/pjesma/izmisljeni-sastav/izmisljena-pjesma.html"
CRAWL = "data/cuspajz/raw/lyrics/20260925"
PACKED = "raw/cuspajz/20261002/"


def html(name: str) -> str:
    return site_pages.decode((PAGES / name).read_bytes(), None)


def test_a_song_page_gives_its_title_performer_and_lines():
    row, artists, reason = site.parse_song(html("song.html"), SONG)
    assert reason == ""
    assert artists == [("izmisljeni-sastav", "Izmisljeni Sastav")]
    assert row["provider_song_id"] == "izmisljeni-sastav/izmisljena-pjesma"
    assert row["song_name"] == "Izmisljena pjesma"
    assert row["artist_url"] == f"{site.BASE}/tekstovi-pjesama/izvodjac/izmisljeni-sastav.html"
    assert row["lyrics"] == "prvi izmisljeni stih\ndrugi izmisljeni stih\n\ntreci & zadnji stih"
    assert row["text_kind"] == "lyrics"
    assert row["release_year_raw"] is None and row["language_label"] is None


def test_windows_line_ends_give_the_same_lines():
    page = html("song.html").replace("\n", "\r\n")
    assert site.parse_song(page, SONG) == site.parse_song(html("song.html"), SONG)


@pytest.mark.parametrize(
    ("name", "reason"),
    [
        ("artist.html", "no_lyric_block"),
        ("empty_text.html", "empty_text"),
        ("traditional.html", "no_artist"),
    ],
)
def test_a_page_with_no_usable_song_gives_no_row(name, reason):
    assert site.parse_song(html(name), SONG) == (None, [], reason)


def test_a_translation_title_marks_the_text_kind():
    row, _, _ = site.parse_song(html("translation.html"), SONG)
    assert row["text_kind"] == "translation"


def test_song_ids_come_from_song_urls_only():
    assert site.song_id(f"{site.BASE}/tekstovi-pjesama/pjesma/narodna-pjesma.html") == (
        "narodna-pjesma"
    )
    assert site.song_id(f"{site.BASE}/tekstovi-pjesama/izvodjac/izmisljeni-sastav.html") is None
    assert site.song_id(f"{site.BASE}/tekstovi-pjesama/pjesme-po-slovima/A.html") is None


def receipt(key: str, url: str, status: int, error: str = "") -> bytes:
    found = {
        "receipt_id": key,
        "url": url,
        "kind": "song",
        "http_status": status,
        "error": error,
        "content_type": "text/html; charset=UTF-8",
        "response_headers": {"Content-Type": "text/html; charset=UTF-8"},
        "started_at_utc": "2026-09-27T10:00:00+00:00",
        "fetched_at_utc": "2026-09-27T10:00:01+00:00",
        "raw_encoding": "gzip",
    }
    return json.dumps(found).encode("utf-8")


def packed_folder(data: Path, tmp: Path) -> None:
    """Pack invented receipts and gzipped bodies like the Balkan crawl: one tar part."""
    crawl = {
        "k1": (SONG, "song.html", 200, ""),
        "k2": (
            f"{site.BASE}/tekstovi-pjesama/izvodjac/izmisljeni-sastav.html",
            "artist.html",
            200,
            "",
        ),
        "k3": (f"{site.BASE}/tekstovi-pjesama/pjesma/narodna.html", "traditional.html", 200, ""),
        "k4": (f"{site.BASE}/tekstovi-pjesama/pjesma/x/prazna.html", "empty_text.html", 200, ""),
        "k5": (f"{site.BASE}/tekstovi-pjesama/pjesma/x/prijevod.html", "translation.html", 200, ""),
        "k6": (f"{site.BASE}/tekstovi-pjesama/pjesma/x/greska.html", None, 0, "ReadTimeout"),
    }
    tree = tmp / "tree"
    for key, (url, page, status, error) in crawl.items():
        path = tree / CRAWL / "receipts" / f"{key}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(receipt(key, url, status, error))
        if page:
            body = (PAGES / page).read_bytes().replace(b"\n", b"\r\n")
            path = tree / CRAWL / "responses" / "20260927" / f"{key}.body.gz"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(gzip.compress(body))
    folder = data / PACKED
    folder.mkdir(parents=True)
    for part in t.pack(tree, tmp / "work"):
        part.path.replace(folder / part.name)
    t.write_members(tmp / "work", folder)


def test_a_packed_folder_of_the_balkan_crawl_parses_and_builds(tmp_path):
    data = tmp_path / "data"
    packed_folder(data, tmp_path)
    result = site_pages.parse_folder(data, site.SOURCE, PACKED, day="20261003")
    assert result == {
        "path": "raw/cuspajz/20261003/",
        "pages_in": 5,
        "songs_out": 2,
        "left_out_empty_text": 1,
        "left_out_no_artist": 1,
        "left_out_not_song_page": 1,
        "receipts_without_page": 1,
        "credits_out": 2,
    }
    built = dumps.build_dump(
        site.SOURCE, data / result["path"], result["path"], data, day="20261004"
    )
    assert built["songs_out"] == 1
    assert built["dropped"] == {"not_lyrics": 1}
    with duckdb.connect() as connection:
        found = connection.execute(
            "SELECT source_song_id, source_artist_id, artist_name FROM read_parquet(?)",
            [(data / built["path"] / "songs.parquet").as_posix()],
        ).fetchall()
    assert found == [
        ("izmisljeni-sastav/izmisljena-pjesma", "izmisljeni-sastav", "Izmisljeni Sastav")
    ]
