# Configuration

The configuration has four sections: `data`, `model`, `inference`, and `output`. The top-level `seed` field sets the reproducibility seed.

Omitted optional fields use the defaults below.

```yaml
data:
  path: observations.csv
  time: year
  frequency: annual
  # unit: country
model:
  outcome: y
  shock: x
  method: ordinary
  response: level
  controls: []
  lagged_controls: [y, x]
  lags: 1
  horizons: [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
inference:
  level: 0.95
  covariance: auto
  nw_lag: horizon_plus_one
  small_sample: false
seed: 20261102
output:
  dir: results
```

## Data

`data.path` accepts CSV and Parquet files. Paths resolve relative to the YAML file.

`data.time` names one time column. `data.unit` names one optional panel identifier.

`frequency` accepts `integer`, `annual`, `quarterly`, or `monthly`. Integer periods must be whole numbers.

Annual strings use `YYYY`. Quarterly strings use `YYYY-Q1` through `YYYY-Q4`. Monthly strings use `YYYY-MM`.

Annual, quarterly, and monthly inputs also accept ISO dates, `YYYY-MM-DD`. The scripts map dates to their containing period.

Multiple observations within one unit-period cause an error. Aggregate the input explicitly before estimation.

Fixed effects and clusters that reference `data.time` use the calendar period. Different date labels within one quarter share its time effect.

Outcome, shock, instrument, and control columns must be numeric. Missing values are permitted. Infinite values cause an error.

## Model

`outcome` and `shock` each name one column. `instrument` names one column for `iv` or `pmw_ratio`.

`controls` adds contemporaneous regressors. `lagged_controls` selects variables with lags from one through `lags`.

The default lagged controls contain the outcome and shock. Adding contemporaneous controls does not add their lags automatically.

`lags` is a nonnegative integer. `horizons` is a nonempty list of nonnegative integers. The scripts sort and deduplicate horizons.

`fixed_effects` overrides panel fixed effects. Use `[]` for a pooled panel regression. Time-series fixed effects are unsupported.

`response` accepts `level`, `cumulative_change`, or `cumulative_sum`. Read [methods.md](methods.md) for the exact definitions.

`pmw_ratio` requires at least one lag. It always includes lagged instruments in addition to the selected lagged controls.

## Inference

`covariance` accepts `auto`, `NW`, `HC1`, `cluster`, or `iid`. Values are case-sensitive.

`auto` chooses `NW` for time series, `HC1` for lag augmentation, and `cluster` for panels.

`nw_lag` accepts `horizon_plus_one` or a nonnegative integer. The Bartlett weight at lag j is `1 - j / (bandwidth + 1)`.

`small_sample: true` multiplies NW covariance by `n / (n - k)`. The default is false. HC1 always uses this multiplier.

`cluster` overrides panel clustering columns. The default contains unit and time. Each cluster dimension must contain at least two groups.

Panel finite-sample settings use `K.adj=TRUE`, `K.fixef="nonnested"`, `G.adj=TRUE`, and `G.df="min"` in fixest.

Time-series intervals use normal quantiles. Panel intervals use t quantiles. Cluster degrees of freedom equal the minimum cluster count minus one.

`level` sets pointwise confidence coverage. Intervals do not form a simultaneous confidence band across horizons.

## Output

`output.dir` sets the output folder. The saved configuration records resolved defaults.

The estimates include `horizon`, `estimate`, `std_error`, `lower`, `upper`, `p_value`, `nobs`, and inference settings.

Diagnostics report exclusions, residual degrees of freedom, lag order, and available first-stage statistics.

`sample_ids` records input row numbers, original time labels, unit identifiers, and calendar indices for each horizon.

First-stage files record horizon-specific IV diagnostics or the full-sample PMW normalization. Formulas use internal aliases with the configuration as their column mapping.
