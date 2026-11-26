"""The page reader of the Georgian lyric site `geolyrics`, for `site_pages.parse_folder`."""

import re
import sys
from html.parser import HTMLParser

from songs.stage_00_ingest.site_pages import song_row

SOURCE = "geolyrics"
BASE = "https://geolyrics.ru"
ARTIST_URL = BASE + "/simgherebi/singer/{}.html"
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
# No whole text marks an instrumental, and no title word marks another kind of text.
INSTRUMENTAL = frozenset()
TITLE_KINDS = ()
_SONG = re.compile(
    re.escape(BASE) + r"/simgherebi/(?!singer/)([A-Za-z0-9_-]+/[A-Za-z0-9_.-]+)\.html"
)
_ARTIST = re.compile(r"/simgherebi/singer/([A-Za-z0-9_-]+)\.html")


class _Page(HTMLParser):
    """Read the first heading, the performers under it and the Georgian lyric block (`div.geo`).

    The block ends where it closes, or at the tabs or the comments that follow it.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.artists: list[tuple[str, str]] = []
        self.heading = ""
        self.title = ""
        self.lines: list[str] | None = None
        self._in = ""
        self._done = False
        self._depth = 0
        self._href: str | None = None
        self._text = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        classes = (dict(attrs).get("class") or "").split()
        if tag == "div" and self._lyric_zone():
            self._depth += 1
            self._done = "tabs" in classes or "comments" in classes
        elif tag == "div" and "geo" in classes and self.lines is None:
            self.lines, self._depth = [""], 1
        elif tag == "h1" and self.lines is None and not self.heading:
            self._in = tag
        elif tag == "h3" and self.lines is None and not self.artists:
            self._in = tag
        elif tag == "h2" and self._lyric_zone() and not self.title:
            self._in = tag
        elif tag == "a" and self._in == "h3":
            self._href, self._text = dict(attrs).get("href") or "", ""
        elif tag in ("p", "br") and self._lyric_zone():
            self.lines.append("")

    def _lyric_zone(self) -> bool:
        return self.lines is not None and not self._done

    def handle_endtag(self, tag: str) -> None:
        if tag == "div" and self._lyric_zone():
            self._depth -= 1
            self._done = self._depth == 0
        elif tag == "a" and self._href is not None:
            found = _ARTIST.fullmatch(self._href.removeprefix(BASE))
            name = " ".join(self._text.split())
            if found and name:
                self.artists.append((found[1], name))
            self._href = None
        elif tag == self._in:
            self._in = ""

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text += data
        elif self._in == "h1":
            self.heading += data
        elif self._in == "h2":
            self.title += data
        elif self._lyric_zone():
            self.lines[-1] += data.replace("\r", "").replace("\n", " ")


def song_id(url: str) -> str | None:
    """Return the song id (`<artist>/<song>`) of a song page URL, or None."""
    found = _SONG.fullmatch(url)
    return found[1] if found else None


def parse_song(html: str, url: str) -> tuple[dict | None, list[tuple[str, str]], str]:
    """Return the row and the performers (id, name) of a song page and '', or None, [] and why."""
    page = _Page()
    page.feed(html)
    page.close()
    if page.lines is None:
        return None, [], "no_lyric_block"
    title = page.title.strip() or page.heading
    return song_row(sys.modules[__name__], url, title, page.artists, page.lines)
