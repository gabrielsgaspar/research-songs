"""The rule for eligible songs and the analysis release, on small invented tables."""

from datetime import date
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from songs.common import manifests, paths, schemas
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


CASES = [
    ("eligible", {}, None, False),
    ("quarantine", {"quality_status": "quarantine"}, "quality_quarantine", False),
    ("unverified", {"quality_status": "source_only_unverified"}, None, False),
    ("suppressed", {"duplicate_decision": "suppress_duplicate"}, "suppressed_duplicate", False),
    ("retained", {"duplicate_decision": "retain"}, None, False),
    ("other_row", {"canonical_song_id": "eligible"}, "not_canonical", False),
    ("own_row", {"canonical_song_id": "own_row"}, None, False),
    ("by_hand", {"route": "manual_review"}, "entered_by_hand", False),
    ("by_hand_old", {"year_source": "manual_review"}, "entered_by_hand", False),
    ("by_hand_named", {"route": "manual_review", "country_iso3": "BEN"}, None, True),
    ("no_year", {"year": None}, "no_year", False),
    ("too_old", {"year": 1899}, "year_out_of_range", False),
    ("too_new", {"year": 2027}, "year_out_of_range", False),
    (
        "first_rule_wins",
        {"quality_status": "quarantine", "year": None},
        "quality_quarantine",
        False,
    ),
    (
        "named_but_quarantined",
        {"route": "manual_review", "country_iso3": "BEN", "year": None},
        "no_year",
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
    result = eligible_songs.classify(songs, groups).project("ineligible_reason, by_exception")
    assert result.fetchall() == [(reason, by_exception)]


def test_with_no_group_a_song_by_hand_is_left_out(tmp_path):
    songs = frame(schemas.COUNTRY_SONGS, [song("s", route="manual_review", country_iso3="BEN")])
    result = eligible_songs.classify(songs, []).project("ineligible_reason, by_exception")
    assert result.fetchall() == [("entered_by_hand", False)]


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
        ],
        [score("t1", 10), score("t2", 20), score("t3", 30), score("gone", 40)],
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
    result = release.build(
        data,
        today=date(2026, 11, 19),
        exceptions_file=exceptions_file(tmp_path, "BEN,invented reason,2026-11-19\n"),
    )
    return data, result


def test_the_manifest_counts_songs_in_out_and_left_out(built):
    data, result = built
    manifest = manifests.read_manifest(result["folder"])
    assert manifest.kind == "analysis" and manifest.path == "analysis/20261119/"
    assert manifest.inputs == [
        "clean/countries/20260101/",
        f"lyrics/BEN/songs/{SONGS_RUN}/",
        f"lyrics/TGO/songs/{SONGS_RUN}/",
        f"lyrics/TGO/scores/{SCORES_RUN}/",
    ]
    assert manifest.counts == {
        "songs": 7,
        "eligible_songs": 5,
        "songs_by_exception": 1,
        "songs_by_exception_BEN": 1,
        "songs_scored": 2,
        "songs_outside_panel": 1,
        "scores": 4,
        "scores_other_lyrics": 1,
        "scores_no_song": 1,
        "left_out_quality_quarantine": 1,
        "left_out_suppressed_duplicate": 0,
        "left_out_not_canonical": 0,
        "left_out_entered_by_hand": 0,
        "left_out_no_year": 1,
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
    ]
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
