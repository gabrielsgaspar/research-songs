"""The page reader of the Arabic lyric site `aama`, for `site_pages.parse_folder`.

A song page is `/lyrics/<slug>`. An artist page (`/artist/<slug>`) links each song as
`/songs/<slug>.html`, and the site redirects that address to `/lyrics/<slug>`. The
reader asks for the `/lyrics/` address, so each song costs one request. The index is
`/artists/<letter>`.

The title and the singer come from the `MusicComposition` schema of the page: `name`
and `recordedAs.byArtist`. The lyricist and the composer of the schema are not
performers. The text is `div.lyrics-text`, one line per `br`.

The reader does not keep two values that the page prints. `datePublished` (the
"release year" of the page) is one year for each singer, the same on all the songs of
the singer and most often the start of the career, so it is not a release year. The
country of origin of the singer has no lyric column.
"""

import html as html_text
import json
import re
import sys
from urllib.parse import unquote

from songs.stage_00_ingest.site_pages import site_path, song_row

SOURCE = "aama"
BASE = "https://www.aama.sa"
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
INSTRUMENTAL = frozenset()
TITLE_KINDS = ()
SEEDS = (BASE + "/", BASE + "/artists")
_SONG = re.compile(r"/lyrics/([^/]+)")
_SONG_LINK = re.compile(r"/songs/([^/]+)\.html")
_ARTIST = re.compile(r"/artist/([^/]+?)(?:\.html)?")
_INDEX = re.compile(r"/artists(?:/[^/]+)?")
_SCHEMA = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)
_TEXT = re.compile(r'<div class="lyrics-text"[^>]*>(.*?)</div>', re.S)
_BREAK = re.compile(r"<br\s*/?>")
_TAG = re.compile(r"<[^>]+>")


def canonicalize(url: str) -> str | None:
    """Return the address the crawl asks for, or None for a page it does not want."""
    path = site_path(BASE, url)
    if path is None:
        return None
    path = unquote(path)
    if path == "/":
        return BASE + "/"
    song = _SONG.fullmatch(path) or _SONG_LINK.fullmatch(path)
    if song:
        return f"{BASE}/lyrics/{song[1]}"
    artist = _ARTIST.fullmatch(path)
    if artist:
        return ARTIST_URL.format(artist[1])
    return BASE + path if _INDEX.fullmatch(path) else None


def song_id(url: str) -> str | None:
    """Return the song id (the slug) of a song page URL, or None."""
    found = _SONG.fullmatch(unquote(site_path(BASE, url) or ""))
    return found[1] if found else None


def is_artist_page(url: str) -> bool:
    """Return True for an artist page."""
    return _ARTIST.fullmatch(unquote(site_path(BASE, url) or "")) is not None


def is_listing(url: str) -> bool:
    """Return True for the home page, a letter index or an artist page."""
    return canonicalize(url) is not None and song_id(url) is None


def parse_song(html: str, url: str) -> tuple[dict | None, list[tuple[str, str]], str]:
    """Return the row and the performers (id, name) of a song page and '', or None, [] and why."""
    song = None
    for found in _SCHEMA.findall(html):
        try:
            schema = json.loads(found)
        except json.JSONDecodeError:
            continue
        if isinstance(schema, dict) and schema.get("@type") == "MusicComposition":
            song = schema
    if song is None:
        return None, [], "no_song_schema"
    text = _TEXT.search(html)
    if text is None:
        return None, [], "no_lyric_block"
    performer = (song.get("recordedAs") or {}).get("byArtist") or {}
    artist = _ARTIST.fullmatch(unquote(site_path(BASE, performer.get("url") or "") or ""))
    name = " ".join(str(performer.get("name") or "").split())
    artists = [(artist[1], name)] if artist and name else []
    lines = [html_text.unescape(_TAG.sub("", line)) for line in _BREAK.split(text[1])]
    return song_row(
        sys.modules[__name__],
        url,
        str(song.get("name") or ""),
        artists,
        lines,
        language_label=song.get("inLanguage") or None,
    )
