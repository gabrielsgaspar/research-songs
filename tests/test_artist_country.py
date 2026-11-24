"""The rule that marks roster artists of another country, on small invented tables."""

from datetime import date
from pathlib import Path

import duckdb
import pandas as pd
import pytest
from typer.testing import CliRunner

from songs.cli import app
from songs.common import manifests, paths, schemas, sync
from songs.common.paths import DATA_ROOT_ENV
from songs.stage_00_ingest import dump_match
from songs.stage_10_clean import artist_country
from songs.stage_10_clean.artist_country import KEEP, OTHER_COUNTRY, decide, profile_evidence

RUN = "20260101T000000Z"
EVERY_CODE = frozenset(artist_country.load_country_words().values())
# Discogs id -> the invented profile and the release countries of the artist.
ARTISTS = {
    1: ("Syrian  traditional singer\nand composer.", ["Syria"] * 5),
    2: ("Soviet pop singer, born in Kyiv.", ["Syria"] * 5),
    3: ("A singer who toured Syria two times.", ["Syria"] * 5),
    4: ("Syrian singer.", ["Syria"] * 3 + ["Ukraine"]),
    5: ("Syrian-born singer.", ["Syria"] * 5),
    6: ("Rock band from Dublin, Ireland.", ["UK", "UK", "Ireland"]),
    7: ("Syrian singer.", [None]),
    8: (None, ["Syria"] * 5),
}
EXPECTED = {
    "a1": ("SYR", False, 5, 0, "Syria", OTHER_COUNTRY),
    "a2": ("SUN", True, 5, 0, "Syria", KEEP),
    "a3": ("", False, 5, 0, "Syria", KEEP),
    "a4": ("SYR", False, 4, 1, "Syria", KEEP),
    "a5": ("", False, 5, 0, "Syria", KEEP),
    "a6": ("IRL", False, 3, 0, "UK", OTHER_COUNTRY),
    "a7": ("SYR", False, 0, 0, "", KEEP),
    "a8": ("", False, 5, 0, "Syria", KEEP),
}


def write(table: schemas.Table, folder: Path, rows: list[dict]) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    names = [column.name for column in table.all_columns]
    schemas.write_table(
        table, schemas.cast_to_schema(table, pd.DataFrame(rows).reindex(columns=names)), folder
    )


def make_data(data: Path) -> Path:
    """Write invented Discogs tables and the roster of one country. Return the songs folder."""
    discogs = paths.clean_catalog_dir(data, "discogs", "20260101")
    discogs.mkdir(parents=True)
    releases = [
        (10 * number + index, number, country)
        for number, (_, countries) in ARTISTS.items()
        for index, country in enumerate(countries)
    ]
    frames = {
        "artists": pd.DataFrame(
            [(number, f"Invented {number}", profile) for number, (profile, _) in ARTISTS.items()],
            columns=["artist_id", "name", "profile"],
        ),
        # Each artist has its first release by a track credit, and that release two times.
        "release_artists": pd.DataFrame(
            [(release, number) for release, number, _ in releases],
            columns=["release_id", "artist_id"],
        ),
        "release_track_artists": pd.DataFrame(
            [(release, 1, number) for release, number, _ in releases if release % 10 == 0],
            columns=["release_id", "track_index", "artist_id"],
        ),
        "releases": pd.DataFrame(
            [(release, country) for release, _, country in releases],
            columns=["release_id", "country"],
        ),
    }
    for name, frame in frames.items():
        duckdb.from_df(frame).write_parquet(str(discogs / f"{name}.parquet"))
    country = paths.country_songs_dir(data, "UKR", RUN)
    roster = [
        {
            "country_iso3": "UKR",
            "artist_id": f"a{number}",
            "artist_name": f"Invented {number}",
            "discogs_artist_id": str(number),
            "attempted": True,
            "songs": 0,
        }
        for number in ARTISTS
    ]
    no_id = roster[0] | {
        "artist_id": "a9",
        "artist_name": "No Such Name",
        "discogs_artist_id": None,
    }
    write(schemas.COUNTRY_ARTISTS, country, [*roster, no_id])
    songs = [
        {
            "country_iso3": "UKR",
            "song_id": f"s{index}",
            "artist_id": artist_id,
            "artist_name": "Invented",
            "song_name": f"Invented title {index}",
            "source": "invented",
            "lyrics": "invented line",
            "lyrics_sha256": f"h{index}",
            "route": "old_layout",
            "run_id": RUN,
        }
        for index, artist_id in enumerate(["a1", "a1", "a1", "a2", "a9"])
    ]
    write(schemas.COUNTRY_SONGS, country, songs)
    for folder in (discogs, country):
        (folder / paths.MANIFEST_NAME).write_text("{}\n", encoding="utf-8")
    return country


def test_each_condition_of_the_rule_decides_a_roster_artist(tmp_path):
    country = make_data(tmp_path)
    discogs = paths.latest_clean_catalog_dir(tmp_path, "discogs")
    rows, songs, artists = artist_country.country_rows(country, discogs, "UKR")
    found = {row["artist_id"]: tuple(row.values())[3:] for row in rows}
    assert found == EXPECTED
    assert (songs, artists) == ({"a1": 3, "a2": 1, "a9": 1}, 9)
    assert {row["discogs_artist_id"] for row in rows} == {str(number) for number in ARTISTS}


def test_a_dry_check_writes_nothing_and_a_write_makes_one_folder(tmp_path):
    country = make_data(tmp_path)
    result = artist_country.check_rosters(tmp_path)
    counts = {
        "countries": 1,
        "artists_in": 9,
        "artists_with_discogs_id": 8,
        "left_out_no_discogs_id": 1,
        "other_country_artists": 2,
        "other_country_artists_with_songs": 1,
        "songs_in": 5,
        "other_country_songs": 3,
    }
    assert result == {"counts": counts, "by_country": {"UKR": (3, 5)}, "folder": None}
    assert not (tmp_path / "clean" / "quality").exists()

    result = artist_country.check_rosters(tmp_path, write=True, today=date(2026, 1, 2))
    folder = paths.clean_artist_country_dir(tmp_path, "20260102")
    assert result["folder"] == folder == paths.latest_clean_artist_country_dir(tmp_path)
    manifest = manifests.read_manifest(folder)
    assert (manifest.kind, manifest.counts) == ("clean_artist_country", counts)
    assert manifest.inputs == [
        "clean/catalog/discogs/20260101/",
        paths.data_relative(tmp_path, country),
    ]
    table = schemas.read_table(schemas.ARTIST_COUNTRY, folder)
    assert len(table) == 8
    assert table.filter(f"decision = '{OTHER_COUNTRY}'").project("artist_id").fetchall() == [
        ("a1",),
        ("a6",),
    ]
    assert folder.parent in sync._parents(tmp_path)
    with pytest.raises(FileExistsError, match="never written over"):
        artist_country.check_rosters(tmp_path, write=True, today=date(2026, 1, 2))


def test_the_check_needs_a_discogs_catalog_folder(tmp_path):
    with pytest.raises(FileNotFoundError, match="clean/catalog/discogs"):
        artist_country.check_rosters(tmp_path)


def test_the_command_is_dry_without_write(tmp_path, monkeypatch):
    make_data(tmp_path)
    monkeypatch.setenv(DATA_ROOT_ENV, str(tmp_path))
    result = CliRunner().invoke(app, ["lyrics", "roster-check"])
    assert result.exit_code == 0, result.output
    assert "with a Discogs id (rows out): 8" in result.output
    assert "other_country: 2 artists, 1 of them with songs" in result.output
    assert "songs of those artists: 3 of 5 (60.00%)" in result.output
    assert "UKR\t3\t5\t60.0%" in result.output
    assert "dry run: nothing written" in result.output
    assert paths.latest_clean_artist_country_dir(tmp_path) is None
    result = CliRunner().invoke(app, ["lyrics", "roster-check", "--write"])
    assert result.exit_code == 0, result.output
    assert paths.latest_clean_artist_country_dir(tmp_path) is not None


@pytest.mark.parametrize(
    ("profile", "stated"),
    [
        ("Syrian traditional singer", "SYR"),
        ("Australian pop, rock band", "AUS"),
        ("A duo from Dublin, Ireland", "IRL"),
        ("Singer from a small town. Later moved to Ireland", ""),
        ("Irish-born singer", ""),
        ("Irish born singer", ""),
        ("Toured Ireland two times", ""),
        ("Northern Irish singer", "GBR"),
        ("UK garage duo", "GBR"),
        ("Uk garage duo", ""),
        ("british band", "GBR"),
        ("US rapper", "USA"),
        ("Tell us, rapper", ""),
        ("Belorussian singer", "BLR"),
        ("Byelorussian singer", "BLR"),
        ("Singer from New Jersey, USA", "USA"),
        ("x" * 150 + " Irish singer", ""),
        (None, ""),
    ],
)
def test_a_profile_states_a_country_only_in_two_forms(profile, stated):
    assert profile_evidence(profile, frozenset())[0] == stated


@pytest.mark.parametrize("phrase", artist_country.IGNORED_PHRASES)
def test_an_ignored_phrase_is_no_country_evidence(phrase):
    text = f"{phrase.upper()} singer from {phrase}"
    assert profile_evidence(text, EVERY_CODE) == ("", False)


def test_the_ignored_phrases_are_the_ones_that_were_decided():
    assert set(artist_country.IGNORED_PHRASES) == {
        "New Jersey",
        "British Columbia",
        "Belgian Congo",
        "New Mexico",
        "New England",
        "Indian Ocean",
        "West Indies",
        "West Indian",
        "Latin American",
        "South American",
        "North American",
        "Central American",
    }


def test_a_home_word_protects_the_artist():
    home = artist_country.home_codes("UKR")
    assert {"UKR", "SUN"} <= home and "RUS" not in home
    assert profile_evidence("Soviet opera singer", home) == ("SUN", True)
    assert profile_evidence("Syrian singer, lives in Ukraine", home) == ("SYR", True)
    assert profile_evidence("Syrian singer", home) == ("SYR", False)
    assert "DEU" in artist_country.home_codes("DDR")
    assert "DDR" in artist_country.home_codes("DEU")
    assert artist_country.home_codes("SUN") == {"SUN"}


@pytest.mark.parametrize(
    ("values", "decision"),
    [
        (("SYR", False, 6, 1, False), OTHER_COUNTRY),
        (("SYR", False, 5, 1, False), KEEP),
        (("SYR", False, 15, 3, False), KEEP),
        (("SYR", False, 6, 1, True), KEEP),
        (("SYR", True, 6, 0, False), KEEP),
        (("", False, 6, 0, False), KEEP),
        (("SYR", False, 0, 0, False), KEEP),
    ],
)
def test_the_decision_needs_all_three_conditions(values, decision):
    assert decide(*values) == decision


def test_a_home_country_wins_a_tie_for_the_most_releases():
    home = frozenset({"Ukraine"})
    assert artist_country.top_country({"Syria": 2, "Ukraine": 2, "Egypt": 1}, home) == "Ukraine"
    assert artist_country.top_country({"Syria": 2, "Egypt": 2}, home) == "Egypt"
    assert artist_country.top_country({}, home) == ""


def test_the_word_list_names_each_word_one_time_and_covers_the_home_file():
    words = artist_country.load_country_words()
    assert len({word.casefold() for word in words}) == len(words)
    assert set(dump_match.load_home_countries()) <= set(words.values())


@pytest.mark.parametrize("rows", ["IRL,Irish\nGBR,irish\n", "irl,Irish\n", "IRL, Irish\n"])
def test_a_bad_word_list_is_refused(tmp_path, rows):
    path = tmp_path / artist_country.WORDS_FILE
    path.parent.mkdir(parents=True)
    path.write_text("country_iso3,word\n" + rows, encoding="utf-8")
    with pytest.raises(ValueError):
        artist_country.load_country_words(tmp_path)


def test_a_country_word_in_the_name_of_the_artist_is_no_evidence():
    text = "Hong Kong Radio is a punk band. The singer is a Mexican drummer."
    assert profile_evidence(text, frozenset({"MEX"})) == ("HKG", True)
    assert profile_evidence(text, frozenset({"MEX"}), ("Hong Kong Radio",)) == ("MEX", True)
    assert profile_evidence(text, frozenset({"HKG"}), ("", "HONG KONG RADIO")) == ("MEX", False)


def test_a_role_of_another_person_is_no_statement():
    assert profile_evidence("Orchestra founded by the German composer", frozenset())[0] == ""
    assert profile_evidence("The German composer and pianist", frozenset())[0] == ""
    assert profile_evidence("German composer and pianist", frozenset())[0] == "DEU"
