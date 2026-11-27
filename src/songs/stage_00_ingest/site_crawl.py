"""Collect one lyric site into a packed raw folder.

The collector is the same for every site that has a page reader. It reads
`robots.txt` first and does not request a page that file disallows. It waits
between requests. A request with no answer, a server error or an empty page is
sent again after each wait of `RETRY_WAITS`. Status 401, 403 or 429 stops the
crawl. Each response is one receipt and one body. At the end the collector packs
those files into `raw/<source>/<YYYYMMDD>/` (`pages-00001.tar.gz`,
`members.parquet` and the manifest). A folder that already has a manifest is
never rewritten. A stopped crawl writes `STOP`, and a later run continues in a
new dated folder: it does not request a URL the earlier folder already stored.

The page reader of the site names `SEEDS`. It names `crawl_urls(html, page_url)`
or `is_listing(url)`. `song_id` decides which pages are songs.
"""

import gzip
import http.client
import json
import os
import re
import shutil
import socket
import tarfile
import threading
import time
import urllib.error
import urllib.request
from collections import Counter, deque
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urljoin, urlsplit, urlunsplit

from songs.common import lyric_sources, manifests, paths, run_records, tar_parts
from songs.stage_00_ingest.site_pages import page_links, site_module, site_path

USER_AGENT = "research-songs-collector/1.0 (academic research project on song lyrics)"
MIN_DELAY_SECONDS = 2.0
TIMEOUT_SECONDS = 30
STOP_STATUSES = (401, 403, 429)
MAX_ERRORS_IN_A_ROW = 3
RETRY_WAITS = (60, 300, 900)
STOP_FILE = "STOP"
ROUTE = "live"
SOURCES = (
    "aama",
    "afghansonglyrics",
    "gitimala",
    "hopamviet",
    "loibaihat",
    "lyricslk",
    "musiburma",
)
PAGE_CAP = 5_000
OFFSET_CAP = 20_000
_NEXT_HREF = re.compile(r"""(?:rel="next"[^>]*href="([^"]+)"|href="([^"]+)"[^>]*rel="next")""")
_LOC = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>")

Fetch = Callable[[str], tuple[int, dict[str, str], bytes]]


class CollectError(ValueError):
    """The collection cannot start."""


class _Stop(Exception):
    """The crawl ends now. The text is the cause."""


def request_url(url: str) -> str:
    """Return `url` with its path percent-encoded. Slashes stay slashes."""
    parts = urlsplit(url)
    path = quote(unquote(parts.path), safe="/")
    return urlunsplit((parts.scheme, parts.netloc, path, parts.query, parts.fragment))


def _http_fetch(url: str) -> tuple[int, dict[str, str], bytes]:
    socket.setdefaulttimeout(TIMEOUT_SECONDS)
    try:
        request = urllib.request.Request(request_url(url), headers={"User-Agent": USER_AGENT})
    except UnicodeError:
        return 400, {}, b""
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            kind = response.headers.get("Content-Type", "")
            return response.status, {"Content-Type": kind}, response.read()
    except UnicodeError:
        return 400, {}, b""
    except urllib.error.HTTPError as error:
        kind = error.headers.get("Content-Type", "") if error.headers else ""
        payload = error.read() if error.fp else b""
        return error.code, {"Content-Type": kind}, payload
    except OSError, http.client.HTTPException:
        return 0, {"X-Timeout": "1"}, b""


def http_fetch(url: str) -> tuple[int, dict[str, str], bytes]:
    """Send one GET. Return the status, a content-type header and the body.

    Status 0 means no answer. The body is the bytes the site sent. A path that
    `urllib` cannot send is a failed request, not a reason to stop the crawl.
    A request that is still open after the timeout returns status 0 as well.
    """
    box: dict = {}

    def run() -> None:
        box["result"] = _http_fetch(url)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(TIMEOUT_SECONDS + 5)
    if thread.is_alive():
        return 0, {"X-Timeout": "1"}, b""
    return box.get("result", (0, {}, b""))


def _text(body: bytes) -> str:
    try:
        return body.decode("utf-8-sig")
    except UnicodeDecodeError:
        return body.decode("utf-8", errors="replace")


def _query_number(url: str, name: str) -> int | None:
    raw = parse_qs(urlsplit(url).query).get(name, [None])[0]
    return int(raw) if raw and raw.isdigit() else None


def _accept(site, url: str) -> str | None:
    """Return a canonical URL on the site that the crawl wants, or None."""
    if hasattr(site, "canonicalize"):
        return site.canonicalize(url)
    absolute = urljoin(site.BASE + "/", url)
    path = site_path(site.BASE, absolute)
    if path is None:
        return None
    for prefix in getattr(site, "SKIP_PREFIXES", ()):
        if path.startswith(prefix):
            return None
    kept = []
    query = parse_qs(urlsplit(absolute).query)
    page = _query_number(absolute, "page")
    offset = _query_number(absolute, "offset")
    letter = query.get("letter", [None])[0]
    if letter and re.fullmatch(r"[0-9A-Za-z-]{1,8}", letter):
        kept.append(f"letter={letter}")
    if page not in (None, 0, 1):
        kept.append(f"page={page}")
    if offset not in (None, 0):
        kept.append(f"offset={offset}")
    base = urlsplit(site.BASE)
    canon = urlunsplit((base.scheme, base.netloc, "/" if path == "/" else path, "&".join(kept), ""))
    for candidate in (canon, canon + "/"):
        if site.song_id(candidate) or site.is_listing(candidate):
            return candidate
    return None


def _linked(site, html: str, page_url: str) -> list[str]:
    """Return the song and listing URLs a page links to."""
    if hasattr(site, "crawl_urls"):
        return [url for url in site.crawl_urls(html, page_url) if url]
    found: list[str] = []
    seen: set[str] = set()

    def add(href: str) -> None:
        canon = _accept(site, urljoin(page_url, href))
        if canon and canon not in seen:
            seen.add(canon)
            found.append(canon)

    for href, _text in page_links(html):
        add(href)
    for match in _NEXT_HREF.finditer(html):
        add(match.group(1) or match.group(2))
    for loc in _LOC.findall(html):
        add(loc)
    current = _accept(site, page_url) or ""
    on_first = _query_number(current, "page") in (None, 1) and _query_number(current, "offset") in (
        None,
        0,
    )
    if not on_first:
        return found
    pages: dict[str, int] = {}
    offsets: dict[str, list[int]] = {}
    for url in list(found):
        bare = urlunsplit(urlsplit(url)._replace(query="", fragment=""))
        page = _query_number(url, "page")
        offset = _query_number(url, "offset")
        if page:
            pages[bare] = max(pages.get(bare, 0), page)
        if offset:
            offsets.setdefault(bare, []).append(offset)
    for bare, last in pages.items():
        if 1 < last <= PAGE_CAP and site.is_listing(bare):
            for number in range(2, last + 1):
                add(f"{bare}?page={number}")
    for bare, values in offsets.items():
        step, end = min(values), max(values)
        if step and end // step <= OFFSET_CAP and site.is_listing(bare):
            for offset in range(step, end + 1, step):
                add(f"{bare}?offset={offset}")
    return found


def _seeds(site) -> list[str]:
    found = []
    for seed in site.SEEDS:
        url = seed if seed.startswith("http") else urljoin(site.BASE + "/", seed)
        canon = _accept(site, url) or url
        if canon not in found:
            found.append(canon)
    return found


class _Session:
    """One run: robots first, a wait between requests, a stop when the site refuses."""

    def __init__(self, fetch: Fetch, sleep: Callable[[float], None], delay: float) -> None:
        self.fetch, self.sleep, self.delay = fetch, sleep, delay
        self.requests = self.errors = self.errors_in_a_row = self.robots_disallowed = 0
        self.retries = 0
        self.robots_ready = False
        self._robots_url = ""

    def _send(self, url: str) -> tuple[int, dict[str, str], bytes]:
        waits = iter(RETRY_WAITS)
        while True:
            if self.requests:
                self.sleep(self.delay)
            self.requests += 1
            try:
                status, headers, body = self.fetch(url)
            except UnicodeError:
                return 400, {}, b""
            if headers.get("X-Timeout"):
                return status, headers, body
            empty = status == 200 and not body.strip()
            passing = status == 0 or status >= 500 or empty
            wait = next(waits, None) if passing else None
            if wait is None:
                return status, headers, body
            self.retries += 1
            self.sleep(wait)

    def read_robots(self, site, fetch_robots: Callable[[str], None]) -> None:
        from urllib.robotparser import RobotFileParser

        self.robots = RobotFileParser()
        self._robots_url = site.BASE + "/robots.txt"
        status, _headers, body = self._send(self._robots_url)
        self.robots_ready = True
        if status == 200 and body.strip():
            self.robots.parse(_text(body).splitlines())
            self.delay = max(self.delay, float(self.robots.crawl_delay(USER_AGENT) or 0))
            fetch_robots(self._robots_url, body)
        elif status in STOP_STATUSES:
            raise _Stop(f"the site answered with HTTP {status}")
        elif 400 <= status < 500:
            self.robots.allow_all = True
        else:
            raise _Stop(f"robots.txt was not read (status {status})")

    def allowed(self, url: str) -> bool:
        return bool(self.robots.can_fetch(USER_AGENT, url))

    def get(self, url: str) -> tuple[int, dict[str, str], bytes, str]:
        """Return status, headers, body and '' or a reason the page was not read."""
        if not self.allowed(url):
            self.robots_disallowed += 1
            return 0, {}, b"", "robots_disallowed"
        status, headers, body = self._send(url)
        if status in STOP_STATUSES:
            raise _Stop(f"the site answered with HTTP {status}")
        if status != 200 or not body.strip():
            self.errors += 1
            return status, headers, body, "http_error"
        self.errors_in_a_row = 0
        return status, headers, body, ""


def _alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _lock(staging: Path) -> None:
    path = staging / "RUNNING"
    staging.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        pid = int(path.read_text(encoding="utf-8").strip() or "0")
        if _alive(pid):
            raise CollectError(f"a crawl of this source is already running (process {pid})")
        path.unlink()
    path.write_text(str(os.getpid()) + "\n", encoding="utf-8", newline="\n")


def _unlock(staging: Path) -> None:
    path = staging / "RUNNING"
    if path.is_file():
        path.unlink()


def _replay(staging: Path, site, seen: set[str], queue: deque[str], queued: set[str]) -> None:
    """Add links from listing pages already saved, so a later run can continue."""
    folder = staging / "receipts"
    if not folder.is_dir():
        return
    for path in sorted(folder.glob("*.json")):
        receipt = json.loads(path.read_text(encoding="utf-8"))
        url = receipt.get("url") or ""
        if url not in seen:
            continue
        body = staging / "responses" / f"{receipt.get('receipt_id', '')}.body.gz"
        if not body.is_file():
            continue
        html = _text(gzip.decompress(body.read_bytes()))
        for link in _linked(site, html, url):
            if link not in queued:
                queued.add(link)
                if site.song_id(link):
                    queue.appendleft(link)
                else:
                    queue.append(link)


def _load_seen(staging: Path) -> set[str]:
    path = staging / "seen.txt"
    if not path.is_file():
        return set()
    return {line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()}


def _urls_in_tar(path: Path) -> set[str]:
    """Return the page URLs stored in one packed raw part."""
    found: set[str] = set()
    try:
        with tarfile.open(path, "r:gz", encoding="utf-8") as archive:
            for member in archive:
                name = member.name.replace("\\", "/")
                receipt_name = f"/{name}"
                if not member.isfile() or "/receipts/" not in receipt_name:
                    continue
                if not name.endswith(".json"):
                    continue
                handle = archive.extractfile(member)
                if handle is None:
                    continue
                receipt = json.loads(handle.read().decode("utf-8"))
                url = receipt.get("url") or ""
                if url:
                    found.add(url)
    except OSError, tarfile.TarError, json.JSONDecodeError, UnicodeError:
        return found
    return found


def _stored_urls(data: Path, source: str, staging: Path) -> set[str]:
    """Return every page URL already stored for this source.

    A later run does not request these. They may be in the staging folder, or in
    any dated raw folder. A dated folder that already has a manifest is never
    rewritten; the new pages go to a new dated folder.
    """
    found = _load_seen(staging)
    receipts = staging / "receipts"
    if receipts.is_dir():
        for path in receipts.glob("*.json"):
            try:
                receipt = json.loads(path.read_text(encoding="utf-8"))
            except OSError, json.JSONDecodeError, UnicodeError:
                continue
            url = receipt.get("url") or ""
            if url:
                found.add(url)
    root = data / "raw" / source
    if root.is_dir():
        for folder in root.iterdir():
            if folder.is_dir():
                for tar_path in folder.glob("pages-*.tar.gz"):
                    found.update(_urls_in_tar(tar_path))
    return found


def _append_seen(staging: Path, url: str) -> None:
    with (staging / "seen.txt").open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(url + "\n")


def _next_id(staging: Path) -> int:
    path = staging / "next_id.txt"
    if path.is_file() and path.read_text(encoding="utf-8").strip().isdigit():
        return int(path.read_text(encoding="utf-8").strip())
    return 1


def _store_id(staging: Path, number: int) -> None:
    (staging / "next_id.txt").write_text(str(number) + "\n", encoding="utf-8", newline="\n")


def _save_page(
    staging: Path,
    number: int,
    url: str,
    status: int,
    headers: dict[str, str],
    body: bytes,
    error: str,
) -> None:
    key = f"{number:08d}"
    receipt = {
        "receipt_id": key,
        "url": url,
        "http_status": status,
        "error": error,
        "content_type": headers.get("Content-Type", ""),
        "response_headers": {"Content-Type": headers.get("Content-Type", "")},
        "started_at_utc": run_records.utc_now(),
        "fetched_at_utc": run_records.utc_now(),
    }
    receipt_path = staging / "receipts" / f"{key}.json"
    body_path = staging / "responses" / f"{key}.body.gz"
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    body_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(
        json.dumps(receipt, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    body_path.write_bytes(gzip.compress(body))


def _destination(data: Path, source: str, day: str | None, *, move_forward: bool) -> Path:
    if day is not None:
        folder = paths.raw_dir(data, source, day)
        if folder.exists():
            raise FileExistsError(
                f"{paths.data_relative(data, folder)} exists; raw data is never written over"
            )
        return folder
    today = datetime.now(UTC).date()
    folder = paths.raw_dir(data, source, today)
    if not folder.exists():
        return folder
    if not move_forward:
        raise FileExistsError(
            f"{paths.data_relative(data, folder)} exists; raw data is never written over"
        )
    for offset in range(1, 30):
        candidate = paths.raw_dir(data, source, today + timedelta(days=offset))
        if not candidate.exists():
            return candidate
    raise FileExistsError(f"raw/{source}/ has no free day in the next 30 days")


def _pack(data: Path, staging: Path, folder: Path, site, stopped: str, counts: dict) -> str | None:
    receipts = staging / "receipts"
    if not receipts.is_dir() or not any(receipts.glob("*.json")):
        if not stopped:
            return None
        folder.mkdir(parents=True)
        (folder / STOP_FILE).write_text(stopped + "\n", encoding="utf-8", newline="\n")
        manifests.write_manifest(
            data,
            folder,
            "raw",
            source=site.SOURCE,
            origin={"url": site.BASE, "retrieved_utc": run_records.utc_now(), "license": None},
            counts=counts,
            notes=stopped,
        )
        return paths.data_relative(data, folder)
    folder.mkdir(parents=True)
    work = staging / "work"
    parts = []
    for part in tar_parts.pack(staging, work, folders=("receipts", "responses")):
        part.path.replace(folder / part.name)
        parts.append(part)
    tar_parts.write_members(work, folder)
    if stopped:
        (folder / STOP_FILE).write_text(stopped + "\n", encoding="utf-8", newline="\n")
    manifests.write_manifest(
        data,
        folder,
        "raw",
        source=site.SOURCE,
        origin={"url": site.BASE, "retrieved_utc": run_records.utc_now(), "license": None},
        counts=counts,
        notes=f"Collected page by page. {stopped}".strip(),
    )
    return paths.data_relative(data, folder)


def _outcome(site, url: str, html: str, counts: Counter) -> None:
    if site.song_id(url) is None:
        counts["listings"] += 1
        return
    counts["songs_fetched"] += 1
    try:
        row, _artists, reason = site.parse_song(html, url)
    except Exception:
        counts["parse_error"] += 1
        return
    if row is None:
        counts[reason or "no_row"] += 1
    else:
        counts["songs_parsed"] += 1


def collect(
    data: Path,
    source: str,
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
    """Collect one site. Write the packed raw folder and one run record.

    Return the counts: requests sent, songs whose pages parsed, and pages left
    out by reason. `day` replaces the date of the folder (for tests).
    """
    try:
        site = site_module(source)
    except Exception as error:
        raise CollectError(str(error)) from error
    listed = next(item for item in lyric_sources.load_lyric_sources() if item.id == source)
    if listed.access != "allowed":
        raise CollectError(f"requests to {source} are {listed.access} in the source file")
    if all(item.id != source for item in lyric_sources.sources_for(iso3)):
        raise CollectError(f"{source} does not serve {iso3} in the source file")
    staging = data / "staging" / "site_crawl" / source
    _lock(staging)
    seen = _stored_urls(data, source, staging)
    move_forward = bool(seen) or bool(reason)
    try:
        folder = _destination(data, source, day, move_forward=move_forward)
    except FileExistsError:
        _unlock(staging)
        raise
    delay = max(delay, MIN_DELAY_SECONDS, listed.request_delay_seconds or 0)
    session = _Session(fetch or http_fetch, sleep, delay)
    number = _next_id(staging)
    counts: Counter = Counter()
    queue: deque[str] = deque(url for url in _seeds(site) if url not in seen)
    queued = set(queue) | seen
    _replay(staging, site, seen, queue, queued)
    artists = 0
    stopped = ""
    limits: dict = {}
    saved: dict = {}
    try:
        with run_records.record_run(
            iso3,
            ROUTE,
            source,
            countries=countries,
            repeat_reason=reason,
            request_delay_seconds=delay,
            artist_limit=artist_limit,
            song_limit=song_limit,
        ) as record:
            try:
                saved_robots = {"done": False}

                def remember_robots(url: str, body: bytes) -> None:
                    nonlocal number
                    if saved_robots["done"]:
                        return
                    saved_robots["done"] = True
                    _save_page(staging, number, url, 200, {"Content-Type": "text/plain"}, body, "")
                    number += 1
                    _store_id(staging, number)

                session.read_robots(site, remember_robots)
                timed_prefix = ""
                timed_run = 0
                skip_prefixes: set[str] = set()
                while queue:
                    url = queue.popleft()
                    if url in seen:
                        continue
                    section = next((part for part in urlsplit(url).path.split("/") if part), "")
                    if section in skip_prefixes:
                        counts["section_timeout"] += 1
                        seen.add(url)
                        _append_seen(staging, url)
                        continue
                    (staging / "status.txt").write_text(
                        f"songs {counts['songs_fetched']}\nqueue {len(queue)}\nurl {url}\n",
                        encoding="utf-8",
                        newline="\n",
                    )
                    if (
                        artist_limit is not None
                        and site.is_artist_page(url)
                        and artists >= artist_limit
                    ):
                        limits["artist_limit"] = artist_limit
                        continue
                    try:
                        status, headers, body, problem = session.get(url)
                    except UnicodeError:
                        status, headers, body, problem = 400, {}, b"", "bad_url"
                    if problem == "robots_disallowed":
                        counts["robots_disallowed"] += 1
                        continue
                    if headers.get("X-Timeout"):
                        counts["timeout"] += 1
                        timed_run = timed_run + 1 if section == timed_prefix else 1
                        timed_prefix = section
                        if timed_run >= 2 and section:
                            skip_prefixes.add(section)
                        continue
                    if problem:
                        counts["http_error"] += 1
                        if 400 <= status < 500:
                            seen.add(url)
                            _append_seen(staging, url)
                        continue
                    _save_page(staging, number, url, status, headers, body, "")
                    number += 1
                    _store_id(staging, number)
                    seen.add(url)
                    _append_seen(staging, url)
                    html = _text(body)
                    _outcome(site, url, html, counts)
                    if site.is_artist_page(url):
                        artists += 1
                    for link in _linked(site, html, url):
                        if link not in queued and session.allowed(link):
                            queued.add(link)
                            if site.song_id(link):
                                queue.appendleft(link)
                            else:
                                queue.append(link)
                        elif link not in queued:
                            counts["robots_disallowed"] += 1
                            queued.add(link)
                    if song_limit is not None and counts["songs_fetched"] >= song_limit:
                        limits["song_limit"] = song_limit
                        stopped = f"The run reached the song limit of {song_limit}."
                        break
                    if counts["songs_fetched"] and counts["songs_fetched"] % 25 == 0:
                        try:
                            print(
                                f"{source} songs={counts['songs_fetched']} "
                                f"parsed={counts['songs_parsed']} queue={len(queue)}",
                                flush=True,
                            )
                        except UnicodeError:
                            pass
            except _Stop as stop:
                stopped = f"The run stopped: {stop}."
                limits["stopped"] = str(stop)
                record.state = "partial"
            except BaseException as error:
                stopped = f"The run stopped: {type(error).__name__}."
                limits["stopped"] = type(error).__name__
                raise
            finally:
                if stopped:
                    (staging / STOP_FILE).write_text(stopped + "\n", encoding="utf-8", newline="\n")
                left = {
                    name: value
                    for name, value in sorted(counts.items())
                    if name not in ("songs_fetched", "songs_parsed", "listings")
                }
                report = {
                    "pages_saved": number - 1,
                    "songs_fetched": counts["songs_fetched"],
                    "songs_parsed": counts["songs_parsed"],
                    "listings": counts["listings"],
                    **{f"left_out_{name}": value for name, value in left.items()},
                }
                record.request_delay_seconds = session.delay
                record.requests_sent = session.requests
                record.artists_attempted = artists
                record.songs_attempted = counts["songs_fetched"] + sum(
                    counts[name] for name in ("http_error", "robots_disallowed", "parse_error")
                )
                record.songs_accepted = counts["songs_parsed"]
                record.songs_rejected = left
                record.limits_hit = limits
                record.rows_added = 0
                if session.robots_disallowed:
                    record.known_gaps.append(
                        "robots.txt disallows "
                        f"{session.robots_disallowed} pages; they were not read"
                    )
                if counts["timeout"]:
                    record.known_gaps.append(
                        f"{counts['timeout']} pages timed out and "
                        f"{counts['section_timeout']} later pages in those sections were skipped"
                    )
                if stopped:
                    record.known_gaps.append(stopped)
                path = _pack(data, staging, folder, site, stopped, report)
                saved.update(path=path, state=record.state, gaps=list(record.known_gaps))
                if path:
                    record.notes = f"{record.notes} Wrote {path}".strip()
                if path and not stopped:
                    for child in list(staging.iterdir()):
                        if child.name == "RUNNING":
                            continue
                        if child.is_dir():
                            shutil.rmtree(child, ignore_errors=True)
                        else:
                            child.unlink(missing_ok=True)
    finally:
        _unlock(staging)
    return {
        "path": saved.get("path"),
        "state": saved.get("state", "failed"),
        "requests_sent": session.requests,
        "retries": session.retries,
        "songs_written": counts["songs_parsed"],
        "songs_left_out": {
            name: value
            for name, value in sorted(counts.items())
            if name not in ("songs_fetched", "songs_parsed", "listings")
        },
        "known_gaps": saved.get("gaps", []),
    }
