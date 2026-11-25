"""The page reader of the lyric site `cuspajz`, for `site_pages.parse_folder`.

A song page is `/tekstovi-pjesama/pjesma/<artist>/<song>.html`. The block
`div#song` holds the heading (`h2`: the artist link and the title in a `span`) and the
text (`p.text`, lines split by `br`). A traditional song has no artist link and no
`span`. The page states no year, album or language.
"""

import re
import sys
from html.parser import HTMLParser

from songs.stage_00_ingest.site_pages import song_row

SOURCE = "cuspajz"
BASE = "https://cuspajz.com"
ARTIST_URL = BASE + "/tekstovi-pjesama/izvodjac/{}.html"
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
_SONG = re.compile(re.escape(BASE) + r"/tekstovi-pjesama/pjesma/((?:[^/?#]+/)?[^/?#]+)\.html")
_ARTIST = re.compile(r"/tekstovi-pjesama/izvodjac/([^/?#]+)\.html")
# Whole texts that stand for no words, as `name_key` values.
INSTRUMENTAL = frozenset({"instrumental", "instrumentalna", "instrumentalno"})
# Words of a title that mark a text that is not the lyric, as `name_key` values.
TITLE_KINDS = (
    ("prijevod", "translation"),
    ("prevod", "translation"),
    ("translation", "translation"),
)


class _Page(HTMLParser):
    """Read the artist link, the title and the text lines of `div#song`."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.artists: list[tuple[str, str]] = []
        self.title = ""
        self.heading = ""
        self.lines: list[str] | None = None
        self._depth = 0
        self._href: str | None = None
        self._text = ""
        self._in = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        found = dict(attrs)
        if tag == "div" and (self._depth or found.get("id") == "song"):
            self._depth += 1
        elif not self._depth:
            return
        elif tag == "h2" and not self._in:
            self._in = "heading"
        elif self._in == "heading" and tag == "a":
            self._href, self._text = found.get("href") or "", ""
        elif self._in == "heading" and tag == "span":
            self._in = "title"
        elif tag == "p" and "text" in (found.get("class") or "").split() and self.lines is None:
            self._in, self.lines = "text", [""]
        elif self._in == "text" and tag == "br":
            self.lines.append("")

    def handle_endtag(self, tag: str) -> None:
        if not self._depth:
            return
        if tag == "div":
            self._depth -= 1
        elif tag == "a" and self._href is not None:
            found = _ARTIST.fullmatch(self._href.removeprefix(BASE))
            name = " ".join(self._text.split())
            if found and name:
                self.artists.append((found[1], name))
            self._href = None
        elif tag == "span" and self._in == "title":
            self._in = "heading"
        elif (tag == "h2" and self._in == "heading") or (tag == "p" and self._in == "text"):
            self._in = "done"

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text += data
        elif self._in == "title":
            self.title += data
        elif self._in == "heading":
            self.heading += data
        elif self._in == "text":
            self.lines[-1] += data.replace("\r", "").replace("\n", " ")


def song_id(url: str) -> str | None:
    """Return the song id of a song page URL (the path after `pjesma/`), or None."""
    found = _SONG.fullmatch(url)
    return found[1] if found else None


def parse_song(html: str, url: str) -> tuple[dict | None, list[tuple[str, str]], str]:
    """Return the row and the performers (id, name) of a song page and '', or None, [] and why."""
    page = _Page()
    page.feed(html)
    page.close()
    if page.lines is None:
        return None, [], "no_lyric_block"
    return song_row(
        sys.modules[__name__], url, page.title or page.heading, page.artists, page.lines
    )
