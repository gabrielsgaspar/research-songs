"""The Core and Total rule, on invented song counts."""

import pandas as pd
import pytest

from songs.stage_50_analysis import sample_tiers

INDEPENDENCE = pd.DataFrame(
    {
        "country_iso3": ["GHA", "CZE", "UKR", "AAA"],
        "independence_year": pd.array([1957, 1993, None, 2015], dtype="Int64"),
        "former_ussr_or_yugoslavia": [False, False, True, False],
    }
).set_index("country_iso3")


def counts(iso3: str, per_decade: dict[int, int]) -> pd.DataFrame:
    return pd.DataFrame(
        {"country_iso3": iso3, "decade": list(per_decade), "num_songs": list(per_decade.values())}
    )


def tier(frame: pd.DataFrame) -> pd.Series:
    return sample_tiers.assign(frame, INDEPENDENCE).set_index("country_iso3").iloc[0]


def every_decade(songs: int) -> dict[int, int]:
    return dict.fromkeys(sample_tiers.SAMPLE_DECADES, songs)


@pytest.mark.parametrize(("songs", "expected"), [(100, "Core"), (99, "Total")])
def test_the_minimum_is_100_songs_in_each_decade(songs, expected):
    row = tier(counts("BRA", {**every_decade(500), 1980: songs}))
    assert (row["analysis_tier"], row["min_decade_songs"]) == (expected, songs)
    assert (row["first_sample_decade"], row["analysis_included"]) == (1950, True)
    assert row["analysis_exclusion_reason"] == ""


def test_a_missing_decade_counts_as_zero_and_the_2020s_do_not_count():
    per_decade = {**every_decade(100), 2020: 0}
    del per_decade[1950]
    row = tier(counts("BRA", per_decade))
    assert (row["analysis_tier"], row["min_decade_songs"]) == ("Total", 0)
    assert tier(counts("BRA", {**every_decade(100), 2020: 0}))["analysis_tier"] == "Core"


def test_a_country_starts_with_the_first_full_decade_after_independence():
    late = {1950: 0, **{decade: 100 for decade in range(1960, 2020, 10)}}
    assert tuple(tier(counts("GHA", late))[["analysis_tier", "first_sample_decade"]]) == (
        "Core",
        1960,
    )
    recent = {1950: 0, 1990: 0, 2000: 100, 2010: 100}
    assert tuple(tier(counts("CZE", recent))[["analysis_tier", "first_sample_decade"]]) == (
        "Core",
        2000,
    )


def test_former_ussr_and_yugoslavia_countries_use_every_decade():
    row = tier(counts("UKR", {**every_decade(100), 1950: 0}))
    assert (row["analysis_tier"], row["first_sample_decade"]) == ("Total", 1950)


def test_a_country_with_no_required_decade_stays_total():
    row = tier(counts("AAA", every_decade(1000)))
    assert row["analysis_tier"] == "Total"
    assert pd.isna(row["first_sample_decade"]) and pd.isna(row["min_decade_songs"])


def test_the_row_counts_cover_every_country():
    frame = pd.concat([counts("BRA", every_decade(100)), counts("PRT", every_decade(5))])
    tiers = sample_tiers.assign(frame, INDEPENDENCE)
    assert sample_tiers.row_counts(tiers) == {
        "countries": 2,
        "tier_core": 1,
        "tier_total": 1,
        "left_out": 0,
    }


def test_two_rows_for_one_country_and_decade_are_refused():
    frame = pd.concat([counts("BRA", {1950: 1}), counts("BRA", {1950: 2})])
    with pytest.raises(ValueError, match="more than one row"):
        sample_tiers.assign(frame, INDEPENDENCE)


def test_the_tracked_file_holds_the_old_lists():
    independence = sample_tiers.load_independence()
    flagged = independence[independence["former_ussr_or_yugoslavia"]]
    years = independence["independence_year"].dropna()
    assert (len(independence), len(flagged), len(years)) == (84, 22, 62)
    assert {"RUS", "SRB", "XKX"} <= set(flagged.index)
    assert years.between(1951, 1993).all()
    assert sample_tiers.required_decades("PSE", independence) == [1990, 2000, 2010]
