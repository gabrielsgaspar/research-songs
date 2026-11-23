"""Collect the lyric site `dainutekstai` into one raw folder.

The collector reads the pages of the site in the order of its own index: the home
page, one page for each letter, one page for each artist, one page for each song.
It writes `raw/dainutekstai/<YYYYMMDD>/` with one lyric table and a manifest. The
table has the shape that `songs dumps build` reads as the family `site_snapshot`.
The collector matches nothing: `songs lyrics import-dump` does that.

The collector reads `robots.txt` first and sends no request that it disallows. It
waits between requests and stops when the site refuses it. A request with no
answer, a server error or an empty page is sent again after each wait of
`RETRY_WAITS`. A run continues the newest earlier folder when that folder has a
stop file: the new folder holds the songs of the earlier folder, and the run reads
only the songs that the earlier folder lacks.
"""

import http.client
import re
import time
import urllib.error
import urllib.request
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import duckdb

from songs.common import lyric_sources, manifests, paths, run_records
from songs.stage_00_ingest.dump_match import name_key

SOURCE = "dainutekstai"
ROUTE = "live"
BASE = "https://dainutekstai.lt"
USER_AGENT = "research-songs-collector/1.0 (academic research project on song lyrics)"
MIN_DELAY_SECONDS = 2.0
TIMEOUT_SECONDS = 30
STOP_STATUSES = (401, 403, 429)
MAX_ERRORS_IN_A_ROW = 3
# Seconds to wait before each new try of a request that got no page.
RETRY_WAITS = (60, 300, 900)
LYRIC_FILE = f"{SOURCE}_lyrics.parquet"
STOP_FILE = "STOP"
COLUMNS = (
    "provider_song_id",
    "song_url",
    "song_name",
    "artist_name",
    "artist_url",
    "lyrics",
    "text_kind",
    "language_label",
    "release_year_raw",
    "retrieved_at_utc",
)
# Texts that the site can show in place of a lyric, as `name_key` values.
PLACEHOLDERS = ("dainos teksto dar nera", "dainos zodziu dar nera", "tekstas ruosiamas")
_LETTER = re.compile(r"/\?catid=\d+")
_ARTIST = re.compile(r"/a\d+/[^/]+\.html")
_SONG = re.compile(r"/(r\d+)/[^/]+\.html")
# The parts of a page that the parser reads: the id or the class of their `div`.
SONG_LIST, BREADCRUMB, LYRICS = "sarasas", "breadcrumb", "dainostekstas"
ZONES = (SONG_LIST, BREADCRUMB, LYRICS)
_DASH = re.compile(r"\s+[-–—]\s+")

Fetch = Callable[[str], tuple[int, str]]


class CollectError(ValueError):
    """The collection cannot start."""


class _Stop(Exception):
    """The crawl ends now. The text is the cause."""


def http_fetch(url: str) -> tuple[int, str]:
    """Send one GET request. Return the HTTP status and the body. Status 0 means no answer."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return response.status, response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as error:
        return error.code, ""
    except OSError, http.client.HTTPException:
        return 0, ""


class _Page(HTMLParser):
    """Read the links, the heading and the lyric block of one page."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str, str]] = []
        self.heading = ""
        self.lyrics = ""
        self._zone = ""
        self._depth = 0
        self._href: str | None = None
        self._text = ""
        self._in_heading = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        found = dict(attrs)
        if tag == "div":
            zone = SONG_LIST if found.get("id") == SONG_LIST else found.get("class")
            if self._zone == LYRICS:
                self._zone = ""
            elif self._zone:
                self._depth += 1
            elif zone in ZONES:
                self._zone, self._depth = zone, 1
        elif tag == "a":
            self._href, self._text = found.get("href") or "", ""
        elif tag == "h1":
            self._in_heading = True
        elif tag == "br" and self._zone == LYRICS:
            self.lyrics += "\n"

    def handle_endtag(self, tag: str) -> None:
        if tag == "div" and self._zone:
            self._depth -= 1
            if self._depth == 0:
                self._zone = ""
        elif tag == "a" and self._href is not None:
            self.links.append((self._href, " ".join(self._text.split()), self._zone))
            self._href = None
        elif tag == "h1":
            self._in_heading = False

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text += data
        if self._in_heading:
            self.heading += data
        if self._zone == LYRICS:
            self.lyrics += data.replace("\r", "").replace("\n", "")


def _read(html: str) -> _Page:
    page = _Page()
    page.feed(html)
    page.close()
    return page


def _site_url(href: str, shape: re.Pattern[str]) -> str:
    """Return the address of a link on the site whose path has the shape, or ''."""
    parts = urlsplit(urljoin(BASE + "/", href))
    path = parts.path + (f"?{parts.query}" if parts.query else "")
    on_site = parts.hostname in ("dainutekstai.lt", "www.dainutekstai.lt")
    return BASE + path if on_site and shape.fullmatch(path) else ""


def _links(page: _Page, shape: re.Pattern[str], zone: str | None = None) -> list[tuple[str, str]]:
    """Return (address, text) of each link with the shape, one time each, in page order."""
    found: dict[str, str] = {}
    for href, text, where in page.links:
        url = _site_url(href, shape)
        if url and (zone is None or where == zone) and not found.get(url):
            found[url] = text
    return list(found.items())


def letter_urls(html: str) -> list[str]:
    """Return the address of each letter page that the home page names."""
    return [url for url, _ in _links(_read(html), _LETTER)]


def artist_links(html: str) -> list[tuple[str, str]]:
    """Return (address, name) of each artist that a letter page names."""
    return _links(_read(html), _ARTIST)


def song_urls(html: str) -> list[str]:
    """Return the address of each song in the song list of an artist page."""
    return [url for url, _ in _links(_read(html), _SONG, SONG_LIST)]


def parse_song(html: str, url: str) -> tuple[dict | None, str]:
    """Return the row of a song page and '', or None and the reason the page gives no row."""
    page = _read(html)
    parts = _DASH.split(" ".join(page.heading.split()), maxsplit=1)
    artists = _links(page, _ARTIST, BREADCRUMB)
    artist_url, artist = artists[0] if artists else ("", parts[0] if len(parts) == 2 else "")
    lines = [line.strip() for line in page.lyrics.split("\n")]
    lyrics = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    if not artist:
        return None, "no_artist"
    if not parts[-1]:
        return None, "no_title"
    if not lyrics:
        return None, "no_lyrics"
    if any(text in name_key(lyrics) for text in PLACEHOLDERS):
        return None, "placeholder"
    row = dict.fromkeys(COLUMNS)
    row.update(
        provider_song_id=_SONG.fullmatch(urlsplit(url).path)[1],
        song_url=url,
        song_name=parts[-1],
        artist_name=artist,
        artist_url=artist_url or None,
        lyrics=lyrics,
        text_kind="lyrics",
        retrieved_at_utc=run_records.utc_now(),
    )
    return row, ""


class _Session:
    """Send the requests of one run: robots first, a wait between requests, a stop on refusal."""

    def __init__(self, fetch: Fetch, sleep: Callable[[float], None], delay: float) -> None:
        self.fetch, self.sleep, self.delay = fetch, sleep, delay
        self.requests = self.errors = self.errors_in_a_row = self.robots_disallowed = 0
        self.retries = 0
        self.robots = RobotFileParser()

    def _send(self, url: str) -> tuple[int, str]:
        """Send a request, and send it again after each wait while the site gives no page.

        No answer, a server error and an empty page can pass with time. Any other
        answer is final.
        """
        waits = iter(RETRY_WAITS)
        while True:
            if self.requests:
                self.sleep(self.delay)
            self.requests += 1
            status, body = self.fetch(url)
            passing = status == 0 or status >= 500 or (status == 200 and not body.strip())
            wait = next(waits, None) if passing else None
            if wait is None:
                return status, body
            self.retries += 1
            self.sleep(wait)

    def read_robots(self) -> None:
        status, body = self._send(BASE + "/robots.txt")
        if status == 200:
            self.robots.parse(body.splitlines())
            self.delay = max(self.delay, float(self.robots.crawl_delay(USER_AGENT) or 0))
        elif status in (401, 403):
            self.robots.disallow_all = True
        elif 400 <= status < 500:
            self.robots.allow_all = True
        else:
            raise _Stop(f"robots.txt was not read (status {status})")

    def get(self, url: str) -> tuple[str, str]:
        """Return the body of a page and '', or '' and the reason the page was not read."""
        if not self.robots.can_fetch(USER_AGENT, url):
            self.robots_disallowed += 1
            return "", "robots_disallowed"
        status, body = self._send(url)
        if status in STOP_STATUSES:
            raise _Stop(f"the site answered with HTTP {status}")
        if status != 200 or not body.strip():
            self.errors += 1
            self.errors_in_a_row += 1
            if self.errors_in_a_row >= MAX_ERRORS_IN_A_ROW:
                raise _Stop(
                    f"{MAX_ERRORS_IN_A_ROW} requests in a row failed (last status {status})"
                )
            return "", "http_error"
        self.errors_in_a_row = 0
        return body, ""


def _crawl(
    session: _Session,
    rows: list[dict],
    counts: Counter,
    limits: dict,
    artist_limit: int | None,
    song_limit: int | None,
) -> None:
    session.read_robots()
    home, problem = session.get(BASE + "/")
    if problem:
        raise _Stop(f"the home page was not read ({problem})")
    artists: dict[str, str] = {}
    for letter in letter_urls(home):
        if artist_limit is not None and len(artists) >= artist_limit:
            break
        artists.update(artist_links(session.get(letter)[0]))
    urls = list(artists)
    if artist_limit is not None and len(urls) >= artist_limit:
        limits["artist_limit"] = artist_limit
        urls = urls[:artist_limit]
    seen = {row["song_url"] for row in rows}
    for artist_url in urls:
        counts["artists"] += 1
        for url in song_urls(session.get(artist_url)[0]):
            if url in seen:
                continue
            if song_limit is not None and len(seen) >= song_limit:
                limits["song_limit"] = song_limit
                return
            seen.add(url)
            try:
                body, problem = session.get(url)
            except _Stop:
                counts["http_error"] += 1
                raise
            row, problem = parse_song(body, url) if body else (None, problem)
            if row is None:
                counts[problem] += 1
            else:
                rows.append(row)


def _earlier_rows(data: Path) -> tuple[Path | None, list[dict]]:
    """Return the newest raw folder and its songs when a run must continue it, if not None, [].

    A run continues a folder that has a stop file: its run ended early.
    """
    folder = paths.latest_raw_dir(data, SOURCE)
    if folder is None or not (folder / STOP_FILE).is_file():
        return None, []
    with duckdb.connect() as connection:
        table = connection.read_parquet((folder / LYRIC_FILE).as_posix())
        found = table.project(", ".join(COLUMNS)).fetchall()
    return folder, [dict(zip(COLUMNS, row, strict=True)) for row in found]


def _write(
    data: Path, folder: Path, rows: list[dict], counts: dict, stopped: str, inputs: list[str]
) -> None:
    """Write the lyric table, the stop file of a run that ended early, and the manifest last."""
    folder.mkdir(parents=True)
    marks = ", ".join("?" for _ in COLUMNS)
    with duckdb.connect() as connection:
        connection.execute(f"CREATE TABLE lyric ({', '.join(f'{c} VARCHAR' for c in COLUMNS)})")
        connection.executemany(
            f"INSERT INTO lyric VALUES ({marks})", [[row[c] for c in COLUMNS] for row in rows]
        )
        connection.execute(
            "COPY lyric TO ? (FORMAT parquet, COMPRESSION zstd)", [(folder / LYRIC_FILE).as_posix()]
        )
    if stopped:
        with (folder / STOP_FILE).open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(stopped + "\n")
    manifests.write_manifest(
        data,
        folder,
        "raw",
        source=SOURCE,
        inputs=inputs,
        origin={"url": BASE, "retrieved_utc": run_records.utc_now(), "license": None},
        counts=counts,
        notes=f"Collected page by page. {stopped}".strip(),
    )


def collect(
    data: Path,
    iso3: str,
    *,
    delay: float = MIN_DELAY_SECONDS,
    artist_limit: int | None = None,
    song_limit: int | None = None,
    reason: str | None = None,
    fetch: Fetch | None = None,
    sleep: Callable[[float], None] = time.sleep,
    countries: Path | None = None,
    day: str | None = None,
) -> dict:
    """Collect the site for a country, write the raw folder and one run record.

    Return the counts: requests sent, songs written, and songs left out by reason.
    The wait between requests is the largest of `delay`, 2 seconds, the delay of the
    source file and the crawl delay of `robots.txt`. A run that ends early keeps the
    songs that it has. Its folder has a stop file, so `songs dumps build` marks the dump
    as incomplete. A run that the site stopped has the state `partial` in its record.
    The next run continues such a folder (`_earlier_rows`): its new folder holds the
    earlier songs, and its record counts only the songs that it read. `day` replaces
    the date of today in the folder name (for tests).
    """
    source = next(item for item in lyric_sources.load_lyric_sources() if item.id == SOURCE)
    if source.access != "allowed":
        raise CollectError(f"requests to {SOURCE} are {source.access} in the source file")
    if iso3 not in source.countries:
        raise CollectError(f"{SOURCE} does not serve {iso3} in the source file")
    folder = paths.raw_dir(data, SOURCE, day or datetime.now(UTC).strftime("%Y%m%d"))
    if folder.exists():
        raise FileExistsError(
            f"{paths.data_relative(data, folder)} exists; raw data is never written over"
        )
    delay = max(delay, MIN_DELAY_SECONDS, source.request_delay_seconds or 0)
    session = _Session(fetch or http_fetch, sleep, delay)
    # shortcut: the rows stay in memory until the run ends, so a killed process loses them;
    # keep a queue in staging/ when a site has more than about 100,000 songs.
    earlier, rows = _earlier_rows(data)
    carried = len(rows)
    counts: Counter = Counter()
    limits: dict = {}
    with run_records.record_run(
        iso3,
        ROUTE,
        SOURCE,
        countries=countries,
        repeat_reason=reason,
        request_delay_seconds=delay,
        artist_limit=artist_limit,
        song_limit=song_limit,
    ) as record:
        stopped = ""
        try:
            _crawl(session, rows, counts, limits, artist_limit, song_limit)
            stopped = " ".join(
                f"The run reached the {name.replace('_', ' ')} of {number}."
                for name, number in limits.items()
            )
        except _Stop as stop:
            stopped = f"The run stopped: {stop}."
            limits["stopped"] = str(stop)
            record.state = "partial"
        except BaseException as error:
            stopped = f"The run stopped: {type(error).__name__}."
            raise
        finally:
            left_out = {
                name: number for name, number in sorted(counts.items()) if name != "artists"
            }
            if session.robots_disallowed:
                record.known_gaps.append(
                    f"robots.txt disallows {session.robots_disallowed} pages; they were not read"
                )
            if session.errors:
                record.known_gaps.append(
                    f"{session.errors} pages gave an error; they were not read"
                )
            if stopped:
                record.known_gaps.append(stopped)
            if earlier:
                record.notes = (
                    f"Continues {paths.data_relative(data, earlier)}: "
                    f"{carried} songs of it are in the new folder."
                )
            record.request_delay_seconds = session.delay
            record.requests_sent = session.requests
            record.artists_attempted = counts["artists"]
            record.songs_attempted = len(rows) - carried + sum(left_out.values())
            record.songs_accepted = len(rows) - carried
            record.songs_rejected = left_out
            record.limits_hit = limits
            record.rows_added = 0
            if len(rows) > carried:
                _write(
                    data,
                    folder,
                    rows,
                    {
                        "pages_requested": session.requests,
                        "songs_written": len(rows),
                        **({"songs_of_earlier_folder": carried} if earlier else {}),
                        **{f"songs_left_out_{name}": number for name, number in left_out.items()},
                    },
                    stopped,
                    [paths.data_relative(data, earlier)] if earlier else [],
                )
                record.notes = f"{record.notes} Wrote {paths.data_relative(data, folder)}".strip()
    return {
        "path": paths.data_relative(data, folder) if len(rows) > carried else None,
        "state": record.state,
        "requests_sent": session.requests,
        "retries": session.retries,
        "songs_written": len(rows),
        "songs_of_earlier_folder": carried,
        "songs_left_out": left_out,
        "known_gaps": record.known_gaps,
    }
