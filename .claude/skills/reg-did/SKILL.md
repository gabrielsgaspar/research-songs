# DID Estimators Skill

## Purpose

This skill runs reusable difference-in-differences estimators from a YAML config file and writes standardized outputs for downstream empirical work.

Supported estimators:

- `callaway_santanna`
- `sun_abraham`
- `bjs`
- `dcdh`
- `twfe_dynamic`

The implementation is R-first and uses maintained package interfaces where possible:

- Callaway-Sant'Anna via `did::att_gt()` and `did::aggte()`
- Sun-Abraham via `fixest::sunab()` inside `fixest::feols()`
- Borusyak-Jaravel-Spiess via `didimputation::did_imputation()`
- de Chaisemartin-D'Haultfoeuille via `DIDmultiplegtDYN::did_multiplegt_dyn()` by default and `DIDmultiplegt::did_multiplegt_old()` optionally
- Dynamic TWFE via `fixest::feols()` with `fixest::i()`

## What This Version Improves

Compared with the original skill, this version:

- uses a portable runtime entrypoint instead of assuming a fixed install path (the skill lives in `.claude/skills/reg-did/`)
- writes a machine-readable `results.json` with estimates, event-study output, diagnostics, and model stats
- centralizes plot styling so users can override defaults from the config
- exports the main figure in a LaTeX-friendly format chosen by the user via `plot.latex_figure_format`
- writes one tight-style PNG sidecar named `event_study_plot.png` for papers, slides, and notes
- standardizes confidence intervals, coefficient naming, and event-study tables across estimators
- records output file paths in metadata
- keeps estimator-specific hyperparameters in the same config surface

## When To Use Each Estimator

- Use `callaway_santanna` when you want transparent ATT(g,t) estimation and explicit aggregation choices.
- Use `sun_abraham` when you want staggered-adoption event-study plots inside a `fixest` workflow.
- Use `bjs` when you want imputation-based staggered DID and explicit horizon-based dynamic effects.
- Use `dcdh` when treatment is more general than simple first-treatment timing or when the user explicitly wants the de Chaisemartin-D'Haultfoeuille estimator.
- Use `twfe_dynamic` only as a baseline or comparability check. It can be misleading under staggered timing with heterogeneous effects.

## Main Interface

The main interface is a YAML config file. At minimum the user should be able to specify:

- the estimator
- the data path and file format
- the outcome variable
- panel identifiers (`unit_id`, `time_id`)
- either `group_id`, `treatment_var`, or `event_time_var`, depending on the estimator
- controls
- clustering
- weights if needed
- estimator-specific hyperparameters
- the output directory
- plot overrides if needed

Example:

```yaml
estimator: "callaway_santanna"
data_path: "data/clean/panel.parquet"
file_format: "parquet"
outcome: "turnout"
unit_id: "municipality_id"
time_id: "year"
group_id: "year_first_treat"
controls:
  - "log_pop"
  - "gdp_pc"
cluster_var:
  - "state"
lead: 5
lag: 5
anticipation: 0
control_group: "nevertreated"
output_dir: "outputs/did/turnout_cs"
plot:
  latex_figure_format: "pdf"
  save_tight_png: true
  omit_title: true
  x_label: "Distance to treatment"
  y_label: null
```

## Commands

Install missing R packages:

```bash
Rscript scripts/install_packages.R
```

Run an estimator:

```bash
Rscript scripts/run_estimator.R path/to/config.yml
```

Shell wrapper:

```bash
bash scripts/run_did_estimator.sh path/to/config.yml
```

## Output Files

Each run can write:

- `tidy_estimates.csv`
- `event_study_estimates.csv`
- estimator-specific extra tables such as `aggregate_group.csv`
- `sample_diagnostics.csv`
- `model_summary.txt`
- `run_metadata.yml`
- `config_used.yml`
- `results.json`
- `event_study_plot.<latex_figure_format>`
- `event_study_plot.png`

Tabular outputs are CSV-only by default to avoid duplicated CSV/Parquet files with the same information. Set `output.save_parquet: true` only when a downstream workflow explicitly needs Parquet copies.
Large estimator input samples, such as `analysis_sample`, should be saved and referenced as Parquet by default to keep regression resources compact; set `data_path` to the `.parquet` file and use `file_format: "parquet"`.
Plot outputs avoid duplicated PNGs by default: `plot.save_tight_png: true` writes the single PNG sidecar as `event_study_plot.png`, not `event_study_plot_tight.png`.

## `results.json`

The JSON output is the main structured artifact for downstream use. It includes:

- run information
- model statistics when available
- sample diagnostics
- main estimates
- event-study estimates
- estimator-specific extra tables

Model statistics are estimator-dependent, but the skill tries to write fields such as:

- estimator name
- number of observations
- R-squared / adjusted R-squared / within R-squared when the estimator exposes them
- overall ATT and standard error where applicable
- reference event time
- horizon/pretrend settings where applicable

## Plot Defaults

By default, the event-study figure:

- uses event time on the x-axis and the estimate on the y-axis
- draws a dashed vertical line at the reference period
- draws a thicker horizontal zero line
- draws 95% confidence intervals as vertical lines
- uses a full box around the plot panel
- uses major grids and visible axis ticks
- exports a LaTeX-friendly figure plus a single tight-style PNG named `event_study_plot.png`

Users can override plot design in the `plot:` block, including:

- width, height, dpi
- line/point/CI visibility
- CI geometry (`linerange` or `errorbar`)
- color
- title and subtitle
- axis labels
- axis breaks and limits
- tick label format
- whether to export `pdf`, `png`, `svg`, or `eps` as the main LaTeX figure

## Important Hyperparameters

Estimator-specific options supported in the config include:

### Callaway-Sant'Anna

- `control_group`: `nevertreated` or `notyettreated`
- `anticipation`
- `balanced_panel_required`
- `lead`, `lag`

### Sun-Abraham

- `reference_event_time`
- `lead`, `lag`
- `extra_fixed_effects`

### BJS

- `horizon`
- `pretrends`
- `event_time_step`

### dCDH

- `dcdh_mode`: `dyn` or `old`
- `effects`
- `placebo`
- `trends_nonparam`
- `trends_lin`
- either `treatment_var` or `group_id`

### TWFE Dynamic

- `reference_event_time`
- `lead`, `lag`
- `event_time_var`
- `extra_fixed_effects`

## Practical Guidance

- `group_id` should represent first treatment period for staggered-adoption estimators.
- Never-treated units can be encoded as `NA`, `0`, or a user-specified `never_treated_value`.
- The skill standardizes these internally and records this in diagnostics.
- `cluster_var` can be a single variable or a vector of variables.
- If treatment timing is ambiguous, validation should fail rather than guess.
- Duplicate `unit_id` x `time_id` rows are treated as an error.
- Character time variables are only coerced to numeric when the coercion is exact.

## Examples

Example configs live in `examples/`.

Start from:

- `examples/config_generic.yml`
- `examples/config_callaway_santanna.yml`
- `examples/config_sun_abraham.yml`
- `examples/config_bjs.yml`
- `examples/config_dcdh.yml`
- `examples/config_twfe_dynamic.yml`

## Recommended Prompting Pattern

A user can now describe the run in natural language, for example:

- estimator: Callaway-Sant'Anna
- data: `data/clean/panel.parquet`
- outcome: `turnout`
- controls: `log_pop`, `gdp_pc`
- cluster by: `state`
- use never-treated as control group
- leads/lags: 5 and 5
- output folder: `outputs/did/turnout_main`
- keep default plot styling but save the LaTeX figure as PDF and also save a tight PNG

That instruction should map directly into a YAML config for this skill.
