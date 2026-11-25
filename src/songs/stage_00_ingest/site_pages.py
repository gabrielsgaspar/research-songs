"""Read the saved pages of a lyric site into one lyric table, with one page reader per site.

The pages are in a packed raw folder (`raw/<source>/<YYYYMMDD>/`, parts
`pages-*.tar.gz`). Each request of the crawl is one receipt
(`.../receipts/<id>.json`: URL, HTTP status, error, headers) and one response body
(`.../responses/<id>.body`: the page as received). The packer writes members in
name order, so the receipts come before the responses.

A site module names `SOURCE`, `BASE`, `COLUMNS` (the lyric columns, with
`provider_song_id`, `song_url` and `retrieved_at_utc`) and two functions:
`song_id(url)` returns the song id of a song page URL or None, and
`parse_song(html, url)` returns the row, the performers as (artist id, name) and '',
or None, [] and the reason the page gives no song.

`parse_folder` reads the parts as a stream and extracts nothing to disk. It writes a
new folder `raw/<source>/<YYYYMMDD>/` with `<source>_lyrics.parquet` (the shape of the
family `site_snapshot` of `songs dumps build`), `<source>_artist_songs.parquet` (each
performer of each song, in page order) and a manifest whose input is the packed
folder. It never writes over a folder.
"""

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
from songs.stage_00_ingest.dumps import check_raw_input

# The sources that have a page reader: a module of the same name in this package.
SITES = ("textpesenok",)
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


def _member_kind(name: str) -> tuple[str, str]:
    """Return ('receipts' or 'responses', the request id) of a member, or ('', '')."""
    parts = name.split("/")
    if len(parts) >= 2 and parts[-2] in ("receipts", "responses"):
        return parts[-2], parts[-1].rsplit(".", 1)[0]
    return "", ""


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
    if receipt.get("status") != 200 or receipt.get("error"):
        return "error_status"
    url = receipt.get("url") or ""
    if site.song_id(url) is None:
        return "not_song_page"
    html = decode(data, (receipt.get("headers") or {}).get("content-type"))
    if html is None:
        return "bad_encoding"
    row, artists, reason = site.parse_song(html, url)
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
