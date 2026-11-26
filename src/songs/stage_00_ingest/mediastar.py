"""The page reader of the Kazakh song database `mediastar`, for `site_pages.parse_folder`."""

import re
import sys
from html.parser import HTMLParser

from songs.stage_00_ingest.site_pages import song_row

SOURCE = "mediastar"
BASE = "https://mediastar.kz"
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
_SONG = re.compile(re.escape(BASE) + r"/index\.php\?view=songs&songId=(\d+)")
# A performer is a singer, a group or a star group; each kind has its own ids.
_PERFORMER = re.compile(
    r"index\.php\?view=(authors&authorId|groups&groupId|starGroups&stargroupId)=(\d+)"
)
_KINDS = {
    "authors&authorId": "author",
    "groups&groupId": "group",
    "starGroups&stargroupId": "stargroup",
}
_NUMBER = re.compile(r"^\d+\.\s*")


class _Page(HTMLParser):
    """Read the song name, the performer links (`div.answerText02`) and the lyric block."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title: str | None = None
        self.performers: list[tuple[str, str]] = []
        self.lines: list[str] | None = None
        self._in_title = self._in_performers = self._done = False
        self._depth = 0
        self._href: str | None = None
        self._text = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        found = dict(attrs)
        classes = (found.get("class") or "").split()
        if tag == "div" and self._in_lyrics():
            self._depth += 1
        elif tag == "div" and "blockSvgDataText" in classes and self.lines is None:
            self.lines, self._depth = [""], 1
        elif tag == "div" and "answerText02" in classes:
            self._in_performers = True
        elif tag == "span" and "clientAnswer" in classes and self.title is None:
            self._in_title, self.title = True, ""
        elif tag == "a" and self._in_performers:
            self._href, self._text = found.get("href") or "", ""
        elif tag in ("p", "br") and self._in_lyrics():
            self.lines.append("")

    def _in_lyrics(self) -> bool:
        return self.lines is not None and not self._done

    def handle_endtag(self, tag: str) -> None:
        if tag == "div" and self._in_lyrics():
            self._depth -= 1
            self._done = self._depth == 0
        elif tag == "div":
            self._in_performers = False
        elif tag == "span":
            self._in_title = False
        elif tag == "a" and self._href is not None:
            found = _PERFORMER.search(self._href)
            name = _NUMBER.sub("", " ".join(self._text.split()))
            if found and name:
                self.performers.append((f"{_KINDS[found[1]]}-{found[2]}", name))
            self._href = None

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text += data
        elif self._in_title:
            self.title += data
        elif self._in_lyrics():
            self.lines[-1] += data.replace("\r", "").replace("\n", " ")


def song_id(url: str) -> str | None:
    """Return the song id of a song page URL, or None."""
    found = _SONG.fullmatch(url)
    return found[1] if found else None


def _lines(lines: list[str]) -> list[str]:
    """Drop the empty paragraphs when the page puts one after every line, else keep them."""
    empty = sum(1 for line in lines if not line.strip())
    return [line for line in lines if line.strip()] if 2 * empty >= len(lines) else lines


def artist_url(artist_id: str) -> str:
    """Return the page address of a performer id (`author-1`, `group-1` or `stargroup-1`)."""
    kind, number = artist_id.split("-")
    view = next(view for view, name in _KINDS.items() if name == kind)
    return f"{BASE}/index.php?view={view}={number}"


ARTIST_URL = artist_url


def parse_song(html: str, url: str) -> tuple[dict | None, list[tuple[str, str]], str]:
    """Return the row and the performers (id, name) of a song page and '', or None, [] and why."""
    page = _Page()
    page.feed(html)
    page.close()
    if page.lines is None:
        return None, [], "no_lyric_block"
    title = page.title or ""
    return song_row(sys.modules[__name__], url, title, page.performers, _lines(page.lines))
