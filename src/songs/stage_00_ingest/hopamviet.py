"""The page reader of the chord site `hopamviet`, for `site_pages.parse_folder`.

A song page is `/chord/song/<slug>/<id>.html`. The `h1` is the title. The credited
person is the composer link, and the singer link when the page names no composer.
The lyric is `#lyric-version-0`. Chord names sit in `span.chord` between words, and
the lines are separated by newlines. The reader removes those spans and then calls
`pesmarica.lyric_lines`.
"""

import re
import sys
from html.parser import HTMLParser
from urllib.parse import urlsplit, urlunsplit

from songs.stage_00_ingest.dump_match import name_key
from songs.stage_00_ingest.pesmarica import lyric_lines
from songs.stage_00_ingest.site_pages import song_row

SOURCE = "hopamviet"
BASE = "https://hopamviet.vn"
ARTIST_URL = BASE + "/chord/{}"
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
SEEDS = (
    BASE + "/",
    BASE + "/info/singers",
    BASE + "/info/composers",
    BASE + "/chord/latest",
    BASE + "/chord/hot",
)
SKIP_PREFIXES = (
    "/chord/printsong/",
    "/chord/search",
    "/auth/",
    "/user/",
    "/sheet/download/",
)
_SONG = re.compile(re.escape(BASE) + r"/chord/song/[^/]+/([A-Za-z0-9]+)\.html")
_PERSON = re.compile(r"/chord/(composer|singer)/(\d+)/([^\"#?]+)")
_CHORD_SPAN = re.compile(r'<span\b[^>]*\bclass="chord"[^>]*>.*?</span>', re.S)
_TITLE = re.compile(r"(?i)^hợp\s*âm\s+")
_TRANSLATION = ("loi dich", "ban dich", "phien dich")
_VOID = frozenset({"br", "img", "hr", "meta", "link", "input", "source", "wbr"})
_LISTING = (
    "/info/singers",
    "/info/composers",
    "/chord/singer/",
    "/chord/composer/",
    "/chord/category/",
    "/chord/rhythm/",
    "/chord/latest",
    "/chord/hot",
)
_ARTIST_PATH = re.compile(r"/chord/(?:singer|composer)/\d+(?:/[^/]*)?")


class _Page(HTMLParser):
    """Read the heading, the composer and singer links, and one lyric block."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.h1 = ""
        self.people: list[tuple[str, str, str]] = []
        self.lyric = ""
        self._depth = 0
        self._mute = 0
        self._lyric = 0
        self._in_h1 = False
        self._href = ""
        self._text = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        found = dict(attrs)
        if tag in _VOID:
            if tag == "br" and self._lyric and not self._mute:
                self.lyric += "\n"
            return
        self._depth += 1
        if self._mute:
            return
        if tag in ("script", "style"):
            self._mute = self._depth
            return
        if tag == "h1" and not self.h1:
            self._in_h1 = True
        if tag == "a" and not self._lyric:
            self._href, self._text = found.get("href") or "", ""
        if tag == "div" and found.get("id") == "lyric-version-0":
            self._lyric = self._depth

    def handle_endtag(self, tag: str) -> None:
        if tag in _VOID:
            return
        if tag == "h1":
            self._in_h1 = False
        if tag == "a" and self._href and not self._mute:
            self._add_person()
        if self._mute and self._depth == self._mute:
            self._mute = 0
        if self._lyric and self._depth == self._lyric:
            self._lyric = 0
        self._depth -= 1

    def handle_data(self, data: str) -> None:
        if self._mute:
            return
        if self._in_h1:
            self.h1 += data
        if self._href:
            self._text += data
        if self._lyric:
            self.lyric += data

    def _add_person(self) -> None:
        found = _PERSON.search(self._href)
        name = " ".join(self._text.split())
        self._href = ""
        if found is None or not name or name_key(name).startswith("xem"):
            return
        kind, number, slug = found.groups()
        self.people.append((kind, f"{kind}/{number}/{slug}", name))


def _artists(people: list[tuple[str, str, str]]) -> list[tuple[str, str]]:
    """Return unique (id, name) composers, or singers when the page has no composer."""
    chosen = [item for item in people if item[0] == "composer"] or [
        item for item in people if item[0] == "singer"
    ]
    unique: list[tuple[str, str]] = []
    seen: set[str] = set()
    for _kind, artist_id, name in chosen:
        if artist_id not in seen:
            seen.add(artist_id)
            unique.append((artist_id, name))
    return unique


def _clean(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def song_id(url: str) -> str | None:
    """Return the song id of a song page URL, or None."""
    found = _SONG.fullmatch(_clean(url))
    return found.group(1) if found else None


def is_listing(url: str) -> bool:
    """Return True when the URL is an index, artist, category or rhythm page."""
    if song_id(url):
        return False
    path = urlsplit(url).path
    return path.startswith(_LISTING)


def is_artist_page(url: str) -> bool:
    """Return True for a singer or composer page."""
    return _ARTIST_PATH.fullmatch(urlsplit(url).path) is not None


def _read(html: str) -> _Page:
    page = _Page()
    page.feed(_CHORD_SPAN.sub("", html))
    page.close()
    return page


def parse_song(html: str, url: str) -> tuple[dict | None, list[tuple[str, str]], str]:
    """Return the row and the performers (id, name) of a song page and '', or None, [] and why."""
    page = _read(html)
    if not page.lyric.strip():
        return None, [], "no_lyric_block"
    title = _TITLE.sub("", " ".join(page.h1.split())).strip()
    if any(phrase in name_key(title) for phrase in _TRANSLATION):
        return None, [], "translation"
    artists = _artists(page.people)
    lines = lyric_lines(page.lyric, title, *(name for _artist_id, name in artists))
    return song_row(sys.modules[__name__], url, title, artists, lines)
