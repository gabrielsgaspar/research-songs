"""World Bank country classifications: income group and region, one row per country."""

import json
from pathlib import Path

import pandas as pd

INCOME_CONCEPT = "Income group"
INCOME_FILE_NAME = "world_bank_income_classification_fy2027.xlsx"
INCOME_SHEET = "List of economies"
INCOME_GROUPS = {"Low income", "Lower middle income", "Upper middle income", "High income"}
# The World Bank lists Guernsey and Jersey as one economy, the Channel Islands.
INCOME_SAME_AS = {"GGY": "CHI", "JEY": "CHI"}

REGION_CONCEPT = "World region"
REGION_FILE_NAME = "countries.json"
REGION_SHORT_NAMES = {
    "Middle East, North Africa, Afghanistan & Pakistan": "Middle East & North Africa"
}
# The World Bank list has no row for these economies and historical states.
# Each one gets the World Bank region of its place on the map.
REGION_OVERRIDES = {
    "AIA": "Latin America & Caribbean",
    "CSK": "Europe & Central Asia",
    "DDR": "Europe & Central Asia",
    "ESH": "Middle East & North Africa",
    "GGY": "Europe & Central Asia",
    "GLP": "Latin America & Caribbean",
    "JEY": "Europe & Central Asia",
    "MTQ": "Latin America & Caribbean",
    "SUN": "Europe & Central Asia",
    "TWN": "East Asia & Pacific",
    "YUG": "Europe & Central Asia",
}


def load_income_groups(path: Path) -> pd.DataFrame:
    """Return `country_iso3`, `world_bank_income_group` from the classification workbook."""
    sheet = pd.read_excel(path, sheet_name=INCOME_SHEET)
    missing = sorted({"Code", "Income group"} - set(sheet.columns))
    if missing:
        raise ValueError(f"the income workbook lacks columns: {missing}")
    rows = sheet.dropna(subset=["Code", "Income group"])
    groups = pd.DataFrame(
        {
            "country_iso3": rows["Code"].astype(str).str.strip().str.upper(),
            "world_bank_income_group": rows["Income group"].astype(str).str.strip(),
        }
    )
    unknown = sorted(set(groups["world_bank_income_group"]) - INCOME_GROUPS)
    if unknown:
        raise ValueError(f"the income workbook has unknown groups: {unknown}")
    if groups["country_iso3"].duplicated().any():
        raise ValueError("the income workbook has duplicate codes")
    by_code = dict(zip(groups["country_iso3"], groups["world_bank_income_group"], strict=True))
    extra = [(code, by_code[same]) for code, same in INCOME_SAME_AS.items() if same in by_code]
    return pd.concat([groups, pd.DataFrame(extra, columns=groups.columns)], ignore_index=True)


def load_regions(path: Path) -> pd.DataFrame:
    """Return `country_iso3`, `region_name` from the stored World Bank country list."""
    pages = json.loads(path.read_text(encoding="utf-8"))["pages"]
    regions = {}
    for record in (record for page in pages for record in page["records"]):
        if record["region"]["id"] == "NA":  # an aggregate, not a country
            continue
        name = record["region"]["value"].strip()
        regions[record["id"].upper()] = REGION_SHORT_NAMES.get(name, name)
    regions.update(REGION_OVERRIDES)
    return pd.DataFrame(sorted(regions.items()), columns=["country_iso3", "region_name"])
