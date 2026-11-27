"""The page reader of `aama`. The fixture page is invented."""

from pathlib import Path

from songs.stage_00_ingest import aama, site_crawl, site_pages

PAGE = (Path(__file__).parent / "fixtures" / "aama" / "song.html").read_text(encoding="utf-8")
URL = aama.BASE + "/lyrics/invented-title"


def test_the_reader_is_a_site_and_a_live_source():
    assert site_pages.site_module("aama") is aama
    assert "aama" in site_crawl.SOURCES


def test_a_song_page_gives_the_singer_the_year_and_the_lines():
    row, artists, reason = aama.parse_song(PAGE, URL)
    assert reason == ""
    assert artists == [("invented-singer", "Invented Singer")]
    assert row["provider_song_id"] == "invented-title"
    assert row["song_name"] == "Invented Title"
    assert row["artist_url"] == aama.BASE + "/artist/invented-singer"
    assert row["release_year_raw"] == "1987 م"
    assert row["language_label"] == "ar"
    assert row["lyrics"] == ("First invented line\nSecond & invented line\n\nكلمة مخترعة أولى")
    assert set(row) == set(aama.COLUMNS)


def test_a_page_without_a_year_or_without_a_part_gives_none_for_it():
    row, _artists, _reason = aama.parse_song(PAGE.replace(',"datePublished":"1987 م"', ""), URL)
    assert row["release_year_raw"] is None
    assert aama.parse_song(PAGE.replace("MusicComposition", "Thing"), URL)[2] == "no_song_schema"
    assert aama.parse_song(PAGE.replace("lyrics-text", "other"), URL)[2] == "no_lyric_block"
    assert aama.parse_song(PAGE.replace('"recordedAs"', '"other"'), URL)[2] == "no_artist"


def test_the_crawl_asks_for_the_lyrics_address_of_each_song_link():
    assert aama.canonicalize("/songs/invented-title.html") == URL
    assert aama.canonicalize(aama.BASE + "/lyrics/%D9%83%D9%84") == aama.BASE + "/lyrics/كل"
    assert (
        aama.canonicalize("/artist/invented-singer.html") == aama.BASE + "/artist/invented-singer"
    )
    assert aama.canonicalize("/artists/%D9%85") == aama.BASE + "/artists/م"
    for unwanted in ("/songs/create", "/search?q=invented", "/takedown", "https://example.org/"):
        assert aama.canonicalize(unwanted) is None
    assert aama.song_id(aama.BASE + "/artist/invented-singer") is None
    assert aama.is_artist_page(aama.BASE + "/artist/invented-singer")
    assert aama.is_listing(aama.BASE + "/artists/م") and not aama.is_listing(URL)
    assert site_crawl._linked(aama, PAGE, URL) == [
        aama.BASE + "/",
        aama.BASE + "/artists/م",
        aama.BASE + "/artist/invented-singer",
        aama.BASE + "/artist/invented-poet",
        aama.BASE + "/lyrics/other-invented-title",
        aama.BASE + "/lyrics/third-invented-title",
    ]


def test_the_collector_takes_a_country_of_the_language_of_the_source(tmp_path):
    def fetch(url: str) -> tuple[int, dict[str, str], bytes]:
        return 403, {}, b""

    result = site_crawl.collect(
        tmp_path / "data", "aama", "SAU", fetch=fetch, countries=tmp_path / "countries"
    )
    assert result["requests_sent"] == 1 and result["state"] == "partial"
