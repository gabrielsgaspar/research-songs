"""The page reader of the Kazakh lyric site `matinder`, for `site_pages.parse_folder`."""

import re
from html.parser import HTMLParser

from songs.stage_00_ingest import site_pages
from songs.stage_00_ingest.dump_match import name_key

SOURCE = "matinder"
BASE = "https://matinder.kz"
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
# A song is `/song/<artist>/<slug>`; a translation is `/song/translation/<artist>/<slug>`.
_SONG = re.compile(r"https://(?:www\.)?matinder\.kz/song/((?:translation/)?[^/?#]+/[^/?#]+)")
_ARTIST = re.compile(r"https://(?:www\.)?matinder\.kz/artist/([^/?#]+)")


class _Page(HTMLParser):
    """Read the title, the artist links of the heading and the lines of the lyric block.

    The block leaves out the text of its scripts (advertising).
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.artists: list[tuple[str, str]] = []
        self.lines: list[str] | None = None
        self._in_title = self._done = False
        self._depth = 0
        self._in_script = False
        self._href: str | None = None
        self._text = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        found = dict(attrs)
        classes = (found.get("class") or "").split()
        if tag in ("script", "style"):
            self._in_script = True
        elif tag == "div" and self._in_lyrics():
            self._depth += 1
            self.lines.append("")
        elif tag == "div" and "song--lyrics__content" in classes and self.lines is None:
            self.lines, self._depth = [""], 1
        elif tag == "h1" and "song--info__title" in classes:
            self._in_title = True
        elif tag == "a" and "song--info__artists--link" in classes:
            self._href, self._text = found.get("href") or "", ""
        elif tag == "br" and self._in_lyrics():
            self.lines.append("")

    def _in_lyrics(self) -> bool:
        return self.lines is not None and not self._done

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style"):
            self._in_script = False
        elif tag == "div" and self._in_lyrics():
            self._depth -= 1
            self._done = self._depth == 0
        elif tag == "h1":
            self._in_title = False
        elif tag == "a" and self._href is not None:
            found = _ARTIST.fullmatch(self._href)
            name = " ".join(self._text.split()).rstrip(" ,&")
            if found and name:
                self.artists.append((found[1], name))
            self._href = None

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text += data
        elif self._in_title:
            self.title += data
        elif self._in_lyrics() and not self._in_script:
            self.lines[-1] += data.replace("\r", "").replace("\n", " ")


def song_id(url: str) -> str | None:
    """Return the song id (the path after `/song/`) of a song or translation URL, or None."""
    found = _SONG.fullmatch(url)
    return found[1] if found else None


def parse_song(html: str, url: str) -> tuple[dict | None, list[tuple[str, str]], str]:
    """Return the row and the performers (id, name) of a song page and '', or None, [] and why."""
    page = _Page()
    page.feed(html)
    page.close()
    if page.lines is None:
        return None, [], "no_lyric_block"
    artists = list(dict.fromkeys(page.artists))
    title = " ".join(page.title.split())
    lyrics = site_pages.lyric_text(page.lines)
    if not artists:
        return None, [], "no_artist"
    if not title:
        return None, [], "no_title"
    if not name_key(lyrics):
        return None, [], "empty_text"
    row = dict.fromkeys(COLUMNS)
    row.update(
        provider_song_id=song_id(url),
        song_url=url,
        song_name=title,
        artist_name=artists[0][1],
        artist_url=f"{BASE}/artist/{artists[0][0]}",
        lyrics=lyrics,
        text_kind="translation" if song_id(url).startswith("translation/") else "lyrics",
    )
    return row, artists, ""
