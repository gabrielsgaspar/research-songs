"""The page reader of the lyric site `loibaihat`, for `site_pages.parse_folder`.

A song page is `/lyric/<id>/<slug>/`. The `h1` is "Lời bài hát" plus the title.
The artist is the first `/nhac-si/` link that has text. The lyric is `div.lyric-song`:
lines are `br` elements, and the block also holds an ad and a repeated heading.
The reader skips those and then calls `pesmarica.lyric_lines`.
"""

import re
import sys
from html.parser import HTMLParser
from urllib.parse import urlsplit, urlunsplit

from songs.stage_00_ingest.dump_match import name_key
from songs.stage_00_ingest.pesmarica import lyric_lines
from songs.stage_00_ingest.site_pages import song_row

SOURCE = "loibaihat"
BASE = "https://loibaihat.biz"
ARTIST_URL = BASE + "/nhac-si/{}/"
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
    *(f"{BASE}/lyrics/{letter}/" for letter in "abcdefghijklmnopqrstuvwxyz"),
    BASE + "/lyrics/vn/",
    BASE + "/lyrics/qt/",
)
SKIP_PREFIXES = ("/timkiem/",)
_SONG = re.compile(re.escape(BASE) + r"/lyric/([A-Za-z0-9]+)/[^/?#]+/?")
_ARTIST = re.compile(r"/nhac-si/([^/?#]+)/?")
_TITLE = re.compile(r"(?i)^lời bài hát\s+")
_LANG = re.compile(r"Ngôn ngữ:\s*</b>\s*</td>\s*<td>([^<]+)", re.I)
_YEAR = re.compile(r"Năm sáng tác:\s*</b>\s*</td>\s*<td>\s*(\d{4})\b", re.I)
_PERFORMERS = re.compile(
    r"Các ca sĩ thể hiện:\s*</b>\s*</td>"
    r"(?:\s*</tr>\s*<tr>\s*<td[^>]*>|\s*<td>)\s*([^<]*)",
    re.I,
)
_TRANSLATION = ("loi dich", "ban dich", "phien dich")
_VOID = frozenset({"br", "img", "hr", "meta", "link", "input", "source", "wbr"})
_MUTE_TAGS = frozenset({"script", "style", "ins", "h2"})


class _Page(HTMLParser):
    """Read the heading, the first artist link and the lyric block."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.h1 = ""
        self.artists: list[tuple[str, str]] = []
        self.lyric = ""
        self._depth = 0
        self._mute = 0
        self._lyric = 0
        self._in_h1 = False
        self._href = ""
        self._text = ""
        self._seen: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        found = dict(attrs)
        classes = (found.get("class") or "").split()
        if tag in _VOID:
            if tag == "br" and self._lyric and not self._mute:
                self.lyric += "\n"
            return
        self._depth += 1
        if self._mute:
            return
        if tag in _MUTE_TAGS or (tag == "div" and "abn" in classes):
            self._mute = self._depth
            return
        if tag == "h1" and not self.h1:
            self._in_h1 = True
        if tag == "a" and not self._lyric:
            self._href, self._text = found.get("href") or "", ""
        if tag == "div" and "lyric-song" in classes:
            self._lyric = self._depth

    def handle_endtag(self, tag: str) -> None:
        if tag in _VOID:
            return
        if tag == "h1":
            self._in_h1 = False
        if tag == "a" and self._href and not self._mute:
            self._add_artist()
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
            piece = data.replace("\r", "").replace("\n", "")
            if piece:
                self.lyric += piece

    def _add_artist(self) -> None:
        found = _ARTIST.search(self._href)
        name = " ".join(self._text.split())
        self._href = ""
        if found is None or not name or found.group(1) in self._seen:
            return
        self._seen.add(found.group(1))
        self.artists.append((found.group(1), name))


def _clean(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def song_id(url: str) -> str | None:
    """Return the song id of a song page URL, or None."""
    found = _SONG.fullmatch(_clean(url))
    return found.group(1) if found else None


def is_listing(url: str) -> bool:
    """Return True for a letter index or an artist page."""
    if song_id(url):
        return False
    path = urlsplit(url).path
    return path.startswith(("/lyrics/", "/nhac-si/"))


def is_artist_page(url: str) -> bool:
    """Return True for an artist page."""
    parts = [part for part in urlsplit(url).path.split("/") if part]
    return len(parts) == 2 and parts[0] == "nhac-si"


def _read(html: str) -> _Page:
    page = _Page()
    page.feed(html)
    page.close()
    return page


def _named_performers(html: str) -> list[tuple[None, str]]:
    """Return singer names from the credit table when the page has no artist link."""
    found = _PERFORMERS.search(html)
    if found is None:
        return []
    names = [" ".join(part.split()) for part in found.group(1).split(",")]
    return [(None, name) for name in names if name]


def parse_song(html: str, url: str) -> tuple[dict | None, list[tuple[str, str]], str]:
    """Return the row and the performers (id, name) of a song page and '', or None, [] and why."""
    page = _read(html)
    if not page.lyric.strip():
        return None, [], "no_lyric_block"
    title = _TITLE.sub("", " ".join(page.h1.split())).strip()
    if any(phrase in name_key(title) for phrase in _TRANSLATION):
        return None, [], "translation"
    language = _LANG.search(html)
    year = _YEAR.search(html)
    columns: dict[str, str] = {}
    if language and language.group(1).strip():
        columns["language_label"] = " ".join(language.group(1).split())
    if year:
        columns["release_year_raw"] = year.group(1)
    artists = list(page.artists) or _named_performers(html)
    lines = lyric_lines(page.lyric, title, *(name for _artist_id, name in artists))
    return song_row(sys.modules[__name__], url, title, artists, lines, **columns)
