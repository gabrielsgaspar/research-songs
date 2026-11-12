"""Democracy: the published series of Acemoglu, Naidu, Restrepo and Robinson (2019)."""

from pathlib import Path

import pandas as pd

CONCEPT = "Democracy"
FILE_NAME = "DDCGdata_final.dta"
FIRST_YEAR = 1960
LAST_YEAR = 2010  # the published series ends here; the project does not extend it


def clean_democracy(frame: pd.DataFrame) -> pd.DataFrame:
    """Return `country_iso3`, `year`, `anrr_democracy` (0 or 1) for the rows with a value.

    The source uses World Bank codes. A few are not ISO3 codes (ROM, ZAR, ...);
    the panel builder gives those their ISO3 codes.
    """
    missing = sorted({"wbcode", "year", "dem"} - set(frame.columns))
    if missing:
        raise ValueError(f"the democracy source lacks columns: {missing}")
    rows = frame.dropna(subset=["dem"])
    democracy = pd.DataFrame(
        {
            "country_iso3": rows["wbcode"].astype(str).str.strip().str.upper(),
            "year": rows["year"].astype("int64"),
            "anrr_democracy": rows["dem"].astype("float64"),
        }
    )
    if democracy.duplicated(["country_iso3", "year"]).any():
        raise ValueError("the democracy source has duplicate country-year rows")
    if not democracy["anrr_democracy"].isin([0.0, 1.0]).all():
        raise ValueError("the democracy source has a value that is not 0 or 1")
    if not democracy["year"].between(FIRST_YEAR, LAST_YEAR).all():
        raise ValueError(f"the democracy source has a year outside {FIRST_YEAR} to {LAST_YEAR}")
    return democracy.sort_values(["country_iso3", "year"]).reset_index(drop=True)


def load_democracy(path: Path) -> pd.DataFrame:
    """Read the replication file and clean it."""
    return clean_democracy(pd.read_stata(path, columns=["wbcode", "year", "dem"]))
