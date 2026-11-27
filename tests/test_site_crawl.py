"""The shared site collector, with a fake fetch and invented pages."""

import duckdb

from songs.common import run_records
from songs.stage_00_ingest import hopamviet, site_crawl, site_pages

SONG_A = f"{hopamviet.BASE}/chord/song/invented-title/W8IUTEST.html"
SONG_B = f"{hopamviet.BASE}/chord/song/second-title/W8IUSEC1.html"
HOME = hopamviet.BASE + "/"
LATEST = hopamviet.BASE + "/chord/latest"


def _song(title: str) -> bytes:
    html = (
        f"<html><body><h1>{title}</h1>"
        "<a href='/chord/composer/3/invented-writer.html'>Invented Writer</a>"
        "<div id='lyric-version-0'>First invented [Am] line\nSecond line giữ dấu</div>"
        "</body></html>"
    )
    return html.encode("utf-8")


def _home() -> bytes:
    html = (
        f"<a href='{SONG_A}'>Invented Title</a>"
        f"<a href='{SONG_B}'>Second Title</a>"
        "<a href='/chord/search?q=secret'>secret</a>"
        "<a href='/chord/latest'>latest</a>"
    )
    return html.encode("utf-8")


def test_a_limited_run_packs_pages_and_a_later_run_continues(tmp_path, monkeypatch):
    ids = iter(f"20261126T00000{number}Z" for number in range(1, 9))
    monkeypatch.setattr(run_records, "new_run_id", lambda now=None: next(ids))
    asked: list[str] = []
    waits: list[float] = []
    home_tries = {"n": 0}

    def fetch(url: str) -> tuple[int, dict[str, str], bytes]:
        asked.append(url)
        if url.endswith("/robots.txt"):
            body = b"User-agent: *\nDisallow: /chord/search\nDisallow: /chord/latest\nAllow: /\n"
            return 200, {"Content-Type": "text/plain"}, body
        if url == HOME:
            home_tries["n"] += 1
            if home_tries["n"] == 1:
                return 0, {}, b""
            return 200, {"Content-Type": "text/html"}, _home()
        if url == SONG_A:
            return 200, {"Content-Type": "text/html; charset=utf-8"}, _song("Invented Title")
        if url == SONG_B:
            return 200, {"Content-Type": "text/html; charset=utf-8"}, _song("Second Title")
        return 200, {"Content-Type": "text/html"}, b"<html></html>"

    data = tmp_path / "data"
    countries = tmp_path / "countries"
    first = site_crawl.collect(
        data,
        "hopamviet",
        "VNM",
        song_limit=1,
        fetch=fetch,
        sleep=waits.append,
        countries=countries,
        day="20261126",
    )
    assert first["state"] == "complete"
    assert first["songs_written"] == 1
    assert 60 in waits
    assert LATEST not in asked
    assert not any("/chord/search" in url for url in asked)
    assert (data / "raw" / "hopamviet" / "20261126" / "STOP").is_file()
    assert (data / "raw" / "hopamviet" / "20261126" / "_MANIFEST.json").is_file()

    first_songs = {url for url in asked if "/chord/song/" in url}
    asked.clear()
    seen_path = data / "staging" / "site_crawl" / "hopamviet" / "seen.txt"
    kept = [
        line
        for line in seen_path.read_text(encoding="utf-8").splitlines()
        if line.strip() not in first_songs
    ]
    seen_path.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8", newline="\n")
    second = site_crawl.collect(
        data,
        "hopamviet",
        "VNM",
        fetch=fetch,
        sleep=lambda _seconds: None,
        countries=countries,
        day="20261127",
        reason="the first run stopped at the song limit",
    )
    assert second["songs_written"] == 1
    second_songs = {url for url in asked if "/chord/song/" in url}
    assert second_songs == {SONG_A, SONG_B} - first_songs
    assert len(second_songs) == 1
    parsed = site_pages.parse_folder(data, "hopamviet", first["path"], day="20261128")
    assert parsed["songs_out"] == 1
    with duckdb.connect() as connection:
        lyric = connection.execute(
            "SELECT lyrics FROM read_parquet(?)",
            [(data / "raw" / "hopamviet" / "20261128" / "hopamviet_lyrics.parquet").as_posix()],
        ).fetchone()[0]
    assert "[Am]" not in lyric and "giữ dấu" in lyric


def test_a_refusal_stops_the_site(tmp_path):
    def fetch(url: str) -> tuple[int, dict[str, str], bytes]:
        if url.endswith("/robots.txt"):
            return 200, {"Content-Type": "text/plain"}, b"User-agent: *\nAllow: /\n"
        if url == HOME:
            return 200, {"Content-Type": "text/html"}, _home()
        return 403, {"Content-Type": "text/html"}, b"no"

    result = site_crawl.collect(
        tmp_path / "data",
        "hopamviet",
        "VNM",
        fetch=fetch,
        sleep=lambda _seconds: None,
        countries=tmp_path / "countries",
        day="20261126",
    )
    assert result["state"] == "partial"
    assert (tmp_path / "data" / "raw" / "hopamviet" / "20261126" / "STOP").is_file()


def test_one_bad_url_does_not_stop_the_crawl(tmp_path, monkeypatch):
    monkeypatch.setattr(run_records, "new_run_id", lambda now=None: "20261126T000009Z")

    def fetch(url: str) -> tuple[int, dict[str, str], bytes]:
        if url.endswith("/robots.txt"):
            return 200, {"Content-Type": "text/plain"}, b"User-agent: *\nAllow: /\n"
        if url == HOME:
            return 200, {"Content-Type": "text/html"}, _home()
        if url == SONG_A:
            raise UnicodeError("bad")
        if url == SONG_B:
            return 200, {"Content-Type": "text/html"}, _song("Second Title")
        return 200, {"Content-Type": "text/html"}, b"<html></html>"

    result = site_crawl.collect(
        tmp_path / "data",
        "hopamviet",
        "VNM",
        fetch=fetch,
        sleep=lambda _seconds: None,
        countries=tmp_path / "countries",
        day="20261126",
    )
    assert result["state"] == "complete"
    assert result["songs_written"] == 1
    assert result["songs_left_out"]["http_error"] >= 1


def test_selected_song_pages_do_not_follow_other_links(tmp_path):
    asked = []

    def fetch(url):
        asked.append(url)
        if url.endswith("/robots.txt"):
            return 200, {}, b"User-agent: *\nAllow: /"
        return 200, {}, _song("Invented Title") + _home()

    result = site_crawl.collect(
        tmp_path / "data",
        "hopamviet",
        "VNM",
        seed_urls=[SONG_A, SONG_A],
        fetch=fetch,
        sleep=lambda seconds: None,
        countries=tmp_path / "countries",
    )
    assert asked == [HOME + "robots.txt", SONG_A]
    assert result["songs_written"] == 1
