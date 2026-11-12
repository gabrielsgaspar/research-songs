"""Fertility: annual national measures from the Human Fertility Database."""

from pathlib import Path

import pandas as pd

CONCEPT = "Fertility"
# The database has its own codes for three national series.
NATIONAL_CODES = {"DEUTNP": "DEU", "FRATNP": "FRA", "GBR_NP": "GBR"}
# Parts of a country. The national series already counts them.
EXCLUDED_AREAS = {"DEUTE", "DEUTW", "GBRTENW", "GBR_NIR", "GBR_SCO"}
# File name -> source column -> panel column. The order is the column order of the panel.
FILE_COLUMNS = {
    "totbirthsRR.txt": {"Total": "hfd_total_live_births"},
    "cbrRR.txt": {"CBR": "hfd_crude_birth_rate"},
    "tfrRR.txt": {
        "TFR": "hfd_total_fertility_rate",
        "TFR40": "hfd_total_fertility_rate_by_age_40",
    },
    "adjtfrRR.txt": {"adjTFR": "hfd_tempo_adjusted_total_fertility_rate"},
    "mabRR.txt": {"MAB": "hfd_mean_age_at_birth", "MAB40": "hfd_mean_age_at_birth_by_age_40"},
    "mabRRbo.txt": {"MAB1": "hfd_mean_age_at_first_birth"},
    "sdmabRR.txt": {
        "sdMAB": "hfd_age_at_birth_standard_deviation",
        "sdMAB40": "hfd_age_at_birth_by_age_40_standard_deviation",
    },
    "patfr.txt": {"PATFR": "hfd_parity_age_adjusted_total_fertility_rate"},
    "pmab.txt": {"TMAB": "hfd_table_mean_age_at_birth"},
    "patfrc.txt": {"PATFR": "hfd_census_parity_age_adjusted_total_fertility_rate"},
    "pmabc.txt": {"TMAB": "hfd_census_table_mean_age_at_birth"},
}
COLUMNS = [column for rename in FILE_COLUMNS.values() for column in rename.values()]
# Lowest and highest value that can be true, by a word in the column name.
RANGES = {"fertility_rate": (0, 10), "mean_age": (10, 60), "standard_deviation": (0, 20)}


def load_fertility(folder: Path) -> pd.DataFrame:
    """Read the 11 source files of a download and return one row per country and year."""
    result = None
    for file_name, rename in FILE_COLUMNS.items():
        # Each file has two title lines, then columns separated by spaces. A dot means missing.
        frame = pd.read_csv(
            folder / file_name, sep=r"\s+", skiprows=2, na_values=".", encoding="utf-8"
        )
        frame = frame[~frame["Code"].isin(EXCLUDED_AREAS)]
        frame = frame.assign(country_iso3=frame["Code"].replace(NATIONAL_CODES))
        frame = frame[["country_iso3", "Year", *rename]].rename(columns={"Year": "year", **rename})
        if frame.duplicated(["country_iso3", "year"]).any():
            raise ValueError(f"duplicate country-year rows in {file_name}")
        result = (
            frame
            if result is None
            else result.merge(frame, on=["country_iso3", "year"], how="outer", validate="1:1")
        )
    result["year"] = result["year"].astype("int64")
    for column in COLUMNS:
        low, high = next(
            (limits for word, limits in RANGES.items() if word in column), (0, float("inf"))
        )
        if ((result[column] < low) | (result[column] > high)).any():
            raise ValueError(f"{column} has a value outside {low} to {high}")
    return result.sort_values(["country_iso3", "year"]).reset_index(drop=True)
