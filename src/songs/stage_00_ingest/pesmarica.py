"""The page reader of the chord site `pesmarica`, for `site_pages.parse_folder`.

A song page is `/akordi/<song id>/<slug>`. Its JSON-LD `MusicComposition` names the
title and the performer (`byArtist`, with the artist page `/akordi/gitara/<id>/...`).
The text is a chord sheet in `pre#song-text`. The reader keeps the lyric lines and
drops the chord lines, the tab lines and the section labels, so `text_kind` is
`lyrics`. The page states `inLanguage` "sr" for every song, also for songs in other
languages, so the reader does not use it. `datePublished` is the date of the post,
not of the song.
"""

import json
import re
import sys
from html import unescape

from songs.stage_00_ingest.dump_match import name_key
from songs.stage_00_ingest.site_pages import song_row

SOURCE = "pesmarica"
BASE = "https://www.pesmarica.rs"
ARTIST_URL = BASE + "/akordi/gitara/{}/"
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
_SONG = re.compile(re.escape(BASE) + r"/akordi/(\d+)/[^?#]+")
_ARTIST = re.compile(re.escape(BASE) + r"/akordi/gitara/(\d+)(?:/[^?#]*)?")
_SCHEMA = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)
_TEXT = re.compile(r'<pre id="song-text"[^>]*>(.*?)</pre>', re.S)
_WITHHELD = "autorskim pravima"
# A chord in letter names (`F#m7`, `Bb/D`), German names (`Fis`, `Cism`, `Es`) or a
# lowercase name (`dm`, `e`).
_CHORD = re.compile(
    r"[(\[{]?(?:[A-H](?:[#b♭♯]|is|es|s)?(?:m|maj|min|mol|dim|aug|sus|add|M|\+)?|[a-h]#?m?)\d*"
    r"(?:(?:sus|add|maj|[#b+-])\d+)*(?:/[A-H][#b♭♯]?)?[)\]}]?[*!]?"
)
_MARK = re.compile(
    r"[(\[{]?(?:\d*x\d*|mol|dur|moll|rif|fill|solo|pauza|\d+)[)\]}]?|[-–.:%*()=>~!{}]+",
    re.IGNORECASE,
)
_SECTION = (
    r"(?:(?:pred)?ref(?:ren|rain)?|chorus|uvod|intro|outro|str(?:ofa)?|verse|solo|bridge|kraj|end"
    r"|instrumental|interlude|pre-?chorus|me[đd]j?u ?igra|riff?|coda|prelaz|prijelaz|for[sš]pil"
    r"|veza|tema|most|рефрен|реф|увод|строфа)"
)
# A credit or note line: a credit word and a colon, or a link.
_CREDIT = re.compile(
    r"\s*(?:(?:transkripcija|album|tekst|muzika|aran[zž]man|skidao|akordi|chords|autor"
    r"|napomena|kontakt|ritam|klju[cč]|modulacija|by|tabs?|obrada|instagram|e-?mail)\s*:"
    r"|capo\b|.*(?:https?://|www\.))",
    re.IGNORECASE,
)
# A section label: the word with a number, then a bracket, a colon, a dot or the line end.
_LABEL = re.compile(
    rf"^\s*[\[(]?\s*{_SECTION}\s*\d*\s*(?:[\])]\s*[.:]?|[.:]|(?=\s*$))\s*", re.IGNORECASE
)
_LABEL_WORD = re.compile(rf"{_SECTION}\d*", re.IGNORECASE)
_LETTER = re.compile(r"[^\W\d_]")
_TAB = re.compile(r"\s*[A-Ha-h]?\s*\|?[-\d|hpbrx/\\~^ ]+")
# Whole texts that stand for no words, as `name_key` values.
INSTRUMENTAL = frozenset({"instrumental", "instrumentalna", "instrumentalno"})
# Words of a title that mark a text that is not the lyric, as `name_key` values.
TITLE_KINDS = (("prevod", "translation"), ("prijevod", "translation"))


def is_chord_line(line: str) -> bool:
    """Return True for a line with no lyric: chords and marks, a tab, a section label alone.

    A line that starts with a section label may also hold a few tokens that are no chord.
    """
    if not line.strip():
        return False
    if (_TAB.fullmatch(line) and line.count("-") >= 4) or not _LETTER.search(line):
        return True
    if _CREDIT.match(line):
        return True
    rest = _LABEL.sub("", line)
    tokens = [token for token in re.split(r"[\s|/,\-–]+", rest) if token]
    labelled = rest != line
    if tokens and _LABEL_WORD.fullmatch(tokens[0]):
        tokens, labelled = tokens[1:], True
    if not tokens:
        return labelled
    chords = sum(bool(_CHORD.fullmatch(token)) for token in tokens)
    other = sum(not _CHORD.fullmatch(token) and not _MARK.fullmatch(token) for token in tokens)
    return chords >= (2 if labelled else 4) * other and (labelled or chords > 0)


def lyric_lines(sheet: str, *heading: str) -> list[str]:
    """Return the lyric lines of a chord sheet.

    The lines lose chord lines, section labels and syllable marks (`Cu___jem`). Lines
    at the start that only repeat the `heading` (the title or the artist) go too.
    """
    lines = [
        re.sub(r"_+", "", _LABEL.sub("", line))
        for line in sheet.replace("\r", "").split("\n")
        if not is_chord_line(line)
    ]
    keys = [name_key(name) for name in heading if name_key(name)]
    while lines and _is_heading(name_key(lines[0]), keys):
        lines.pop(0)
    return lines


def _is_heading(line: str, keys: list[str]) -> bool:
    """Return True when a line key is empty, is one of `keys` or holds all of them."""
    return not line or line in keys or bool(keys and all(key in line for key in keys))


def song_id(url: str) -> str | None:
    """Return the song id of a song page URL, or None."""
    found = _SONG.fullmatch(url)
    return found[1] if found else None


def parse_song(html: str, url: str) -> tuple[dict | None, list[tuple[str, str]], str]:
    """Return the row and the performers (id, name) of a song page and '', or None, [] and why."""
    schemas = [json.loads(found) for found in _SCHEMA.findall(html)]
    song = next(
        (s for s in schemas if isinstance(s, dict) and s.get("@type") == "MusicComposition"), None
    )
    if song is None:
        return None, [], "no_song_schema"
    text = _TEXT.search(html)
    if text is None:
        return None, [], "text_withheld" if _WITHHELD in html else "no_lyric_block"
    performer = song.get("byArtist") or {}
    artist = _ARTIST.fullmatch(performer.get("url") or "")
    name = " ".join(str(performer.get("name") or "").split())
    artists = [(artist[1], name)] if artist and name else []
    title = str(song.get("name") or "")
    # The sheets are escaped twice (`&amp;#039;`).
    lines = lyric_lines(unescape(unescape(text[1])), title, name)
    return song_row(sys.modules[__name__], url, title, artists, lines)
