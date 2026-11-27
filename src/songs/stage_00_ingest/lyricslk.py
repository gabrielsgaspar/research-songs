"""The page reader of the Sri Lankan lyric site `lyricslk`, for `site_pages.parse_folder`.

A song page is `/song/<singer slug>/<song slug>`. The attribute `data-song-title-en`
holds the title in Latin letters. The singers are the `/artist/` links that carry
`data-artist-en`; the links of the lyricist and of the composer carry other attributes,
so the reader does not take them. The page prints no release year. The text in Sinhala
letters is `pre[data-lyrics-si]`, and the same text in Latin letters is
`pre[data-lyrics-en]`. The reader keeps the Sinhala text, or the Latin text when the
page has no Sinhala text. A `span` inside the `pre` is a site notice, not a lyric line.
"""

import sys
from html.parser import HTMLParser
from urllib.parse import urlsplit

from songs.stage_00_ingest.site_pages import song_row

SOURCE = "lyricslk"
BASE = "https://lyrics-lk.com"
ARTIST_URL = BASE + "/artist/{}"
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
SEEDS = (BASE + "/sitemap.xml", BASE + "/artists")
SKIP_PREFIXES = ("/api/", "/search")
_TEXTS = (("data-lyrics-si", "si"), ("data-lyrics-en", "si-Latn"))


class _Page(HTMLParser):
    """Read the title, the singers and the two texts of a song page."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.artists: list[tuple[str, str]] = []
        self.texts: dict[str, str] = {}
        self._text = ""
        self._notice = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        found = dict(attrs)
        if not self.title:
            self.title = found.get("data-song-title-en") or ""
        if tag == "a" and found.get("data-artist-en"):
            parts = [part for part in urlsplit(found.get("href") or "").path.split("/") if part]
            name = " ".join(found["data-artist-en"].split())
            if len(parts) == 2 and parts[0] == "artist" and name:
                self.artists.append((parts[1], name))
        if tag == "pre":
            self._text = next((label for name, label in _TEXTS if name in found), "")
        elif tag == "span" and self._text:
            self._notice += 1

    def handle_endtag(self, tag: str) -> None:
        if tag == "pre":
            self._text = ""
            self._notice = 0
        elif tag == "span" and self._notice:
            self._notice -= 1

    def handle_data(self, data: str) -> None:
        if self._text and not self._notice:
            self.texts[self._text] = self.texts.get(self._text, "") + data


def song_id(url: str) -> str | None:
    """Return the song id of a song page URL, or None."""
    parts = [part for part in urlsplit(url).path.split("/") if part]
    if len(parts) == 3 and parts[0] == "song":
        return f"{parts[1]}/{parts[2]}"
    return None


def is_artist_page(url: str) -> bool:
    """Return True for an artist page."""
    parts = [part for part in urlsplit(url).path.split("/") if part]
    return len(parts) == 2 and parts[0] == "artist"


def is_listing(url: str) -> bool:
    """Return True for the sitemap, the artist index or an artist page."""
    return urlsplit(url).path.rstrip("/") in ("/sitemap.xml", "/artists") or is_artist_page(url)


def parse_song(html: str, url: str) -> tuple[dict | None, list[tuple[str, str]], str]:
    """Return the row and the singers (id, name) of a song page and '', or None, [] and why."""
    page = _Page()
    page.feed(html)
    page.close()
    label = next((label for _name, label in _TEXTS if page.texts.get(label, "").strip()), None)
    if label is None:
        return None, [], "no_lyric_block"
    lines = page.texts[label].splitlines()
    return song_row(
        sys.modules[__name__], url, page.title, page.artists, lines, language_label=label
    )
