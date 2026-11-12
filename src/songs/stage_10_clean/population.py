"""Population: United Nations World Population Prospects 2024, medium variant."""

from pathlib import Path

import numpy as np
import pandas as pd

CONCEPT = "Population"
FILE_NAME = "WPP2024_Demographic_Indicators_Medium.csv.gz"
SOURCE_COLUMNS = ["ISO3_code", "LocTypeName", "Variant", "Time", "TPopulation1July"]
MIN_YEAR = 1950
MAX_YEAR = 2100
FIRST_PROJECTED_YEAR = 2024  # estimates end in 2023
EXPECTED_COUNTRIES = 237


def clean_population(frame: pd.DataFrame) -> pd.DataFrame:
    """Return population in persons, the projection flag and the log, by country and year."""
    missing = sorted(set(SOURCE_COLUMNS) - set(frame.columns))
    if missing:
        raise ValueError(f"the population source lacks columns: {missing}")
    rows = frame[
        frame["LocTypeName"].eq("Country/Area")
        & frame["Variant"].eq("Medium")
        & frame["Time"].between(MIN_YEAR, MAX_YEAR)
    ]
    # The source reports thousands of persons.
    total = pd.to_numeric(rows["TPopulation1July"], errors="raise").astype("float64") * 1000.0
    year = pd.to_numeric(rows["Time"], errors="raise").astype("int64")
    population = pd.DataFrame(
        {
            "country_iso3": rows["ISO3_code"].astype(str).str.upper(),
            "year": year,
            "population_total": total,
            "population_is_projected": year >= FIRST_PROJECTED_YEAR,
            "log_population": np.log(total),
        }
    )
    if population.duplicated(["country_iso3", "year"]).any():
        raise ValueError("the population source has duplicate country-year rows")
    if not population["country_iso3"].str.fullmatch(r"[A-Z]{3}").all():
        raise ValueError("the population source has a code that is not three letters")
    if not (population["population_total"] > 0).all():
        raise ValueError("the population source has a value that is missing or not positive")
    return population.sort_values(["country_iso3", "year"]).reset_index(drop=True)


def load_population(path: Path) -> pd.DataFrame:
    """Read the raw file, clean it, and refuse a file that is not the full 2024 edition."""
    population = clean_population(pd.read_csv(path, usecols=SOURCE_COLUMNS, low_memory=False))
    countries = population["country_iso3"].nunique()
    expected_rows = EXPECTED_COUNTRIES * (MAX_YEAR - MIN_YEAR + 1)
    if countries != EXPECTED_COUNTRIES or len(population) != expected_rows:
        raise ValueError(
            f"expected {EXPECTED_COUNTRIES} countries and {expected_rows} rows, "
            f"found {countries} and {len(population)}"
        )
    return population
