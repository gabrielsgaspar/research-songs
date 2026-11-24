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


def text_keys(*texts: str | None) -> list[tuple]:
    rows = ", ".join("(?)" for _ in texts)
    sql = f"SELECT {lyric_hash.text_keys_sql()} FROM (VALUES {rows}) AS t(lyrics)"
    return duckdb.connect().execute(sql, list(texts)).fetchall()


def test_texts_that_differ_in_case_punctuation_and_spacing_have_one_text_key():
    base = "An invented first line, and a second one!\nThird line: 1 2 3"
    variants = [base, "AN INVENTED first line and a second one\n\n third line 123 ...", base + " "]
    keys = text_keys(*variants)
    assert len(set(keys)) == 1
    kept = "aninventedfirstlineandasecondonethirdline123"
    assert keys[0] == (hashlib.sha256(kept.encode("utf-8")).hexdigest(),) * 2


def test_the_start_key_reads_only_the_first_kept_characters():
    start = "x" * lyric_hash.START_CHARS
    (one, two) = text_keys(start + " invented end", start + " other end")
    assert one[0] != two[0] and one[1] == two[1]


def test_letters_and_digits_of_every_script_stay():
    texts = [
        "Ελληνικό κείμενο, πολύ μακρύ, για δοκιμή ναι",
        "Русский текст для проверки ключа, да",
        "日本語の発明された歌詞の一行です。日本語の発明された歌詞の二行目です",
        "نص عربي مخترع للاختبار فقط، سطر ثان ١٢٣",
    ]
    keys = text_keys(*texts, *(text.upper() + "?!" for text in texts))
    assert keys[: len(texts)] == keys[len(texts) :]
    assert len({key[0] for key in keys}) == len(texts) and all(key[0] for key in keys)
    # Composed and decomposed accents give one key.
    assert text_keys("café " * 10) == text_keys("café " * 10)


def test_a_short_empty_or_null_text_has_no_key():
    short = "a" * (lyric_hash.MIN_KEPT_CHARS - 1) + "!!! ... ,,,"
    assert text_keys(short, "", None, " ,.;") == [(None, None)] * 4
    assert text_keys("a" * lyric_hash.MIN_KEPT_CHARS)[0][0] is not None
