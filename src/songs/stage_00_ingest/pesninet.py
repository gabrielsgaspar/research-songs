"""Read original song text and performer credits from Pesni.net song pages."""

import re
import sys
from html.parser import HTMLParser

from songs.stage_00_ingest.site_pages import site_path, song_row

SOURCE = "pesninet"
BASE = "https://www.pesni.net"
ARTIST_URL = BASE + "/text/{}"
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
SEEDS = ()
INSTRUMENTAL = frozenset({"instrumental", "инструментал"})
TITLE_KINDS = (("перевод", "translation"), ("аккорды", "chords"))
_SONG = re.compile(r"/text/([\w-]+/[\w-]+)")


def song_id(url: str) -> str | None:
    """Return the artist and song slugs from the site's song URL."""
    found = _SONG.fullmatch(site_path(BASE, url) or "")
    return found[1] if found else None


def is_artist_page(url: str) -> bool:
    """This source collects only named song pages."""
    return False


class _Page(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.artist = ""
        self.title = ""
        self.url = ""
        self.parts: list[str] = []
        self.depth = 0
        self.found = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        fields = dict(attrs)
        classes = (fields.get("class") or "").split()
        if tag == "div" and "song-page" in classes:
            self.artist = fields.get("data-quote-artist-value") or ""
            self.title = fields.get("data-quote-title-value") or ""
            self.url = fields.get("data-quote-url-value") or ""
        if tag == "div" and not self.found and "song-block-text" in classes:
            self.found = True
            self.depth = 1
        elif self.depth and tag == "div":
            self.depth += 1
        elif self.depth and tag in {"br", "p"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if self.depth and tag == "div":
            self.depth -= 1

    def handle_data(self, data: str) -> None:
        if self.depth:
            self.parts.append(data)


def parse_song(html: str, url: str) -> tuple[dict | None, list[tuple[str, str]], str]:
    """Read the original block and its named artist from a song page."""
    key = song_id(url)
    page = _Page()
    page.feed(html)
    page.close()
    if not key or (page.url and key != song_id(page.url)):
        return None, [], "not_song_page"
    if not page.found:
        return None, [], "no_lyric_block"
    artists = [(key.split("/", 1)[0], page.artist)] if page.artist.strip() else []
    return song_row(
        sys.modules[__name__], url, page.title, artists, "".join(page.parts).splitlines()
    )
