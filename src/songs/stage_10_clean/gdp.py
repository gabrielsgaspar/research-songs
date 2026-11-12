"""GDP per capita: the Maddison Project Database file from Our World in Data."""

from pathlib import Path

import pandas as pd

CONCEPT = "GDP per capita"
FILE_NAME = "gdp-per-capita-maddison-project-database.csv"
VALUE_COLUMN = "GDP per capita"
MIN_COUNTRIES = 150
MIN_LAST_YEAR = 2020


def clean_gdp(frame: pd.DataFrame) -> pd.DataFrame:
    """Return `country_iso3`, `year`, `gdp_per_capita` for the country rows of the source."""
    missing = sorted({"Code", "Year", VALUE_COLUMN} - set(frame.columns))
    if missing:
        raise ValueError(f"the GDP source lacks columns: {missing}")
    # Aggregates (World, regions) have no code or a code that is not three letters.
    rows = frame[frame["Code"].astype(str).str.fullmatch(r"[A-Z]{3}")]
    gdp = pd.DataFrame(
        {
            "country_iso3": rows["Code"].astype(str),
            "year": rows["Year"].astype("int64"),
            "gdp_per_capita": pd.to_numeric(rows[VALUE_COLUMN], errors="coerce"),
        }
    ).dropna(subset=["gdp_per_capita"])
    if gdp.duplicated(["country_iso3", "year"]).any():
        raise ValueError("the GDP source has duplicate country-year rows")
    if not (gdp["gdp_per_capita"] > 0).all():
        raise ValueError("the GDP source has a value that is not positive")
    return gdp.sort_values(["country_iso3", "year"]).reset_index(drop=True)


def load_gdp(path: Path) -> pd.DataFrame:
    """Read the raw file, clean it, and refuse a file that is too short to be the full one."""
    gdp = clean_gdp(pd.read_csv(path, encoding="utf-8"))
    countries = gdp["country_iso3"].nunique()
    if countries < MIN_COUNTRIES:
        raise ValueError(f"expected at least {MIN_COUNTRIES} countries, found {countries}")
    if gdp["year"].max() < MIN_LAST_YEAR:
        raise ValueError(f"the GDP source ends before {MIN_LAST_YEAR}")
    return gdp
