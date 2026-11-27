"""The page reader of the chord site `hopamchuan`, for `site_pages.parse_folder`.

A song page is `/song/<id>/<slug>`. The `h1` is the title. The performers are the
`/artist/` links in the header, before `#song-lyric`. Each lyric line is a
`div.chord_lyric_line`: the words are `span.hopamchuan_lyric` and the chord names
are `span.hopamchuan_chord`. The reader keeps the words and then calls
`pesmarica.lyric_lines`.
"""

import re
import sys
from html.parser import HTMLParser
from urllib.parse import parse_qs, urljoin, urlsplit, urlunsplit

from songs.stage_00_ingest.dump_match import name_key
from songs.stage_00_ingest.pesmarica import lyric_lines
from songs.stage_00_ingest.site_pages import page_links, site_path, song_row

SOURCE = "hopamchuan"
BASE = "https://hopamchuan.com"
ARTIST_URL = BASE + "/artist/{}"
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
INSTRUMENTAL = frozenset({"instrumental", "khong loi"})
TITLE_KINDS = ()
SEEDS = ("/", "/rhythm", "/genre")
_SONG = re.compile(r"/song/(\d+)(?:/[^/]+)?")
_LIST = re.compile(r"/(?:artist/\d+(?:/[^/]+)?|rhythm(?:/v/[^/]+)?|genre(?:/v/[^/]+)?)")
_SKIP = (
    "/auth",
    "/manage",
    "/user",
    "/profile",
    "/playlist",
    "/song/create",
    "/report",
    "/find_by_chord",
    "/scale",
    "/apps",
    "/deals",
)
_TRANSLATION = ("loi dich", "ban dich", "phien dich")
_OFFSET_CAP = 20_000
_VOID = frozenset({"br", "img", "hr", "meta", "link", "input", "source", "wbr"})


class _Song(HTMLParser):
    """Read the heading, the header artists and the lyric lines."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.h1 = ""
        self.artists: list[tuple[str, str]] = []
        self.lines: list[str] = []
        self.saw_sheet = False
        self._in = 0
        self._modes: list[str] = []
        self._past = False
        self._in_h1 = False
        self._href = ""
        self._text = ""
        self._seen: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        found = dict(attrs)
        classes = set((found.get("class") or "").split())
        if tag in _VOID:
            return
        if found.get("id") == "song-lyric":
            self.saw_sheet = True
            self._past = True
            self._in = 1
            return
        if self._in and tag == "div":
            self._in += 1
        if tag == "h1" and not self.h1 and not self._past:
            self._in_h1 = True
        if tag == "a" and not self._past:
            self._href, self._text = found.get("href") or "", ""
        if not self._in:
            return
        if tag == "div" and ("chord_lyric_line" in classes or "empty_line" in classes):
            self._modes.append("line")
            self.lines.append("")
        if tag == "span" and "hopamchuan_lyric" in classes:
            self._modes.append("words")

    def handle_endtag(self, tag: str) -> None:
        if tag in _VOID:
            return
        if tag == "h1":
            self._in_h1 = False
        if tag == "a" and self._href and not self._past:
            self._add_artist()
        if tag == "span" and self._modes and self._modes[-1] == "words":
            self._modes.pop()
        if tag == "div" and self._modes and self._modes[-1] == "line":
            self._modes.pop()
        if self._in and tag == "div":
            self._in -= 1

    def handle_data(self, data: str) -> None:
        if self._in_h1:
            self.h1 += data
        if self._href and not self._past:
            self._text += data
        if self._modes and self._modes[-1] == "words" and self.lines:
            self.lines[-1] += data

    def _add_artist(self) -> None:
        parts = [part for part in urlsplit(self._href).path.split("/") if part]
        name = " ".join(self._text.split())
        self._href = ""
        if len(parts) < 2 or parts[0] != "artist" or not parts[1].isdigit() or not name:
            return
        if parts[1] in self._seen:
            return
        self._seen.add(parts[1])
        self.artists.append((parts[1], name))


def _offset(url: str) -> int | None:
    raw = parse_qs(urlsplit(url).query).get("offset", [None])[0]
    return int(raw) if raw and raw.isdigit() else None


def canonicalize(url: str) -> str | None:
    """Return the on-site song or listing URL, or None."""
    path = site_path(BASE, url)
    if path is None or path.startswith(_SKIP):
        return None
    if _SONG.fullmatch(path) is None and _LIST.fullmatch(path) is None:
        return None
    offset = _offset(url)
    if offset in (None, 0):
        return BASE + path
    return f"{BASE}{path}?offset={offset}"


def song_id(url: str) -> str | None:
    """Return the song id of a song page URL, or None."""
    path = site_path(BASE, url)
    found = _SONG.fullmatch(path or "")
    return found.group(1) if found else None


def is_listing(url: str) -> bool:
    """Return True for an artist, rhythm or genre page."""
    path = site_path(BASE, url) or ""
    return _LIST.fullmatch(path) is not None and song_id(url) is None


def is_artist_page(url: str) -> bool:
    """Return True for an artist page."""
    path = site_path(BASE, url) or ""
    return path.startswith("/artist/")


def crawl_urls(html: str, page_url: str) -> list[str]:
    """Return the song and listing URLs a page links to, including later offsets."""
    found: list[str] = []
    seen: set[str] = set()

    def add(href: str) -> None:
        canon = canonicalize(urljoin(page_url, href))
        if canon and canon not in seen:
            seen.add(canon)
            found.append(canon)

    for href, _text in page_links(html):
        add(href)
    if _offset(page_url) not in (None, 0):
        return found
    groups: dict[str, list[int]] = {}
    for url in list(found):
        offset = _offset(url)
        if offset:
            bare = urlunsplit(urlsplit(url)._replace(query="", fragment=""))
            groups.setdefault(bare, []).append(offset)
    for bare, values in groups.items():
        step, end = min(values), max(values)
        if step and end // step <= _OFFSET_CAP and is_listing(bare):
            for offset in range(step, end + 1, step):
                add(f"{bare}?offset={offset}")
    return found


def _read(html: str) -> _Song:
    page = _Song()
    page.feed(html)
    page.close()
    return page


def parse_song(html: str, url: str) -> tuple[dict | None, list[tuple[str, str]], str]:
    """Return the row and the performers (id, name) of a song page and '', or None, [] and why."""
    if song_id(url) is None:
        return None, [], "not_song_page"
    page = _read(html)
    if not page.saw_sheet:
        return None, [], "no_lyric_block"
    title = " ".join(page.h1.split())
    if any(phrase in name_key(title) for phrase in _TRANSLATION):
        return None, [], "translation"
    lines = lyric_lines("\n".join(page.lines), title, *(name for _artist_id, name in page.artists))
    return song_row(sys.modules[__name__], url, title, page.artists, lines)
