"""The page reader of the Bengali lyric site `gitimala`, for `site_pages.parse_folder`.

A song page is `/lyrics/<slug>/`. The block `div.lyrics-title` holds the performers
(the `/artist/` links), the title (`h1`) and the album (the `/album/` link). Most
titles give the song two times, in Latin letters and in Bengali letters, with a dash
between them. The reader keeps the Latin part, because the roster and Discogs write
Bengali titles in Latin letters. The lyric is `div.lyric-text`, up to the comments
heading: a `br` ends a line and a `p` ends a stanza. The page prints no year. The
crawl starts at the sitemap index and reads the lyric sitemaps only.
"""

import re
import sys
from html import unescape
from urllib.parse import unquote, urlsplit

from songs.stage_00_ingest.pesmarica import lyric_lines
from songs.stage_00_ingest.site_pages import page_links, plain_text, song_row

SOURCE = "gitimala"
BASE = "https://gitimala.com"
ARTIST_URL = BASE + "/artist/{}/"
COLUMNS = (
    "provider_song_id",
    "song_url",
    "song_name",
    "artist_name",
    "artist_url",
    "album_name",
    "lyrics",
    "text_kind",
    "language_label",
    "release_year_raw",
    "retrieved_at_utc",
)
INSTRUMENTAL = frozenset({"instrumental"})
TITLE_KINDS = (("chords", "chords"), ("chord", "chords"))
SEEDS = (BASE + "/sitemap_index.xml",)
SKIP_PREFIXES = ("/wp-",)
_SONG = re.compile(r"/lyrics/([^/]+)/")
_SITEMAP = re.compile(r"/lyrics-sitemap\d*\.xml")
_HEAD = re.compile(r'class="lyrics-title">(.*?)<article', re.S)
_H1 = re.compile(r"<h1[^>]*>(.*?)</h1>", re.S)
_LYRIC = re.compile(
    r'class="\s*lyric-text[^"]*">(.*?)(?:<!-- Facebook|<h3|<ul|class="\s*lyric-bottom)', re.S
)
_DASH = re.compile(r"\s+[-–—]\s+")
_BENGALI = re.compile(r"[ঀ-৿]")


def song_id(url: str) -> str | None:
    """Return the song id of a song page URL, or None. The id is the slug."""
    found = _SONG.fullmatch(urlsplit(url).path)
    return unquote(found[1]) if found else None


def is_listing(url: str) -> bool:
    """Return True for the sitemap index and for a lyric sitemap."""
    path = urlsplit(url).path
    return path == "/sitemap_index.xml" or bool(_SITEMAP.fullmatch(path))


def is_artist_page(url: str) -> bool:
    """Return True for an artist page."""
    parts = [part for part in urlsplit(url).path.split("/") if part]
    return len(parts) == 2 and parts[0] == "artist"


def latin_title(title: str) -> str:
    """Return the Latin part of a title in two scripts, or the title as it is."""
    parts = [part for part in _DASH.split(title) if part.strip()]
    latin = [part for part in parts if not _BENGALI.search(part)]
    return " - ".join(latin) if latin and len(latin) < len(parts) else title


def _linked(head: str, section: str) -> list[tuple[str, str]]:
    """Return (slug, text) of each link of the title block to a page of `section`."""
    found = []
    for href, text in page_links(head):
        parts = [part for part in urlsplit(href).path.split("/") if part]
        if len(parts) == 2 and parts[0] == section and text:
            found.append((unquote(parts[1]), text))
    return found


def parse_song(html: str, url: str) -> tuple[dict | None, list[tuple[str, str]], str]:
    """Return the row and the performers (id, name) of a song page and '', or None, [] and why."""
    head = _HEAD.search(html)
    lyric = _LYRIC.search(html)
    if head is None or lyric is None:
        return None, [], "no_lyric_block"
    heading = _H1.search(head[1])
    title = latin_title(" ".join(unescape(plain_text(heading[1] if heading else "")).split()))
    artists = _linked(head[1], "artist")
    albums = _linked(head[1], "album")
    text = plain_text(lyric[1].replace("\n", " ").replace("</p>", "</p><br/>"))
    lines = lyric_lines(text, title, *(name for _artist_id, name in artists))
    columns = {"album_name": albums[0][1]} if albums else {}
    return song_row(sys.modules[__name__], url, title, artists, lines, **columns)
