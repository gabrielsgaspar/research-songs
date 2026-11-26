"""Read the saved pages of a lyric site into one lyric table, with one page reader per site.

The pages are in a packed raw folder (`raw/<source>/<YYYYMMDD>/`, parts
`pages-*.tar.gz`). Each request of the crawl is one receipt
(`.../receipts/<id>.json`: URL, HTTP status, error, headers) and one response body
(`.../responses/[<day>/]<id>.body`, or `.body.gz` when the crawl stored it gzipped).
Crawls name the receipt fields in one of two ways (`status`, `headers`, `started_at`
or `http_status`, `response_headers`, `fetched_at_utc`). The packer writes members in
name order, so the receipts come before the responses.

A site module names `SOURCE`, `BASE`, `COLUMNS` (the lyric columns, with
`provider_song_id`, `song_url` and `retrieved_at_utc`), `ARTIST_URL` (the artist page
with `{}` for the artist id, or a function of the artist id), `INSTRUMENTAL` and
`TITLE_KINDS` (see `song_row`) and two functions: `song_id(url)` returns the song id of
a song page URL or None, and
`parse_song(html, url)` returns the row, the performers as (artist id, name) and '',
or None, [] and the reason the page gives no song. `song_row` makes that result from
what the page shows.

`parse_folder` reads the parts as a stream and extracts nothing to disk. It writes a
new folder `raw/<source>/<YYYYMMDD>/` with `<source>_lyrics.parquet` (the shape of the
family `site_snapshot` of `songs dumps build`), `<source>_artist_songs.parquet` (each
performer of each song, in page order) and a manifest whose input is the packed
folder. It never writes over a folder.
"""

import gzip
import importlib
import json
import re
import tarfile
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

import duckdb
import pandas as pd

from songs.common import manifests, paths, run_records
from songs.stage_00_ingest.dump_match import name_key
from songs.stage_00_ingest.dumps import check_raw_input

# The sources that have a page reader: a module of the same name in this package.
SITES = (
    "cuspajz",
    "geolyrics",
    "georgianlyrics",
    "kyrgyzaudio",
    "matinder",
    "mediastar",
    "pesmarica",
    "textpesenok",
)
CREDIT_COLUMNS = ("provider_song_id", "credit_position", "provider_artist_id", "artist_name")
_CHARSET = re.compile(rb"""charset\s*=\s*["']?([A-Za-z0-9_-]+)""")


class ParseError(ValueError):
    """The folder cannot be parsed."""


def site_module(source: str) -> ModuleType:
    """Return the page reader of a source. Raise ParseError when the source has none."""
    if source not in SITES:
        raise ParseError(f"no page parser for {source}; one exists for {', '.join(SITES)}")
    return importlib.import_module(f"songs.stage_00_ingest.{source}")


def decode(body: bytes, content_type: str | None) -> str | None:
    """Return the page as text, or None when its bytes do not decode.

    UTF-8 first. Then the charset of the header or of the page, when it names one.
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


def song_row(
    site: ModuleType,
    url: str,
    title: str,
    artists: list[tuple[str, str]],
    lines: list[str],
    **columns: str | None,
) -> tuple[dict | None, list[tuple[str, str]], str]:
    """Return the row, the performers and '' of a song page, or None, [] and the reason.

    `lines` are the text lines as the page shows them; the text squeezes spaces and keeps
    at most one empty line between stanzas. A text that is a whole `site.INSTRUMENTAL`
    value gives no row. A title word of `site.TITLE_KINDS` sets `text_kind`. `columns`
    fill or replace other lyric columns, such as `release_year_raw` or `text_kind`. An
    artist with no id (None) has no `artist_url`.
    """
    artists = list(dict.fromkeys(artists))
    title = " ".join(title.split())
    text = "\n".join(" ".join(line.split()) for line in lines)
    lyrics = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not artists:
        return None, [], "no_artist"
    if not title:
        return None, [], "no_title"
    if not name_key(lyrics):
        return None, [], "empty_text"
    if name_key(lyrics) in site.INSTRUMENTAL:
        return None, [], "instrumental"
    words = name_key(title).split()
    kind = next((kind for word, kind in site.TITLE_KINDS if word in words), "lyrics")
    artist_id = artists[0][0]
    if artist_id is None:
        artist_url = None
    elif callable(site.ARTIST_URL):
        artist_url = site.ARTIST_URL(artist_id)
    else:
        artist_url = site.ARTIST_URL.format(artist_id)
    row = dict.fromkeys(site.COLUMNS)
    row.update(
        provider_song_id=site.song_id(url),
        song_url=url,
        song_name=title,
        artist_name=artists[0][1],
        artist_url=artist_url,
        lyrics=lyrics,
        text_kind=kind,
    )
    row.update(columns)
    return row, artists, ""


def _member_kind(name: str) -> tuple[str, str]:
    """Return ('receipts' or 'responses', the request id) of a member, or ('', '')."""
    parts = name.split("/")
    for kind in ("receipts", "responses"):
        if kind in parts[-3:-1]:
            return kind, parts[-1].split(".", 1)[0]
    return "", ""


def _field(receipt: dict, *names: str):
    """Return the first field of a receipt that is set, under any of its names."""
    return next((receipt[name] for name in names if receipt.get(name) is not None), None)


def _content_type(receipt: dict) -> str | None:
    headers = _field(receipt, "headers", "response_headers") or {}
    found = {key.lower(): value for key, value in headers.items()}.get("content-type")
    return found or receipt.get("content_type")


def read_pages(folder: Path, site: ModuleType) -> tuple[list[dict], list[tuple], Counter]:
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
                if member.name.endswith(".gz"):
                    data = gzip.decompress(data)
                if kind == "receipts":
                    receipts[key] = json.loads(data.decode("utf-8"))
                    continue
                counts["pages_in"] += 1
                reason = _one_page(site, receipts.pop(key, None), data, rows, credits)
                counts[reason or "songs_out"] += 1
    counts["receipts_without_page"] = len(receipts)
    return list(rows.values()), credits, counts


def _one_page(
    site: ModuleType, receipt: dict | None, data: bytes, rows: dict[str, dict], credits: list
) -> str:
    """Add the song of one page to `rows` and `credits`. Return '' or the reason it gives none."""
    if receipt is None:
        return "no_receipt"
    if _field(receipt, "status", "http_status") != 200 or receipt.get("error"):
        return "error_status"
    url = receipt.get("url") or ""
    if site.song_id(url) is None:
        return "not_song_page"
    html = decode(data, _content_type(receipt))
    if html is None:
        return "bad_encoding"
    row, artists, reason = site.parse_song(html, url)
    if row is None:
        return reason
    if row["provider_song_id"] in rows:
        return "duplicate_url"
    evidence = receipt.get("source_evidence") or {}
    row["retrieved_at_utc"] = evidence.get("requested_at") or _field(
        receipt, "started_at", "fetched_at_utc", "started_at_utc"
    )
    rows[row["provider_song_id"]] = row
    credits.extend(
        (row["provider_song_id"], position, artist_id, name)
        for position, (artist_id, name) in enumerate(artists, start=1)
    )
    return ""


def parse_folder(data: Path, source: str, raw_input: str, *, day: str | None = None) -> dict:
    """Parse a packed folder and write the new raw folder of the same source. Return the counts.

    `raw_input` is `raw/<source>/<YYYYMMDD>/`, relative to the data folder. The new
    folder has the date of today in UTC, or `day`.
    """
    site = site_module(source)
    raw_input = check_raw_input(raw_input)
    source_folder = data / raw_input
    if not raw_input.startswith(f"raw/{source}/") or not source_folder.is_dir():
        raise ParseError(f"no folder raw/{source}/<YYYYMMDD>/ at {raw_input}")
    folder = paths.raw_dir(data, source, day or datetime.now(UTC).strftime("%Y%m%d"))
    if folder.exists():
        raise FileExistsError(
            f"{paths.data_relative(data, folder)} exists; raw data is never written over"
        )
    rows, credits, counts = read_pages(source_folder, site)
    if not rows:
        raise ParseError(f"{raw_input} gave no song")
    folder.mkdir(parents=True)
    with duckdb.connect() as connection:
        connection.execute("SET memory_limit = '4GB'")
        connection.execute("SET threads = 2")
        lyric = pd.DataFrame(rows, columns=list(site.COLUMNS), dtype="string")
        credit = pd.DataFrame(credits, columns=list(CREDIT_COLUMNS))
        for frame, name in ((lyric, "lyrics"), (credit, "artist_songs")):
            connection.register("frame", frame)
            connection.execute(
                "COPY (SELECT * FROM frame) TO ? (FORMAT parquet, COMPRESSION zstd)",
                [(folder / f"{source}_{name}.parquet").as_posix()],
            )
            connection.unregister("frame")
    report = {"pages_in": counts["pages_in"], "songs_out": counts["songs_out"]}
    totals = ("pages_in", "songs_out", "receipts_without_page")
    left_out = sorted(name for name in counts if name not in totals)
    report.update({f"left_out_{name}": counts[name] for name in left_out if counts[name]})
    if counts["receipts_without_page"]:
        report["receipts_without_page"] = counts["receipts_without_page"]
    report["credits_out"] = len(credits)
    manifests.write_manifest(
        data,
        folder,
        "raw",
        source=source,
        inputs=[paths.data_relative(data, source_folder)],
        origin={"url": site.BASE, "retrieved_utc": None, "license": None},
        counts=report,
        notes=f"Parsed from the saved pages of {paths.data_relative(data, source_folder)} "
        f"at {run_records.utc_now()}.",
    )
    return {"path": paths.data_relative(data, folder), **report}
