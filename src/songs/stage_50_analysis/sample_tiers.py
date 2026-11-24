"""The analysis sample: each country is Core or Total (old decisions 0132 and 0236).

Total holds every country with songs. A country is also Core when it has at least
`CORE_MIN_SONGS_PER_DECADE` eligible songs in each required full decade. The
required decades run from the 1950s through the 2010s. A country that became
independent after 1950 starts with the first full decade after its independence
year. Former USSR and Yugoslavia countries always start with the 1950s. A country
with no required decade stays Total.

The independence years and the USSR and Yugoslavia list are in
`resources/independence_years.csv` (source `independence_years_old_pipeline` in
`resources/data_sources.toml`). The caller counts the songs with
`eligible_songs.classify`; this module only applies the rule to the counts.
"""

from pathlib import Path

import pandas as pd

from songs.common.paths import resolve_project_root

INDEPENDENCE_FILE = Path("resources") / "independence_years.csv"
SAMPLE_DECADES = tuple(range(1950, 2020, 10))
CORE_MIN_SONGS_PER_DECADE = 100
CORE = "Core"
TOTAL = "Total"
COLUMNS = (
    "country_iso3",
    "analysis_tier",
    "analysis_included",
    "analysis_exclusion_reason",
    "first_sample_decade",
    "min_decade_songs",
)


def load_independence(root: Path | None = None) -> pd.DataFrame:
    """Return the tracked independence years and the USSR and Yugoslavia flag, by country."""
    path = resolve_project_root(root) / INDEPENDENCE_FILE
    frame = pd.read_csv(path, encoding="utf-8", dtype={"independence_year": "Int64"})
    if frame["country_iso3"].duplicated().any():
        raise ValueError(f"{INDEPENDENCE_FILE}: a country appears twice")
    return frame.set_index("country_iso3")


def required_decades(iso3: str, independence: pd.DataFrame) -> list[int]:
    """Return the full decades (start years) in which a country needs enough songs for Core."""
    if iso3 not in independence.index or independence.at[iso3, "former_ussr_or_yugoslavia"]:
        return list(SAMPLE_DECADES)
    year = independence.at[iso3, "independence_year"]
    if pd.isna(year):
        return list(SAMPLE_DECADES)
    first = (int(year) // 10) * 10 + 10
    return [decade for decade in SAMPLE_DECADES if decade >= first]


def assign(counts: pd.DataFrame, independence: pd.DataFrame | None = None) -> pd.DataFrame:
    """Return one row per country of `counts` with its tier and the numbers behind it.

    `counts` has `country_iso3`, `decade` (the start year, for example 1950) and
    `num_songs`: eligible songs by country and decade. A required decade with no row
    counts as 0 songs. Every country is included, so the exclusion reason is empty.
    """
    if counts.duplicated(["country_iso3", "decade"]).any():
        raise ValueError("counts has more than one row for a country and decade")
    independence = load_independence() if independence is None else independence
    by_decade = counts.groupby("country_iso3")[["decade", "num_songs"]].apply(
        lambda group: dict(zip(group["decade"], group["num_songs"], strict=True))
    )
    rows = []
    for iso3, songs in by_decade.items():
        decades = required_decades(iso3, independence)
        lowest = min((int(songs.get(decade, 0)) for decade in decades), default=None)
        core = lowest is not None and lowest >= CORE_MIN_SONGS_PER_DECADE
        rows.append(
            (iso3, CORE if core else TOTAL, True, "", decades[0] if decades else None, lowest)
        )
    frame = pd.DataFrame(rows, columns=list(COLUMNS))
    return frame.astype({"first_sample_decade": "Int64", "min_decade_songs": "Int64"})


def row_counts(tiers: pd.DataFrame) -> dict[str, int]:
    """Return the countries, the countries with each tier label, and the countries left out.

    The Total sample is every included country; the label `Total` marks those not in Core.
    """
    return {
        "countries": len(tiers),
        "tier_core": int((tiers["analysis_tier"] == CORE).sum()),
        "tier_total": int((tiers["analysis_tier"] == TOTAL).sum()),
        "left_out": int((~tiers["analysis_included"]).sum()),
    }
