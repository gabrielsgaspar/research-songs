"""Page readers for the Vietnam and Myanmar chord sites. Invented pages only."""

import sys

import pytest

from songs.stage_00_ingest import hopamchuan, hopamviet, loibaihat, musiburma
from songs.stage_00_ingest.pesmarica import is_chord_line

SITES = (hopamviet, loibaihat, hopamchuan, musiburma)


def _hopamviet(chord_only: bool = False) -> tuple[str, str]:
    url = f"{hopamviet.BASE}/chord/song/invented-title/W8IUTEST.html"
    body = (
        "Dm    G7    C\n"
        if chord_only
        else (
            'First invented <span class="chord">[Dm]</span> line\n'
            "Am   G   C\n"
            "Second line [Am] giữ dấu\n"
        )
    )
    html = (
        "<html><body><h1>Invented Title</h1>"
        "<a href='/chord/composer/3/invented-writer.html'>Invented Writer</a>"
        f"<div id='lyric-version-0'>{body}</div></body></html>"
    )
    return url, html


def _loibaihat(chord_only: bool = False) -> tuple[str, str]:
    url = f"{loibaihat.BASE}/lyric/abc12/invented-title/"
    body = (
        "Am G C<br>"
        if chord_only
        else ("<h2>Invented Title</h2>First invented [Am] line<br>Am G C<br>Second line giữ dấu")
    )
    html = (
        "<html><body><h1>Lời bài hát Invented Title</h1>"
        "<a href='/nhac-si/invented-writer/'>Invented Writer</a>"
        f"<div class='lyric-song'>{body}</div></body></html>"
    )
    return url, html


def _hopamchuan(chord_only: bool = False) -> tuple[str, str]:
    url = f"{hopamchuan.BASE}/song/9/invented-title"
    if chord_only:
        lines = "<div class='chord_lyric_line'><span class='hopamchuan_lyric'>Am G C</span></div>"
    else:
        lines = (
            "<div class='chord_lyric_line'><span class='hopamchuan_lyric'>First invented "
            "[Am] line</span><span class='hopamchuan_chord'>C</span></div>"
            "<div class='chord_lyric_line'><span class='hopamchuan_lyric'>Am G C</span></div>"
            "<div class='chord_lyric_line'><span class='hopamchuan_lyric'>Second line giữ dấu"
            "</span></div>"
        )
    html = (
        "<html><body><h1>Invented Title</h1>"
        "<a href='/artist/9/invented-writer'>Invented Writer</a>"
        f"<div id='song-lyric'>{lines}</div></body></html>"
    )
    return url, html


def _musiburma(chord_only: bool = False) -> tuple[str, str]:
    url = f"{musiburma.BASE}/songs/invented-writer/invented-title"
    if chord_only:
        rows = "<div class='flex flex-wrap'><div class='whitespace-pre-wrap'>Am G C</div></div>"
    else:
        rows = (
            "<span class='lyric-section-label'>INTRO</span>"
            "<div class='flex flex-wrap'>"
            "<div class='mb-1'>Am</div><div class='whitespace-pre-wrap'>First invented [Am] </div>"
            "<div class='mb-1'>G</div><div class='whitespace-pre-wrap'>line</div>"
            "</div>"
            "<div class='flex flex-wrap'><div class='whitespace-pre-wrap'>Am G C</div></div>"
            "<div class='flex flex-wrap'><div class='whitespace-pre-wrap'>Second line စမ်း</div>"
            "</div>"
        )
    html = (
        "<html><body><h1>Invented Title</h1>"
        "<a href='/artists/invented-writer'>Invented Writer</a>"
        f"<div id='chord-lyrics-content'>{rows}</div></body></html>"
    )
    return url, html


PAGES = {
    "hopamviet": _hopamviet,
    "loibaihat": _loibaihat,
    "hopamchuan": _hopamchuan,
    "musiburma": _musiburma,
}


@pytest.mark.parametrize("name", PAGES)
def test_a_chord_sheet_keeps_the_lyric_lines(name):
    site = sys.modules[f"songs.stage_00_ingest.{name}"]
    url, html = PAGES[name]()
    row, artists, reason = site.parse_song(html, url)
    assert reason == ""
    assert row["song_name"] == "Invented Title"
    assert row["text_kind"] == "lyrics"
    assert artists[0][1] == "Invented Writer"
    assert "[Am]" not in row["lyrics"] and "<" not in row["lyrics"]
    assert all(not is_chord_line(line) for line in row["lyrics"].splitlines() if line.strip())
    assert "First invented line" in row["lyrics"]
    if name == "musiburma":
        assert "စမ်း" in row["lyrics"] and "INTRO" not in row["lyrics"]
    else:
        assert "giữ dấu" in row["lyrics"]


@pytest.mark.parametrize("name", PAGES)
def test_a_chord_only_page_gives_no_lyric(name):
    site = sys.modules[f"songs.stage_00_ingest.{name}"]
    url, html = PAGES[name](chord_only=True)
    assert site.parse_song(html, url)[0] is None


def test_a_translation_title_is_not_a_lyric():
    url, html = _loibaihat()
    html = html.replace("Invented Title", "Ban dich gia")
    row, _artists, reason = loibaihat.parse_song(html, url)
    assert row is None and reason == "translation"


def test_song_ids_come_from_song_urls_only():
    assert hopamviet.song_id(f"{hopamviet.BASE}/chord/song/invented/W8IUTEST.html") == "W8IUTEST"
    assert hopamviet.song_id(f"{hopamviet.BASE}/info/singers") is None
    assert loibaihat.song_id(f"{loibaihat.BASE}/lyric/abc12/invented/") == "abc12"
    assert hopamchuan.song_id(f"{hopamchuan.BASE}/song/9/invented") == "9"
    assert hopamchuan.song_id(f"{hopamchuan.BASE}/song/create") is None
    assert musiburma.song_id(f"{musiburma.BASE}/songs/invented-writer/invented-title") == (
        "invented-writer/invented-title"
    )
    assert musiburma.song_id(f"{musiburma.BASE}/api/songs") is None
