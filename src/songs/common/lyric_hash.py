"""The text hash of a song: the hash by which the lyric-hash lists name a lyric text.

The old pipeline stored `lyrics_text_hash` for each row: the SHA-256 of the lyric
text after a whitespace normalization. The lists `suspect_text_hashes.csv` and
`song_quarantine.csv` in `resources/lyrics/` name texts by that hash. The old
import keeps the stored hash. Every other row gets the hash of `normalized_sha256`,
which repeats the old normalization: Unicode NFC, one kind of line end, one space
for each run of spaces and tabs, no blank space at the ends of a line, and no blank
lines at the start or the end.

The text keys find the same lyrics from two sources, which differ in punctuation,
spacing or case. The kept text is the text in Unicode NFC, in lower case, with
every character removed that is not a letter or a digit of any script. Marks are
removed too, so a vowel sign of Devanagari or Thai does not count. `text_key` is the
SHA-256 of the whole kept text, and `start_key` the SHA-256 of its first
`START_CHARS` characters. A kept text of fewer than `MIN_KEPT_CHARS` characters has
no key: such a text is a placeholder or a fragment, not a lyric (the import leaves
out a text of fewer than 30 characters for the same reason).
"""

import hashlib
import re
import unicodedata

import duckdb

FUNCTION = "songs_normalized_sha256"
MIN_KEPT_CHARS = 30
START_CHARS = 300


def text_keys_sql(text: str = "lyrics") -> str:
    """Return the SQL items `text_key, start_key` of the text column `text`, for DuckDB."""
    kept = rf"regexp_replace(lower(nfc_normalize({text})), '[^\p{{L}}\p{{N}}]', '', 'g')"
    short = f"length({kept}) < {MIN_KEPT_CHARS}"
    return (
        f"CASE WHEN NOT {short} THEN sha256({kept}) END AS text_key, "
        f"CASE WHEN NOT {short} THEN sha256(left({kept}, {START_CHARS})) END AS start_key"
    )


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
