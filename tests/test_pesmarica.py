"""The page parser of pesmarica, on invented pages. No test reads real data or the network.

The fixtures in `tests/fixtures/pesmarica/` copy the tags, classes and JSON-LD of the
site. Every name, chord sheet and lyric line is invented.
"""

from pathlib import Path

import pytest

from songs.stage_00_ingest import pesmarica as site
from songs.stage_00_ingest import site_pages

PAGES = Path(__file__).parent / "fixtures" / "pesmarica"
SONG = f"{site.BASE}/akordi/501/Izmisljeni-Bend--Izmisljena-Pesma"


def html(name: str) -> str:
    return site_pages.decode((PAGES / name).read_bytes(), None)


def test_a_chord_sheet_gives_its_lyric_lines_only():
    row, artists, reason = site.parse_song(html("song.html"), SONG)
    assert reason == ""
    assert artists == [("77", "Izmisljeni Bend")]
    assert row["provider_song_id"] == "501"
    assert row["song_name"] == "Izmisljena Pesma"
    assert row["artist_url"] == f"{site.BASE}/akordi/gitara/77/"
    assert row["lyrics"] == (
        "Prvi izmisljeni stih,\ndrugi izmisljeni stih.\n\n"
        "Al' refren je izmisljen\ntreci stih posle oznake"
    )
    assert row["text_kind"] == "lyrics"
    assert row["language_label"] is None and row["release_year_raw"] is None


@pytest.mark.parametrize(
    "line",
    [
        "Bb    |Ebmaj7 F  |Gm    |D",
        "Intro: E ,C#m A E H E 2x",
        "Uvod /Dm CBF/Gm F Em A7/",
        "Hm Fism D",
        "E-mol A-mol H-dur",
        "dm C dm C",
        "Ref:",
        "[Verse 1]",
        "Str. 1",
        "e|---0---1---3---|",
        "....|....|",
        "Transkripcija: neko",
        "Capo 2",
        "Kapo na II polju",
        "Akorde pisao: neko",
        "Hm,F#.........",
        "Svira se ovako: Dm H Gm",
        "Verse Intro:",
    ],
)
def test_lines_with_no_lyric_are_chord_lines(line):
    assert site.is_chord_line(line)


@pytest.mark.parametrize(
    "line",
    ["", "A ti me ne pitaj", "Da Bog da", "Kraj mene si", "Ref: Da li si", "Am I wrong", "Hej-hej"],
)
def test_lyric_lines_are_no_chord_lines(line):
    assert not site.is_chord_line(line)


@pytest.mark.parametrize(
    ("name", "reason"),
    [
        ("withheld.html", "text_withheld"),
        ("no_artist_page.html", "no_artist"),
        ("artist.html", "no_song_schema"),
    ],
)
def test_a_page_with_no_usable_song_gives_no_row(name, reason):
    assert site.parse_song(html(name), SONG) == (None, [], reason)


def test_song_ids_come_from_song_urls_only():
    assert site.song_id(f"{site.BASE}/akordi/12/Bend--Pesma") == "12"
    assert site.song_id(f"{site.BASE}/akordi/gitara/77/Izmisljeni-Bend") is None
    assert site.song_id(f"{site.BASE}/Akordi/A/0") is None


def test_chords_in_a_lyric_line_go_and_the_words_stay():
    sheet = "[G]Prvi iz[D7]misljeni [G]stih\n[G][G] [Am]\nA ti [ne] znas"
    assert site.lyric_lines(sheet) == ["Prvi izmisljeni stih", " ", "A ti [ne] znas"]
