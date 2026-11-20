"""The text hash of a song: the hash by which the lyric-hash lists name a lyric text.

The old pipeline stored `lyrics_text_hash` for each row: the SHA-256 of the lyric
text after a whitespace normalization. The lists `suspect_text_hashes.csv` and
`song_quarantine.csv` in `resources/lyrics/` name texts by that hash. The old
import keeps the stored hash. Every other row gets the hash of `normalized_sha256`,
which repeats the old normalization: Unicode NFC, one kind of line end, one space
for each run of spaces and tabs, no blank space at the ends of a line, and no blank
lines at the start or the end.
"""

import hashlib
import re
import unicodedata

import duckdb

FUNCTION = "songs_normalized_sha256"


def normalized_sha256(text: str | None) -> str | None:
    """Return the SHA-256 of the normalized text, hex. Return None when the text is blank."""
    text = unicodedata.normalize("NFC", text or "").replace("\r\n", "\n").replace("\r", "\n")
    normal = "\n".join(re.sub("[ \t]+", " ", line).strip() for line in text.split("\n"))
    normal = normal.strip("\n")
    return hashlib.sha256(normal.encode("utf-8")).hexdigest() if normal else None


def fill_text_hash(
    connection: duckdb.DuckDBPyConnection, songs: duckdb.DuckDBPyRelation
) -> duckdb.DuckDBPyRelation:
    """Return the songs with `lyrics_text_hash` filled from `lyrics` where it is empty."""
    known = connection.sql(
        f"SELECT count(*) FROM duckdb_functions() WHERE function_name = '{FUNCTION}'"
    ).fetchall()[0][0]
    if not known:
        connection.create_function(FUNCTION, normalized_sha256, ["VARCHAR"], "VARCHAR")
    return songs.project(
        f"* REPLACE (coalesce(lyrics_text_hash, {FUNCTION}(lyrics)) AS lyrics_text_hash)"
    )
