args <- commandArgs(trailingOnly = TRUE)
file_arg <- grep("^--file=", commandArgs(), value = TRUE)
skillroot <- if (length(args)) normalizePath(args[1L]) else dirname(dirname(normalizePath(sub("^--file=", "", file_arg), mustWork = TRUE)))
source(file.path(skillroot, "scripts", "runtime.R"))
runtime_init(skillroot)
source(file.path(skillroot, "scripts", "estimator.R"))
close_enough <- function(a, b, tolerance = 1e-9) stopifnot(isTRUE(all.equal(as.numeric(a), as.numeric(b), tolerance = tolerance)))
fails <- function(expression, text) {
  error <- tryCatch({ force(expression); NULL }, error = identity)
  stopifnot(inherits(error, "error"), grepl(text, conditionMessage(error), fixed = TRUE))
}
set.seed(903L)
n <- 120L
innovations <- matrix(rnorm(n * 2L), ncol = 2L)
innovations[, 2L] <- innovations[, 2L] + 0.4 * innovations[, 1L]
y <- matrix(0, n, 2L, dimnames = list(NULL, c("rate", "output")))
a <- matrix(c(0.55, -0.2, 0.1, 0.35), 2L)
for (t in 2:n) y[t, ] <- a %*% y[t - 1L, ] + innovations[t, ]
data <- data.frame(time = 1900L + seq_len(n), y)
data$z <- innovations[, 1L] + 0.2 * rnorm(n)
config <- list(data = list(time = "time", frequency = "annual"),
  model = list(variables = c("rate", "output"), lags = 2L), inference = list(bootstrap_draws = 0L))
result <- run_var(config, data)
stopifnot(nrow(result$estimates) == 44L, result$diagnostics$residual_n == n - 2L)
point <- result$estimates
close_enough(point$estimate[point$horizon == 0L], diag(2L))
fit <- var_fit(y, 2L)
close_enough(point$estimate[point$horizon == 1L], fit$coefficients[[1L]])
close_enough(point$estimate[point$horizon == 2L], fit$coefficients[[1L]] %*% fit$coefficients[[1L]] + fit$coefficients[[2L]])
close_enough(as.matrix(result$extra$covariance_ml[-1L]), crossprod(fit$residuals) / (n - 2L))
close_enough(as.matrix(result$extra$covariance_df_adjusted[-1L]), crossprod(fit$residuals) / (n - 7L))
named <- config
named$model$variables <- c("policy rate", "real output")
named_data <- data
names(named_data)[2:3] <- named$model$variables
named$model$method <- "recursive"
named$model$order <- rev(named$model$variables)
named_result <- run_var(named, named_data)
stopifnot(identical(named_result$extra$impact$response, named$model$variables))
seeded <- config
seeded$seed <- 902L
stopifnot(run_var(seeded, data)$resolved_config$seed == 902L)
seeded$inference$seed <- 903L
fails(run_var(seeded, data), "top level")

recursive <- config
recursive$model$method <- "recursive"
recursive$model$order <- c("output", "rate")
recursive_result <- run_var(recursive, data)
impact <- as.matrix(recursive_result$extra$impact[-1L])
close_enough(impact %*% t(impact), fit$covariance_df_adjusted)
stopifnot(impact[2L, 2L] == 0)
recursive$model$normalization_variable <- "rate"
recursive$model$impact_target <- 0.25
normalized <- run_var(recursive, data)
close_enough(normalized$extra$impact$rate[1L], 0.25)
stopifnot(normalized$diagnostics$normalization_shock == "rate")
cross_normalized <- recursive
cross_normalized$model$normalization_shock <- "output"
cross_result <- run_var(cross_normalized, data)
reference_fit <- vars::VAR(y[, c("output", "rate")], p = 2L, type = "const")
reference_path <- vars::Psi(reference_fit, nstep = 10L)[c(2L, 1L), , , drop = FALSE]
reference_path[, 1L, ] <- reference_path[, 1L, ] * 0.25 / reference_path[1L, 1L, 1L]
close_enough(cross_result$estimates$estimate, reference_path)
close_enough(cross_result$extra$impact$output[1L], 0.25)
close_enough(cross_result$extra$impact$rate, recursive_result$extra$impact$rate)
stopifnot(cross_result$diagnostics$normalization_shock == "output")
invalid_shock <- config
invalid_shock$model$normalization_shock <- "rate"
fails(run_var(invalid_shock, data), "needs normalization_variable")
invalid_shock <- recursive
invalid_shock$model$normalization_shock <- "missing"
fails(run_var(invalid_shock, data), "Unknown normalization_shock")
invalid_shock <- recursive
invalid_shock$model$normalization_variable <- "output"
invalid_shock$model$normalization_shock <- "rate"
fails(run_var(invalid_shock, data), "denominator is zero")
recursive$model$order <- NULL
fails(run_var(recursive, data), "model.order")

selected <- config
selected$model$lags <- NULL
selected$model$max_lags <- 4L
selection <- run_var(selected, data)$extra$lag_selection
stopifnot(all(selection$n == n - 4L), sum(selection$selected) == 1L)
for (p in 1:4) {
  rows <- seq.int(5L, n)
  x <- cbind(y[rows - 1L, , drop = FALSE])
  if (p > 1L) for (lag in 2:p) x <- cbind(x, y[rows - lag, , drop = FALSE])
  x <- cbind(x, 1)
  u <- lm.fit(x, y[rows, , drop = FALSE])$residuals
  bic <- as.numeric(determinant(crossprod(u) / length(rows), logarithm = TRUE)$modulus) + (4L * p + 2L) * log(length(rows)) / length(rows)
  close_enough(selection$BIC[p], bic)
}

proxy <- config
proxy$model$method <- "proxy"
proxy$model$instrument <- "z"
proxy$model$normalization_variable <- "rate"
proxy$model$impact_target <- 1
invalid_shock <- proxy
invalid_shock$model$normalization_shock <- "z"
fails(run_var(invalid_shock, data), "does not accept normalization_shock")
proxy_result <- run_var(proxy, data)
stopifnot(all(is.na(proxy_result$estimates$lower)), proxy_result$diagnostics$proxy$instrument_n == n - 2L)
ztilde <- lm.fit(fit$x, data$z[3:n])$residuals
covariance <- as.numeric(crossprod(fit$residuals, ztilde))
close_enough(proxy_result$extra$impact$z, covariance / covariance[1L])
small_instrument <- data
small_instrument$z <- data$z * 1e-10
close_enough(run_var(proxy, small_instrument)$extra$impact$z, proxy_result$extra$impact$z)
proxy$model$proxy_residualization <- "augmented_var"
augmented <- run_var(proxy, data)
ztilde <- lm.fit(cbind(fit$x, data$z[2:(n - 1L)], data$z[1:(n - 2L)]), data$z[3:n])$residuals
covariance <- as.numeric(crossprod(fit$residuals, ztilde))
close_enough(augmented$extra$impact$z, covariance / covariance[1L])
missing_proxy <- data
missing_proxy$z[20:25] <- NA_real_
subset <- run_var(proxy, missing_proxy)
stopifnot(subset$diagnostics$residual_n == n - 2L,
  subset$diagnostics$proxy$instrument_n == n - 10L,
  !subset$diagnostics$proxy$instrument_sample_is_var_sample,
  !any(subset$extra$instrument_sample$row %in% 20:27))
proxy$inference$bootstrap_draws <- 5L
fails(run_var(proxy, data), "point estimates only")
proxy$inference$bootstrap_draws <- 0L
proxy$inference$ci <- TRUE
fails(run_var(proxy, data), "point estimates only")
proxy$inference$ci <- NULL
constant <- data
constant$z <- 1
fails(run_var(proxy, constant), "not estimable")

bootstrap <- config
bootstrap$model$horizons <- 0:3
bootstrap$inference$bootstrap_draws <- 5L
bootstrap$inference$resampling_indices <- rbind(seq_len(n - 2L), rev(seq_len(n - 2L)),
  rep(1:59, 2L), c(2:(n - 2L), 1L), c(3:(n - 2L), 1L, 2L))
boot_result <- run_var(bootstrap, data)
bootstrap_again <- run_var(bootstrap, data)
close_enough(boot_result$estimates$lower, bootstrap_again$estimates$lower)
close_enough(boot_result$estimates$upper, bootstrap_again$estimates$upper)
stopifnot(all(is.finite(boot_result$estimates$lower)), all(boot_result$estimates$lower <= boot_result$estimates$upper))
paths <- matrix(NA_real_, nrow = 16L, ncol = 5L)
for (b in 1:5) {
  simulated <- y
  u <- sweep(fit$residuals, 2L, colMeans(fit$residuals), "-")
  for (t in 3:n) simulated[t, ] <- as.numeric(vars::Bcoef(fit$fit)[, "const"] +
    fit$coefficients[[1L]] %*% simulated[t - 1L, ] + fit$coefficients[[2L]] %*% simulated[t - 2L, ]) +
    u[bootstrap$inference$resampling_indices[b, t - 2L], ]
  refit <- vars::VAR(simulated, p = 2L, type = "const")
  paths[, b] <- as.numeric(vars::Phi(refit, nstep = 3L))
}
close_enough(boot_result$estimates$lower, apply(paths, 1L, quantile, probs = 0.025, type = 7L))
close_enough(boot_result$estimates$upper, apply(paths, 1L, quantile, probs = 0.975, type = 7L))
recursive_boot <- bootstrap
recursive_boot$model$method <- "recursive"
recursive_boot$model$order <- c("rate", "output")
recursive_paths <- paths
normalized_paths <- paths
for (b in 1:5) {
  simulated <- y
  u <- sweep(fit$residuals, 2L, colMeans(fit$residuals), "-")
  for (t in 3:n) simulated[t, ] <- as.numeric(vars::Bcoef(fit$fit)[, "const"] +
    fit$coefficients[[1L]] %*% simulated[t - 1L, ] + fit$coefficients[[2L]] %*% simulated[t - 2L, ]) +
    u[bootstrap$inference$resampling_indices[b, t - 2L], ]
  refit <- vars::VAR(simulated, p = 2L, type = "const")
  draw_path <- vars::Psi(refit, nstep = 3L)
  recursive_paths[, b] <- as.numeric(draw_path)
  draw_path[, 1L, ] <- draw_path[, 1L, ] * 0.25 / draw_path[2L, 1L, 1L]
  normalized_paths[, b] <- as.numeric(draw_path)
}
recursive_boot_result <- run_var(recursive_boot, data)
close_enough(recursive_boot_result$estimates$lower, apply(recursive_paths, 1L, quantile, probs = 0.025, type = 7L))
close_enough(recursive_boot_result$estimates$upper, apply(recursive_paths, 1L, quantile, probs = 0.975, type = 7L))
normalized_boot <- recursive_boot
normalized_boot$model$normalization_variable <- "output"
normalized_boot$model$normalization_shock <- "rate"
normalized_boot$model$impact_target <- 0.25
normalized_boot_result <- run_var(normalized_boot, data)
close_enough(normalized_boot_result$estimates$lower, apply(normalized_paths, 1L, quantile, probs = 0.025, type = 7L))
close_enough(normalized_boot_result$estimates$upper, apply(normalized_paths, 1L, quantile, probs = 0.975, type = 7L))
bootstrap$inference$resampling_indices[1L, ] <- 0L
fails(run_var(bootstrap, data), "resampling_indices")

bad <- data
bad$time[10L] <- bad$time[9L]
fails(run_var(config, bad), "unique")
bad <- data[-10L, ]
fails(run_var(config, bad), "without gaps")
bad <- data
bad$rate[8L] <- NA_real_
fails(run_var(config, bad), "complete and finite")
panel <- config
panel$data$unit <- "country"
fails(run_var(panel, data), "one time series")
too_many <- config
too_many$model$lags <- 100L
fails(run_var(too_many, data), "insufficient")
unstable <- data
unstable$rate <- 1.1^seq_len(n) + data$rate
unstable_result <- suppressWarnings(run_var(config, unstable))
stopifnot(!unstable_result$diagnostics$stable)
stationary_boot <- config
stationary_boot$inference$bootstrap_draws <- 2L
fails(run_var(stationary_boot, unstable), "unstable")
stopifnot(identical(var_time_index(c("2000-Q4", "2001-Q1"), "quarterly"), c(8004L, 8005L)))
stopifnot(identical(var_time_index(c("2000-12", "2001-01"), "monthly"), c(24012L, 24013L)))
cat("VAR behavior checks passed.\n")
