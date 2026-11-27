"""The page reader of afghansonglyrics. Invented pages only."""

from songs.stage_00_ingest import afghansonglyrics, site_crawl

URL = f"{afghansonglyrics.BASE}/Artist/Lyrics/77/Invented-Title"


def _panel(kind: str, title: str, singer: str, slug: str, lyric: str) -> str:
    return (
        f"<div class='panel panel-warning {kind}'><div class='panel-heading'><h1>{title}<br />"
        f"<small>by</small><a href='/Artist/Albums/9/{slug}'>{singer}</a></h1></div>"
        f"<div class='panel-body'><div class='lyric'>{lyric}</div></div></div>"
    )


def _page(native: str = "<p>خط یک ساختگی<br />خط دو</p>\n<p>خط سه</p>") -> str:
    return (
        "<html><body><a href='/Artist/All-Lyrics/9/Invented-Singer'>Lyrics (2)</a>"
        + _panel("dari-text", "عنوان ساختگی", "خواننده", "x", native)
        + "<input type='hidden' id='engTitle' value='Invented Title' />"
        + _panel(
            "en-text",
            "Invented Title",
            "Invented Singer",
            "Invented-Singer",
            "<p>First invented line<br />Second line</p>",
        )
        + "<a href='/Artist/Albums/3/Other'>Other Singer</a></body></html>"
    )


def test_a_song_page_gives_the_latin_title_and_singer_and_the_native_text():
    row, artists, reason = afghansonglyrics.parse_song(_page(), URL)
    assert reason == ""
    assert artists == [("9/Invented-Singer", "Invented Singer"), ("9/Invented-Singer", "خواننده")]
    assert row["provider_song_id"] == "77"
    assert row["song_name"] == "Invented Title"
    assert row["artist_name"] == "Invented Singer"
    assert row["artist_url"] == f"{afghansonglyrics.BASE}/Artist/All-Lyrics/9/Invented-Singer"
    assert row["lyrics"] == "خط یک ساختگی\nخط دو\n\nخط سه"
    assert row["release_year_raw"] is None


def test_an_empty_native_panel_gives_the_latin_text():
    row, _artists, _reason = afghansonglyrics.parse_song(_page(native=" "), URL)
    assert row["lyrics"] == "First invented line\nSecond line"


def test_a_page_with_no_text_gives_no_song():
    html = _page(native="").replace("First invented line<br />Second line", "")
    assert afghansonglyrics.parse_song(html, URL) == (None, [], "no_lyric_block")


def test_the_crawl_takes_songs_and_singer_lists_only():
    base = afghansonglyrics.BASE
    html = (
        "<a href='/Artist/Lyrics/77/Invented-Title'>a</a>"
        "<a href='/Artist/All-Lyrics/9/Invented-Singer'>b</a>"
        "<a href='/Home/Browse?page=3'>3</a><a href='/Home/Browse?alphabet=B'>B</a>"
        "<a href='/Artist/Albums/9/Invented-Singer'>c</a><a href='/Account/Login'>d</a>"
    )
    assert site_crawl._linked(afghansonglyrics, html, base + "/Home/Browse") == [
        URL,
        base + "/Artist/All-Lyrics/9/Invented-Singer",
        base + "/Home/Browse?page=3",
        base + "/Home/Browse",
        base + "/Home/Browse?page=2",
    ]
    assert afghansonglyrics.song_id(base + "/Artist/All-Lyrics/9/Invented-Singer") is None
    assert afghansonglyrics.is_artist_page(base + "/Artist/All-Lyrics/9/Invented-Singer")
    assert not afghansonglyrics.is_artist_page(base + "/Home/Browse")
