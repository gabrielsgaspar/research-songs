"""Crises: four sources, one table with a row per country, year and crisis family.

Each row says whether the country was in a crisis that year (`state`), whether a
crisis started (`onset`), and how many started (`event_count`). A row exists only
where the source covers the country and the year, so 0 means "covered, no crisis".
"""

import csv
import re
from pathlib import Path

import pandas as pd

from songs.common.paths import resolve_project_root

KEYS = ["country_iso3", "year"]

BANKING_CONCEPT = "Banking crises"
BANKING_FILE_NAME = "SYSTEMIC_BANKING_CRISES_DATABASE_2026.xlsx"
BANKING_SHEET = "Crisis Resolution and Outcomes"
BANKING_YEARS = range(1970, 2026)

DEFAULT_CONCEPT = "Sovereign defaults"
DEFAULT_FILE_NAME = "BoC-BoE-Database-2024.xlsx"
DEFAULT_SHEET = "2024 in progress"

CURRENCY_CONCEPT = "Currency crises"
CURRENCY_EPISODES_FILE_NAME = "large_depreciations_episodes.dta"
CURRENCY_MONTHLY_FILE_NAME = "large_depreciations_monthly.dta"
CURRENCY_YEARS = range(1971, 2025)

# The episodes of the Hanke and Krus table. An entity with no code is a historical
# state or a region with no country of today, and it marks no country.
HYPERINFLATION_FILE = Path("resources") / "hyperinflation_episodes.csv"
HYPERINFLATION_YEARS = range(1795, 2013)

# Country names as the crisis sources spell them, where the registry spells them differently.
NAMES_FILE = Path("resources") / "crisis_country_names.csv"


def name_lookup(registry: pd.DataFrame) -> dict[str, str]:
    """Return lower-case country name -> ISO3: registry names, then the tracked spellings.

    A tracked spelling with an empty code is a known entity that is not in the registry.
    """
    lookup = {
        name.casefold(): code
        for code, name in zip(registry["country_iso3"], registry["country_name"], strict=True)
    }
    with (resolve_project_root() / NAMES_FILE).open(encoding="utf-8", newline="") as handle:
        lookup.update(
            {row["name"].casefold(): row["country_iso3"] for row in csv.DictReader(handle)}
        )
    return lookup


def to_iso3(names: pd.Series, lookup: dict[str, str]) -> pd.Series:
    """Turn source country names into ISO3 codes. Refuse a name that the lookup does not know."""
    # The sources mark footnotes with a number and a slash, or with a dagger or section sign.
    cleaned = names.astype(str).str.replace(r"\s*\d+/\s*$|[†§]", "", regex=True).str.strip()
    unknown = sorted({name for name in cleaned if name.casefold() not in lookup})
    if unknown:
        raise ValueError(f"country names not in {NAMES_FILE.as_posix()}: {unknown}")
    return cleaned.map(lambda name: lookup[name.casefold()] or None)


def _grid(countries: set[str], years: range, family: str) -> pd.DataFrame:
    """Return one row of zeros for every country and year that a source covers."""
    index = pd.MultiIndex.from_product([sorted(countries), years], names=KEYS)
    return index.to_frame(index=False).assign(family=family, state=0, onset=0, event_count=0)


def episode_grid(
    episodes: pd.DataFrame, countries: set[str], years: range, family: str
) -> pd.DataFrame:
    """Mark episodes (`country_iso3`, `start_year`, `end_year`) on a grid of zeros."""
    grid = _grid(countries, years, family)
    for episode in episodes[episodes["country_iso3"].isin(countries)].itertuples():
        same_country = grid["country_iso3"].eq(episode.country_iso3)
        in_episode = grid["year"].between(episode.start_year, episode.end_year)
        start = same_country & grid["year"].eq(episode.start_year)
        grid.loc[same_country & in_episode, "state"] = 1
        grid.loc[start, "onset"] = 1
        grid.loc[start, "event_count"] += 1
    return grid


def load_banking(path: Path, countries: set[str], lookup: dict[str, str]) -> pd.DataFrame:
    """Banking crises from the Laeven and Valencia workbook. An episode with no end lasts 1 year."""
    events = pd.read_excel(path, sheet_name=BANKING_SHEET)
    events = events.rename(columns={events.columns[0]: "name"})
    events = events[events["name"].notna()]
    for column in ("Start", "End"):
        year = events[column].astype(str).str.extract(r"(\d{4})")[0]
        events[column] = pd.to_numeric(year, errors="coerce")
    events = events[events["Start"].notna()]
    episodes = pd.DataFrame(
        {
            "country_iso3": to_iso3(events["name"], lookup),
            "start_year": events["Start"].astype(int),
            "end_year": events["End"].fillna(events["Start"]).astype(int),
        }
    )
    return episode_grid(episodes, countries, BANKING_YEARS, "banking_crisis")


def load_sovereign_default(path: Path, lookup: dict[str, str]) -> pd.DataFrame:
    """Sovereign defaults from the Bank of Canada and Bank of England workbook.

    The sheet has one row per country and one column per year, with the debt in default.
    A country is in default in a year with debt above zero. An empty cell is not covered.
    """
    sheet = pd.read_excel(path, sheet_name=DEFAULT_SHEET, header=None)
    years = {
        column: int(match.group(0))
        for column, value in sheet.iloc[0].items()
        if (match := re.search(r"(19|20)\d{2}", str(value)))
    }
    # A country row has a number in the second column and a name in the third.
    rows = sheet[
        pd.to_numeric(sheet.iloc[:, 1], errors="coerce").notna() & sheet.iloc[:, 2].notna()
    ]
    records = []
    for code, (_, row) in zip(to_iso3(rows.iloc[:, 2], lookup), rows.iterrows(), strict=True):
        previous = None
        for column, year in years.items():
            value = pd.to_numeric(row[column], errors="coerce")
            if pd.isna(code) or pd.isna(value):
                previous = None
                continue
            state = int(value > 0)
            onset = int(state == 1 and previous != 1)
            records.append((code, year, "sovereign_default", state, onset, onset))
            previous = state
    grid = pd.DataFrame(records, columns=[*KEYS, "family", "state", "onset", "event_count"])
    # Two source rows can share one code. The country is in default when either row is.
    return grid.groupby([*KEYS, "family"], as_index=False).max()


def load_hyperinflation(countries: set[str]) -> pd.DataFrame:
    """Hyperinflations from the tracked table of episodes."""
    episodes = pd.read_csv(resolve_project_root() / HYPERINFLATION_FILE, encoding="utf-8")
    episodes = episodes.dropna(subset=["country_iso3"])
    return episode_grid(episodes, countries, HYPERINFLATION_YEARS, "hyperinflation")


def load_currency(episodes_path: Path, monthly_path: Path, countries: set[str]) -> pd.DataFrame:
    """Currency crises: the large depreciations of Culiuc and Park.

    The monthly file says which months are in an episode; a year is in crisis when one of
    its months is. The episodes file gives the start year of each episode. Only countries
    in the monthly file are covered.
    """
    monthly = pd.read_stata(monthly_path, columns=["wbcode", "t", "episode"])
    monthly = monthly.assign(
        country_iso3=monthly["wbcode"].astype(str).str.upper(),
        year=pd.to_datetime(monthly["t"]).dt.year,
    )
    state = monthly.groupby(KEYS, as_index=False)["episode"].max()
    episodes = pd.read_stata(episodes_path, columns=["wbcode", "episodeYr"]).dropna()
    starts = pd.DataFrame(
        {
            "country_iso3": episodes["wbcode"].astype(str).str.upper(),
            "year": episodes["episodeYr"].astype(int),
        }
    )
    starts = starts.groupby(KEYS, as_index=False).size()
    grid = _grid(set(monthly["country_iso3"]) & countries, CURRENCY_YEARS, "currency_crisis")
    grid = grid.merge(state, on=KEYS, how="left").merge(starts, on=KEYS, how="left")
    grid["state"] = (grid.pop("episode") > 0).astype(int)
    grid["event_count"] = grid.pop("size").fillna(0).astype(int)
    grid["onset"] = (grid["event_count"] > 0).astype(int)
    return grid


def combine(parts: list[pd.DataFrame]) -> pd.DataFrame:
    """Stack the families and mark each onset that is the only one in its country and year."""
    crises = pd.concat(parts, ignore_index=True)
    if crises.duplicated([*KEYS, "family"]).any():
        raise ValueError("the crisis table has duplicate country-year-family rows")
    onsets = crises.groupby(KEYS)["onset"].transform("sum")
    return crises.assign(clean_event=crises["onset"].eq(1) & onsets.eq(1))
