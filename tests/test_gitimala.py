"""The page reader of the Bengali lyric site gitimala. Invented pages only."""

from songs.stage_00_ingest import gitimala, site_crawl

URL = f"{gitimala.BASE}/lyrics/invented-title/"


def _page(title: str = "Invented Title &#8211; গান", artist: bool = True) -> str:
    link = f"<a href='{gitimala.BASE}/artist/invented-singer/'>Invented Singer</a>"
    return (
        "<html><body><a href='/artist/menu-name/'>Menu Name</a>"
        f'<div class="lyrics-title"><h3>{link if artist else ""}</h3>'
        f'<div class="pull-left"><h1>{title}</h1></div>'
        f"<h4>in <a href='{gitimala.BASE}/album/invented-album/'>Invented Album</a></h4></div>"
        '<article><div class="\nlyric-text margint20">\n'
        '<div class="ads"><script>var ad = 1;</script></div>\n'
        "<p>First invented line<br />\nSecond line গান</p>\n<p>Third line</p>\n"
        "<!-- Facebook Comments Plugin --><h3>Comments</h3><p>0 comments</p>"
        f"<ul class='related-list'><li><a href='{gitimala.BASE}/lyrics/second-title/'>Second"
        "</a></li></ul></div>"
        '<div class="\nlyric-bottom clearfix"><p>Added by</p></div></article></body></html>'
    )


def test_a_song_page_gives_the_singer_the_latin_title_and_the_album():
    row, artists, reason = gitimala.parse_song(_page(), URL)
    assert reason == ""
    assert artists == [("invented-singer", "Invented Singer")]
    assert row["song_name"] == "Invented Title"
    assert row["artist_url"] == f"{gitimala.BASE}/artist/invented-singer/"
    assert row["album_name"] == "Invented Album"
    assert row["release_year_raw"] is None
    assert row["lyrics"] == "First invented line\nSecond line গান\n\nThird line"


def test_a_title_in_one_script_stays_whole():
    assert gitimala.latin_title("গান") == "গান"
    assert gitimala.latin_title("Invented - Title") == "Invented - Title"
    assert gitimala.latin_title("গান – Invented Title") == "Invented Title"


def test_a_page_with_no_artist_or_no_lyric_block_gives_no_song():
    assert gitimala.parse_song(_page(artist=False), URL)[2] == "no_artist"
    assert gitimala.parse_song("<html><h1>Invented</h1></html>", URL)[2] == "no_lyric_block"
    row, _artists, _reason = gitimala.parse_song(_page("Invented Title Chords"), URL)
    assert row["text_kind"] == "chords"


def test_song_ids_come_from_song_urls_only():
    assert gitimala.song_id(URL) == "invented-title"
    assert gitimala.song_id(f"{gitimala.BASE}/lyrics/invented-%e0%a6%97/") == "invented-গ"
    assert gitimala.song_id(f"{gitimala.BASE}/lyrics/") is None
    assert gitimala.song_id(f"{gitimala.BASE}/artist/invented-singer/") is None
    assert gitimala.is_artist_page(f"{gitimala.BASE}/artist/invented-singer/")


def test_the_crawl_follows_lyric_sitemaps_and_song_pages_only():
    index = (
        f"<loc>{gitimala.BASE}/lyrics-sitemap2.xml</loc><loc>{gitimala.BASE}/artist-sitemap.xml"
        f"</loc><loc>{gitimala.BASE}/wp-content/x.jpg</loc>"
    )
    found = site_crawl._linked(gitimala, index, gitimala.SEEDS[0])
    assert found == [f"{gitimala.BASE}/lyrics-sitemap2.xml"]
    assert site_crawl._linked(gitimala, _page(), URL) == [f"{gitimala.BASE}/lyrics/second-title/"]
    assert site_crawl.SOURCES.count("gitimala") == 1
