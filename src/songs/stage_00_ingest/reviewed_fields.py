"""Apply reviewed field changes to a full country table and check the written rows."""

from pathlib import Path

import duckdb

from songs.common import schemas


def write_reviewed_table(
    db: duckdb.DuckDBPyConnection,
    table: schemas.Table,
    parent: Path,
    output: Path,
    changes: dict[str, dict],
    fields: tuple[str, ...],
) -> None:
    """Keep the complete parent table and replace selected fields of unique songs."""
    original = schemas.read_table(table, parent, db)
    original.create_view("review_parent", replace=True)
    names = ", ".join(fields)
    db.execute("DROP TABLE IF EXISTS reviewed_values")
    db.execute(
        f"CREATE TEMP TABLE reviewed_values AS SELECT song_id, {names} FROM review_parent LIMIT 0"
    )
    values = [(song, *(row[f] for f in fields)) for song, row in changes.items()]
    if values:
        db.executemany(
            f"INSERT INTO reviewed_values VALUES ({', '.join('?' for _ in values[0])})", values
        )
    matches = db.sql(
        "SELECT count(p.song_id) FROM reviewed_values r LEFT JOIN review_parent p USING(song_id) "
        "GROUP BY r.song_id HAVING count(p.song_id) <> 1"
    )
    if matches.fetchone():
        raise ValueError("A reviewed song is missing or has multiple parent rows.")
    replacements = ", ".join(
        f"CASE WHEN r.song_id IS NULL THEN p.{f} ELSE r.{f} END AS {f}" for f in fields
    )
    expected = db.sql(
        f"SELECT p.* REPLACE ({replacements}) FROM review_parent p "
        "LEFT JOIN reviewed_values r USING(song_id)"
    )
    destination = schemas.write_table(table, expected, output)
    expected.create_view("review_expected", replace=True)
    db.read_parquet(str(destination)).create_view("review_written", replace=True)
    # Group full-row digests to check untouched fields and repeated rows within bounded memory.
    digests = "SELECT sha256(to_json(t)) h, count(*) n FROM {} t GROUP BY h"
    a, b = (digests.format(name) for name in ("review_expected", "review_written"))
    if db.sql(f"({a} EXCEPT {b}) UNION ALL ({b} EXCEPT {a}) LIMIT 1").fetchone():
        raise ValueError("Written rows differ from the reviewed result.")
