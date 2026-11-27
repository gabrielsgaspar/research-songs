"""The page reader of the chord site `musiburma`, for `site_pages.parse_folder`.

A song page is `/songs/<artist slug>/<song slug>`. The `h1` is the title. The
performers are the `/artists/` links in the line under the title. The sheet is
`#chord-lyrics-content`. Each syllable is a `div.whitespace-pre-wrap`, and the chord
sits in the `div.mb-1` above it. A flex row is one line. The reader keeps the
syllables, drops the chord row, and then calls `pesmarica.lyric_lines`.
"""

import sys
from html.parser import HTMLParser
from urllib.parse import urlsplit

from songs.stage_00_ingest.dump_match import name_key
from songs.stage_00_ingest.pesmarica import lyric_lines
from songs.stage_00_ingest.site_pages import song_row

SOURCE = "musiburma"
BASE = "https://www.musiburma.com"
ARTIST_URL = BASE + "/artists/{}"
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
INSTRUMENTAL = frozenset({"instrumental"})
TITLE_KINDS = ()
SEEDS = (
    BASE + "/",
    BASE + "/sitemap.xml",
    BASE + "/songs",
    BASE + "/artists",
    BASE + "/albums",
    BASE + "/composers",
)
SKIP_PREFIXES = ("/api/",)
_INDEXES = frozenset({"songs", "artists", "albums", "composers", "collections"})
_TRANSLATION = ("loi dich", "ban dich", "translation")
_VOID = frozenset({"br", "img", "hr", "meta", "link", "input", "source", "wbr"})


class _Page(HTMLParser):
    """Read the heading, the header artists and the syllable lines of the sheet."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.h1 = ""
        self.artists: list[tuple[str, str]] = []
        self.lines: list[str] = []
        self.saw_sheet = False
        self._depth = 0
        self._sheet = 0
        self._mute = 0
        self._in_h1 = False
        self._href = ""
        self._text = ""
        self._capture = False
        self._line = ""
        self._seen: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        found = dict(attrs)
        classes = set((found.get("class") or "").split())
        if tag in _VOID:
            return
        self._depth += 1
        if found.get("id") == "chord-lyrics-content":
            self.saw_sheet = True
            self._sheet = self._depth
            self._flush()
        if self._mute:
            return
        if tag in ("script", "style"):
            self._mute = self._depth
            return
        if tag == "h1" and not self.h1:
            self._in_h1 = True
        if tag == "a" and not self._sheet:
            self._href, self._text = found.get("href") or "", ""
        if not self._sheet:
            return
        if tag == "div" and "mb-1" in classes:
            self._mute = self._depth
            return
        if tag == "div" and "flex-wrap" in classes:
            self._flush()
        if tag == "div" and "whitespace-pre-wrap" in classes:
            self._capture = True

    def handle_endtag(self, tag: str) -> None:
        if tag in _VOID:
            return
        if tag == "h1":
            self._in_h1 = False
        if tag == "a" and self._href and not self._mute and not self._sheet:
            self._add_artist()
        if tag == "span" and self._capture:
            self._capture = False
            self._flush()
        if tag == "div" and self._capture:
            self._capture = False
        if self._mute and self._depth == self._mute:
            self._mute = 0
        if self._sheet and self._depth == self._sheet:
            self._flush()
            self._sheet = 0
        self._depth -= 1

    def handle_data(self, data: str) -> None:
        if self._mute:
            return
        if self._in_h1:
            self.h1 += data
        if self._href and not self._sheet:
            self._text += data
        if self._capture:
            self._line += data

    def _add_artist(self) -> None:
        parts = [part for part in urlsplit(self._href).path.split("/") if part]
        name = " ".join(self._text.split())
        self._href = ""
        if len(parts) != 2 or parts[0] != "artists" or not name or parts[1] in self._seen:
            return
        self._seen.add(parts[1])
        self.artists.append((parts[1], name))

    def _flush(self) -> None:
        text = " ".join(self._line.replace("\xa0", " ").split())
        if text:
            self.lines.append(text)
        self._line = ""


def song_id(url: str) -> str | None:
    """Return the song id of a song page URL, or None."""
    parts = [part for part in urlsplit(url).path.split("/") if part]
    if len(parts) == 3 and parts[0] == "songs":
        return f"{parts[1]}/{parts[2]}"
    return None


def is_listing(url: str) -> bool:
    """Return True for a songs, artists, albums, composers or collections page."""
    if song_id(url):
        return False
    parts = [part for part in urlsplit(url).path.split("/") if part]
    return bool(parts) and parts[0] in _INDEXES


def is_artist_page(url: str) -> bool:
    """Return True for an artist page."""
    parts = [part for part in urlsplit(url).path.split("/") if part]
    return len(parts) == 2 and parts[0] == "artists"


def _read(html: str) -> _Page:
    page = _Page()
    page.feed(html)
    page.close()
    return page


def parse_song(html: str, url: str) -> tuple[dict | None, list[tuple[str, str]], str]:
    """Return the row and the performers (id, name) of a song page and '', or None, [] and why."""
    page = _read(html)
    if not page.saw_sheet:
        return None, [], "no_lyric_block"
    title = " ".join(page.h1.split())
    if any(phrase in name_key(title) for phrase in _TRANSLATION):
        return None, [], "translation"
    lines = lyric_lines("\n".join(page.lines), title, *(name for _artist_id, name in page.artists))
    return song_row(sys.modules[__name__], url, title, page.artists, lines)
