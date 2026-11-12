"""The country-year panel: one row per country of the registry and year, 1900 to 2026.

`build` reads every input, joins them, and writes `countries.parquet` and its manifest
to a new dated folder, `clean/countries/<YYYYMMDD>/`. It never writes over a panel that
exists. The manifest names every input file that the build read
(`docs/standards/data_layout.md`).

Sources that are not lyrics are read from their raw files, at the paths in
`resources/data_sources.toml`. Four inputs come from the lyrics corpus and are
read as clean files that another stage writes: the country registry, the analysis
sample, the song counts and the artist counts. The populism series is also read
as a clean file, because its raw file is not in the data folder yet.
"""

from collections.abc import Callable
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd

from songs.common import manifests, paths
from songs.common.data_sources import canonical
from songs.common.years import MAX_SONG_YEAR, MIN_SONG_YEAR
from songs.stage_10_clean import (
    crises,
    democracy,
    fertility,
    gdp,
    labor,
    population,
    world_bank_countries,
)

FAMILIES = ("banking_crisis", "currency_crisis", "hyperinflation", "sovereign_default")
CRISIS_MEASURES = {
    "state": "max(state)",
    "onset": "max(onset)",
    "event_count": "max(event_count)",
    "clean_event": "bool_or(clean_event)",
}
CRISIS_COLUMNS = [f"{family}_{measure}" for family in FAMILIES for measure in CRISIS_MEASURES]

# Table -> columns and types. The order of the value columns is their order in the panel.
SCHEMAS = {
    "registry": "country_iso3 VARCHAR, country_name VARCHAR, in_wvs BOOLEAN, in_evs BOOLEAN",
    "regions": "country_iso3 VARCHAR, region_name VARCHAR",
    "income_groups": "country_iso3 VARCHAR, world_bank_income_group VARCHAR",
    "sample": "country_iso3 VARCHAR, analysis_tier VARCHAR, analysis_included BOOLEAN, "
    "analysis_exclusion_reason VARCHAR",
    "gdp": "country_iso3 VARCHAR, year INTEGER, gdp_per_capita DOUBLE",
    "population": "country_iso3 VARCHAR, year INTEGER, population_total DOUBLE, "
    "population_is_projected BOOLEAN, log_population DOUBLE",
    "labor": f"country_iso3 VARCHAR, year INTEGER, {labor.COLUMN} DOUBLE",
    "fertility": "country_iso3 VARCHAR, year INTEGER, "
    + ", ".join(f"{column} DOUBLE" for column in fertility.COLUMNS),
    "democracy": "country_iso3 VARCHAR, year INTEGER, anrr_democracy DOUBLE",
    "songs": "country_iso3 VARCHAR, year INTEGER, num_songs BIGINT",
    "artists": "country_iso3 VARCHAR, year INTEGER, num_artists BIGINT, "
    "discogs_artists_available BIGINT, discogs_dump_date VARCHAR, artist_count_method VARCHAR",
    "populism": "country_iso3 VARCHAR, year INTEGER, populist BIGINT, populism_start TINYINT, "
    "independent BIGINT",
    "crises": "country_iso3 VARCHAR, year INTEGER, family VARCHAR, state BIGINT, onset BIGINT, "
    "event_count BIGINT, clean_event BOOLEAN",
}
YEARLY = ["gdp", "population", "labor", "fertility", "democracy", "songs", "artists", "populism"]
COUNTRY_COLUMNS = (
    "country_iso3",
    "country_name",
    "year",
    "region_name",
    "world_bank_income_group",
    "analysis_tier",
    "analysis_included",
    "analysis_exclusion_reason",
    "in_wvs",
    "in_evs",
    "gdp_per_capita",
    "gdp_source_name",
    "population_total",
    "population_is_projected",
    "log_population",
    labor.COLUMN,
    *fertility.COLUMNS,
    "anrr_democracy",
    "num_songs",
    "num_artists",
    "discogs_artists_available",
    "discogs_dump_date",
    "artist_count_method",
    "populist",
    "populism_start",
    "independent",
    *CRISIS_COLUMNS,
    "any_crisis_state",
    "any_crisis_onset",
)

# Codes that some sources still use for a country that has an ISO3 code.
# A row with an old code takes the ISO3 code, and the old code gets no rows of its own.
OLD_CODES = {
    "NAU": "NRU",
    "ROM": "ROU",
    "SER": "SRB",
    "SIN": "SGP",
    "UAE": "ARE",
    "ZAR": "COD",
}

# Clean files that this module does not build: (input name, path under the data folder).
CLEAN_FILES = {
    "registry": "extraction/countries.parquet",
    "sample": "clean/analysis_sample.parquet",
    "songs": "clean/country_year_song_counts.parquet",
    "artists": "clean/country_year_artist_counts.parquet",
    "populism": "clean/populism.parquet",
}
# Raw files: (input name, concept in the data source file, file name in its raw folder).
RAW_FILES = {
    "gdp": (gdp.CONCEPT, gdp.FILE_NAME),
    "population": (population.CONCEPT, population.FILE_NAME),
    "labor": (labor.CONCEPT, labor.FILE_NAME),
    "fertility": (fertility.CONCEPT, ""),
    "democracy": (democracy.CONCEPT, democracy.FILE_NAME),
    "income_groups": (world_bank_countries.INCOME_CONCEPT, world_bank_countries.INCOME_FILE_NAME),
    "regions": (world_bank_countries.REGION_CONCEPT, world_bank_countries.REGION_FILE_NAME),
    "banking": (crises.BANKING_CONCEPT, crises.BANKING_FILE_NAME),
    "sovereign_default": (crises.DEFAULT_CONCEPT, crises.DEFAULT_FILE_NAME),
    "currency_episodes": (crises.CURRENCY_CONCEPT, crises.CURRENCY_EPISODES_FILE_NAME),
    "currency_monthly": (crises.CURRENCY_CONCEPT, crises.CURRENCY_MONTHLY_FILE_NAME),
}
# The currency table is read only when both of its files are present.
CURRENCY_INPUTS = {"currency_episodes", "currency_monthly"}
# How each clean file names the columns of its table: panel name -> expression on the file.
CLEAN_SELECT = {
    "sample": {
        "analysis_tier": "tier",
        "analysis_included": "included",
        "analysis_exclusion_reason": "exclusion_reason",
    },
    "songs": {},
    "artists": {"num_artists": "scraped_artists", "artist_count_method": "count_method"},
    "populism": {"country_iso3": "iso3", "populism_start": "pop_start"},
}


def default_inputs(data: Path) -> dict[str, Path | None]:
    """Return where each input is. None means the data source file names no raw folder."""
    inputs: dict[str, Path | None] = {name: data / path for name, path in CLEAN_FILES.items()}
    for name, (concept, file_name) in RAW_FILES.items():
        raw_path = canonical(concept).raw_path
        inputs[name] = data / raw_path / file_name if raw_path else None
    return inputs


def _columns(table: str) -> list[str]:
    return [part.split()[0] for part in SCHEMAS[table].split(", ")]


def _read_clean(name: str, path: Path) -> pd.DataFrame:
    """Read a clean Parquet file with the column names of its table."""
    rename = CLEAN_SELECT[name]
    select = ", ".join(f"{rename.get(column, column)} AS {column}" for column in _columns(name))
    return duckdb.sql(f"SELECT {select} FROM read_parquet('{path.as_posix()}')").df()


def _read_registry(path: Path) -> tuple[pd.DataFrame, list[str]]:
    """Read the registry. Return it with the names of the survey columns that it lacks."""
    registry = duckdb.sql(
        "SELECT * RENAME (country AS country_iso3) "
        f"FROM read_parquet('{path.as_posix()}') ORDER BY country"
    ).df()
    registry["country_iso3"] = registry["country_iso3"].str.strip().str.upper()
    registry = registry[registry["country_iso3"].str.fullmatch(r"[A-Z]{3}")]
    registry = registry[~registry["country_iso3"].isin(OLD_CODES)]
    if registry["country_iso3"].duplicated().any():
        raise ValueError("the registry has duplicate country codes")
    absent = [column for column in ("in_wvs", "in_evs") if column not in registry.columns]
    return registry.assign(**dict.fromkeys(absent)), [f"registry.{column}" for column in absent]


def read_tables(
    inputs: dict[str, Path | None], *, allow_missing: bool = False
) -> tuple[dict[str, pd.DataFrame], list[str]]:
    """Read every input. Return the tables and the names of the inputs that are absent.

    An absent input stops the build, unless `allow_missing` is set. Then its columns
    are empty in the panel, and the caller must report the names.
    """
    absent = sorted(name for name, path in inputs.items() if path is None or not path.exists())
    if "registry" in absent:
        raise FileNotFoundError(f"the country registry is absent: {inputs['registry']}")
    registry, no_survey = _read_registry(inputs["registry"])
    absent += no_survey
    if absent and not allow_missing:
        raise FileNotFoundError(f"inputs of the country panel are absent: {absent}")
    countries = set(registry["country_iso3"])
    lookup = crises.name_lookup(registry)
    readers: dict[str, Callable[[], pd.DataFrame]] = {
        "regions": lambda: world_bank_countries.load_regions(inputs["regions"]),
        "income_groups": lambda: world_bank_countries.load_income_groups(inputs["income_groups"]),
        "gdp": lambda: gdp.load_gdp(inputs["gdp"]),
        "population": lambda: population.load_population(inputs["population"]),
        "labor": lambda: labor.load_female_labor_force(inputs["labor"]),
        "fertility": lambda: fertility.load_fertility(inputs["fertility"]),
        "democracy": lambda: democracy.load_democracy(inputs["democracy"]),
        **{name: lambda name=name: _read_clean(name, inputs[name]) for name in CLEAN_SELECT},
    }
    tables = {"registry": registry}
    tables |= {name: read() for name, read in readers.items() if name not in absent}
    parts = [crises.load_hyperinflation(countries)]  # the episodes are a tracked file
    if "banking" not in absent:
        parts.append(crises.load_banking(inputs["banking"], countries, lookup))
    if "sovereign_default" not in absent:
        parts.append(crises.load_sovereign_default(inputs["sovereign_default"], lookup))
    if not CURRENCY_INPUTS & set(absent):
        parts.append(
            crises.load_currency(inputs["currency_episodes"], inputs["currency_monthly"], countries)
        )
    tables["crises"] = crises.combine(parts)
    return tables, absent


def join_panel(tables: dict[str, pd.DataFrame], gdp_source_name: str) -> duckdb.DuckDBPyRelation:
    """Join the tables into the panel. A table that is not given leaves its columns empty."""
    connection = duckdb.connect()
    old_codes = pd.DataFrame(OLD_CODES.items(), columns=["old", "iso3"])
    connection.register("old_codes", old_codes)
    for name, schema in SCHEMAS.items():
        connection.execute(f"CREATE TABLE {name} ({schema})")
        if name not in tables:
            continue
        connection.register("frame", tables[name])
        connection.execute(
            f"INSERT INTO {name} BY NAME SELECT {', '.join(_columns(name)[1:])}, "
            "coalesce(old_codes.iso3, upper(frame.country_iso3)) AS country_iso3 "
            "FROM frame LEFT JOIN old_codes ON upper(frame.country_iso3) = old_codes.old"
        )
        keys = (
            "country_iso3"
            + (", year" if "year" in schema else "")
            + (", family" if name == "crises" else "")
        )
        if connection.execute(
            f"SELECT 1 FROM {name} GROUP BY {keys} HAVING count(*) > 1"
        ).fetchall():
            raise ValueError(f"the {name} table has more than one row for one key ({keys})")
    crisis_wide = ", ".join(
        f"{aggregate} FILTER (WHERE family = '{family}') AS {family}_{measure}"
        for family in FAMILIES
        for measure, aggregate in CRISIS_MEASURES.items()
    )
    yearly_columns = ", ".join(f"{name}.* EXCLUDE (country_iso3, year)" for name in YEARLY[1:])
    yearly_joins = " ".join(f"LEFT JOIN {name} USING (country_iso3, year)" for name in YEARLY)

    def any_crisis(measure: str) -> str:
        # Empty when no family covers the row; otherwise 1 when any family has a 1.
        values = ", ".join(f"coalesce({family}_{measure}, 0)" for family in FAMILIES)
        some = ", ".join(f"{family}_{measure}" for family in FAMILIES)
        return f"CASE WHEN coalesce({some}) IS NULL THEN NULL ELSE greatest({values}) END"

    panel = connection.sql(
        f"""
        WITH crisis_wide AS (
            SELECT country_iso3, year, {crisis_wide} FROM crises GROUP BY country_iso3, year
        )
        SELECT
            country_iso3, registry.country_name, years.year, region_name,
            world_bank_income_group, sample.* EXCLUDE (country_iso3), in_wvs, in_evs,
            gdp_per_capita,
            CASE WHEN gdp_per_capita IS NOT NULL THEN $gdp_source_name END AS gdp_source_name,
            {yearly_columns},
            crisis_wide.* EXCLUDE (country_iso3, year),
            {any_crisis("state")} AS any_crisis_state,
            {any_crisis("onset")} AS any_crisis_onset
        FROM registry
        CROSS JOIN (
            SELECT CAST(year AS INTEGER) AS year
            FROM range({MIN_SONG_YEAR}, {MAX_SONG_YEAR + 1}) AS years(year)
        ) AS years
        LEFT JOIN regions USING (country_iso3)
        LEFT JOIN income_groups USING (country_iso3)
        LEFT JOIN sample USING (country_iso3)
        {yearly_joins}
        LEFT JOIN crisis_wide USING (country_iso3, year)
        ORDER BY country_iso3, year
        """,
        params={"gdp_source_name": gdp_source_name},
    )
    if tuple(panel.columns) != COUNTRY_COLUMNS:
        raise ValueError(f"the panel columns differ from the contract: {panel.columns}")
    return panel


def codes_outside_registry(tables: dict[str, pd.DataFrame]) -> dict[str, list[str]]:
    """Return, per table, the country codes that the registry does not have. They get no rows."""
    known = set(tables["registry"]["country_iso3"])
    outside = {}
    for name, table in tables.items():
        codes = {OLD_CODES.get(code, code) for code in table["country_iso3"].str.upper()} - known
        if codes:
            outside[name] = sorted(codes)
    return outside


def files_read(data: Path, inputs: dict[str, Path | None], absent: list[str]) -> list[str]:
    """Return the input files that a build read, as paths relative to the data folder.

    An absent input is not read. The currency table needs both of its files, so when
    one is absent the other is not read. The fertility input is a folder of files.
    """
    skipped = set(absent)
    if skipped & CURRENCY_INPUTS:
        skipped |= CURRENCY_INPUTS
    files = []
    for name, path in inputs.items():
        if name in skipped:
            continue
        files += [path / file for file in fertility.FILE_COLUMNS] if name == "fertility" else [path]
    return sorted({paths.data_relative(data, file) for file in files})


def build(data: Path, *, allow_missing: bool = False, today: date | None = None) -> dict:
    """Build the panel and write it, with its manifest, to `clean/countries/<YYYYMMDD>/`.

    The manifest names every input file that the build read. The folder is the
    version of the panel; a correction is a build on a later day.
    """
    folder = paths.clean_countries_dir(data, today or date.today())
    if folder.exists():
        raise FileExistsError(
            f"{folder} exists; a panel is never written over. "
            f"A folder without {paths.MANIFEST_NAME} is a build that did not end."
        )
    inputs = default_inputs(data)
    tables, absent = read_tables(inputs, allow_missing=allow_missing)
    panel = join_panel(tables, canonical(gdp.CONCEPT).source)
    folder.mkdir(parents=True)
    out = folder / manifests.COUNTRIES_FILE
    panel.write_parquet(str(out), compression="zstd")
    notes = (
        "The tracked files in resources/ that the build reads are inputs too; "
        "code_commit names their version."
    )
    if absent:
        notes += f" Absent inputs, their columns are empty: {', '.join(absent)}."
    manifests.write_manifest(
        data,
        folder,
        "clean_countries",
        inputs=files_read(data, inputs, absent),
        counts={"rows": len(panel), "countries": len(tables["registry"])},
        notes=notes,
    )
    return {
        "path": out,
        "manifest": folder / paths.MANIFEST_NAME,
        "rows": len(panel),
        "absent_inputs": absent,
        "codes_outside_registry": codes_outside_registry(tables),
    }
