# Methods and interpretation

## Ordinary local projections

For each horizon h, regress the selected response on the current shock, contemporaneous controls, and configured lagged controls.

The shock coefficient estimates a conditional response. A causal interpretation requires a valid shock and adequate conditioning variables.

An intercept enters each time-series equation. Panels absorb the selected fixed effects. Unit and time fixed effects are the panel default.

The estimation sample changes by horizon. The scripts save its exact input identifiers.

An outcome equal to its shock has a horizon-zero level response of one. Its interval is a point, and its p-value is unavailable.

Zero residual variance also gives a point interval and no p-value. Constant time-series outcomes use fixest's matrix estimator with the same full-rank design.

For time series, the default covariance uses Bartlett Newey-West weights through lag `h + 1`. It does not prewhiten residuals.

The default omits the `n / (n - k)` multiplier. Set `small_sample: true` when the source convention requires that multiplier.

Scores at missing calendar dates do not become adjacent. NW cross-products pair observations at the stated calendar lag.

The checked Ramey-Zubairy archive uses `nwest.m` without the finite-sample multiplier. Match transformations, horizons, and lag controls separately.

## Response definitions

- `level` uses `y(t + h)`.
- `cumulative_change` uses `y(t + h) - y(t - 1)`.
- `cumulative_sum` uses the sum of `y(t)` through `y(t + h)`.

No response transformation changes the shock or control columns. Transform those columns before running the skill when the model requires it.

The cumulative change requires its two endpoints. The cumulative sum requires every included period. Required lags impose their own sample restrictions.

## Lag augmentation

`lag_augmented` adds one lag beyond `model.lags` for every selected lagged control. Use a sufficiently rich lagged state for the intended design.

This named method supports time-series OLS with HC1 covariance. It does not combine HAC inference, panel fixed effects, or instruments.

The checked Montiel Olea-Plagborg-Moller archive separates its lag order from the underlying `lp.m` regression. The additional lag is explicit here.

HC1 uses heteroskedasticity-robust scores with the `n / (n - k)` multiplier. Intervals use normal critical values.

## Instrumental variables

`iv` uses fixest 2SLS separately at each horizon. It instruments the current shock with the current excluded instrument.

The first stage uses the same complete observations as its horizon's second stage. Included controls enter both stages.

The TS sandwich uses projected regressors and structural residuals. NW, HC1, and iid options retain conventional strong-instrument inference.

Diagnostics include the excluded instrument's robust Wald F statistic and partial R-squared. They do not certify instrument strength or exclusion.

The F statistic is the squared first-stage coefficient divided by its covariance estimate. It is not a weak-IV-robust test.

A full-rank, perfect first stage makes 2SLS equal OLS. The scripts use that algebraic limit and retain the projected-regressor covariance.

Diagnostics flag the perfect first stage and report partial R-squared as one. Its Wald F statistic is unavailable because residual variance is zero.

State the instrument's relevance, exclusion, timing, and sample assumptions. Weak instruments require a separate validated inference procedure.

Panel IV is unsupported in version one.

## PMW normalization ratio

`pmw_ratio` reproduces the point-estimate construction in the checked Plagborg-Moller-Wolf `LP_IV.m` archive.

First, regress the current normalization variable, `shock`, on the instrument and all selected lagged controls. Include lagged instruments.

Keep this normalization coefficient from the full available first-stage sample. Do not shorten that sample for a response horizon.

Next, regress each horizon response on the current instrument and the same lagged controls. Divide its instrument coefficient by the normalization coefficient.

This ratio differs from horizon-specific 2SLS when the first-stage sample changes. It returns no standard errors, p-values, or confidence intervals.

To match the archive, supply its complete lagged state through `lagged_controls`. Keep `controls: []` unless the target specification adds current controls.

The first-stage normalization must be nonzero. A nonzero estimate alone does not establish reliable IV inference.

## Panels

The panel default absorbs unit and time effects and clusters by both dimensions. The configuration can override fixed effects and clustering.

The covariance uses explicit fixest finite-sample adjustments. Cluster confidence intervals use a t distribution with the minimum cluster count minus one.

With few clusters, this conventional interval can be unreliable. This bundle does not implement a wild cluster bootstrap.

Panel NW, panel IV, and panel lag augmentation require separate validation before support.

## Source boundaries

The local source review includes Jordà applications, Ramey-Zubairy, Montiel Olea-Plagborg-Moller, and Plagborg-Moller-Wolf replication files.

Their estimation conventions are distinct. A matched point estimate does not make their confidence intervals interchangeable.

The bundle does not include restricted source data. Independent author comparisons must record source hashes, transformations, sample dates, and target formulas.
