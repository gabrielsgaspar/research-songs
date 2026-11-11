---
name: reg-fe
description: Run a fixed-effects or standard linear regression in R using fixest::feols, with configurable outcome, controls, fixed effects, clustering, and output directory. Produces a machine-readable JSON summary of results.
allowed-tools: Bash
---

# reg-fe

Use this skill to run a linear regression in R with `fixest::feols`.

The user can specify:
- the dataset path
- the outcome variable
- the main regressors and optional controls
- fixed effects, if any
- cluster-robust standard errors, if any
- output directory

The skill writes a `results.json` file in the chosen output directory.

## Expected config structure

Create a YAML config file like this:

```yaml
data:
  path: path/to/data.parquet

regression:
  outcome: y
  regressors:
    - treatment
  controls:
    - x1
    - x2
  fixed_effects:
    - municipality_id
    - year
  cluster:
    - municipality_id

output:
  dir: resources/regressions/example_run
```

Notes:
- `regressors` should contain the main variables of interest.
- `controls` is optional.
- `fixed_effects` is optional. If omitted, the model is estimated without absorbed fixed effects.
- `cluster` is optional. It may be a single variable or multiple clustering variables.

## Run

```bash
bash scripts/run_reg_fe.sh examples/config_basic.yml
```

Or directly:

```bash
Rscript scripts/install_packages.R
Rscript scripts/run_regression.R examples/config_basic.yml
```

## Output

The output folder will contain:
- `results.json`: full regression output in machine-readable form
- `model_formula.txt`: the exact formula used in estimation
- `run_metadata.json`: basic run metadata

## JSON contents

The JSON includes:
- estimator name
- formula
- outcome
- regressors
- controls
- fixed effects
- cluster variables
- number of observations
- number of coefficients
- r-squared, adjusted r-squared, within r-squared when available
- RMSE when available
- coefficient table with estimate, standard error, t-statistic, p-value, and confidence intervals
- fixed effect sizes when available

## Supported data formats

Detected from file extension:
- `.parquet`
- `.csv`
- `.rds`
- `.feather`

## Example user request

“Use reg-fe with `data/clean/panel.parquet`, outcome `log_y`, regressors `treated`, controls `x1` and `x2`, fixed effects `unit_id` and `year`, cluster by `unit_id`, and save to `resources/regressions/test/`.”
