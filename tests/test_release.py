"""The rule for eligible songs and the analysis release, on small invented tables."""

from datetime import date
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from songs.common import campaigns, manifests, paths, run_records, schemas
from songs.stage_30_topics.topic_ids import TOPIC_IDS
from songs.stage_50_analysis import eligible_songs, release
from songs.stage_50_analysis.countries_panel import COUNTRY_COLUMNS

LYRIC = "invented line for a test"
SONGS_RUN = "20260101T000000Z"
SCORES_RUN = "20260102T000000Z"
FIRST, LAST = TOPIC_IDS[0], TOPIC_IDS[-1]


def song(song_id: str, **over) -> dict:
    """One invented song row that is eligible unless `over` changes it."""
    row = {
        "country_iso3": "TGO",
        "song_id": song_id,
        "artist_id": "a1",
        "artist_name": "Invented Artist",
        "source": "invented",
        "lyrics": LYRIC,
        "lyrics_sha256": "0" * 64,
        "lyrics_text_hash": "0" * 64,
        "year": 1990,
        "route": "old_layout",
        "run_id": SONGS_RUN,
    }
    return row | over


def frame(table: schemas.Table, rows: list[dict]) -> duckdb.DuckDBPyRelation:
    """Return rows as a relation with every column of a table; absent cells are null."""
    names = [column.name for column in table.all_columns]
    return schemas.cast_to_schema(table, pd.DataFrame(rows).reindex(columns=names))


def exceptions_file(tmp_path: Path, rows: str = "") -> Path:
    path = tmp_path / "eligibility_exceptions.csv"
    path.write_text("country_iso3,reason,decided\n" + rows, encoding="utf-8")
    return path


SUSPECT, OTHER_SITE, CHANGED = "a" * 64, "b" * 64, "c" * 64


def list_files(tmp_path: Path, suspect: str = "", quarantine: str = "") -> tuple[Path, Path]:
    """Write a list of suspect texts and a list of songs in quarantine; return both paths."""
    files = (tmp_path / "suspect_text_hashes.csv", tmp_path / "song_quarantine.csv")
    for path, columns, rows in zip(
        files,
        (eligible_songs.SUSPECT_COLUMNS, eligible_songs.QUARANTINE_COLUMNS),
        (suspect, quarantine),
        strict=True,
    ):
        path.write_text(",".join(columns) + "\n" + rows, encoding="utf-8")
    return files


ZEROS = "0" * 64
SUSPECT_ROWS = f"*,{SUSPECT},check_a\nother_site,{OTHER_SITE},check_b\n"
QUARANTINE_ROWS = (
    f"quarantined,a1,invented,{ZEROS},check_c\nchanged,a1,invented,{CHANGED},check_c\n"
    f"other_artist,a9,invented,{ZEROS},check_c\n"
)
OLD_COLUMNS = "song_id,country,artist_id,provider,lyrics_text_hash,decision,reason,"
OLD_COLUMNS += "source_check_id,reviewed_by,reviewed_at\n"


def invented_lists(tmp_path: Path) -> tuple[Path, Path]:
    return list_files(tmp_path, SUSPECT_ROWS, QUARANTINE_ROWS)


def artist_files(tmp_path: Path, excluded: str = "", countries: str = "") -> tuple[Path, Path]:
    """Write a list of excluded artists and a list of artist countries; return both paths."""
    files = (tmp_path / "excluded_artists.csv", tmp_path / "artist_countries.csv")
    for path, columns, rows in zip(
        files,
        (eligible_songs.EXCLUDED_ARTIST_COLUMNS, eligible_songs.ARTIST_COUNTRY_COLUMNS),
        (excluded, countries),
        strict=True,
    ):
        path.write_text(",".join(columns) + "\n" + rows, encoding="utf-8")
    return files


def all_lists(tmp_path: Path) -> dict[str, duckdb.DuckDBPyRelation]:
    """The invented lists of the rule, on the default connection of the test songs."""
    connection = duckdb.default_connection()
    hashes = eligible_songs.load_hash_lists(connection, *invented_lists(tmp_path))
    artists = artist_files(tmp_path, "a_out,spoken_word\n", "a_moved,GHA\n")
    lists = hashes | eligible_songs.load_artist_lists(connection, *artists)
    lists |= eligible_songs.load_held_countries(connection, held_countries(tmp_path))
    return lists | eligible_songs.load_text_copies(connection, tmp_path)


def held_countries(tmp_path: Path) -> Path:
    """Write campaign records in which NER stopped after it added songs; return the folder."""
    countries = tmp_path / "countries"
    campaigns.open_campaign("NER", "An invented goal", songs_before=10, countries=countries)
    campaigns.close_campaign(
        "NER", "stopped", "Check the roster.", reason="roster", songs_after=12, countries=countries
    )
    return countries


def old_quarantine(tmp_path: Path, rows: str) -> Path:
    """Write a list of songs in quarantine in the old format, with invented rows."""
    path = tmp_path / "old_song_quarantine.csv"
    path.write_text(OLD_COLUMNS + rows, encoding="utf-8")
    return path


def test_the_import_keeps_the_quarantine_rows_and_the_columns_of_the_rule(tmp_path):
    data = tmp_path / "data"
    old = old_quarantine(
        tmp_path,
        f"s2,TGO,a1,Site, {ZEROS.upper()} ,quarantine,a free text,check_a,someone,2026-01-01\n"
        f"s1,TGO,a1,site,{ZEROS},Quarantine,a free text,,someone,2026-01-01\n"
        f"s1,TGO,a1,site,{ZEROS},quarantine,again,check_b,someone,2026-01-01\n"
        f"s3,TGO,a1,site,{ZEROS},accepted,a free text,check_a,someone,2026-01-01\n"
        f"s4,TGO,,site,{ZEROS},quarantine,a free text,check_a,someone,2026-01-01\n",
    )
    result = eligible_songs.import_old_song_quarantine(old, data, date(2026, 11, 20))
    assert result["folder"] == paths.clean_song_quarantine_dir(data, "20261120")
    assert result["counts"] == {
        "rows_read": 5,
        "left_out_not_quarantine": 1,
        "left_out_empty_key": 1,
        "left_out_repeated_key": 1,
        "rows_written": 2,
    }
    written = (result["folder"] / manifests.SONG_QUARANTINE_FILE).read_text(encoding="utf-8")
    assert written == (
        "song_id,artist_id,source,lyrics_text_hash,check_id\n"
        f"s1,a1,site,{ZEROS},unrecorded\ns2,a1,site,{ZEROS},check_a\n"
    )
    assert "free text" not in written and "someone" not in written
    assert manifests.read_manifest(result["folder"]).kind == "clean_song_quarantine"
    assert eligible_songs.quarantine_file(data) == result["folder"] / "song_quarantine.csv"
    with pytest.raises(FileExistsError, match="never written over"):
        eligible_songs.import_old_song_quarantine(old, data, date(2026, 11, 20))


def test_the_rule_needs_a_complete_quarantine_folder(tmp_path):
    with pytest.raises(FileNotFoundError, match="song_quarantine"):
        eligible_songs.quarantine_file(tmp_path)


def write_artist_countries(data: Path, day: str, rows: list[tuple[str, str, str]]) -> None:
    """Write a table of artist countries from (country, artist id, decision) rows."""
    folder = paths.clean_artist_country_dir(data, day)
    folder.mkdir(parents=True)
    full = [
        {
            "country_iso3": code,
            "artist_id": artist_id,
            "discogs_artist_id": "1",
            "stated_country": "",
            "home_word": False,
            "releases": 0,
            "releases_home": 0,
            "top_release_country": "",
            "decision": decision,
        }
        for code, artist_id, decision in rows
    ]
    schemas.write_table(schemas.ARTIST_COUNTRY, frame(schemas.ARTIST_COUNTRY, full), folder)
    manifests.write_manifest(data, folder, "clean_artist_country", inputs=["z"])


CHECKED = [
    ("on_the_roster_that_the_table_names", {"artist_id": "a_checked"}, "artist_country"),
    ("on_a_roster_with_no_row", {"artist_id": "a_checked", "country_iso3": "BEN"}, None),
    ("kept_in_the_newest_table", {"artist_id": "a_kept"}, None),
    # The tracked list names this artist, so the table does not decide.
    ("list_says_home", {"artist_id": "a_moved", "country_iso3": "GHA"}, None),
    ("list_says_other", {"artist_id": "a_moved"}, "artist_country"),
]


@pytest.mark.parametrize(("song_id", "over", "reason"), CHECKED, ids=[c[0] for c in CHECKED])
def test_the_table_of_artist_countries_leaves_out_an_artist_of_another_country(
    tmp_path, song_id, over, reason
):
    data = tmp_path / "data"
    other, keep = schemas.OTHER_COUNTRY, schemas.KEEP
    write_artist_countries(data, "20260101", [("TGO", "a_kept", other)])
    write_artist_countries(
        data,
        "20260102",
        [("TGO", "a_checked", other), ("TGO", "a_kept", keep), ("GHA", "a_moved", other)],
    )
    connection = duckdb.default_connection()
    lists = eligible_songs.load_hash_lists(connection, *list_files(tmp_path))
    lists |= eligible_songs.load_artist_lists(
        connection, *artist_files(tmp_path, countries="a_moved,GHA\n"), data
    )
    lists |= eligible_songs.load_text_copies(connection, data)
    lists |= eligible_songs.load_held_countries(connection, tmp_path)
    songs = frame(schemas.COUNTRY_SONGS, [song(song_id, **over)])
    result = eligible_songs.classify(songs, [], lists)
    assert result.project("ineligible_reason").fetchall() == [(reason,)]


def write_text_copies(data: Path, day: str, rows: list[tuple[str, str]]) -> None:
    """Write a table of text copies from (country, song id) rows."""
    folder = paths.clean_text_copies_dir(data, day)
    folder.mkdir(parents=True)
    full = [
        {"country_iso3": code, "song_id": song_id, "kept_song_id": "k", "reason": "same_text"}
        for code, song_id in rows
    ]
    schemas.write_table(schemas.TEXT_COPIES, frame(schemas.TEXT_COPIES, full), folder)
    manifests.write_manifest(data, folder, "clean_text_copies", inputs=["z"])


COPIES = [
    ("listed", {}, "text_copy"),
    ("listed_in_another_country", {"country_iso3": "BEN"}, None),
    ("only_in_the_older_table", {}, None),
    # The duplicate rules come first.
    ("listed_and_re_release", {"re_release": True}, "re_release"),
    ("listed_and_too_old", {"year": 1899}, "text_copy"),
]


@pytest.mark.parametrize(("song_id", "over", "reason"), COPIES, ids=[c[0] for c in COPIES])
def test_the_newest_table_of_text_copies_leaves_out_a_listed_song(tmp_path, song_id, over, reason):
    data = tmp_path / "data"
    write_text_copies(data, "20260101", [("TGO", "only_in_the_older_table")])
    listed = ("listed", "listed_in_another_country", "listed_and_re_release", "listed_and_too_old")
    write_text_copies(data, "20260102", [("TGO", name) for name in listed])
    connection = duckdb.default_connection()
    lists = eligible_songs.load_hash_lists(connection, *list_files(tmp_path))
    lists |= eligible_songs.load_artist_lists(connection, *artist_files(tmp_path), data)
    lists |= eligible_songs.load_text_copies(connection, data)
    lists |= eligible_songs.load_held_countries(connection, tmp_path)
    songs = frame(schemas.COUNTRY_SONGS, [song(song_id, **over)])
    result = eligible_songs.classify(songs, [], lists)
    assert result.project("ineligible_reason").fetchall() == [(reason,)]


def test_with_no_table_of_text_copies_no_song_is_a_copy(tmp_path):
    lists = eligible_songs.load_text_copies(duckdb.default_connection(), tmp_path)
    assert lists["text_copy"].fetchall() == []
    assert lists["uncredited_song"].fetchall() == []


UNCREDITED = [
    ("listed", {}, "uncredited_song"),
    ("listed_in_another_country", {"country_iso3": "BEN"}, None),
    ("listed_and_a_copy", {}, "text_copy"),
]


@pytest.mark.parametrize(("song_id", "over", "reason"), UNCREDITED, ids=[c[0] for c in UNCREDITED])
def test_the_newest_table_of_uncredited_songs_leaves_out_a_listed_song(
    tmp_path, song_id, over, reason
):
    data = tmp_path / "data"
    write_text_copies(data, "20260101", [("TGO", "listed_and_a_copy")])
    folder = paths.clean_uncredited_songs_dir(data, "20260102")
    folder.mkdir(parents=True)
    rows = [
        {"country_iso3": "TGO", "song_id": name, "reason": schemas.MERGED_ARTIST_ID}
        for name in ("listed", "listed_in_another_country", "listed_and_a_copy")
    ]
    schemas.write_table(schemas.UNCREDITED_SONGS, frame(schemas.UNCREDITED_SONGS, rows), folder)
    manifests.write_manifest(data, folder, "clean_uncredited_songs", inputs=["z"])
    connection = duckdb.default_connection()
    lists = eligible_songs.load_hash_lists(connection, *list_files(tmp_path))
    lists |= eligible_songs.load_artist_lists(connection, *artist_files(tmp_path), data)
    lists |= eligible_songs.load_text_copies(connection, data)
    lists |= eligible_songs.load_held_countries(connection, tmp_path)
    songs = frame(schemas.COUNTRY_SONGS, [song(song_id, **over)])
    result = eligible_songs.classify(songs, [], lists)
    assert result.project("ineligible_reason").fetchall() == [(reason,)]


CASES = [
    ("eligible", {}, None, False),
    ("suspect_text", {"lyrics_text_hash": SUSPECT, "source": "Invented"}, "suspect_text", False),
    ("suspect_on_other_site", {"lyrics_text_hash": OTHER_SITE}, None, False),
    (
        "suspect_on_its_site",
        {"lyrics_text_hash": OTHER_SITE, "source": "other_site"},
        "suspect_text",
        False,
    ),
    ("quarantined", {}, "quarantined_song", False),
    ("changed", {}, None, False),  # the text changed after the check
    ("other_artist", {}, None, False),  # the list names this song id with another artist
    ("excluded", {"artist_id": "a_out"}, "excluded_artist", False),
    ("moved", {"artist_id": "a_moved"}, "artist_country", False),
    ("moved_home", {"artist_id": "a_moved", "country_iso3": "GHA"}, None, False),
    ("held", {"country_iso3": "NER", "route": "dump_name"}, "held_country", False),
    ("held_older_song", {"country_iso3": "NER"}, None, False),
    ("campaign_not_held", {"route": "dump_name"}, None, False),
    ("quarantine", {"quality_status": "quarantine"}, "quality_quarantine", False),
    ("unverified", {"quality_status": "source_only_unverified"}, None, False),
    ("suppressed", {"duplicate_decision": "suppress_duplicate"}, "suppressed_duplicate", False),
    ("retained", {"duplicate_decision": "retain"}, None, False),
    ("other_row", {"canonical_song_id": "eligible"}, "not_canonical", False),
    ("own_row", {"canonical_song_id": "own_row"}, None, False),
    ("re_release", {"re_release": True}, "re_release", False),
    ("original_release", {"re_release": False}, None, False),
    ("by_hand", {"route": "manual_review"}, "entered_by_hand", False),
    ("year_fixed_by_hand", {"year_source": "manual_review"}, None, False),
    ("by_hand_named", {"route": "manual_review", "country_iso3": "BEN"}, None, True),
    ("no_year", {"year": None}, None, False),
    ("too_old", {"year": 1899}, "year_out_of_range", False),
    ("too_new", {"year": 2027}, "year_out_of_range", False),
    (
        "first_rule_wins",
        {"quality_status": "quarantine", "year": 1899},
        "quality_quarantine",
        False,
    ),
    (
        "named_and_no_year",
        {"route": "manual_review", "country_iso3": "BEN", "year": None},
        None,
        True,
    ),
    (
        "named_but_quarantined",
        {"route": "manual_review", "country_iso3": "BEN", "quality_status": "quarantine"},
        "quality_quarantine",
        False,
    ),
]


@pytest.mark.parametrize(
    ("song_id", "over", "reason", "by_exception"), CASES, ids=[c[0] for c in CASES]
)
def test_the_rule_gives_each_song_one_reason(tmp_path, song_id, over, reason, by_exception):
    groups = eligible_songs.load_exceptions(
        exceptions_file(tmp_path, "BEN,invented reason,2026-11-19\n")
    )
    songs = frame(schemas.COUNTRY_SONGS, [song(song_id, **over)])
    result = eligible_songs.classify(songs, groups, all_lists(tmp_path))
    assert result.project("ineligible_reason, by_exception").fetchall() == [(reason, by_exception)]
    assert result.columns == [*songs.columns, "ineligible_reason", "by_exception"]


def test_with_no_group_a_song_by_hand_is_left_out(tmp_path):
    songs = frame(schemas.COUNTRY_SONGS, [song("s", route="manual_review", country_iso3="BEN")])
    connection = duckdb.default_connection()
    lists = eligible_songs.load_hash_lists(connection, *list_files(tmp_path))
    lists |= eligible_songs.load_artist_lists(connection, *artist_files(tmp_path))
    lists |= eligible_songs.load_text_copies(connection, tmp_path)
    lists |= eligible_songs.load_held_countries(connection, tmp_path)
    result = eligible_songs.classify(songs, [], lists).project("ineligible_reason, by_exception")
    assert result.fetchall() == [("entered_by_hand", False)]


@pytest.mark.parametrize(
    ("suspect", "quarantine", "message"),
    [
        (f"*,{SUSPECT},\n", "", "a cell is empty"),
        (f"*,{SUSPECT.upper()},check\n", "", "64 lower-case hex"),
        (f"Site,{SUSPECT},check\n", "", "not lower case"),
        (f"*,{SUSPECT},check\n*,{SUSPECT},another\n", "", "named twice"),
        ("", f"s,a1,site,{SUSPECT},check\ns,a1,site,{SUSPECT},check\n", "named twice"),
    ],
)
def test_a_bad_hash_list_is_refused(tmp_path, suspect, quarantine, message):
    with pytest.raises(ValueError, match=message):
        eligible_songs.load_hash_lists(duckdb.connect(), *list_files(tmp_path, suspect, quarantine))


def test_a_hash_list_with_other_columns_is_refused(tmp_path):
    suspect, quarantine = list_files(tmp_path)
    suspect.write_text("provider,lyrics_text_hash,check_id\n", encoding="utf-8")
    with pytest.raises(ValueError, match="the columns must be"):
        eligible_songs.load_hash_lists(duckdb.connect(), suspect, quarantine)


@pytest.mark.parametrize(
    ("excluded", "countries", "message"),
    [
        ("a1,spoken_word\na1,duplicate_entry\n", "", "named twice"),
        ("a1,\n", "", "a cell is empty"),
        ("", "a1,Gha\n", "Gha"),
        ("", "a1,GHA\na1,TGO\n", "named twice"),
    ],
)
def test_a_bad_artist_list_is_refused(tmp_path, excluded, countries, message):
    with pytest.raises(ValueError, match=message):
        eligible_songs.load_artist_lists(
            duckdb.connect(), *artist_files(tmp_path, excluded, countries)
        )


def test_the_tracked_artist_lists_are_valid():
    lists = eligible_songs.load_artist_lists(duckdb.connect())
    assert all(len(relation) for relation in lists.values())


def test_the_tracked_list_of_suspect_texts_is_valid(tmp_path):
    _, quarantine = list_files(tmp_path)
    lists = eligible_songs.load_hash_lists(duckdb.connect(), quarantine=quarantine)
    assert len(lists["suspect_text"])


@pytest.mark.parametrize(
    ("rows", "message"),
    [
        ("BEN,,2026-11-19\n", "the reason is empty"),
        ("Ben,a reason,2026-11-19\n", "Ben"),
        ("BEN,a reason,19.11.2026\n", "19.11.2026"),
        ("BEN,a reason,2026-11-19\nBEN,another,2026-11-20\n", "more than one group"),
    ],
)
def test_a_bad_exceptions_file_is_refused(tmp_path, rows, message):
    with pytest.raises(ValueError, match=message):
        eligible_songs.load_exceptions(exceptions_file(tmp_path, rows))


def test_the_tracked_exceptions_file_is_valid():
    eligible_songs.load_exceptions()


def test_every_country_with_a_manual_review_run_has_an_exception_group():
    named = {group.country_iso3 for group in eligible_songs.load_exceptions()}
    by_hand = {
        record.iso3
        for record in run_records.read_run_records()
        if record.route == eligible_songs.MANUAL_ROUTE and not record.corrects_existing_songs
    }
    assert by_hand <= named, f"add a row to the exceptions file for {sorted(by_hand - named)}"


def write_country(data: Path, iso3: str, songs: list[dict], scores: list[dict] | None) -> None:
    """Write a complete songs folder, and a scores folder when `scores` is given."""
    folder = paths.country_songs_dir(data, iso3, SONGS_RUN)
    folder.mkdir(parents=True)
    schemas.write_table(schemas.COUNTRY_SONGS, frame(schemas.COUNTRY_SONGS, songs), folder)
    for table in (schemas.COUNTRY_ARTISTS, schemas.COUNTRY_LINKS):
        schemas.write_table(table, schemas.empty_table(table), folder)
    manifests.write_manifest(
        data, folder, "country_songs", country_iso3=iso3, run_id=SONGS_RUN, inputs=["x/"]
    )
    if scores is None:
        return
    folder = paths.country_scores_dir(data, iso3, SCORES_RUN)
    folder.mkdir(parents=True)
    schemas.write_table(schemas.SCORE_TOPICS, frame(schemas.SCORE_TOPICS, scores), folder)
    schemas.write_table(
        schemas.SCORE_PROVENANCE, schemas.empty_table(schemas.SCORE_PROVENANCE), folder
    )
    manifests.write_manifest(
        data, folder, "country_scores", country_iso3=iso3, run_id=SCORES_RUN, inputs=["y/"]
    )


def write_panel(data: Path, codes: list[str]) -> None:
    """Write a complete country-year table with the columns of the contract, for 1989 to 1991."""
    folder = paths.clean_countries_dir(data, "20260101")
    folder.mkdir(parents=True)
    rows = ", ".join(f"('{code}', {year})" for code in codes for year in (1989, 1990, 1991))
    others = ", ".join(
        f"CAST(NULL AS VARCHAR) AS {name}"
        for name in COUNTRY_COLUMNS
        if name not in {"country_iso3", "year"}
    )
    relation = duckdb.sql(
        f"SELECT country_iso3, CAST(year AS INTEGER) AS year, {others} "
        f"FROM (VALUES {rows}) AS grid(country_iso3, year)"
    ).project(", ".join(COUNTRY_COLUMNS))
    relation.write_parquet(str(folder / manifests.COUNTRIES_FILE))
    manifests.write_manifest(data, folder, "clean_countries", inputs=["z"])
    # An empty list of songs in quarantine; a test that needs rows writes a newer one.
    eligible_songs.import_old_song_quarantine(old_quarantine(data, ""), data, date(2026, 1, 1))


def score(song_id: str, first: int, sha: str = "0" * 64) -> dict:
    return {"country_iso3": "TGO", "song_id": song_id, "lyrics_sha256": sha, FIRST: first}


@pytest.fixture
def built(tmp_path):
    data = tmp_path / "data"
    write_panel(data, ["TGO", "BEN", "GHA"])
    write_country(
        data,
        "TGO",
        [
            song("t1"),
            song("t2", artist_id="a2"),
            song("t3", year=1991, lyrics_sha256="1" * 64),
            song("t4", quality_status="quarantine"),
            song("t5", year=None),
            song("t6", re_release=True),
            song("t7", lyrics_text_hash=SUSPECT),
            song("quarantined"),
            song("t8", artist_id="a_out"),
            song("t9", artist_id="a_moved"),
            song("t10", artist_id="a_checked"),
            song("t11"),
        ],
        [score("t1", 10), score("t2", 20), score("t3", 30), score("gone", 40), score("t4", 50)],
    )
    write_country(
        data,
        "BEN",
        [
            song("b1", country_iso3="BEN", route="manual_review"),
            song("b2", country_iso3="BEN", year=1950),
        ],
        None,
    )
    old = old_quarantine(tmp_path, f"quarantined,TGO,a1,Invented,{ZEROS},quarantine,x,c,y,z\n")
    eligible_songs.import_old_song_quarantine(old, data, date(2026, 1, 2))
    write_artist_countries(data, "20260103", [("TGO", "a_checked", schemas.OTHER_COUNTRY)])
    write_text_copies(data, "20260104", [("TGO", "t11")])
    suspect, _ = invented_lists(tmp_path)
    excluded, countries = artist_files(tmp_path, "a_out,spoken_word\n", "a_moved,GHA\n")
    result = release.build(
        data,
        today=date(2026, 11, 19),
        exceptions_file=exceptions_file(tmp_path, "BEN,invented reason,2026-11-19\n"),
        suspect_file=suspect,
        excluded_artists_file=excluded,
        artist_countries_file=countries,
    )
    return data, result


def test_the_manifest_counts_songs_in_out_and_left_out(built):
    data, result = built
    manifest = manifests.read_manifest(result["folder"])
    assert manifest.kind == "analysis" and manifest.path == "analysis/20261119/"
    assert manifest.inputs == [
        "clean/countries/20260101/",
        "clean/quality/song_quarantine/20260102/",
        "clean/quality/artist_country/20260103/",
        "clean/quality/text_copies/20260104/",
        f"lyrics/BEN/songs/{SONGS_RUN}/",
        f"lyrics/TGO/songs/{SONGS_RUN}/",
        f"lyrics/TGO/scores/{SCORES_RUN}/",
    ]
    assert manifest.counts == {
        "songs": 14,
        "eligible_songs": 6,
        "songs_by_exception": 1,
        "songs_by_exception_BEN": 1,
        "songs_scored": 2,
        "songs_in_country_year": 4,
        "country_year_left_out_no_year": 1,
        "songs_outside_panel": 1,
        "scores": 5,
        "scores_other_lyrics": 1,
        "scores_no_song": 1,
        "scores_ineligible_song": 1,
        "left_out_quality_quarantine": 1,
        "left_out_suspect_text": 1,
        "left_out_quarantined_song": 1,
        "left_out_excluded_artist": 1,
        "left_out_artist_country": 2,
        "left_out_held_country": 0,
        "left_out_suppressed_duplicate": 0,
        "left_out_not_canonical": 0,
        "left_out_re_release": 1,
        "left_out_text_copy": 1,
        "left_out_uncredited_song": 0,
        "left_out_entered_by_hand": 0,
        "left_out_year_out_of_range": 0,
        "countries": 2,
        "country_years": 9,
    }
    assert result["counts"] == manifest.counts


def test_a_score_joins_on_song_id_and_lyric_hash(built):
    data, result = built
    songs = schemas.read_table(schemas.ANALYSIS_SONGS, result["folder"])
    assert songs.project(f"song_id, scored, by_exception, {FIRST}").order("song_id").fetchall() == [
        ("b1", False, True, None),
        ("b2", False, False, None),
        ("t1", True, False, 10),
        ("t2", True, False, 20),
        ("t3", False, False, None),  # the score is of other lyric text
        ("t5", False, False, None),  # no year: in songs.parquet, not in country_year.parquet
    ]
    assert songs.filter("song_id = 't5'").project("year").fetchall() == [(None,)]
    assert "lyrics" not in songs.columns and "artist_name" not in songs.columns


def test_the_country_year_table_counts_and_averages_the_eligible_songs(built):
    data, result = built
    table = schemas.read_table(schemas.ANALYSIS_COUNTRY_YEAR, result["folder"])
    assert set(COUNTRY_COLUMNS) - set(table.columns) == {"artist_count_method"}
    columns = (
        "country_iso3, year, num_songs, num_artists, num_songs_by_exception, num_songs_scored, "
        f"{FIRST}, {LAST}"
    )
    assert table.project(columns).order("country_iso3, year").fetchall() == [
        ("BEN", 1989, 0, 0, 0, 0, None, None),
        ("BEN", 1990, 1, 1, 1, 0, None, None),
        ("BEN", 1991, 0, 0, 0, 0, None, None),
        ("GHA", 1989, None, None, None, None, None, None),  # no songs folder
        ("GHA", 1990, None, None, None, None, None, None),
        ("GHA", 1991, None, None, None, None, None, None),
        ("TGO", 1989, 0, 0, 0, 0, None, None),
        ("TGO", 1990, 2, 2, 0, 2, 15.0, None),
        ("TGO", 1991, 1, 1, 0, 0, None, None),
    ]


def test_a_release_is_never_written_over_and_needs_its_inputs(built, tmp_path):
    data, result = built
    with pytest.raises(FileExistsError, match="never written over"):
        release.build(data, today=date(2026, 11, 19), exceptions_file=exceptions_file(tmp_path))
    with pytest.raises(FileNotFoundError, match="clean/countries"):
        release.build(tmp_path / "empty", today=date(2026, 11, 19))


def test_a_release_with_no_scores_keeps_its_songs(tmp_path):
    data = tmp_path / "data"
    write_panel(data, ["TGO"])
    write_country(data, "TGO", [song("t1")], None)
    result = release.build(
        data, today=date(2026, 11, 19), exceptions_file=exceptions_file(tmp_path)
    )
    assert result["counts"]["eligible_songs"] == 1 and result["counts"]["scores"] == 0
    songs = schemas.read_table(schemas.ANALYSIS_SONGS, result["folder"])
    assert songs.project(f"song_id, scored, {FIRST}").fetchall() == [("t1", False, None)]


def test_inputs_that_would_lose_rows_are_refused(tmp_path):
    data = tmp_path / "data"
    write_panel(data, ["TGO"])
    with pytest.raises(FileNotFoundError, match="no country"):
        release.build(data, today=date(2026, 11, 19), exceptions_file=exceptions_file(tmp_path))
    write_country(data, "TGO", [song("t1", country_iso3="BEN")], None)
    with pytest.raises(ValueError, match="another country"):
        release.build(data, today=date(2026, 11, 19), exceptions_file=exceptions_file(tmp_path))


def test_scores_with_no_songs_folder_are_refused(tmp_path):
    data = tmp_path / "data"
    write_panel(data, ["TGO"])
    write_country(data, "TGO", [song("t1")], None)
    (data / "lyrics" / "BEN" / "songs").mkdir(parents=True)
    folder = paths.country_scores_dir(data, "BEN", SCORES_RUN)
    folder.mkdir(parents=True)
    (folder / paths.MANIFEST_NAME).write_text("{}", encoding="utf-8")
    with pytest.raises(FileNotFoundError, match="BEN has scores"):
        release.country_folders(data)


def test_a_panel_with_other_columns_is_refused(tmp_path):
    data = tmp_path / "data"
    folder = paths.clean_countries_dir(data, "20260101")
    folder.mkdir(parents=True)
    duckdb.sql("SELECT 'TGO' AS country_iso3, 1990 AS year").write_parquet(
        str(folder / manifests.COUNTRIES_FILE)
    )
    manifests.write_manifest(data, folder, "clean_countries", inputs=["z"])
    eligible_songs.import_old_song_quarantine(old_quarantine(data, ""), data, date(2026, 1, 1))
    write_country(data, "TGO", [song("t1")], None)
    with pytest.raises(ValueError, match="COUNTRY_COLUMNS"):
        release.build(data, today=date(2026, 11, 19), exceptions_file=exceptions_file(tmp_path))
