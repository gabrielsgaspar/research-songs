"""Read the saved pages of the lyric site `textpesenok` into one lyric table.

The pages are in a packed raw folder (`raw/textpesenok/<YYYYMMDD>/`, parts
`pages-*.tar.gz`). Each request of the crawl is one receipt
(`.../receipts/<id>.json`: URL, HTTP status, error, headers) and one response body
(`.../responses/<id>.body`: the page as received). The packer writes members in
name order, so the receipts come before the responses.

The parser reads the parts as a stream and extracts nothing to disk. It writes a
new folder `raw/textpesenok/<YYYYMMDD>/` with `textpesenok_lyrics.parquet` (the
shape of the family `site_snapshot` of `songs dumps build`),
`textpesenok_artist_songs.parquet` (each performer of each song, in page order) and
a manifest whose input is the packed folder. It never writes over a folder.
"""

import json
import re
import tarfile
from collections import Counter
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path

import duckdb
import pandas as pd

from songs.common import manifests, paths, run_records
from songs.stage_00_ingest.dump_match import name_key
from songs.stage_00_ingest.dumps import check_raw_input

SOURCE = "textpesenok"
BASE = "https://text-pesenok.ru"
LYRIC_FILE = f"{SOURCE}_lyrics.parquet"
CREDIT_FILE = f"{SOURCE}_artist_songs.parquet"
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
CREDIT_COLUMNS = ("provider_song_id", "credit_position", "provider_artist_id", "artist_name")
_SONG = re.compile(re.escape(BASE) + r"/t(\d+)-[^/?#]*")
_ARTIST = re.compile(r"/artist-(\d+)(?:-[^/?#]*)?")
_CHARSET = re.compile(rb"""charset\s*=\s*["']?([A-Za-z0-9_-]+)""")
_HEADING_END = re.compile(r"\s+[—–-]\s+текст песни\s*$")
# Whole texts that stand for no words, as `name_key` values.
INSTRUMENTAL = frozenset({"instrumental", "инструментал", "инструментальная композиция"})
# Words of a title that mark a text that is not the lyric, as `name_key` values.
TITLE_KINDS = (("перевод", "translation"), ("аккорды", "chords"))
# Reasons a page gives no song, in the order they are tested.
LEFT_OUT = (
    "no_receipt",
    "error_status",
    "not_song_page",
    "bad_encoding",
    "no_lyric_block",
    "no_artist",
    "no_title",
    "empty_text",
    "instrumental",
    "duplicate_url",
)


class ParseError(ValueError):
    """The folder cannot be parsed."""


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


def decode(body: bytes, content_type: str | None) -> str | None:
    """Return the page as text, or None when its bytes do not decode.

    UTF-8 first, because the site serves UTF-8. Then the charset of the header or of
    the page, when it names one.
    """
    try:
        return body.decode("utf-8-sig")
    except UnicodeDecodeError:
        pass
    named = _CHARSET.search((content_type or "").encode("ascii", "replace")) or _CHARSET.search(
        body[:4096]
    )
    if named is None:
        return None
    try:
        return body.decode(named[1].decode("ascii"))
    except LookupError, UnicodeDecodeError:
        return None


def parse_song(html: str, url: str) -> tuple[dict | None, list[tuple[str, str]], str]:
    """Return the row and the performers (id, name) of a song page and '', or None, [] and why."""
    page = _Page()
    page.feed(html)
    page.close()
    if page.lines is None:
        return None, [], "no_lyric_block"
    artists = list(dict.fromkeys(page.artists))
    title = " ".join(page.title.split()) or _HEADING_END.sub("", " ".join(page.heading.split()))
    lines = [" ".join(line.split()) for line in page.lines]
    lyrics = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    if not artists:
        return None, [], "no_artist"
    if not title:
        return None, [], "no_title"
    if not name_key(lyrics):
        return None, [], "empty_text"
    if name_key(lyrics) in INSTRUMENTAL:
        return None, [], "instrumental"
    title_key = name_key(title)
    kind = next((kind for word, kind in TITLE_KINDS if word in title_key.split()), "lyrics")
    row = dict.fromkeys(COLUMNS)
    row.update(
        provider_song_id=_SONG.fullmatch(url)[1],
        song_url=url,
        song_name=title,
        artist_name=artists[0][1],
        artist_url=f"{BASE}/artist-{artists[0][0]}",
        lyrics=lyrics,
        text_kind=kind,
    )
    return row, artists, ""


def _member_kind(name: str) -> tuple[str, str]:
    """Return ('receipts' or 'responses', the request id) of a member, or ('', '')."""
    parts = name.split("/")
    if len(parts) >= 2 and parts[-2] in ("receipts", "responses"):
        return parts[-2], parts[-1].rsplit(".", 1)[0]
    return "", ""


def read_pages(folder: Path) -> tuple[list[dict], list[tuple], Counter]:
    """Read every part of a packed folder. Return the rows, the credits and the counts."""
    parts = sorted(folder.glob("pages-*.tar.gz"))
    if not parts:
        raise ParseError(f"{folder.name} has no pages-*.tar.gz parts")
    receipts: dict[str, dict] = {}
    rows: dict[str, dict] = {}
    credits: list[tuple] = []
    counts: Counter = Counter()
    for part in parts:
        with tarfile.open(part, mode="r|gz", encoding="utf-8") as tar:
            for member in tar:
                kind, key = _member_kind(member.name)
                if not member.isfile() or not kind:
                    continue
                data = tar.extractfile(member).read()
                if kind == "receipts":
                    receipts[key] = json.loads(data.decode("utf-8"))
                    continue
                counts["pages_in"] += 1
                reason = _one_page(receipts.pop(key, None), data, rows, credits)
                counts[reason or "songs_out"] += 1
    counts["receipts_without_page"] = len(receipts)
    return list(rows.values()), credits, counts


def _one_page(
    receipt: dict | None, data: bytes, rows: dict[str, dict], credits: list[tuple]
) -> str:
    """Add the song of one page to `rows` and `credits`. Return '' or the reason it gives none."""
    if receipt is None:
        return "no_receipt"
    if receipt.get("status") != 200 or receipt.get("error"):
        return "error_status"
    url = receipt.get("url") or ""
    if _SONG.fullmatch(url) is None:
        return "not_song_page"
    html = decode(data, (receipt.get("headers") or {}).get("content-type"))
    if html is None:
        return "bad_encoding"
    row, artists, reason = parse_song(html, url)
    if row is None:
        return reason
    if row["provider_song_id"] in rows:
        return "duplicate_url"
    evidence = receipt.get("source_evidence") or {}
    row["retrieved_at_utc"] = evidence.get("requested_at") or receipt.get("started_at")
    rows[row["provider_song_id"]] = row
    credits.extend(
        (row["provider_song_id"], position, artist_id, name)
        for position, (artist_id, name) in enumerate(artists, start=1)
    )
    return ""


def parse_folder(data: Path, raw_input: str, *, day: str | None = None) -> dict:
    """Parse a packed folder and write the new raw folder of the same source. Return the counts.

    `raw_input` is `raw/textpesenok/<YYYYMMDD>/`, relative to the data folder. The new
    folder has the date of today in UTC, or `day`.
    """
    raw_input = check_raw_input(raw_input)
    source_folder = data / raw_input
    if not raw_input.startswith(f"raw/{SOURCE}/") or not source_folder.is_dir():
        raise ParseError(f"no folder raw/{SOURCE}/<YYYYMMDD>/ at {raw_input}")
    folder = paths.raw_dir(data, SOURCE, day or datetime.now(UTC).strftime("%Y%m%d"))
    if folder.exists():
        raise FileExistsError(
            f"{paths.data_relative(data, folder)} exists; raw data is never written over"
        )
    rows, credits, counts = read_pages(source_folder)
    if not rows:
        raise ParseError(f"{raw_input} gave no song")
    folder.mkdir(parents=True)
    with duckdb.connect() as connection:
        connection.execute("SET memory_limit = '4GB'")
        connection.execute("SET threads = 2")
        lyric = pd.DataFrame(rows, columns=list(COLUMNS), dtype="string")
        credit = pd.DataFrame(credits, columns=list(CREDIT_COLUMNS))
        for frame, name in ((lyric, LYRIC_FILE), (credit, CREDIT_FILE)):
            connection.register("frame", frame)
            connection.execute(
                "COPY (SELECT * FROM frame) TO ? (FORMAT parquet, COMPRESSION zstd)",
                [(folder / name).as_posix()],
            )
            connection.unregister("frame")
    report = {"pages_in": counts["pages_in"], "songs_out": counts["songs_out"]}
    report.update({f"left_out_{name}": counts[name] for name in LEFT_OUT if counts[name]})
    if counts["receipts_without_page"]:
        report["receipts_without_page"] = counts["receipts_without_page"]
    report["credits_out"] = len(credits)
    manifests.write_manifest(
        data,
        folder,
        "raw",
        source=SOURCE,
        inputs=[paths.data_relative(data, source_folder)],
        origin={"url": BASE, "retrieved_utc": None, "license": None},
        counts=report,
        notes=f"Parsed from the saved pages of {paths.data_relative(data, source_folder)} "
        f"at {run_records.utc_now()}.",
    )
    return {"path": paths.data_relative(data, folder), **report}
