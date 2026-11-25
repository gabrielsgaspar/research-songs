"""Five page readers of saved lyric sites, on invented pages.

The fixtures in `tests/fixtures/<source>/` copy the tags and classes of each site. Every
name and every lyric line is invented. No test reads real data or the network.
"""

import gzip
import json
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote

import pytest

from songs.common import tar_parts as t
from songs.stage_00_ingest import (
    dumps,
    geolyrics,
    georgianlyrics,
    kyrgyzaudio,
    matinder,
    mediastar,
    site_pages,
)

FIXTURES = Path(__file__).parent / "fixtures"


def html(source: str, name: str) -> str:
    return site_pages.decode((FIXTURES / source / name).read_bytes(), None)


def test_each_reader_is_a_site():
    for site in (geolyrics, georgianlyrics, kyrgyzaudio, matinder, mediastar):
        assert site_pages.site_module(site.SOURCE) is site


def test_song_row_takes_an_artist_url_function_an_artist_without_id_and_a_text_kind():
    site = SimpleNamespace(
        COLUMNS=(
            "provider_song_id",
            "song_url",
            "song_name",
            "artist_name",
            "artist_url",
            "lyrics",
            "text_kind",
        ),
        ARTIST_URL=lambda artist_id: f"page of {artist_id}",
        INSTRUMENTAL=frozenset(),
        TITLE_KINDS=(),
        song_id=lambda url: url,
    )
    lines = ["", " a  b ", "", "", "", "c", ""]
    row, artists, _ = site_pages.song_row(site, "u", " T ", [("1", "A"), ("1", "A")], lines)
    assert (row["artist_url"], row["lyrics"], artists) == ("page of 1", "a b\n\nc", [("1", "A")])
    row, _, _ = site_pages.song_row(site, "u", "T", [(None, "A")], ["x"], text_kind="translation")
    assert (row["artist_url"], row["text_kind"]) == (None, "translation")


def test_geolyrics_reads_the_georgian_block_only():
    url = f"{geolyrics.BASE}/simgherebi/invented-band/invented_song.html"
    row, artists, reason = geolyrics.parse_song(html("geolyrics", "song.html"), url)
    assert reason == ""
    assert artists == [("invented-band", "Выдуманная группа")]
    assert row["provider_song_id"] == "invented-band/invented_song"
    assert row["song_name"] == "გამოგონილი სიმღერა"
    assert row["artist_url"] == f"{geolyrics.BASE}/simgherebi/singer/invented-band.html"
    assert row["lyrics"] == (
        "პირველი გამოგონილი სტრიქონი\nმეორე გამოგონილი სტრიქონი\n\nმესამე სტრიქონი"
    )
    assert geolyrics.song_id(f"{geolyrics.BASE}/simgherebi/singer/invented-band.html") is None
    assert geolyrics.parse_song(html("geolyrics", "no_text.html"), url) == (
        None,
        [],
        "no_lyric_block",
    )


def test_georgianlyrics_credits_the_person_tags_and_reads_the_post_body():
    url = f"{georgianlyrics.BASE}/{quote('სიმღერის-ტექსტი')}/x-y/"
    row, artists, reason = georgianlyrics.parse_song(html("georgianlyrics", "song.html"), url)
    assert reason == ""
    assert artists == [
        ("invented-composer", "Invented Composer"),
        ("invented-singer", "Invented Singer"),
    ]
    assert row["provider_song_id"] == "სიმღერის-ტექსტი/x-y"
    assert row["song_name"] == "გამოგონილი სიმღერა"
    assert row["artist_url"] == f"{georgianlyrics.BASE}/tag/invented-composer/"
    assert row["lyrics"] == (
        "პირველი გამოგონილი სტრიქონი,\nმეორე გამოგონილი სტრიქონი,\n\nმესამე სტრიქონი."
    )
    assert georgianlyrics.song_id(f"{georgianlyrics.BASE}/tag/invented-singer/") is None


@pytest.mark.parametrize(
    ("name", "reason"), [("genre_only.html", "no_artist"), ("listing.html", "no_lyric_block")]
)
def test_georgianlyrics_gives_no_row_without_a_person_or_a_post(name, reason):
    url = f"{georgianlyrics.BASE}/საგალობელი/x/"
    assert georgianlyrics.parse_song(html("georgianlyrics", name), url) == (None, [], reason)


def test_mediastar_reads_the_performers_and_drops_the_paragraph_after_each_line():
    url = f"{mediastar.BASE}/index.php?view=songs&songId=11001"
    row, artists, reason = mediastar.parse_song(html("mediastar", "song.html"), url)
    assert reason == ""
    assert artists == [("author-21001", "Invented Singer"), ("stargroup-40001", "Invented Duo")]
    assert row["provider_song_id"] == "11001"
    assert row["song_name"] == "Ойдан ән"
    assert row["artist_url"] == f"{mediastar.BASE}/index.php?view=authors&authorId=21001"
    assert row["lyrics"] == "Бірінші ойдан жол,\nЕкінші ойдан жол.\nҮшінші жол."
    assert mediastar.song_id(f"{mediastar.BASE}/index.php?view=songs&songType=00") is None
    no_performer = html("mediastar", "no_performer.html")
    assert mediastar.parse_song(no_performer, url) == (None, [], "no_artist")


def test_kyrgyzaudio_reads_the_artist_page_title_and_text_without_the_notes():
    url = f"{kyrgyzaudio.BASE}/invented-singer-invented-song-teksti/"
    row, artists, reason = kyrgyzaudio.parse_song(html("kyrgyzaudio", "song.html"), url)
    assert reason == ""
    assert artists == [("muzyka/invented-singer", "Invented Singer")]
    assert row["provider_song_id"] == "invented-singer-invented-song-teksti"
    assert row["song_name"] == "Invented Song"
    assert row["artist_url"] == f"{kyrgyzaudio.BASE}/muzyka/invented-singer/"
    assert row["lyrics"] == "Биринчи ойдон сап\nЭкинчи ойдон сап\n\nКайырма:\nҮчүнчү сап"
    assert kyrgyzaudio.song_id(f"{kyrgyzaudio.BASE}/muzyka/invented-singer/") is None


@pytest.mark.parametrize(
    ("name", "reason"), [("book.html", "not_song"), ("mp3_only.html", "empty_text")]
)
def test_kyrgyzaudio_gives_no_row_for_a_book_or_a_post_without_text(name, reason):
    url = f"{kyrgyzaudio.BASE}/x/"
    assert kyrgyzaudio.parse_song(html("kyrgyzaudio", name), url) == (None, [], reason)


@pytest.mark.parametrize(
    ("heading", "artist", "title"),
    [
        ("Invented Singer — Invented Song", "Invented Singer", "Invented Song"),
        ("Invented Singer, Guest — Invented Song", "Invented Singer", "Invented Song"),
        ("Invented — Band — Song — Part", "Invented - Band", "Song — Part"),
        ("Invented Singer. Invented Song тексти жана mp3", "Invented Singer", "Invented Song"),
        ("Invented Song тексти / Жаңы ыр 2026", "Other", "Invented Song"),
        ("Invented Singer » Invented Song —", "Invented Singer", "Invented Song"),
    ],
)
def test_kyrgyzaudio_title_leaves_out_the_artist_and_the_site_words(heading, artist, title):
    assert kyrgyzaudio._title(heading, artist) == title


def test_matinder_reads_the_artist_links_and_the_line_blocks_without_scripts():
    url = f"{matinder.BASE}/song/invented-singer-invented-guest/oydan-an"
    row, artists, reason = matinder.parse_song(html("matinder", "song.html"), url)
    assert reason == ""
    assert artists == [("invented-singer", "Invented Singer"), ("invented-guest", "Invented Guest")]
    assert row["provider_song_id"] == "invented-singer-invented-guest/oydan-an"
    assert row["song_name"] == "Ойдан ән"
    assert row["artist_url"] == f"{matinder.BASE}/artist/invented-singer"
    assert row["lyrics"] == "Бірінші ойдан жол\nЕкінші ойдан жол\n\nҚайырмасы:\nҮшінші жол"
    assert row["text_kind"] == "lyrics"
    assert matinder.parse_song(html("matinder", "empty.html"), url) == (None, [], "empty_text")


def test_matinder_marks_a_translation_page_and_reads_the_www_address():
    url = "https://www.matinder.kz/song/translation/invented-singer/oydan-an"
    row, _, _ = matinder.parse_song(html("matinder", "song.html"), url)
    assert row["provider_song_id"] == "translation/invented-singer/oydan-an"
    assert row["text_kind"] == "translation"
    assert matinder.song_id(f"{matinder.BASE}/artist/invented-singer") is None


def test_a_folder_of_gzipped_responses_in_day_folders_parses(tmp_path):
    """The later crawls write `responses/<day>/<id>.body.gz` and `http_status` receipts."""
    data, crawl = tmp_path / "data", tmp_path / "tree" / "data" / "geolyrics" / "raw" / "c" / "d"
    pages = {
        "r1": (f"{geolyrics.BASE}/simgherebi/invented-band/invented_song.html", "song.html", 200),
        "r2": (f"{geolyrics.BASE}/simgherebi/singer/invented-band.html", "no_text.html", 200),
        "r3": (f"{geolyrics.BASE}/simgherebi/invented-band/lost.html", "no_text.html", 404),
    }
    for key, (url, page, status) in pages.items():
        receipt = {
            "receipt_id": key,
            "url": url,
            "http_status": status,
            "error": "",
            "content_type": "text/html; charset=utf-8",
            "started_at_utc": "2026-11-15T20:12:53+00:00",
        }
        for path, content in (
            (crawl / "receipts" / f"{key}.json", json.dumps(receipt).encode("utf-8")),
            (
                crawl / "responses" / "20261115" / f"{key}.body.gz",
                gzip.compress((FIXTURES / "geolyrics" / page).read_bytes()),
            ),
        ):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
    folder = data / "raw" / "geolyrics" / "20261116"
    folder.mkdir(parents=True)
    for part in t.pack(tmp_path / "tree", tmp_path / "work"):
        part.path.replace(folder / part.name)
    t.write_members(tmp_path / "work", folder)

    result = site_pages.parse_folder(data, "geolyrics", "raw/geolyrics/20261116/", day="20261125")
    assert result == {
        "path": "raw/geolyrics/20261125/",
        "pages_in": 3,
        "songs_out": 1,
        "left_out_error_status": 1,
        "left_out_not_song_page": 1,
        "credits_out": 1,
    }
    built = dumps.build_dump(
        "geolyrics", data / result["path"], result["path"], data, day="20261126"
    )
    assert built["songs_out"] == 1
