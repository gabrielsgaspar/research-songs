# VAR configuration

The configuration is YAML. Paths resolve relative to the configuration file. The input can be CSV or Parquet.

## Data

`data.path` is the input file. `data.time` is the time column. `data.frequency` accepts `integer`, `annual`, `quarterly`, or `monthly`. The default frequency is `integer`. Integer and annual periods must be consecutive integers. Quarterly periods accept `YYYY-Qn`, `YYYYQn`, or ISO dates. Monthly periods accept `YYYY-MM` or ISO dates. Each ISO date must represent a distinct consecutive period. Rows must already follow time order.

`data.unit` is prohibited because the estimator accepts one time series. Model variables must be numeric, finite, and complete throughout the selected sample. The estimator rejects gaps and duplicate periods. It does not remove rows to repair missing data. Proxy instruments can contain missing values.

## Model

`model.variables` lists at least two distinct input columns in their model order. `model.lags` fixes a positive lag count when supplied. Without fixed lags, `model.lag_selection` must be `BIC`. `model.max_lags` defaults to 12. The sample size caps the candidate maximum before the estimator compares candidate models.

`model.method` accepts `reduced_form`, `recursive`, or `proxy`. The default is `reduced_form`. `model.horizons` lists distinct nonnegative integers. The default is `[0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10]`.

`model.covariance` accepts `df_adjusted` or `ml`. The default is `df_adjusted`. This setting determines the recursive impact scale. Both covariance estimates appear in the output.

For `recursive`, `model.order` must list every model variable exactly once. The order starts with the variable that has no contemporaneous response to later shocks. Output response rows retain `model.variables` order. Shock columns follow `model.order`.

`model.normalization_variable` and `model.impact_target` form an optional pair. The variable must appear in `model.variables`. The target must be finite and nonzero. The target uses the supplied units of the normalization variable. No automatic percent, percentage-point, or basis-point conversion occurs.

For reduced-form and recursive methods, `model.normalization_shock` selects the shock column to rescale. It defaults to `normalization_variable` when the normalization pair is supplied. Only the selected shock column changes. The estimator divides that column by its normalization-variable impact and multiplies it by the target. A zero impact causes an error. The selector requires the normalization pair and a known shock name. Proxy VAR rejects this selector because its instrument already selects the only shock.

For `proxy`, the normalization pair is required. `model.instrument` names one numeric column outside `model.variables`. `model.proxy_residualization` accepts `controls`, `augmented_var`, or `none`. The default is `controls`. `controls` residualizes the instrument on the intercept and lagged model variables. `augmented_var` also includes the instrument's own lags. `none` uses the centered instrument without lag controls. `model.residualize_proxy: false` also selects `none`. Conflicting residualization settings cause an error.

## Inference

`seed` is a top-level nonnegative integer. Its default is `20261102`. `inference.seed` is prohibited.

`inference.level` defaults to `0.95` and must lie between zero and one. `inference.bootstrap_draws` defaults to 1,999 for reduced-form and recursive methods. It defaults to zero for proxy VAR. Zero requests point estimates only. Proxy VAR rejects positive draws and explicit confidence-interval requests.

`inference.resampling_indices` is an optional verification matrix. It has one row per draw and one column per VAR residual observation. Each entry is a one-based residual row index. The estimator uses these indices directly and does not draw random indices.

## Output

`output.dir` is required. The estimator prepares its files before it writes them to this directory. A repeat run can replace files with the same output names. The estimator refuses to replace the input file.

The reusable R entry point is `run_var(config, data)` in `scripts/estimator.R`. It returns `estimates`, `diagnostics`, `extra`, and `resolved_config`. The CLI writes those results with `scripts/runtime.R`.
