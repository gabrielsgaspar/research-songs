"""The page reader of the lyric site `textpesenok`, for `site_pages.parse_folder`."""

import re
import sys
from html.parser import HTMLParser

from songs.stage_00_ingest.site_pages import song_row

SOURCE = "textpesenok"
BASE = "https://text-pesenok.ru"
ARTIST_URL = BASE + "/artist-{}"
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
_SONG = re.compile(re.escape(BASE) + r"/t(\d+)-[^/?#]*")
_ARTIST = re.compile(r"/artist-(\d+)(?:-[^/?#]*)?")
_HEADING_END = re.compile(r"\s+[—–-]\s+текст песни\s*$")
# Whole texts that stand for no words, as `name_key` values.
INSTRUMENTAL = frozenset({"instrumental", "инструментал", "инструментальная композиция"})
# Words of a title that mark a text that is not the lyric, as `name_key` values.
TITLE_KINDS = (("перевод", "translation"), ("аккорды", "chords"))


class _Page(HTMLParser):
    """Read the breadcrumb artists, the breadcrumb title, the heading and the lyric block."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.artists: list[tuple[str, str]] = []
        self.title = ""
        self.heading = ""
        self.lines: list[str] | None = None
        self._zone = ""
        self._depth = 0
        self._href: str | None = None
        self._text = ""
        self._in_title = self._in_heading = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        classes = (dict(attrs).get("class") or "").split()
        if tag == "div":
            if self._zone:
                self._depth += 1
            elif "breadcrumbs" in classes:
                self._zone, self._depth = "crumbs", 1
            elif "main_text-slova" in classes and self.lines is None:
                self._zone, self._depth, self.lines = "lyrics", 1, [""]
        elif self._zone == "crumbs" and tag == "a":
            self._href, self._text = dict(attrs).get("href") or "", ""
        elif self._zone == "crumbs" and tag == "span" and "mitems__count" in classes:
            self._in_title = True
        elif self._zone == "lyrics" and tag in ("p", "br"):
            self.lines.append("")
        elif tag == "h1":
            self._in_heading = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "div" and self._zone:
            self._depth -= 1
            if self._depth == 0:
                self._zone = ""
        elif tag == "a" and self._href is not None:
            found = _ARTIST.fullmatch(self._href.removeprefix(BASE))
            name = " ".join(self._text.split())
            if found and name:
                self.artists.append((found[1], name))
            self._href = None
        elif tag == "span":
            self._in_title = False
        elif tag == "h1":
            self._in_heading = False

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text += data
        if self._in_title:
            self.title += data
        if self._in_heading:
            self.heading += data
        if self._zone == "lyrics":
            self.lines[-1] += data.replace("\r", "").replace("\n", " ")


def song_id(url: str) -> str | None:
    """Return the song id of a song page URL, or None."""
    found = _SONG.fullmatch(url)
    return found[1] if found else None


def parse_song(html: str, url: str) -> tuple[dict | None, list[tuple[str, str]], str]:
    """Return the row and the performers (id, name) of a song page and '', or None, [] and why."""
    page = _Page()
    page.feed(html)
    page.close()
    if page.lines is None:
        return None, [], "no_lyric_block"
    title = page.title.strip() or _HEADING_END.sub("", " ".join(page.heading.split()))
    return song_row(sys.modules[__name__], url, title, page.artists, page.lines)
