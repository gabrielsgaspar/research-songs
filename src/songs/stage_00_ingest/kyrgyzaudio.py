"""The page reader of the Kyrgyz song site `kyrgyzaudio`, for `site_pages.parse_folder`.

A song is a post at `/<slug>/`. The breadcrumb names the section (Kyrgyz, Kazakh, Uzbek or
Russian songs, books) and, for most songs, the artist. The heading is "Artist — Title".
"""

import re
import sys
from html.parser import HTMLParser
from urllib.parse import unquote

from songs.stage_00_ingest.site_pages import song_row

SOURCE = "kyrgyzaudio"
BASE = "https://kyrgyz-audio.com"
ARTIST_URL = BASE + "/{}/"
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
_SONG = re.compile(re.escape(BASE) + r"/([^/?#]+)/")
_SECTION = re.compile(re.escape(BASE) + r"/([^/?#]+)/(?:([^/?#]+)/)?")
# Sections of books and other prose read aloud, not songs.
NOT_SONGS = frozenset({"kitepter", "chygarmalar"})
_DASH = re.compile(r"\s+[—–]\s+")
# The words "text" or "text and mp3" and anything after them end a title.
_TEXT_WORD = re.compile(r"\s*\b(?:текст|тексти)\b.*$", re.IGNORECASE)
_LEAD = " .,»:&-—–"
_SKIP = frozenset({"a", "figure", "iframe", "h2", "h3", "h4", "script", "style"})


def _title(heading: str, artist: str) -> str:
    """Return the song title of a heading "Artist — Title" with the artist of the breadcrumb.

    A heading that starts with the artist, with any dash, loses it first. The title is the
    text after the next long dash, or all of the text that is left.
    """
    same = str.maketrans("—–", "--")
    if artist and heading.translate(same).casefold().startswith(artist.translate(same).casefold()):
        heading = heading[len(artist) :]
    title = _DASH.split(heading, maxsplit=1)[-1]
    return _TEXT_WORD.sub("", title.lstrip(_LEAD)).rstrip(" —–-")


class _Page(HTMLParser):
    """Read the breadcrumb links, the heading and the lyric block (`div#textpesni`).

    The block leaves out the text of links, video embeds, their headings and scripts, and ends
    at the rights note.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.crumbs: list[tuple[str, str]] = []
        self.heading = ""
        self.lines: list[str] | None = None
        self._in_crumbs = self._in_heading = self._done = False
        self._depth = self._skip = 0
        self._href: str | None = None
        self._text = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        found = dict(attrs)
        classes = (found.get("class") or "").split()
        if tag in _SKIP and self._in_lyrics():
            self._skip += 1
        if tag == "div" and self._in_lyrics():
            self._depth += 1
        elif tag == "div" and found.get("id") == "textpesni" and self.lines is None:
            self.lines, self._depth = [""], 1
        elif tag == "nav" and "rank-math-breadcrumb" in classes:
            self._in_crumbs = True
        elif tag == "h1" and "entry-title" in classes:
            self._in_heading = True
        elif tag == "a" and self._in_crumbs:
            self._href, self._text = found.get("href") or "", ""
        elif tag == "p" and "ka-rights-note" in classes and self._in_lyrics():
            self._done = True
        elif tag == "p" and self._in_lyrics():
            self.lines += ["", ""]
        elif tag == "br" and self._in_lyrics():
            self.lines.append("")

    def _in_lyrics(self) -> bool:
        return self.lines is not None and not self._done

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP and self._skip and self._in_lyrics():
            self._skip -= 1
        if tag == "div" and self._in_lyrics():
            self._depth -= 1
            self._done = self._depth == 0
        elif tag == "nav":
            self._in_crumbs = False
        elif tag == "h1":
            self._in_heading = False
        elif tag == "a" and self._href is not None:
            self.crumbs.append((unquote(self._href), " ".join(self._text.split())))
            self._href = None

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text += data
        elif self._in_heading:
            self.heading += data
        elif self._in_lyrics() and not self._skip:
            self.lines[-1] += data.replace("\r", "").replace("\n", " ")


def song_id(url: str) -> str | None:
    """Return the slug of a post URL (one path segment), or None."""
    found = _SONG.fullmatch(unquote(url))
    return found[1] if found else None


def parse_song(html: str, url: str) -> tuple[dict | None, list[tuple[str, str | None]], str]:
    """Return the row and the performers (id, name) of a song post and '', or None, [] and why.

    The artist id is the section and slug of the artist page (`muzyka/<slug>`). An artist
    with no page in the breadcrumb has the name of the heading and no id.
    """
    page = _Page()
    page.feed(html)
    page.close()
    if page.lines is None:
        return None, [], "no_lyric_block"
    sections = [_SECTION.fullmatch(href) for href, _ in page.crumbs]
    if not sections or sections[0] is None:
        return None, [], "no_section"
    if sections[0][1] in NOT_SONGS:
        return None, [], "not_song"
    heading = " ".join(page.heading.split())
    artists = [
        (f"{found[1]}/{found[2]}", name)
        for found, (_, name) in zip(sections, page.crumbs, strict=True)
        if found and found[2] and name
    ]
    parts = _DASH.split(heading, maxsplit=1)
    if not artists and len(parts) == 2:
        artists = [(None, parts[0])]
    title = _title(heading, artists[0][1] if artists else "")
    return song_row(sys.modules[__name__], url, title, artists, page.lines)
