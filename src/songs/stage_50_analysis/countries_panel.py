"""The country-year panel: one row per country of the registry and year, 1900 to 2026.

`build` reads every input, joins them, and writes `countries.parquet` and its manifest
to a new dated folder, `clean/countries/<YYYYMMDD>/`. It never writes over a panel that
exists. The manifest names every input file that the build read and counts the songs
in, out and left out (`docs/standards/data_layout.md`).

The registry is every country with a folder in `countries/`, named as in the World
Bank income workbook. The song and artist counts and the analysis tier come from the
eligible songs: `eligible_songs.classify` over the newest complete songs folder of
each country, with the same rule and counts as the analysis release. `sample_tiers`
gives the tier. Sources that are not lyrics are read from their raw files, at the
paths in `resources/data_sources.toml`. The populism series is a file of the old
pipeline, kept as received in `raw/populism_fst/<YYYYMMDD>/`; the build reads the
newest complete folder. The survey columns and the Discogs columns have no source,
so they are empty and the build reports them absent (`NO_SOURCE`).
"""

import re
from collections.abc import Callable
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd

from songs.common import manifests, paths, schemas
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
from songs.stage_50_analysis import eligible_songs, sample_tiers

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

# Files of the old pipeline: input name -> (source in `raw/`, file name in its version folder).
OLD_PIPELINE_FILES = {"populism": ("populism_fst", "populism.parquet")}
# Columns that no input fills yet: they are empty, and the build reports them absent.
NO_SOURCE = [
    "artists.discogs_artists_available",
    "artists.discogs_dump_date",
    "registry.in_evs",
    "registry.in_wvs",
]
ARTIST_COUNT_METHOD = "distinct artist_id of the eligible songs"
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
CLEAN_SELECT = {"populism": {"country_iso3": "iso3", "populism_start": "pop_start"}}


def default_inputs(data: Path) -> dict[str, Path | None]:
    """Return where each input is. None means that the input has no raw folder."""
    inputs: dict[str, Path | None] = {}
    for name, (source, file_name) in OLD_PIPELINE_FILES.items():
        folder = paths.latest_raw_dir(data, source)
        inputs[name] = folder / file_name if folder else None
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


def registry_from_countries(root: Path, names: Path | None) -> pd.DataFrame:
    """Return one row per country folder in `countries/` of `root`, less the old codes.

    The name comes from the World Bank income workbook at `names`. A country that the
    workbook lacks, or every country when `names` is None, has an empty name. The
    survey columns are empty (`NO_SOURCE`).
    """
    codes = sorted(
        folder.name
        for folder in (root / "countries").iterdir()
        if folder.is_dir()
        and re.fullmatch("[A-Z]{3}", folder.name)
        and folder.name not in OLD_CODES
    )
    registry = pd.DataFrame({"country_iso3": codes})
    if names is not None:
        registry = registry.merge(world_bank_countries.load_names(names), how="left")
    return registry.reindex(columns=_columns("registry"))


def song_inputs(data: Path) -> list[Path]:
    """Return the folders that the count of the eligible songs reads; none with no songs."""
    folders = [songs for _, songs, _ in eligible_songs.country_folders(data)]
    if not folders:
        return []
    found = (
        paths.latest_clean_song_quarantine_dir(data),
        paths.latest_clean_artist_country_dir(data),
        paths.latest_clean_text_copies_dir(data),
    )
    return folders + [folder for folder in found if folder is not None]


def song_tables(data: Path) -> tuple[dict[str, pd.DataFrame], dict[str, int]]:
    """Return the song, artist and sample tables from the eligible songs, and their counts.

    A country with a songs folder has 0 songs in a year with no eligible song. The
    tier comes from the eligible songs by decade (`sample_tiers.assign`). The counts
    give the songs read, the songs that enter, the songs left out for each reason
    and the countries of each tier. With no complete songs folder, there are no tables.
    """
    countries = eligible_songs.country_folders(data)
    if not countries:
        return {}, {"countries_with_songs": 0}
    connection = duckdb.connect()
    covered = pd.DataFrame({"country_iso3": [code for code, _, _ in countries]})
    connection.register("covered", covered)
    eligible_songs.read_country_tables(
        connection,
        "songs",
        schemas.COUNTRY_SONGS,
        [(code, folder) for code, folder, _ in countries],
        ", ".join(eligible_songs.SONG_COLUMNS),
    )
    exceptions, lists = eligible_songs.load_rule(connection, data)
    eligible_songs.classify(connection.table("songs"), exceptions, lists).create("classified")
    eligible = connection.table("classified").filter("ineligible_reason IS NULL")
    eligible_songs.year_counts(eligible).create("year_counts")
    yearly = connection.sql(
        f"""
        SELECT country_iso3, CAST(year AS INTEGER) AS year,
            coalesce(num_songs, 0) AS num_songs, coalesce(num_artists, 0) AS num_artists
        FROM covered
        CROSS JOIN range({MIN_SONG_YEAR}, {MAX_SONG_YEAR + 1}) AS years(year)
        LEFT JOIN year_counts USING (country_iso3, year)
        """
    ).df()
    decades = connection.sql(
        "SELECT country_iso3, year // 10 * 10 AS decade, "
        "count_if(ineligible_reason IS NULL) AS num_songs FROM classified GROUP BY ALL"
    ).df()
    tiers = sample_tiers.assign(decades)
    tables = {
        "songs": yearly[["country_iso3", "year", "num_songs"]],
        "artists": yearly[["country_iso3", "year", "num_artists"]].assign(
            discogs_artists_available=None,
            discogs_dump_date=None,
            artist_count_method=ARTIST_COUNT_METHOD,
        ),
        "sample": tiers,
    }
    counts = {"countries_with_songs": len(countries)}
    counts |= eligible_songs.reason_counts(connection.table("classified"))
    counts |= {f"sample_{name}": number for name, number in sample_tiers.row_counts(tiers).items()}
    return tables, counts


def read_tables(
    inputs: dict[str, Path | None],
    data: Path,
    *,
    allow_missing: bool = False,
    root: Path | None = None,
) -> tuple[dict[str, pd.DataFrame], list[str], dict[str, int]]:
    """Read every input. Return the tables, the names of the absent inputs, and the counts.

    The registry comes from `countries/` of `root` (default: the project root), and the
    songs from `data`. An absent input stops the build, unless `allow_missing` is set.
    Then its columns are empty in the panel, and the caller must report the names.
    The columns in `NO_SOURCE` are always absent.
    """
    absent = sorted(name for name, path in inputs.items() if path is None or not path.exists())
    registry = registry_from_countries(
        paths.resolve_project_root(root),
        None if "income_groups" in absent else inputs["income_groups"],
    )
    song, counts = song_tables(data)
    absent = sorted([*absent, *([] if song else ["songs"]), *NO_SOURCE])
    if not allow_missing:
        raise FileNotFoundError(f"inputs of the country panel are absent: {absent}")
    countries = set(registry["country_iso3"])
    lookup = crises.name_lookup(registry.dropna(subset=["country_name"]))
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
    tables = {"registry": registry, **song}
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
    counts |= {
        "registry_countries": len(registry),
        "registry_no_name": int(registry["country_name"].isna().sum()),
    }
    return tables, absent, counts


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
    The count of the eligible songs reads the folders of `song_inputs`.
    """
    skipped = set(absent)
    if skipped & CURRENCY_INPUTS:
        skipped |= CURRENCY_INPUTS
    files = []
    for name, path in inputs.items():
        if name in skipped:
            continue
        files += [path / file for file in fertility.FILE_COLUMNS] if name == "fertility" else [path]
    files += song_inputs(data)
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
    tables, absent, counts = read_tables(inputs, data, allow_missing=allow_missing)
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
        counts={"rows": len(panel), "countries": len(tables["registry"]), **counts},
        notes=notes,
    )
    return {
        "path": out,
        "manifest": folder / paths.MANIFEST_NAME,
        "rows": len(panel),
        "absent_inputs": absent,
        "counts": counts,
        "codes_outside_registry": codes_outside_registry(tables),
    }
