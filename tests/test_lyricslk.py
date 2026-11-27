"""The page reader of lyricslk and its crawl, on an invented page. No test uses the network."""

from pathlib import Path

from songs.stage_00_ingest import lyricslk, site_crawl, site_pages

PAGE = (Path(__file__).parent / "fixtures" / "lyricslk" / "song.html").read_text(encoding="utf-8")
URL = f"{lyricslk.BASE}/song/invented-singer/invented-title"


def test_the_singers_are_the_artists_and_the_sinhala_text_is_kept():
    row, artists, reason = lyricslk.parse_song(PAGE, URL)
    assert reason == ""
    assert artists == [("invented-singer", "Invented Singer"), ("second-singer", "Second Singer")]
    assert row["provider_song_id"] == "invented-singer/invented-title"
    assert row["song_name"] == "Invented Title"
    assert row["artist_name"] == "Invented Singer"
    assert row["artist_url"] == f"{lyricslk.BASE}/artist/invented-singer"
    assert row["language_label"] == "si"
    assert row["release_year_raw"] is None
    assert row["lyrics"].splitlines() == [
        "කඛග ඝඞච ඡජඣ ඤටඨ",
        "ඩඪණ තථද ධනප ඵබභ",
        "",
        "මයර ලවශ ෂසහ ළෆඅ",
    ]


def test_a_page_with_no_sinhala_text_gives_the_latin_text():
    html = PAGE.replace("data-lyrics-si", "data-other")
    row, _artists, reason = lyricslk.parse_song(html, URL)
    assert reason == ""
    assert row["language_label"] == "si-Latn"
    assert row["lyrics"].startswith("First invented line\nSecond invented line\n\nThird")
    assert "Copied" not in row["lyrics"]


def test_a_page_with_no_text_or_no_singer_gives_no_song():
    no_text = PAGE.replace("data-lyrics-si", "data-other").replace("data-lyrics-en", "data-other")
    assert lyricslk.parse_song(no_text, URL)[2] == "no_lyric_block"
    assert lyricslk.parse_song(PAGE.replace("data-artist-en", "data-other"), URL)[2] == "no_artist"


def test_a_page_that_sends_the_browser_to_another_url_gives_no_song():
    html = '<html><head><meta id="__next-page-redirect" http-equiv="refresh"/></head></html>'
    assert lyricslk.parse_song(html, URL) == (None, [], "redirect")


def test_song_ids_and_listings_come_from_the_url():
    assert lyricslk.song_id(f"{lyricslk.BASE}/artist/invented-singer") is None
    assert lyricslk.is_artist_page(f"{lyricslk.BASE}/artist/invented-singer")
    assert lyricslk.is_listing(f"{lyricslk.BASE}/sitemap.xml")
    assert not lyricslk.is_listing(URL)
    assert not lyricslk.is_listing(f"{lyricslk.BASE}/lyricists")


def test_the_crawl_reads_the_sitemap_and_skips_search_pages(tmp_path):
    asked: list[str] = []
    sitemap = (
        f"<urlset><url><loc>{URL}</loc></url><url><loc>{lyricslk.BASE}/api/x</loc></url></urlset>"
    )

    def fetch(url: str) -> tuple[int, dict[str, str], bytes]:
        asked.append(url)
        if url.endswith("/robots.txt"):
            return 200, {"Content-Type": "text/plain"}, b"User-agent: *\nDisallow: /api/\n"
        if url.endswith("/sitemap.xml"):
            return 200, {"Content-Type": "application/xml"}, sitemap.encode("utf-8")
        if url == URL:
            return 200, {"Content-Type": "text/html"}, PAGE.encode("utf-8")
        return 200, {"Content-Type": "text/html"}, b"<html></html>"

    result = site_crawl.collect(
        tmp_path / "data",
        "lyricslk",
        "LKA",
        fetch=fetch,
        sleep=lambda _seconds: None,
        countries=tmp_path / "countries",
        day="20261127",
    )
    assert result["songs_written"] == 1
    assert not any("/api/" in url or "/search" in url for url in asked)
    parsed = site_pages.parse_folder(tmp_path / "data", "lyricslk", result["path"], day="20261128")
    assert parsed["songs_out"] == 1
