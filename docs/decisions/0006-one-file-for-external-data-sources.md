---
id: "0006"
title: One file says where every external variable comes from
status: accepted
date: 2026-11-12
supersedes: null
---

# One file says where every external variable comes from

## Context

The analysis uses many variables that are not lyrics: income, population, democracy, fertility, crises and others. Several concepts had two sources in use at the same time, so the answer to "where is this from?" depended on the script.

## Decision

`resources/data_sources.toml` lists every external source: concept, status, columns, publisher, version, link and raw file path. Each concept has at most one `canonical` source, and every analysis uses that one. `docs/standards/data_sources.md` is generated from the file.

The choices on 2026-11-12:

| Concept | Canonical source |
| --- | --- |
| GDP per capita | Maddison Project Database 2023, the series in the country-year panel. Penn World Table 11.0 is for robustness only. |
| Democracy | Acemoglu, Naidu, Restrepo and Robinson (2019), as published. The extended series is retired. |
| Fertility | Human Fertility Database. The Our World in Data series is retired. |
| Income inequality | World Bank Gini index. SWIID is retired. |
| Population | United Nations World Population Prospects 2024. |

To change a source, change its status in the file and record the reason in a new decision.

## Consequences

- One edit changes a source everywhere, and the change is visible in a pull request.
- The Human Fertility Database covers a limited set of countries, mostly high-income. Fertility analyses lose the other countries.
- The published democracy series ends in 2010. Analyses that use it stop there.
- Some entries are marked as not checked, because the raw file or its version was not confirmed. The work that rebuilds the country-year panel must confirm them.
