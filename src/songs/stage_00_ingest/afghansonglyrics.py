"""The page reader of the lyric site `afghansonglyrics`, for `site_pages.parse_folder`.

A song page is `/Artist/Lyrics/<id>/<slug>`. It has two panels. `div.dari-text` holds
the title, the singer and the lyric in Persian script. `div.en-text` holds the same in
Latin letters. In each panel the `h1` is the title, then `small`, then a link
`/Artist/Albums/<artist id>/<slug>` with the name of the singer, and `div.lyric` is
the text. The reader takes the title from the Latin panel, because Discogs writes
Afghan titles in Latin letters. It gives the singer two credits with one artist id:
the Latin name first, then the name in Persian script, because the roster holds names
in both scripts. It takes the lyric from the Persian-script panel, and from the Latin
panel when the first one is empty. The page prints no year and no album.

`/Home/Browse` is the index of the singers, and `/Artist/All-Lyrics/<artist id>/<slug>`
lists the songs of one singer.
"""

import re
import sys
from html.parser import HTMLParser
from urllib.parse import urlsplit

from songs.stage_00_ingest.site_pages import song_row

SOURCE = "afghansonglyrics"
BASE = "https://www.afghansonglyrics.com"
ARTIST_URL = BASE + "/Artist/All-Lyrics/{}"
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
SEEDS = (BASE + "/", BASE + "/Home/Browse")
_SONG = re.compile(r"/Artist/Lyrics/(\d+)(?:/[^/]*)?/?")
_ARTIST = re.compile(r"/Artist/Albums/(\d+/[^/?#]+)")
_PANELS = {"dari-text": "native", "en-text": "latin"}
_VOID = frozenset({"br", "img", "hr", "meta", "link", "input", "source", "wbr"})


class _Page(HTMLParser):
    """Read the title, the singer and the lyric of each of the two panels."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = {"native": "", "latin": ""}
        self.lyric = {"native": "", "latin": ""}
        self.singer: dict[str, tuple[str, str]] = {}
        self._depth = 0
        self._panel = ""
        self._panel_depth = 0
        self._lyric = 0
        self._in_title = False
        self._href = ""
        self._text = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        found = dict(attrs)
        classes = (found.get("class") or "").split()
        if tag in _VOID:
            if tag == "br" and self._lyric:
                self.lyric[self._panel] += "\n"
            return
        self._depth += 1
        panel = next((_PANELS[name] for name in classes if name in _PANELS), "")
        if tag == "div" and panel and not self._panel:
            self._panel, self._panel_depth = panel, self._depth
        if not self._panel:
            return
        if tag == "h1":
            self._in_title = True
        if tag in ("small", "a"):
            self._in_title = False
        if tag == "a" and not self._lyric:
            self._href, self._text = found.get("href") or "", ""
        if tag == "div" and "lyric" in classes:
            self._lyric = self._depth

    def handle_endtag(self, tag: str) -> None:
        if tag in _VOID:
            return
        if tag == "h1":
            self._in_title = False
        if tag == "a" and self._href:
            self._add_artist()
        if tag == "p" and self._lyric:
            self.lyric[self._panel] += "\n\n"
        if self._lyric and self._depth == self._lyric:
            self._lyric = 0
        if self._panel and self._depth == self._panel_depth:
            self._panel = ""
        self._depth -= 1

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title[self._panel] += data
        if self._href:
            self._text += data
        if self._lyric:
            self.lyric[self._panel] += data.replace("\r", "").replace("\n", " ")

    def _add_artist(self) -> None:
        found = _ARTIST.search(self._href)
        name = " ".join(self._text.split())
        self._href = ""
        if found and name and self._panel not in self.singer:
            self.singer[self._panel] = (found.group(1), name)


def song_id(url: str) -> str | None:
    """Return the song id of a song page URL, or None."""
    found = _SONG.fullmatch(urlsplit(url).path)
    return found.group(1) if found else None


def is_listing(url: str) -> bool:
    """Return True for the index of the singers or for the song list of one singer."""
    path = urlsplit(url).path.rstrip("/")
    return path == "/Home/Browse" or is_artist_page(url)


def is_artist_page(url: str) -> bool:
    """Return True for a page of the song list of one singer."""
    return urlsplit(url).path.startswith("/Artist/All-Lyrics/")


def parse_song(html: str, url: str) -> tuple[dict | None, list[tuple[str, str]], str]:
    """Return the row and the singer (id, name) of a song page and '', or None, [] and why."""
    page = _Page()
    page.feed(html)
    page.close()
    lyric = page.lyric["native"].strip() or page.lyric["latin"].strip()
    if not lyric:
        return None, [], "no_lyric_block"
    title = page.title["latin"].strip() or page.title["native"]
    found = [page.singer[panel] for panel in ("latin", "native") if panel in page.singer]
    artists = [(found[0][0], name) for _artist_id, name in found]
    return song_row(sys.modules[__name__], url, title, artists, lyric.splitlines())
