"""Read the original lyric paragraphs of a Tekst-pesni.online song at its new address."""

import re
import sys
from html import unescape
from urllib.parse import urlsplit

from songs.stage_00_ingest.site_pages import song_row

SOURCE = "tekstpesnionline"
BASE = "https://naizust.com"
SEEDS = ()
ARTIST_URL = None
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
INSTRUMENTAL = frozenset({"инструментал", "instrumental"})
TITLE_KINDS = (("перевод", "translation"), ("аккорды", "chords"))
_PATH = re.compile(r"/([a-z0-9]+(?:-[a-z0-9]+)+)/?")
_HEADINGS = re.compile(r"<h2\b[^>]*>(.*?)</h2>", re.I | re.S)
_PARAGRAPH = re.compile(r"\s*<p\b[^>]*>(.*?)</p>", re.I | re.S)


def song_id(url: str) -> str | None:
    parts = urlsplit(url)
    match = _PATH.fullmatch(parts.path)
    if parts.netloc == "naizust.com" and parts.scheme == "https" and not parts.query and match:
        return match[1]
    return None


def canonicalize(url: str) -> str | None:
    slug = song_id(url)
    return f"{BASE}/{slug}/" if slug else None


def is_artist_page(url: str) -> bool:
    return False


def crawl_urls(html: str, page_url: str) -> list[str]:
    """The collector takes explicit song seeds. Related posts can belong to other artists."""
    return []


def _text(fragment: str) -> str:
    return unescape(re.sub(r"<[^>]+>", "", fragment)).strip()


def parse_song(html: str, url: str) -> tuple[dict | None, list, str]:
    heading = re.search(r"<h1\b[^>]*>(.*?)</h1>", html, re.I | re.S)
    if not heading:
        return None, [], "no_title"
    credit = " ".join(_text(heading[1]).split())
    pair = re.split(r"\s+[—–-]\s+", credit, maxsplit=1)
    if len(pair) != 2:
        return None, [], "no_artist"
    artists = [(None, name.strip()) for name in pair[0].split(", ") if name.strip()]
    for section in _HEADINGS.finditer(html):
        if " ".join(_text(section[1]).split()) != "Текст " + credit:
            continue
        pos = section.end()
        lines = []
        while block := _PARAGRAPH.match(html, pos):
            paragraph = block[1]
            if re.search(r"<(?:div|iframe|script|style|img|a|video)\b", paragraph, re.I):
                break
            lines.extend(_text(line) for line in re.split(r"<br\s*/?>", paragraph, flags=re.I))
            lines.append("")
            pos = block.end()
        return song_row(sys.modules[__name__], url, pair[1], artists, lines)
    return None, [], "no_lyric_block"
