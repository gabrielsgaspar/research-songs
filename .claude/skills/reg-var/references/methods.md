# VAR methods

## Estimation and lag selection

The estimator fits `Y[t] = c + A[1]Y[t-1] + ... + A[p]Y[t-p] + U[t]`. Each equation uses OLS and an intercept through `vars::VAR`. The estimator does not detrend, difference, standardize, log, or seasonally adjust the input.

For fixed lags, the residual sample contains `T - p` observations. The number of regressors per equation is `K*p + 1`. The residual degrees of freedom are `T - p - K*p - 1`. The design must have full column rank and positive residual degrees of freedom. The residual covariance must have full rank.

For BIC, the preliminary candidate maximum is `min(max_lags, floor((T - 2)/(K + 1)))`. Each candidate uses the common residual sample from `p_max + 1` through `T`. The candidate fit drops the first `p_max - p` input rows before estimation. Nonestimable candidates remain in the table with their failure reason. The estimator selects the smallest BIC among estimable candidates. Ties select the smaller lag count. The selected model then refits on its full `T - p` residual sample.

Let `N = T - p_max` and `q = K*K*p + K` for a candidate. The table reports `Sigma_ML = U'U/N`, `AIC = log(det(Sigma_ML)) + 2*q/N`, and `BIC = log(det(Sigma_ML)) + log(N)*q/N`. These criteria include intercept parameters.

## Impact responses

The reduced-form impact matrix is the identity matrix. Each shock is one unit in one residual coordinate. These are not orthogonal structural shocks.

The recursive impact matrix is the lower Cholesky factor in `model.order`. The default shock size is one structural standard deviation from the degrees-of-freedom-adjusted covariance. With an explicit target, the estimator rescales `normalization_shock` to the specified impact on `normalization_variable`. The shock selector defaults to the normalization variable. An instrument-first recursive shock can therefore use a different variable's impact for normalization.

The moving-average recurrence uses `Phi[0] = I` and `Phi[h] = sum(A[l]*Phi[h-l])` over available lags. The response at horizon `h` is `Phi[h]*impact`.

## Proxy impact and sample

The estimator fits the VAR on every complete model-variable period. It uses only periods with an available instrument and required instrument lags for proxy identification. It does not refit the VAR on that subset. The output records the full VAR sample and the separate proxy row indices.

The default `controls` mode residualizes the instrument on the VAR intercept and lagged model variables. The `augmented_var` mode adds the instrument's own lags to those controls. This mode matches the augmented `[Z Y]` VAR residualization in Plagborg-Moller and Wolf's `Figure_2.m`. Their source then estimates the separate VAR for `Y` and uses its residual covariance with the augmented instrument residual. The source is in `reports/lp_archive_review_20261102/source/lp_var_replication/replication_files/Empirical_Application/Figure_2.m` in the development repository. The portable skill does not require that source directory.

With proxy residual `z_tilde`, the unscaled impact direction is `U'z_tilde/N_proxy`. The estimator divides this vector by its normalization-variable entry and multiplies it by `impact_target`. A zero denominator causes an error. The scale factor `N_proxy` cancels in this ratio.

First-stage diagnostics regress the normalization-variable VAR residual on an intercept and `z_tilde` within the proxy sample. The output reports its coefficient, R-squared, F statistic, degrees of freedom, residual correlation, and normalization denominator. These values describe relevance in the selected sample. They do not establish exclusion, exogeneity, or robust weak-instrument inference. The skill does not produce proxy confidence intervals.

## Covariance and stability

Both covariance files use the full selected VAR residual sample. `covariance_ml.csv` contains `U'U/N`. `covariance_df_adjusted.csv` contains `U'U/(N - K*p - 1)`. The default recursive factor uses the second convention.

The diagnostic output contains companion eigenvalues and their moduli. The model is stable only when every modulus is less than one. An unstable model can produce point responses with a warning. Stationary bootstrap inference stops for an unstable fitted model.

## Residual bootstrap

The bootstrap holds the selected lag count fixed. It centers each residual column and resamples entire residual rows with replacement. It preserves the original first `p` observations and simulates all later observations from the fitted intercept and lag matrices. Every draw refits the VAR and recomputes its impact matrix. The bootstrap uses the same covariance and normalization convention as the point estimate. The intervals are pointwise percentile intervals with R quantile type 7. The default uses 1,999 draws, a 95% level, and seed `20261102`. The bootstrap does not discard or replace failed draws. The run stops and identifies the failed draw. This inference assumes a stable VAR and suitable identically distributed innovations. It does not supply heteroskedasticity-robust, wild, weak-instrument, or simultaneous-band inference.
