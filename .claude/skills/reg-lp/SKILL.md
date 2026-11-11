---
name: reg-lp
description: Estimate local projection impulse responses in R with fixest, including time series, panel fixed effects, lag augmentation, and external instruments. Use for LP regressions and explicit author-code comparisons, not VAR estimation.
---

# Local projections in R

Use this portable bundle to estimate one regression for each horizon. The scripts do not use repository code or cloud services.

Read [methods.md](references/methods.md) before choosing an estimator. Read [config.md](references/config.md) before writing the configuration.

## Workflow

1. State the outcome, shock, time scale, response definition, and identification assumptions.
2. Choose a named method and covariance convention.
3. Write a YAML file from an [example](examples/time_series.yml).
4. Run setup once for the local R installation.
5. Run the estimator from any working directory.
6. Check sample identifiers, formulas, first stages, and exclusions before interpreting the response.
7. Give the user the saved estimates, diagnostics, and PNG plot.

```text
CSV or Parquet + YAML
        |
Calendar-keyed leads and lags
        |
One fixest regression per horizon
        |
Estimates + samples + diagnostics + PNG
```

```sh
Rscript --vanilla <skill-root>/scripts/setup.R
Rscript --vanilla <skill-root>/scripts/run_lp.R <config.yml>
Rscript --vanilla <skill-root>/tests/test_lp.R
python <skill-root>/scripts/install.py
python <skill-root>/scripts/install.py --verify
```

Replace `<skill-root>` with the bundle's absolute folder path. Replace `<config.yml>` with the configuration file path.

The Python installer copies the skill into the configured skills folder. The `--verify` option checks the installed copy.

Input and output paths resolve relative to the YAML file. Use an output folder outside the skill bundle.

## Defaults

The default method is `ordinary`. Horizons run from zero through ten. Each regression includes an intercept and one lag of the outcome and shock.

Time series use Bartlett Newey-West covariance with bandwidth `h + 1`. The default excludes the finite-sample multiplier. Confidence intervals use normal critical values.

Panels use unit and time fixed effects. Their default covariance clusters by unit and time. Cluster confidence intervals use the minimum cluster count minus one.

## Method limits

- `ordinary` supports time series and panels.
- `lag_augmented` adds one lag to the configured order. It supports time-series OLS with HC1 covariance.
- `iv` estimates horizon-specific 2SLS. Its conventional intervals require strong instruments.
- `pmw_ratio` divides horizon reduced forms by one full-sample normalization coefficient. It returns point estimates only.

Version one rejects panel IV and panel lag augmentation. It rejects duplicate unit-period keys and collinear specifications.

Missing periods stay missing. A lead refers to a calendar period, not the next stored row. Cumulative sums require every included period.

An LP coefficient does not establish causality. Explain shock timing, omitted-variable restrictions, and instrument validity where applicable.

## Verification

Run the bundled self-checks after setup. They compare results with independent base-R regressions and matrix calculations.

Use author fixtures only for their stated sample, transformations, lag order, and normalization. A matching coefficient does not validate another method's uncertainty calculation.

Setup is separate from estimation. Statistical scripts do not install packages or access the network.

If `Rscript` is absent from PATH, use its full executable path. Keep the `--vanilla` flag.

Run `python tests/test_install.py` from the skill directory to check the installer without changing personal folders.
