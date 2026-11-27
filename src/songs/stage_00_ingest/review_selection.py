"""Append a checked selection from a frozen review workbook to a country snapshot."""

from pathlib import Path

import duckdb
import pandas as pd

from songs.common import lyric_hash, manifests, paths, run_records, schemas
from songs.stage_00_ingest import review_workbooks as review


def remaining(rows: pd.DataFrame, parent: Path) -> pd.DataFrame:
    """Recognize a replay only when the stored artist, source and text agree."""
    if rows["song_id"].duplicated().any() or rows["song_url"].duplicated().any():
        raise ValueError("the selection repeats a song ID or source URL")
    with duckdb.connect() as db:
        db.read_parquet(str(parent / "songs.parquet")).create_view("stored")
        db.register("chosen", rows)
        collisions = db.sql(
            """
            SELECT c.song_id FROM chosen c JOIN stored s USING (song_id)
            WHERE c.lyrics_sha256 IS DISTINCT FROM s.lyrics_sha256
               OR c.artist_id IS DISTINCT FROM s.artist_id
               OR c.song_url IS DISTINCT FROM s.song_url OR s.route IS DISTINCT FROM 'manual_review'
            """
        ).fetchall()
        if collisions:
            raise ValueError("stored song IDs conflict with the selection")
        ids = {
            r[0]
            for r in db.sql(
                "SELECT song_id FROM chosen ANTI JOIN stored USING (song_id)"
            ).fetchall()
        }
    return rows[rows.song_id.isin(ids)].copy()


def append(
    data: Path,
    code: str,
    book: Path,
    parent: Path,
    rows: pd.DataFrame,
    rejected: dict[str, int],
    links: pd.DataFrame | None = None,
) -> tuple[Path, int]:
    """Write a country version after the caller has checked identities and duplicates."""
    if paths.latest_country_songs_dir(data, code) != parent:
        raise ValueError("country snapshot changed before import")
    selected = remaining(rows, parent)
    if selected.empty:
        return parent, 0
    if len(selected) != len(rows):
        raise ValueError("partially applied selection requires a new duplicate check")
    if (
        not selected.country_iso3.eq(code).all()
        or not selected.route.eq(review.ROUTE).all()
        or not selected.discogs_artist_id.str.fullmatch(r"[1-9][0-9]*").fillna(False).all()
        or selected.lyrics.fillna("").str.strip().eq("").any()
    ):
        raise ValueError("a selected row lacks a checked country, route, artist or lyric")
    selected["lyrics_text_hash"] = selected.lyrics.map(lyric_hash.normalized_sha256)
    bulk = paths.data_relative(data, book)
    if book.parent.parent != data / "raw" / "manual_review" / code:
        raise ValueError("workbook must be in the raw manual review folder of the country")
    if not (book.parent / paths.MANIFEST_NAME).is_file():
        manifests.write_manifest(data, book.parent, "raw_manual_review", country_iso3=code)
    with run_records.record_run(code, review.ROUTE, review.SOURCE, bulk_file=bulk) as record:
        folder = paths.country_songs_dir(data, code, record.run_id)
        folder.mkdir(parents=True, exist_ok=False)
        counts = review.write_country_songs(
            selected,
            parent,
            folder,
            record.run_id,
            record.started_utc,
            links,
            preserve_parent_hashes=True,
        )
        if counts["songs_replaced"] or counts["songs_added"] != len(selected):
            raise ValueError("country write did not append exactly the selected songs")
        if not remaining(selected, folder).empty:
            raise ValueError("read-back failed to recognize all selected songs")
        with duckdb.connect() as db:
            for table in schemas.GROUPS["country_tables"]:
                schemas.read_table(table, folder, db)
            old = schemas.read_table(schemas.COUNTRY_SONGS, parent, db, fill_absent=True)
            old.create_view("old")
            db.read_parquet(str(folder / "songs.parquet")).create_view("current_songs")
            columns = ", ".join(f'"{name}"' for name in old.columns)
            if db.sql(
                f"SELECT {columns} FROM old EXCEPT SELECT {columns} FROM current_songs LIMIT 1"
            ).fetchall():
                raise ValueError("a parent song changed")
        if paths.latest_country_songs_dir(data, code) != parent:
            raise ValueError("country snapshot changed during import")
        manifests.write_manifest(
            data,
            folder,
            "country_songs",
            country_iso3=code,
            run_id=record.run_id,
            inputs=[paths.data_relative(data, parent), paths.data_relative(data, book.parent)],
            counts=counts,
            notes="Reviewer-selected additions with verified Discogs artists.",
        )
        record.songs_rejected = rejected
        record.rows_added = record.songs_accepted = len(selected)
        record.songs_attempted = len(selected) + sum(rejected.values())
        record.artists_attempted = int(selected.artist_id.nunique())
        record.requests_sent = 0
    return folder, len(selected)
