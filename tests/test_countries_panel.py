"""The clean builders and the country-year panel, on small invented inputs."""

from datetime import date
from pathlib import Path

import duckdb
import pandas as pd
import pytest
from test_release import SONGS_RUN, old_quarantine, song, write_country
from typer.testing import CliRunner

from songs.cli import app
from songs.common import manifests, paths
from songs.common.paths import data_root
from songs.stage_10_clean import (
    crises,
    democracy,
    fertility,
    gdp,
    labor,
    population,
    world_bank_countries,
)
from songs.stage_50_analysis import countries_panel as panel
from songs.stage_50_analysis import eligible_songs, sample_tiers

FIXTURES = Path(__file__).parent / "fixtures" / "panel"
REGISTRY = pd.DataFrame(
    {
        "country_iso3": ["BRA", "PRT", "ROU"],
        "country_name": ["Brazil", "Portugal", "Romania"],
        "in_wvs": [True, False, None],
        "in_evs": [False, True, None],
    }
)
LOOKUP = {"brazil": "BRA", "portugal": "PRT", "old empire": ""}


def rows(relation: duckdb.DuckDBPyRelation, where: str, columns: str) -> list[tuple]:
    return relation.filter(where).project(columns).fetchall()


def test_gdp_keeps_country_rows_with_a_value():
    clean = gdp.clean_gdp(pd.read_csv(FIXTURES / "maddison.csv", encoding="utf-8"))
    assert clean.values.tolist() == [
        ["BRA", 1990, 5000.5],
        ["BRA", 1991, 5100.0],
        ["PRT", 1990, 9000.0],
    ]
    with pytest.raises(ValueError, match="duplicate"):
        gdp.clean_gdp(
            pd.DataFrame({"Code": ["BRA", "BRA"], "Year": [1990, 1990], gdp.VALUE_COLUMN: [1, 2]})
        )
    with pytest.raises(ValueError, match="at least"):
        gdp.load_gdp(FIXTURES / "maddison.csv")  # far fewer countries than the real file


def test_population_is_in_persons_and_marks_projections():
    clean = population.clean_population(pd.read_csv(FIXTURES / "wpp.csv", encoding="utf-8"))
    assert clean["country_iso3"].tolist() == ["BRA", "BRA"]  # medium variant, countries, from 1950
    assert clean["population_total"].tolist() == [200_000_500.0, 201_000_000.0]
    assert clean["population_is_projected"].tolist() == [False, True]
    with pytest.raises(ValueError, match="expected 237 countries"):
        population.load_population(FIXTURES / "wpp.csv")


def test_female_labor_force_becomes_one_row_per_country_and_year():
    clean = labor.load_female_labor_force(FIXTURES / "wdi_female_labor.csv")
    assert clean.values.tolist() == [["BRA", 1990, 44.5], ["BRA", 1991, 45.0], ["PRT", 1991, 50.25]]


def test_democracy_keeps_rows_with_a_value_and_refuses_other_values(tmp_path):
    source = pd.DataFrame(
        {"wbcode": ["ROM", "ROM", "BRA"], "year": [1960.0, 1961.0, 1960.0], "dem": [0.0, None, 1.0]}
    )
    source.to_stata(tmp_path / democracy.FILE_NAME, write_index=False)
    clean = democracy.load_democracy(tmp_path / democracy.FILE_NAME)
    assert clean.values.tolist() == [["BRA", 1960, 1.0], ["ROM", 1960, 0.0]]
    with pytest.raises(ValueError, match="not 0 or 1"):
        democracy.clean_democracy(source.assign(dem=0.5))
    with pytest.raises(ValueError, match="outside 1960 to 2010"):
        democracy.clean_democracy(source.assign(year=2011.0))


def write_fertility_files(folder: Path, total_fertility: str = "1.5") -> None:
    for file_name, rename in fertility.FILE_COLUMNS.items():
        header = "Code Year " + " ".join(rename)
        values = " ".join(
            total_fertility if "TFR" in column else "5" if column.startswith("sd") else "30"
            for column in rename
        )
        lines = ["Invented title", "", header, f"DEUTNP 1990 {values}", f"DEUTE 1990 {values}"]
        lines.append("PRT 1990 " + " ".join("." for _ in rename))
        (folder / file_name).write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_fertility_joins_the_files_and_keeps_national_series(tmp_path):
    write_fertility_files(tmp_path)
    clean = fertility.load_fertility(tmp_path)
    assert clean["country_iso3"].tolist() == ["DEU", "PRT"]  # the part of Germany is left out
    assert list(clean.columns) == ["country_iso3", "year", *fertility.COLUMNS]
    assert clean.loc[0, "hfd_total_fertility_rate"] == 1.5
    assert clean.loc[1, fertility.COLUMNS].isna().all()  # a dot is a missing value
    write_fertility_files(tmp_path, total_fertility="15")
    with pytest.raises(ValueError, match="outside 0 to 10"):
        fertility.load_fertility(tmp_path)


def test_income_groups_and_regions(tmp_path):
    workbook = tmp_path / "income.xlsx"
    sheet = pd.DataFrame(
        {
            "Economy": ["Brazil", "Channel Islands", "World"],
            "Code": ["BRA", "CHI", "WLD"],
            "Income group": ["Upper middle income", "High income", None],
        }
    )
    sheet.to_excel(workbook, sheet_name=world_bank_countries.INCOME_SHEET, index=False)
    groups = world_bank_countries.load_income_groups(workbook)
    groups = dict(zip(groups["country_iso3"], groups["world_bank_income_group"], strict=True))
    assert groups == {"BRA": "Upper middle income"} | dict.fromkeys(
        ["CHI", "GGY", "JEY"], "High income"
    )

    regions = world_bank_countries.load_regions(FIXTURES / "world_bank_countries.json")
    regions = dict(zip(regions["country_iso3"], regions["region_name"], strict=True))
    assert regions["BRA"] == "Latin America & Caribbean"
    assert regions["EGY"] == "Middle East & North Africa"
    assert regions["TWN"] == "East Asia & Pacific"  # an override
    assert "WLD" not in regions


def test_country_names_become_codes_and_an_unknown_name_stops_the_build():
    names = pd.Series(["Brazil 2/", "Portugal†", "Old Empire"])
    codes = crises.to_iso3(names, LOOKUP)
    assert codes[:2].tolist() == ["BRA", "PRT"] and pd.isna(codes[2])  # a known entity, no code
    with pytest.raises(ValueError, match="Atlantis"):
        crises.to_iso3(pd.Series(["Atlantis"]), LOOKUP)
    lookup = crises.name_lookup(REGISTRY)
    assert lookup["brazil"] == "BRA" and lookup["vietnam"] == "VNM"


def test_episodes_mark_state_onset_and_count():
    episodes = pd.DataFrame(
        {
            "country_iso3": ["BRA", "BRA", "XXX"],
            "start_year": [1990, 1990, 1990],
            "end_year": [1991, 1990, 1990],
        }
    )
    grid = crises.episode_grid(episodes, {"BRA", "PRT"}, range(1989, 1993), "banking_crisis")
    brazil = grid[grid["country_iso3"] == "BRA"]
    assert brazil["state"].tolist() == [0, 1, 1, 0]
    assert brazil["onset"].tolist() == [0, 1, 0, 0]
    assert brazil["event_count"].tolist() == [0, 2, 0, 0]
    assert grid[grid["country_iso3"] == "PRT"]["state"].tolist() == [
        0,
        0,
        0,
        0,
    ]  # covered, no crisis


def test_hyperinflation_reads_the_tracked_episodes():
    grid = crises.load_hyperinflation({"BRA", "PRT"})
    brazil = grid[(grid["country_iso3"] == "BRA") & (grid["state"] == 1)]
    assert brazil["year"].tolist() == [1989, 1990]
    assert grid["year"].min() == 1795 and grid["year"].max() == 2012


def test_banking_reads_start_and_end_years(tmp_path):
    workbook = tmp_path / "banking.xlsx"
    sheet = pd.DataFrame(
        {
            "Country": ["Brazil", "Portugal", None],
            "Start": [1990, "2008", 1],
            "End": ["1994", "ongoing", 1],
        }
    )
    sheet.to_excel(workbook, sheet_name=crises.BANKING_SHEET, index=False)
    grid = crises.load_banking(workbook, {"BRA", "PRT"}, LOOKUP)
    in_crisis = grid[grid["state"] == 1]
    assert in_crisis[in_crisis["country_iso3"] == "BRA"]["year"].tolist() == [
        1990,
        1991,
        1992,
        1993,
        1994,
    ]
    assert in_crisis[in_crisis["country_iso3"] == "PRT"]["year"].tolist() == [2008]  # no end year


def test_sovereign_default_reads_debt_in_default(tmp_path):
    workbook = tmp_path / "default.xlsx"
    sheet = pd.DataFrame(
        [
            [None, None, " ", None, 1960, 1961, 1962, 1963],
            [None, None, "A title", None, None, None, None, None],
            [None, 1, "Brazil", None, 0, 12.5, 3, 0],
            [None, 2, "Portugal", None, None, 4, None, 5],
            [None, 3, "Old Empire", None, 1, 1, 1, 1],
        ]
    )
    sheet.to_excel(workbook, sheet_name=crises.DEFAULT_SHEET, index=False, header=False)
    grid = crises.load_sovereign_default(workbook, LOOKUP)
    brazil = grid[grid["country_iso3"] == "BRA"]
    assert brazil["state"].tolist() == [0, 1, 1, 0]
    assert brazil["onset"].tolist() == [0, 1, 0, 0]
    portugal = grid[grid["country_iso3"] == "PRT"]
    assert portugal["year"].tolist() == [1961, 1963]  # an empty cell is not covered
    assert portugal["onset"].tolist() == [1, 1]
    assert set(grid["country_iso3"]) == {"BRA", "PRT"}


def test_currency_crises_come_from_months_and_episode_starts(tmp_path):
    months = pd.DataFrame(
        {
            "wbcode": ["BRA", "BRA", "BRA", "ATL"],
            "t": pd.to_datetime(["1999-01-01", "1999-02-01", "2001-05-01", "1999-01-01"]),
            "episode": [0.0, 1.0, 0.0, 1.0],
        }
    )
    months.to_stata(tmp_path / "monthly.dta", write_index=False)
    starts = pd.DataFrame({"wbcode": ["BRA", "BRA"], "episodeYr": [1999.0, 1999.0]})
    starts.to_stata(tmp_path / "episodes.dta", write_index=False)
    grid = crises.load_currency(tmp_path / "episodes.dta", tmp_path / "monthly.dta", {"BRA", "PRT"})
    assert set(grid["country_iso3"]) == {"BRA"}  # only countries of the monthly file are covered
    marked = grid[grid["state"] == 1]
    assert marked[["year", "onset", "event_count"]].values.tolist() == [[1999, 1, 2]]
    assert len(grid) == len(crises.CURRENCY_YEARS)


def test_a_clean_event_is_the_only_onset_of_its_country_and_year():
    def part(family, onsets):
        return pd.DataFrame(
            {
                "country_iso3": "BRA",
                "year": [1990, 1991],
                "family": family,
                "state": onsets,
                "onset": onsets,
                "event_count": onsets,
            }
        )

    table = crises.combine([part("banking_crisis", [1, 1]), part("hyperinflation", [1, 0])])
    assert table["clean_event"].tolist() == [False, True, False, False]
    with pytest.raises(ValueError, match="duplicate"):
        crises.combine([part("banking_crisis", [1, 1]), part("banking_crisis", [0, 0])])


def small_tables() -> dict[str, pd.DataFrame]:
    crisis_rows = pd.DataFrame(
        {
            "country_iso3": ["BRA", "BRA", "BRA"],
            "year": [1990, 1990, 1991],
            "family": ["banking_crisis", "hyperinflation", "banking_crisis"],
            "state": [0, 1, 0],
            "onset": [0, 1, 0],
            "event_count": [0, 1, 0],
            "clean_event": [False, True, False],
        }
    )
    return {
        "registry": REGISTRY,
        "gdp": gdp.clean_gdp(pd.read_csv(FIXTURES / "maddison.csv", encoding="utf-8")),
        "democracy": pd.DataFrame(
            {"country_iso3": ["ROM", "bra"], "year": [1990, 1990], "anrr_democracy": [1.0, 0.0]}
        ),
        "labor": pd.DataFrame({"country_iso3": ["WLD"], "year": [1990], labor.COLUMN: [50.0]}),
        "crises": crisis_rows,
    }


def test_the_panel_has_one_row_per_registry_country_and_year():
    result = panel.join_panel(small_tables(), "Invented GDP source")
    assert tuple(result.columns) == panel.COUNTRY_COLUMNS
    assert len(result) == 3 * 127
    assert result.aggregate("min(year), max(year)").fetchall() == [(1900, 2026)]
    brazil = "country_iso3 = 'BRA' AND year = 1990"
    assert rows(result, brazil, "country_name, in_wvs, gdp_per_capita, gdp_source_name") == [
        ("Brazil", True, 5000.5, "Invented GDP source")
    ]
    assert rows(
        result, brazil, "banking_crisis_state, hyperinflation_onset, hyperinflation_clean_event"
    ) == [(0, 1, True)]
    assert rows(result, brazil, "any_crisis_state, any_crisis_onset, currency_crisis_state") == [
        (1, 1, None)
    ]
    assert rows(result, "country_iso3 = 'BRA' AND year = 1991", "any_crisis_state") == [(0,)]
    # No source covers this row, so "any crisis" is empty, not zero.
    assert rows(
        result, "country_iso3 = 'ROU' AND year = 1990", "any_crisis_state, gdp_source_name"
    ) == [(None, None)]
    # A table that is not given leaves its columns empty.
    assert result.aggregate("count(num_songs), count(populist), count(region_name)").fetchall() == [
        (0, 0, 0)
    ]


def test_an_old_code_takes_its_iso3_code_and_other_codes_are_reported():
    tables = small_tables()
    result = panel.join_panel(tables, "x")
    assert rows(result, "anrr_democracy IS NOT NULL", "country_iso3, anrr_democracy") == [
        ("BRA", 0.0),
        ("ROU", 1.0),
    ]
    assert panel.codes_outside_registry(tables) == {"labor": ["WLD"]}
    tables["democracy"] = pd.DataFrame(
        {"country_iso3": ["ROM", "ROU"], "year": [1990, 1990], "anrr_democracy": [1.0, 0.0]}
    )
    with pytest.raises(ValueError, match="more than one row"):
        panel.join_panel(tables, "x")


def country_root(tmp_path: Path, codes: list[str]) -> Path:
    """Write a project root with a folder in `countries/` for each code."""
    root = tmp_path / "repo"
    for code in codes:
        (root / "countries" / code / "runs").mkdir(parents=True)
    (root / "countries" / "README.md").write_text("invented", encoding="utf-8")
    return root


def test_the_registry_is_the_country_folders_with_world_bank_names(tmp_path):
    root = country_root(tmp_path, ["BRA", "ROM", "TWN"])
    registry = panel.registry_from_countries(root, FIXTURES / "world_bank_countries.json")
    assert list(registry.columns) == ["country_iso3", "country_name", "in_wvs", "in_evs"]
    assert registry["country_iso3"].tolist() == ["BRA", "TWN"]  # ROM is an old code
    assert registry["country_name"].iloc[0] == "Brazil"
    assert registry["country_name"].isna().tolist() == [False, True]  # TWN is not on the list
    assert registry[["in_wvs", "in_evs"]].isna().all().all()
    assert panel.registry_from_countries(root, None)["country_name"].isna().all()


def write_songs(data: Path) -> None:
    """Write BRA with 100 eligible songs in each decade from the 1950s to the 2010s, and ROU."""
    core = [
        song(f"c{n}", country_iso3="BRA", artist_id=f"a{n % 3}", year=1950 + n // 100 * 10)
        for n in range(700)
    ]
    core += [
        song("c_no_year", country_iso3="BRA", year=None),
        song("c_out", country_iso3="BRA", quality_status="quarantine"),
    ]
    write_country(data, "BRA", core, None)
    write_country(data, "ROU", [song("r1", country_iso3="ROU")], None)
    eligible_songs.import_old_song_quarantine(old_quarantine(data, ""), data, date(2026, 1, 1))


def test_the_song_tables_count_the_eligible_songs_and_give_the_tier(tmp_path):
    assert panel.song_tables(tmp_path) == ({}, {"countries_with_songs": 0})
    write_songs(tmp_path)
    tables, counts = panel.song_tables(tmp_path)
    assert counts["countries_with_songs"] == 2
    assert (counts["songs"], counts["eligible_songs"], counts["eligible_songs_no_year"]) == (
        703,
        702,
        1,
    )
    assert counts["left_out_quality_quarantine"] == 1
    assert (counts["sample_tier_core"], counts["sample_tier_total"]) == (1, 1)
    songs = tables["songs"].set_index(["country_iso3", "year"])["num_songs"]
    assert len(songs) == 2 * 127  # every year of a country with songs, 0 in a year with none
    assert songs["BRA", 1950] == 100 and songs["BRA", 1955] == 0
    assert songs["ROU", 1990] == 1 and songs["ROU", 1991] == 0
    artists = tables["artists"].set_index(["country_iso3", "year"])
    assert artists.loc[("BRA", 1950), "num_artists"] == 3
    assert set(artists["artist_count_method"]) == {panel.ARTIST_COUNT_METHOD}
    sample = tables["sample"]
    tiers = dict(zip(sample["country_iso3"], sample["analysis_tier"], strict=True))
    assert tiers == {"BRA": sample_tiers.CORE, "ROU": sample_tiers.TOTAL}


def test_build_stops_on_absent_inputs_and_never_writes_over_a_panel(tmp_path):
    write_songs(tmp_path)
    with pytest.raises(FileNotFoundError, match="democracy"):
        panel.build(tmp_path)
    result = panel.build(tmp_path, allow_missing=True, today=date(2026, 1, 2))
    assert result["path"] == tmp_path / "clean" / "countries" / "20260102" / "countries.parquet"
    assert result["rows"] == result["counts"]["registry_countries"] * 127
    assert {"democracy", "gdp", *panel.NO_SOURCE} <= set(result["absent_inputs"])
    assert "songs" not in result["absent_inputs"]
    written = duckdb.read_parquet(result["path"].as_posix())
    assert tuple(written.columns) == panel.COUNTRY_COLUMNS
    bra = "country_iso3 = 'BRA' AND year = 1950"
    assert rows(written, bra, "num_songs, num_artists, analysis_tier") == [(100, 3, "Core")]
    # A country of the registry with no songs folder has empty counts and no tier.
    arg = "country_iso3 = 'ARG' AND year = 1950"
    assert rows(written, arg, "num_songs, analysis_tier") == [(None, None)]
    # The tracked hyperinflation episodes need no raw file.
    assert rows(written, "country_iso3 = 'BRA' AND hyperinflation_onset = 1", "year") == [(1989,)]
    with pytest.raises(FileExistsError):
        panel.build(tmp_path, allow_missing=True, today=date(2026, 1, 2))


def test_with_no_songs_the_song_columns_are_empty(tmp_path):
    tables, absent, _ = panel.read_tables(
        panel.default_inputs(tmp_path), tmp_path, allow_missing=True
    )
    assert "songs" in absent and "sample" not in tables
    result = panel.join_panel(tables, "x")
    assert result.aggregate("count(num_songs), count(analysis_tier)").fetchall() == [(0, 0)]


def test_build_writes_a_manifest_that_names_the_inputs_it_read(tmp_path):
    write_songs(tmp_path)
    result = panel.build(tmp_path, allow_missing=True, today=date(2026, 1, 2))
    folder = paths.latest_clean_countries_dir(tmp_path)
    assert folder == result["path"].parent
    assert result["manifest"] == folder / paths.MANIFEST_NAME
    manifest = manifests.read_manifest(folder)
    assert (manifest.kind, manifest.path) == ("clean_countries", "clean/countries/20260102/")
    assert manifest.inputs == [  # the only inputs that are present
        "clean/quality/song_quarantine/20260101/",
        f"lyrics/BRA/songs/{SONGS_RUN}/",
        f"lyrics/ROU/songs/{SONGS_RUN}/",
    ]
    assert [(file["path"], file["rows"]) for file in manifest.files] == [
        ("countries.parquet", result["rows"])
    ]
    countries = result["counts"]["registry_countries"]
    assert manifest.counts == {"rows": result["rows"], "countries": countries, **result["counts"]}
    assert manifest.counts["eligible_songs"] == 702
    assert "democracy" in manifest.notes and "resources/" in manifest.notes
    assert (manifest.country_iso3, manifest.source, manifest.run_id, manifest.origin) == (None,) * 4


def test_the_inputs_of_a_build_are_the_files_that_it_read(tmp_path):
    write_songs(tmp_path)
    inputs = panel.default_inputs(tmp_path)
    no_raw_folder = sorted(name for name, path in inputs.items() if path is None)
    files = panel.files_read(tmp_path, inputs, [*no_raw_folder, "currency_monthly"])
    assert files == sorted(set(files)) and f"lyrics/BRA/songs/{SONGS_RUN}/" in files
    assert not any(file.startswith("/") or ":" in file for file in files)
    # Fertility is a folder: the build reads each of its files.
    folder = inputs["fertility"].relative_to(tmp_path).as_posix()
    assert {file for file in files if file.startswith(f"{folder}/")} == {
        f"{folder}/{name}" for name in fertility.FILE_COLUMNS
    }
    # The currency table needs both files. One is absent, so the other was not read.
    assert not any(file.endswith(inputs["currency_episodes"].name) for file in files)
    assert any(file.endswith(inputs["sovereign_default"].name) for file in files)


def test_the_command_reports_what_it_wrote(monkeypatch, tmp_path):
    monkeypatch.setenv("SONGS_DATA_ROOT", str(tmp_path))
    write_songs(tmp_path)
    result = CliRunner().invoke(app, ["panel", "countries", "--allow-missing"])
    assert result.exit_code == 0, result.output
    assert "wrote" in result.output and "absent inputs" in result.output
    assert paths.MANIFEST_NAME in result.output


@pytest.mark.needs_data
def test_the_real_inputs_join_to_a_full_grid():
    data = data_root()
    tables, _, counts = panel.read_tables(panel.default_inputs(data), data, allow_missing=True)
    result = panel.join_panel(tables, "x")
    assert len(result) == len(tables["registry"]) * 127
    assert counts["countries_with_songs"] > 0
