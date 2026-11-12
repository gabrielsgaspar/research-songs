# Data sources

This page is generated from `resources/data_sources.toml`. Do not edit it by hand.

To rebuild it, run `python -m songs.common.data_sources --write`.

It answers one question: where does a variable come from? Each concept has at most one canonical source, and every analysis uses that one.

| Status | Meaning |
| --- | --- |
| canonical | The source every analysis uses |
| robustness | A second source, for robustness checks only |
| supplementary | Used by one analysis only |
| retired | Was used before; no analysis may read it |

"Checked: no" means that the source or version comes from notes, not from the download itself.

## Summary

| Concept | Canonical source | Version |
| --- | --- | --- |
| GDP per capita | Maddison Project Database, through Our World in Data | 2023 |
| Income inequality (Gini) | World Bank, World Development Indicators, SI.POV.GINI | downloaded 2026-11-10 |
| Income group | World Bank country classification by income | fiscal year 2027 |
| Population | United Nations, World Population Prospects | 2024, medium variant |
| Fertility | Human Fertility Database | downloaded 2026-09-21 |
| Divorce rate | United Nations Statistics Division, Demographic Yearbook, table 16 | not stated |
| Female labor force participation | World Bank, World Development Indicators, SL.TLF.CACT.FE.ZS (ILO modeled estimate) | downloaded 2026-09-21 |
| Democracy | Acemoglu, Naidu, Restrepo and Robinson (2019), Democracy Does Cause Growth, replication data | Journal of Political Economy 2019 |
| Populist leaders | Funke, Schularick and Trebesch, Populist Leaders and the Economy | not stated |
| Banking crises | Laeven and Valencia, Systemic Banking Crises Database | 2026 edition, 1970 to 2025 |
| Sovereign defaults | Bank of Canada and Bank of England, Sovereign Default Database | 2024 |
| Hyperinflations | Hanke and Krus, World Hyperinflations, table of episodes | May 2013 |
| Currency crises | Culiuc and Park, Large Depreciations, IMF Working Paper 25/221 | November 2025 |
| World region | World Bank regions, with a short list of project overrides | not stated |
| Artist and release catalog | Discogs monthly data dumps | 2026-06-01 |
| Artist aliases and rosters | MusicBrainz JSON data dumps | 2026-06-24 |

## GDP per capita

### `gdp_maddison` (canonical)

- Source: Maddison Project Database, through Our World in Data
- Version: 2023
- Unit: 2011 international dollars
- Columns: `gdp_per_capita`
- Link: <https://ourworldindata.org/grapher/gdp-per-capita-maddison-project-database>
- Raw files: `raw/owid_maddison_gdp/20261013/`
- Checked: yes
- Notes: This is the GDP series in the country-year panel.

### `gdp_pwt` (robustness)

- Source: Penn World Table
- Version: 11.0
- Unit: expenditure-side real GDP (rgdpe) divided by population
- Columns: `gdp_per_capita_pwt`
- Link: <https://www.rug.nl/ggdc/productivity/pwt/>
- Checked: no
- Notes: The raw file was not found on the workstation when this entry was written.

### `gdp_wdi_current_usd` (retired)

- Source: World Bank, World Development Indicators, NY.GDP.PCAP.CD
- Version: not stated
- Unit: current US dollars
- Link: <https://data.worldbank.org/indicator/NY.GDP.PCAP.CD>
- Checked: no
- Notes: Current dollars are not comparable over long periods.

## Income inequality (Gini)

### `gini_wdi` (canonical)

- Source: World Bank, World Development Indicators, SI.POV.GINI
- Version: downloaded 2026-11-10
- Unit: index, 0 to 100
- Columns: `gini`
- Link: <https://data.worldbank.org/indicator/SI.POV.GINI>
- Raw files: `raw/crisis_review_20261110/`
- Checked: yes
- Notes: Coverage is thin before 1980 and for low-income countries.

### `gini_swiid` (retired)

- Source: Standardized World Income Inequality Database (SWIID)
- Version: not stated
- Unit: index, 0 to 100, disposable income
- Link: <https://fsolt.org/swiid/>
- Checked: no
- Notes: Replaced by the World Bank series.

## Income group

### `income_group_world_bank` (canonical)

- Source: World Bank country classification by income
- Version: fiscal year 2027
- Columns: `world_bank_income_group`
- Link: <https://datahelpdesk.worldbank.org/knowledgebase/articles/906519>
- Raw files: `raw/world_bank_income/20260907/`
- Checked: yes

## Population

### `population_un_wpp` (canonical)

- Source: United Nations, World Population Prospects
- Version: 2024, medium variant
- Unit: persons
- Columns: `population_total`, `population_is_projected`, `log_population`
- Link: <https://population.un.org/wpp/>
- Raw files: `raw/un_wpp/2024/`
- Checked: yes
- Notes: Years after the last estimate are projections; `population_is_projected` marks them.

## Fertility

### `fertility_hfd` (canonical)

- Source: Human Fertility Database
- Version: downloaded 2026-09-21
- Unit: children per woman, and related rates
- Columns: `hfd_*`
- Link: <https://www.humanfertility.org/>
- Raw files: `raw/hfd/20260921/`
- Checked: yes
- Notes: 14 columns with the prefix `hfd_`. The database covers a limited set of countries, mostly high-income.

### `fertility_owid` (retired)

- Source: Our World in Data, children born per woman (from UN World Population Prospects)
- Version: downloaded 2026-09-21
- Unit: children per woman
- Link: <https://ourworldindata.org/grapher/children-born-per-woman>
- Raw files: `raw/owid_fertility/20260921/`
- Checked: yes
- Notes: Covers more countries than the Human Fertility Database. Retired so that every analysis uses one fertility source.

## Divorce rate

### `divorce_unsd` (canonical)

- Source: United Nations Statistics Division, Demographic Yearbook, table 16
- Version: not stated
- Unit: divorces per 1,000 persons
- Columns: `divorce_rate_per_1000`
- Link: <https://unstats.un.org/unsd/demographic-social/products/dyb/>
- Raw files: `raw/unsd_divorces/undata_pop_table16/`
- Checked: yes
- Notes: Divorce counts divided by the population from `population_un_wpp`.

## Female labor force participation

### `female_labor_force_wdi` (canonical)

- Source: World Bank, World Development Indicators, SL.TLF.CACT.FE.ZS (ILO modeled estimate)
- Version: downloaded 2026-09-21
- Unit: percent of women aged 15 and over
- Columns: `female_labor_force_participation_rate`
- Link: <https://data.worldbank.org/indicator/SL.TLF.CACT.FE.ZS>
- Raw files: `raw/world_bank_wdi/20260921/`
- Checked: yes

## Democracy

### `democracy_anrr` (canonical)

- Source: Acemoglu, Naidu, Restrepo and Robinson (2019), Democracy Does Cause Growth, replication data
- Version: Journal of Political Economy 2019
- Unit: 0 or 1
- Columns: `anrr_democracy`
- Link: <https://www.journals.uchicago.edu/doi/10.1086/700936>
- Checked: no
- Notes: The series as published, 1960 to 2010, with no extension. The raw file was not found on the workstation when this entry was written.

### `democracy_vdem` (supplementary)

- Source: V-Dem electoral democracy and freedom of expression indices, through Our World in Data
- Version: not stated
- Unit: index, 0 to 1
- Columns: `democracy`, `expression`
- Link: <https://ourworldindata.org/grapher/electoral-democracy-index>
- Raw files: `raw/crisis_review_20261110/`
- Checked: no
- Notes: Used only in the review of crisis events, as context.

### `democracy_anrr_augmented` (retired)

- Source: The published democracy series, extended by the project
- Version: not stated
- Unit: 0 or 1
- Checked: no
- Notes: The source of the extension is not documented. Use `democracy_anrr`.

## Populist leaders

### `populism_fst` (canonical)

- Source: Funke, Schularick and Trebesch, Populist Leaders and the Economy
- Version: not stated
- Columns: `populist`, `populism_start`, `independent`
- Link: <https://www.aeaweb.org/articles?id=10.1257/aer.20202045>
- Checked: no
- Notes: The raw file and the code that cleans it were not found when this entry was written.

## Banking crises

### `banking_crises_laeven_valencia` (canonical)

- Source: Laeven and Valencia, Systemic Banking Crises Database
- Version: 2026 edition, 1970 to 2025
- Columns: `banking_crisis_*`
- Checked: no
- Notes: The raw file was not found on the workstation when this entry was written.

## Sovereign defaults

### `sovereign_default_boc_boe` (canonical)

- Source: Bank of Canada and Bank of England, Sovereign Default Database
- Version: 2024
- Columns: `sovereign_default_*`
- Raw files: `raw/crisis_review_20261109/`
- Checked: yes

## Hyperinflations

### `hyperinflation_hanke_krus` (canonical)

- Source: Hanke and Krus, World Hyperinflations, table of episodes
- Version: May 2013
- Columns: `hyperinflation_*`
- Checked: no
- Notes: The raw file was not found on the workstation when this entry was written.

## Currency crises

### `currency_crises_culiuc_park` (canonical)

- Source: Culiuc and Park, Large Depreciations, IMF Working Paper 25/221
- Version: November 2025
- Columns: `currency_crisis_*`
- Raw files: `raw/crisis_review_20261109/`
- Checked: yes

## United States recessions

### `us_recessions_nber` (supplementary)

- Source: National Bureau of Economic Research, business cycle dates
- Version: not stated
- Link: <https://www.nber.org/research/business-cycle-dating>
- Raw files: `raw/crisis_review_20261110/`
- Checked: yes
- Notes: Used only for shading in time-series figures.

## Inflation

### `inflation_wdi` (supplementary)

- Source: World Bank, World Development Indicators, FP.CPI.TOTL.ZG
- Version: downloaded 2026-11-10
- Unit: percent per year
- Columns: `inflation`
- Link: <https://data.worldbank.org/indicator/FP.CPI.TOTL.ZG>
- Raw files: `raw/crisis_review_20261110/`
- Checked: yes
- Notes: Used only in the review of crisis events.

## Youth unemployment

### `youth_unemployment_wdi` (supplementary)

- Source: World Bank, World Development Indicators, SL.UEM.1524.ZS
- Version: downloaded 2026-11-10
- Unit: percent of the labor force aged 15 to 24
- Columns: `youth_unemployment`
- Link: <https://data.worldbank.org/indicator/SL.UEM.1524.ZS>
- Raw files: `raw/crisis_review_20261110/`
- Checked: yes
- Notes: Used only in the review of crisis events.

## World region

### `region_world_bank` (canonical)

- Source: World Bank regions, with a short list of project overrides
- Version: not stated
- Columns: `region_name`
- Link: <https://datahelpdesk.worldbank.org/knowledgebase/articles/906519>
- Checked: no
- Notes: The overrides must move to a tracked file with the code that applies them.

## Land area

### `land_area_wdi` (supplementary)

- Source: World Bank, World Development Indicators, AG.LND.TOTL.K2
- Version: downloaded 2026-08-28
- Unit: square kilometers
- Link: <https://data.worldbank.org/indicator/AG.LND.TOTL.K2>
- Checked: no
- Notes: The raw file was not found on the workstation when this entry was written.

## Artist and release catalog

### `catalog_discogs` (canonical)

- Source: Discogs monthly data dumps
- Version: 2026-06-01
- Link: <https://data.discogs.com/>
- Raw files: `raw/discogs/`
- Checked: no
- Notes: Artists, releases, release countries and years. The version is read from a folder name.

## Artist aliases and rosters

### `catalog_musicbrainz` (canonical)

- Source: MusicBrainz JSON data dumps
- Version: 2026-06-24
- Link: <https://metabrainz.org/datasets>
- Raw files: `musicbrainz/clean/20260624-001001/`
- Checked: no
- Notes: Used for artist names in other scripts and for country rosters. The version is read from a folder name.
