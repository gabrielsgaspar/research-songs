"""Female labor force participation: one World Development Indicators download."""

from pathlib import Path

import pandas as pd

CONCEPT = "Female labor force participation"
FILE_NAME = "API_SL.TLF.CACT.FE.ZS_DS2_en_csv_v2_345713.csv"
INDICATOR = "SL.TLF.CACT.FE.ZS"
COLUMN = "female_labor_force_participation_rate"
HEADER_LINES = 4  # the download starts with four lines that are not the table


def clean_female_labor_force(frame: pd.DataFrame) -> pd.DataFrame:
    """Turn the wide table (one column per year) into country-year rows with a value."""
    missing = sorted({"Country Code", "Indicator Code"} - set(frame.columns))
    if missing:
        raise ValueError(f"the labor force source lacks columns: {missing}")
    years = [column for column in frame.columns if str(column).isdigit()]
    long = frame[frame["Indicator Code"].eq(INDICATOR)].melt(
        id_vars="Country Code", value_vars=years, var_name="year", value_name=COLUMN
    )
    labor = pd.DataFrame(
        {
            "country_iso3": long["Country Code"].astype(str).str.strip().str.upper(),
            "year": long["year"].astype("int64"),
            COLUMN: pd.to_numeric(long[COLUMN], errors="coerce"),
        }
    ).dropna(subset=[COLUMN])
    if labor.duplicated(["country_iso3", "year"]).any():
        raise ValueError("the labor force source has duplicate country-year rows")
    return labor.sort_values(["country_iso3", "year"]).reset_index(drop=True)


def load_female_labor_force(path: Path) -> pd.DataFrame:
    """Read the raw download and clean it."""
    return clean_female_labor_force(pd.read_csv(path, skiprows=HEADER_LINES, encoding="utf-8"))
