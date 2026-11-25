"""The page parser of textpesenok, on invented pages. No test reads real data or the network.

The fixtures in `tests/fixtures/textpesenok/` copy the tags and classes of the site.
Every name and every lyric line is invented.
"""

import json
from pathlib import Path

import duckdb
import pytest

from songs.common import manifests, paths
from songs.common import tar_parts as t
from songs.stage_00_ingest import dumps, site_pages
from songs.stage_00_ingest import textpesenok as site

PAGES = Path(__file__).parent / "fixtures" / "textpesenok"
BASE = site.BASE
CRAWL = "raw/text_pesenok_lyrics/20260924"
PACKED = "raw/textpesenok/20260101/"


def html(name: str) -> str:
    return site_pages.decode((PAGES / name).read_bytes(), None)


def test_a_song_page_gives_its_title_performers_and_lines():
    row, artists, reason = site.parse_song(html("song.html"), f"{BASE}/t1-invented-title")
    assert reason == ""
    assert artists == [("101", "Invented Band"), ("102", "Made-Up Guest")]
    assert row["provider_song_id"] == "1"
    assert row["song_name"] == "Invented Title & Co"
    assert row["artist_name"] == "Invented Band"
    assert row["artist_url"] == f"{BASE}/artist-101"
    assert row["lyrics"] == "first invented line\nsecond invented line\n\nвыдуманная строка три"
    assert row["text_kind"] == "lyrics"


@pytest.mark.parametrize(
    ("name", "reason"),
    [
        ("artist.html", "no_lyric_block"),
        ("empty_text.html", "empty_text"),
        ("instrumental.html", "instrumental"),
    ],
)
def test_a_page_with_no_lyric_gives_no_row(name, reason):
    assert site.parse_song(html(name), f"{BASE}/t2-x") == (None, [], reason)


def test_a_translation_title_marks_the_text_kind():
    row, _, _ = site.parse_song(html("translation.html"), f"{BASE}/t3-x")
    assert row["text_kind"] == "translation"


def test_a_page_in_another_charset_decodes_by_its_header_or_its_meta():
    body = (PAGES / "song_cp1251.html").read_bytes()
    with pytest.raises(UnicodeDecodeError):
        body.decode("utf-8")
    row, artists, _ = site.parse_song(site_pages.decode(body, None), f"{BASE}/t4-x")
    assert artists == [("103", "Выдуманный певец")]
    assert row["song_name"] == "Выдуманная песня"
    assert site_pages.decode("абв".encode("cp1251"), "text/html; charset=windows-1251") == "абв"
    assert site_pages.decode(b"\xff\xfe\xfa", None) is None


def receipt(key: str, url: str, status: int = 200, error: str = "") -> bytes:
    found = {
        "id": key,
        "url": url,
        "status": status,
        "error": error,
        "headers": {"content-type": "text/html"},
        "body_path": f"responses/{key}.body",
        "started_at": "2026-09-24T23:15:49+00:00",
        "source_evidence": {"requested_at": "2026-09-24T19:34:03+00:00"},
    }
    return json.dumps(found).encode("utf-8")


def packed_folder(data: Path, tmp: Path) -> Path:
    """Pack invented receipts and responses like the archive of the site: one tar part."""
    crawl = {
        "a1": (f"{BASE}/t1-invented-title", "song.html", 200, ""),
        "a2": (f"{BASE}/t1-invented-title", "song.html", 200, ""),
        "a3": (f"{BASE}/artist-101-invented-band", "artist.html", 200, ""),
        "a4": (f"{BASE}/t4-x", "song_cp1251.html", 200, ""),
        "a5": (f"{BASE}/t5-x", "empty_text.html", 200, ""),
        "a6": (f"{BASE}/t6-x", "translation.html", 200, ""),
        "a7": (f"{BASE}/t7-x", None, 0, "ReadTimeout"),
    }
    tree = tmp / "tree"
    for key, (url, page, status, error) in crawl.items():
        for kind, content in (
            ("receipts", receipt(key, url, status, error)),
            ("responses", (PAGES / page).read_bytes() if page else b""),
        ):
            path = tree / CRAWL / kind / f"{key}.{'json' if kind == 'receipts' else 'body'}"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
    folder = data / PACKED
    folder.mkdir(parents=True)
    for part in t.pack(tree, tmp / "work"):
        part.path.replace(folder / part.name)
    t.write_members(tmp / "work", folder)
    return folder


def test_a_packed_folder_parses_to_a_lyric_table_that_the_builder_reads(tmp_path):
    data = tmp_path / "data"
    packed_folder(data, tmp_path)
    result = site_pages.parse_folder(data, site.SOURCE, PACKED, day="20260102")
    assert result == {
        "path": "raw/textpesenok/20260102/",
        "pages_in": 7,
        "songs_out": 3,
        "left_out_error_status": 1,
        "left_out_not_song_page": 1,
        "left_out_empty_text": 1,
        "left_out_duplicate_url": 1,
        "credits_out": 4,
    }
    folder = data / result["path"]
    manifest = manifests.read_manifest(folder)
    assert manifest.inputs == [PACKED]
    with duckdb.connect() as connection:
        columns = {
            row[0]
            for row in connection.execute(
                "DESCRIBE SELECT * FROM read_parquet(?)",
                [(folder / f"{site.SOURCE}_lyrics.parquet").as_posix()],
            ).fetchall()
        }
    assert dumps.detect_family(columns) == "site_snapshot"

    built = dumps.build_dump(site.SOURCE, folder, result["path"], data, day="20260103")
    assert built["family"] == "site_snapshot"
    assert built["songs_out"] == 2
    assert built["dropped"] == {"not_lyrics": 1}
    with duckdb.connect() as connection:
        credits = connection.execute(
            "SELECT source_song_id, credit_position, source_artist_id, artist_name "
            "FROM read_parquet(?) ORDER BY 1, 2",
            [(data / built["path"] / "songs.parquet").as_posix()],
        ).fetchall()
    assert credits == [
        ("1", 1, "101", "Invented Band"),
        ("1", 2, "102", "Made-Up Guest"),
        ("4", 1, "103", "Выдуманный певец"),
    ]

    with pytest.raises(FileExistsError):
        site_pages.parse_folder(data, site.SOURCE, PACKED, day="20260102")


def test_a_folder_of_another_source_is_refused(tmp_path):
    (tmp_path / "raw" / "other" / "20260101").mkdir(parents=True)
    with pytest.raises(site_pages.ParseError):
        site_pages.parse_folder(tmp_path, site.SOURCE, "raw/other/20260101/", day="20260102")
    assert not paths.raw_dir(tmp_path, site.SOURCE, "20260102").exists()


def test_a_source_with_no_page_reader_is_refused():
    with pytest.raises(site_pages.ParseError):
        site_pages.site_module("no_such_site")
    assert site_pages.site_module(site.SOURCE) is site
