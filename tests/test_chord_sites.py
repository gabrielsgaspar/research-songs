"""Page readers and the shared crawl, on invented pages. No test uses the network."""

from songs.stage_00_ingest import hopamviet, loibaihat, musiburma, site_crawl

HOPAM = """<!DOCTYPE html><html><body>
<h1>Invented Title</h1>
<a href="https://hopamviet.vn/chord/composer/9/invented-writer.html">Invented Writer</a>
<div id="lyric-version-0">Dòng giả có <span class="chord">[Am]</span> chữ ệ
Am G C F
Dòng thứ hai</div>
</body></html>"""

LOI = """<!DOCTYPE html><html><body>
<h1>Lời bài hát Invented Title</h1>
<table class="lyric-des"><tr><td><b>Nhạc sĩ/ Sáng tác:</b></td>
<td><a href="/nhac-si/invented-writer/">Invented Writer</a></td></tr>
<tr><td><b>Ngôn ngữ:</b></td><td>Gia</td></tr>
<tr><td><b>Năm sáng tác:</b></td><td>1999</td></tr></table>
<div class="lyric-song"><h2>Invented Title</h2>
<div class="abn"><script>advert</script></div>
Dòng [G] giả có chữ ệ<br>
Am G C F<br>
Dòng thứ hai</div>
<div id="commentResult">Đề nghị bỏ qua</div>
</body></html>"""

MUSI = """<!DOCTYPE html><html><body>
<h1 class="song-reader-title">Invented</h1>
<p><a href="/artists/invented-one">Invented One</a>,
<a href="/artists/invented-two">Invented Two</a></p>
<div id="chord-lyrics-content">
<div class="lyric-section-head"><span class="lyric-section-label">INTRO</span></div>
<div class="flex flex-wrap">
<span><div class="mb-1"><span>C</span></div>
<div class="whitespace-pre-wrap">ကခ </div></span>
<span><div class="mb-1"> </div>
<div class="whitespace-pre-wrap">ဂ</div></span>
</div>
<div class="flex flex-wrap"><div class="whitespace-pre-wrap">C G Am F</div></div>
</div>
</body></html>"""


def test_hopamviet_drops_chord_lines_and_chords_inside_a_line():
    url = "https://hopamviet.vn/chord/song/invented/AAA111.html"
    row, artists, reason = hopamviet.parse_song(HOPAM, url)
    assert reason == ""
    assert artists == [("composer/9/invented-writer.html", "Invented Writer")]
    assert row["song_name"] == "Invented Title"
    assert row["lyrics"] == "Dòng giả có chữ ệ\nDòng thứ hai"
    assert row["text_kind"] == "lyrics"
    assert "[" not in row["lyrics"]


def test_hopamviet_drops_a_translation_and_a_chord_only_page():
    url = "https://hopamviet.vn/chord/song/invented/AAA111.html"
    translated = HOPAM.replace("Invented Title", "Invented ban dich")
    assert hopamviet.parse_song(translated, url)[2] == "translation"
    chords = HOPAM.replace('Dòng giả có <span class="chord">[Am]</span> chữ ệ', "Am")
    chords = chords.replace("Dòng thứ hai", "G C")
    assert hopamviet.parse_song(chords, url)[2] == "empty_text"


def test_loibaihat_uses_the_singer_names_when_the_page_has_no_artist_link():
    html = LOI.replace(
        '<a href="/nhac-si/invented-writer/">Invented Writer</a>',
        "",
    ).replace(
        "Năm sáng tác:",
        "Các ca sĩ thể hiện:</b></td><td>Invented One, Invented Two</td></tr>"
        "<tr><td><b>Năm sáng tác:",
    )
    row, artists, reason = loibaihat.parse_song(html, "https://loibaihat.biz/lyric/abc12/invented/")
    assert reason == ""
    assert artists == [(None, "Invented One"), (None, "Invented Two")]
    assert row["artist_url"] is None
    assert row["lyrics"] == "Dòng giả có chữ ệ\nDòng thứ hai"
    url = "https://loibaihat.biz/lyric/abc12/invented/"
    row, artists, reason = loibaihat.parse_song(LOI, url)
    assert reason == ""
    assert artists == [("invented-writer", "Invented Writer")]
    assert row["song_name"] == "Invented Title"
    assert row["lyrics"] == "Dòng giả có chữ ệ\nDòng thứ hai"
    assert row["language_label"] == "Gia"
    assert row["release_year_raw"] == "1999"
    assert "advert" not in row["lyrics"]
    assert "bỏ qua" not in row["lyrics"]


def test_musiburma_drops_the_chord_row_and_keeps_burmese_letters():
    url = "https://www.musiburma.com/songs/invented-one/invented"
    row, artists, reason = musiburma.parse_song(MUSI, url)
    assert reason == ""
    assert artists == [("invented-one", "Invented One"), ("invented-two", "Invented Two")]
    assert row["song_name"] == "Invented"
    assert row["lyrics"] == "ကခ ဂ"
    assert row["text_kind"] == "lyrics"
    assert musiburma.song_id("https://www.musiburma.com/artists/invented-one") is None


def test_request_url_encodes_a_right_single_quotation_mark():
    url = site_crawl.request_url("https://example.test/lyric/o\u2019brian/page")
    assert url == "https://example.test/lyric/o%E2%80%99brian/page"


def test_a_non_ascii_path_is_percent_encoded(monkeypatch):
    seen = {}

    def fake_urlopen(request, timeout):
        seen["url"] = request.full_url
        raise OSError("no network")

    monkeypatch.setattr(site_crawl.urllib.request, "urlopen", fake_urlopen)
    status, _headers, body = site_crawl.http_fetch("https://example.test/lyric/o\u2019brian")
    assert status == 0
    assert body == b""
    assert seen["url"] == "https://example.test/lyric/o%E2%80%99brian"
    assert "\u2019" not in seen["url"]


def test_one_bad_url_does_not_abort_the_crawl(tmp_path):
    bad = "https://hopamviet.vn/chord/song/o\u2019brian/ABC123.html"
    song = "https://hopamviet.vn/chord/song/invented/AAA111.html"
    home = f'<html><body><a href="{bad}">bad</a><a href="{song}">one</a></body></html>'

    def fetch(url):
        if "\u2019" in url:
            raise UnicodeEncodeError("ascii", url, 24, 25, "ordinal not in range(128)")
        if url.endswith("/robots.txt"):
            return 200, {"Content-Type": "text/plain"}, b"User-agent: *\nAllow: /\n"
        if url == song:
            return 200, {"Content-Type": "text/html"}, HOPAM.encode()
        return 200, {"Content-Type": "text/html"}, home.encode()

    result = site_crawl.collect(
        tmp_path / "data",
        "hopamviet",
        "VNM",
        fetch=fetch,
        sleep=lambda _seconds: None,
        countries=tmp_path / "countries",
        day="20260103",
    )
    assert result["songs_written"] == 1
    assert result["songs_left_out"]["http_error"] == 1
    assert (tmp_path / "data" / "raw" / "hopamviet" / "20260103" / "_MANIFEST.json").is_file()


def test_a_crawl_saves_a_song_and_skips_a_disallowed_path(tmp_path):
    song = "https://hopamviet.vn/chord/song/invented/AAA111.html"
    blocked = "https://hopamviet.vn/chord/song/blocked/NO111.html"
    printed = "https://hopamviet.vn/chord/printsong/secret.html"
    home = (
        f'<html><body><a href="{song}">one</a>'
        f'<a href="{blocked}">no</a><a href="{printed}">sheet</a></body></html>'
    )
    pages = {
        "https://hopamviet.vn/robots.txt": (
            200,
            b"User-agent: *\nDisallow: /chord/printsong/\n"
            b"Disallow: /chord/song/blocked/\nAllow: /\n",
        ),
        "https://hopamviet.vn/": (200, home.encode()),
        "https://hopamviet.vn/info/singers": (200, b"<html></html>"),
        "https://hopamviet.vn/info/composers": (200, b"<html></html>"),
        song: (200, HOPAM.encode()),
    }
    asked = []

    def fetch(url):
        asked.append(url)
        status, body = pages.get(url, (404, b""))
        return status, {"Content-Type": "text/html"}, body

    result = site_crawl.collect(
        tmp_path / "data",
        "hopamviet",
        "VNM",
        fetch=fetch,
        sleep=lambda _seconds: None,
        countries=tmp_path / "countries",
        day="20260101",
    )
    assert result["songs_written"] == 1
    assert result["path"] == "raw/hopamviet/20260101/"
    assert song in asked
    assert blocked not in asked
    assert printed not in asked
    folder = tmp_path / "data" / "raw" / "hopamviet" / "20260101"
    assert (folder / "_MANIFEST.json").is_file()
    assert list(folder.glob("pages-*.tar.gz"))
    assert not (folder / "STOP").is_file()


def test_a_refusal_stops_the_crawl_and_writes_stop(tmp_path):
    song = "https://hopamviet.vn/chord/song/invented/AAA111.html"
    home = f'<html><body><a href="{song}">one</a></body></html>'

    def fetch(url):
        if url.endswith("/robots.txt"):
            return 200, {"Content-Type": "text/plain"}, b"User-agent: *\nAllow: /\n"
        if url == song:
            return 403, {"Content-Type": "text/html"}, b""
        return 200, {"Content-Type": "text/html"}, home.encode()

    result = site_crawl.collect(
        tmp_path / "data",
        "hopamviet",
        "VNM",
        fetch=fetch,
        sleep=lambda _seconds: None,
        countries=tmp_path / "countries",
        day="20260102",
    )
    assert result["state"] == "partial"
    folder = tmp_path / "data" / "raw" / "hopamviet" / "20260102"
    assert (folder / "STOP").is_file()
    assert "403" in (folder / "STOP").read_text(encoding="utf-8")
