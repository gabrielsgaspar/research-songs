"""The collector of dainutekstai, on invented pages. No request leaves the test.

The pages copy the structure of the site: its tags, ids and classes. Every name and
every lyric line is invented.
"""

import dataclasses

import duckdb
import pytest
from typer.testing import CliRunner

from songs.cli import app
from songs.common import lyric_sources, manifests, paths, run_records, schemas
from songs.stage_00_ingest import dainutekstai as site
from songs.stage_00_ingest import dumps

BASE = site.BASE
ROBOTS_OPEN = "User-agent: *\nAllow: /\n"
ARTISTS = {"a1": "Invented Band", "a2": "Second Singer"}
# Song id -> (artist id, title, lyric lines). The song r3 is on the pages of both artists.
SONGS = {
    "r1": ("a1", "First Title", ["invented line one", "invented line two", "", "invented line 3"]),
    "r2": ("a1", "Second Title", []),
    "r3": ("a2", "Third Title", ["another invented line"]),
}


def artist_url(key: str) -> str:
    return f"{BASE}/{key}/{key}-dainu-zodziai.html"


def song_url(key: str) -> str:
    return f"{BASE}/{key}/{key}-song.html"


def song_page(key: str) -> str:
    artist, title, lines = SONGS[key]
    name = ARTISTS[artist]
    return (
        f"<html><body><div class='breadcrumb'><a href='/'>Home</a> > "
        f"<a href='/{artist}/{artist}-dainu-zodziai.html'>{name}</a></div>"
        f"<h1>{name} - {title}</h1>"
        f"<div class='dainostekstas'>{'<br>\n'.join(lines)}<br>"
        '<div id="container"><div class="ratingblock">Rating: 4/5</div></div>\n</div>'
        "<table><tr><td><a href='/r99/other-song.html'>Other Song</a></td></tr></table>"
        "</body></html>"
    )


def artist_page(key: str) -> str:
    keys = [song for song, (artist, _, _) in SONGS.items() if artist == key or song == "r3"]
    rows = "".join(
        f"<tr><td><a href='/{song}/{song}-song.html'><img alt='x'></a></td>"
        f"<td>1. <a href='/{song}/{song}-song.html'>{ARTISTS[key]} - {SONGS[song][1]}</a>"
        "<div class='vnl'>invented preview</div></td></tr>"
        for song in keys
    )
    return (
        "<html><body><a href='/r98/top-song.html'>Top Song</a>"
        f"<div class='breadcrumb'><a href='../index.php?catid=3'>A</a></div>"
        f'<div id="sarasas"><table>{rows}</table></div></body></html>'
    )


def fake_site(**changes) -> dict[str, tuple[int, str]]:
    """Return address -> (status, body) of a small invented site."""
    letter = "".join(
        f"<a href='/{key}/{key}-dainu-zodziai.html'>{name}</a> (2)<br>"
        for key, name in ARTISTS.items()
    )
    pages = {
        f"{BASE}/robots.txt": (200, ROBOTS_OPEN),
        f"{BASE}/": (200, '<a href="/?catid=3">A</a> <a href="http://ru.dainutekstai.lt/">RU</a>'),
        f"{BASE}/?catid=3": (200, f"<div style='margin-left:45px'>{letter}</div>"),
        **{artist_url(key): (200, artist_page(key)) for key in ARTISTS},
        **{song_url(key): (200, song_page(key)) for key in SONGS},
    }
    return pages | changes


@pytest.fixture
def run(tmp_path):
    """Run the collector on a fake site. Return the result, the requests and the waits."""

    def start(pages=None, **settings):
        asked, waits = [], []
        pages = fake_site() if pages is None else pages

        def fetch(url):
            asked.append(url)
            return pages.get(url, (404, ""))

        try:
            result = site.collect(
                tmp_path / "data",
                "LTU",
                fetch=fetch,
                sleep=waits.append,
                countries=tmp_path / "countries",
                **settings,
            )
        except Exception as error:
            result = error
        return result, asked, waits

    return start


def record_of(tmp_path) -> run_records.RunRecord:
    (record,) = run_records.read_run_records("LTU", tmp_path / "countries")
    return record


def test_the_parsers_read_the_index_the_song_list_and_the_song_page():
    pages = fake_site()
    assert site.letter_urls(pages[f"{BASE}/"][1]) == [f"{BASE}/?catid=3"]
    assert site.artist_links(pages[f"{BASE}/?catid=3"][1]) == [
        (artist_url("a1"), "Invented Band"),
        (artist_url("a2"), "Second Singer"),
    ]
    assert site.song_urls(artist_page("a1")) == [song_url("r1"), song_url("r2"), song_url("r3")]
    row, reason = site.parse_song(song_page("r1"), song_url("r1"))
    assert reason == ""
    assert row["provider_song_id"] == "r1"
    assert (row["artist_name"], row["song_name"]) == ("Invented Band", "First Title")
    assert row["artist_url"] == artist_url("a1")
    assert row["lyrics"] == "invented line one\ninvented line two\n\ninvented line 3"
    assert site.parse_song(song_page("r2"), song_url("r2")) == (None, "no_lyrics")
    placeholder = song_page("r1").replace("invented line one", "Dainos teksto dar nėra")
    assert site.parse_song(placeholder, song_url("r1")) == (None, "placeholder")
    assert site.parse_song("<h1></h1>", song_url("r1")) == (None, "no_artist")


def test_a_run_writes_a_raw_folder_that_the_dump_builder_reads(run, tmp_path):
    result, asked, waits = run()
    data = tmp_path / "data"
    folder = paths.latest_raw_dir(data, "dainutekstai")
    assert result["path"] == paths.data_relative(data, folder)
    assert result["songs_written"] == 2
    assert result["songs_left_out"] == {"no_lyrics": 1}
    # robots.txt first; the song that two artists list is requested one time.
    assert asked[0] == f"{BASE}/robots.txt"
    assert len(asked) == len(set(asked)) == result["requests_sent"] == 8
    assert waits == [site.MIN_DELAY_SECONDS] * 7

    manifest = manifests.read_manifest(folder)
    assert manifest.kind == "raw"
    assert manifest.origin["url"] == BASE
    assert manifest.counts == {
        "pages_requested": 8,
        "songs_written": 2,
        "songs_left_out_no_lyrics": 1,
    }
    assert [entry["path"] for entry in manifest.files] == [site.LYRIC_FILE]
    columns = set(duckdb.read_parquet(str(folder / site.LYRIC_FILE)).columns)
    assert dumps.detect_family(columns) == "site_snapshot"

    built = dumps.build_dump("dainutekstai", folder, result["path"], data, day="20261124")
    assert (built["family"], built["rows_out"], built["incomplete"]) == ("site_snapshot", 2, False)
    songs = schemas.read_table(schemas.DUMP_SONGS, data / built["path"]).order("source_song_id")
    assert songs.project("source_song_id, artist_name, song_name").fetchall() == [
        ("r1", "Invented Band", "First Title"),
        ("r3", "Second Singer", "Third Title"),
    ]
    assert all(row[0] for row in songs.project("fetched_utc").fetchall())

    record = record_of(tmp_path)
    assert (record.route, record.source, record.state) == ("live", "dainutekstai", "complete")
    assert record.request_delay_seconds == site.MIN_DELAY_SECONDS
    assert (record.requests_sent, record.artists_attempted) == (8, 2)
    assert (record.songs_attempted, record.songs_accepted) == (3, 2)
    assert record.songs_rejected == {"no_lyrics": 1}
    assert (record.rows_added, record.limits_hit, record.known_gaps) == (0, {}, [])
    assert result["path"] in record.notes


def test_the_wait_is_never_shorter_than_the_crawl_delay_of_robots(run, tmp_path):
    pages = fake_site(**{f"{BASE}/robots.txt": (200, "User-agent: *\nCrawl-delay: 7\n")})
    _, _, waits = run(pages, delay=0.1)
    assert set(waits) == {7.0}
    assert record_of(tmp_path).request_delay_seconds == 7.0


def test_a_page_that_robots_disallows_is_skipped_and_counted(run, tmp_path):
    robots = "User-agent: *\nDisallow: /r1/\n"
    result, asked, _ = run(fake_site(**{f"{BASE}/robots.txt": (200, robots)}))
    assert song_url("r1") not in asked
    assert result["songs_left_out"] == {"no_lyrics": 1, "robots_disallowed": 1}
    assert record_of(tmp_path).known_gaps == ["robots.txt disallows 1 pages; they were not read"]


@pytest.mark.parametrize("status", [403, 429])
def test_a_refusal_stops_the_run_and_keeps_the_songs_it_has(run, tmp_path, status):
    result, asked, _ = run(fake_site(**{song_url("r3"): (status, "")}))
    assert asked[-1] == song_url("r3")
    assert (result["state"], result["songs_written"]) == ("partial", 1)
    record = record_of(tmp_path)
    assert record.state == "partial"
    assert record.limits_hit == {"stopped": f"the site answered with HTTP {status}"}
    assert record.known_gaps == [f"The run stopped: the site answered with HTTP {status}."]
    data = tmp_path / "data"
    folder = paths.latest_raw_dir(data, "dainutekstai")
    assert (folder / site.STOP_FILE).is_file()
    assert dumps.build_dump("dainutekstai", folder, result["path"], data)["incomplete"] is True


def test_three_failed_requests_in_a_row_stop_the_run(run, tmp_path):
    broken = {song_url(key): (500, "") for key in SONGS}
    result, _, _ = run(fake_site(**broken))
    assert (result["path"], result["songs_written"]) == (None, 0)
    assert not (tmp_path / "data" / "raw").exists()
    record = record_of(tmp_path)
    assert record.state == "partial"
    assert record.songs_rejected == {"http_error": 3}
    assert record.known_gaps[0] == "3 pages gave an error; they were not read"


def test_no_robots_answer_stops_the_run_before_any_page(run, tmp_path):
    result, asked, _ = run(fake_site(**{f"{BASE}/robots.txt": (0, "")}))
    assert asked == [f"{BASE}/robots.txt"]
    assert result["state"] == "partial"


def test_a_song_limit_ends_the_run_and_marks_the_folder(run, tmp_path):
    result, asked, _ = run(song_limit=1)
    assert [url for url in asked if "/r" in url and "robots" not in url] == [song_url("r1")]
    assert result["state"] == "complete"
    record = record_of(tmp_path)
    assert (record.song_limit, record.limits_hit) == (1, {"song_limit": 1})
    folder = paths.latest_raw_dir(tmp_path / "data", "dainutekstai")
    assert (folder / site.STOP_FILE).is_file()


def test_an_artist_limit_reads_only_that_number_of_artists(run, tmp_path):
    _, asked, _ = run(artist_limit=1)
    assert artist_url("a1") in asked
    assert artist_url("a2") not in asked
    assert record_of(tmp_path).limits_hit == {"artist_limit": 1}


def test_a_second_run_on_the_same_day_sends_no_request(run, tmp_path):
    run()
    before = sorted(path.name for path in (tmp_path / "data").rglob("*"))
    error, asked, _ = run(reason="again")
    assert isinstance(error, FileExistsError)
    assert asked == []
    assert sorted(path.name for path in (tmp_path / "data").rglob("*")) == before
    assert len(run_records.read_run_records("LTU", tmp_path / "countries")) == 1


def test_a_source_that_is_not_allowed_or_another_country_is_refused(run, monkeypatch):
    sources = lyric_sources.load_lyric_sources()
    blocked = [
        dataclasses.replace(source, access="blocked") if source.id == site.SOURCE else source
        for source in sources
    ]
    monkeypatch.setattr(lyric_sources, "load_lyric_sources", lambda: blocked)
    error, asked, _ = run()
    assert isinstance(error, site.CollectError)
    assert asked == []
    monkeypatch.setattr(lyric_sources, "load_lyric_sources", lambda: sources)
    with pytest.raises(site.CollectError):
        site.collect(None, "BRA", fetch=lambda url: pytest.fail("a request was sent"))


def test_the_user_agent_names_the_project_and_no_browser():
    assert site.USER_AGENT.startswith("research-songs-collector/")
    assert "Mozilla" not in site.USER_AGENT
    assert "@" not in site.USER_AGENT


def test_the_command_refuses_a_source_with_no_collector():
    result = CliRunner().invoke(app, ["lyrics", "collect", "genius", "LTU"])
    assert result.exit_code == 1
    assert "no collector for genius" in result.output
