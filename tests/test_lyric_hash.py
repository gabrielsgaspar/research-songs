"""The text hash by which the lyric-hash lists name a text, on invented text."""

import hashlib

import duckdb

from songs.common import lyric_hash


def test_texts_that_differ_only_in_blank_space_have_one_hash():
    base = "First invented line\nSecond invented line"
    expected = hashlib.sha256(base.encode("utf-8")).hexdigest()
    variants = [
        base,
        "First invented line \nSecond invented line",
        "First invented line\r\nSecond invented line\r\n",
        "\n  First  invented\tline\nSecond invented line\n\n",
        "First invented line\rSecond invented line",
    ]
    assert {lyric_hash.normalized_sha256(text) for text in variants} == {expected}
    # Unicode composition: an e with a combining accent is the composed character.
    assert lyric_hash.normalized_sha256("café") == lyric_hash.normalized_sha256("café")
    # A blank line inside the text stays.
    assert lyric_hash.normalized_sha256("a\n\nb") != lyric_hash.normalized_sha256("a\nb")


def test_a_blank_text_has_no_hash():
    assert lyric_hash.normalized_sha256(" \n\t\n") is None
    assert lyric_hash.normalized_sha256(None) is None


def test_fill_keeps_a_stored_hash_and_computes_a_missing_one():
    connection = duckdb.connect()
    songs = connection.sql(
        "SELECT * FROM (VALUES ('kept', 'stored'), ('text', NULL)) AS t(lyrics, lyrics_text_hash)"
    )
    for _ in range(2):  # the function is made once for each connection
        filled = lyric_hash.fill_text_hash(connection, songs)
    assert filled.order("lyrics").fetchall() == [
        ("kept", "stored"),
        ("text", hashlib.sha256(b"text").hexdigest()),
    ]
