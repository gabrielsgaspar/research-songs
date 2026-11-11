`%||%` <- function(x, y) if (is.null(x)) y else x

var_integer <- function(x, name, minimum = 0L) {
  if (length(x) != 1L || !is.numeric(x) || !is.finite(x) || x != floor(x) || x < minimum || x > .Machine$integer.max) {
    stop(name, " must be an integer from ", minimum, " through ", .Machine$integer.max, ".")
  }
  as.integer(x)
}

var_time_index <- function(x, frequency) {
  if (anyNA(x) || anyDuplicated(x)) stop("Time values must be complete and unique.")
  if (frequency %in% c("integer", "annual")) {
    index <- suppressWarnings(as.numeric(as.character(x)))
    if (any(!is.finite(index)) || any(index != floor(index))) stop("Time values must be integers.")
  } else if (frequency == "quarterly") {
    text <- as.character(x)
    if (all(grepl("^[0-9]{4}-?Q[1-4]$", text))) {
      index <- as.integer(substr(text, 1L, 4L)) * 4L + as.integer(sub(".*Q", "", text))
    } else {
      date <- suppressWarnings(as.Date(text))
      if (anyNA(date)) stop("Quarterly time needs YYYY-Qn or ISO dates.")
      index <- as.integer(format(date, "%Y")) * 4L + (as.integer(format(date, "%m")) - 1L) %/% 3L + 1L
    }
  } else if (frequency == "monthly") {
    text <- as.character(x)
    text[grepl("^[0-9]{4}-[0-9]{2}$", text)] <- paste0(text[grepl("^[0-9]{4}-[0-9]{2}$", text)], "-01")
    date <- suppressWarnings(as.Date(text))
    if (anyNA(date)) stop("Monthly time needs YYYY-MM or ISO dates.")
    index <- as.integer(format(date, "%Y")) * 12L + as.integer(format(date, "%m"))
  } else stop("data.frequency must be integer, annual, quarterly, or monthly.")
  if (length(index) < 2L || any(diff(index) != 1L)) stop("Time must increase by one period without gaps.")
  index
}

var_fit <- function(y, p) {
  fit <- vars::VAR(y, p = p, type = "const")
  x <- as.matrix(fit$datamat[, -(seq_len(ncol(y))), drop = FALSE])
  rank <- qr(x)$rank
  df <- nrow(x) - ncol(x)
  if (rank != ncol(x) || df <= 0L) stop("The VAR design is rank deficient or has no residual degrees of freedom.")
  u <- as.matrix(stats::residuals(fit))
  colnames(u) <- colnames(y)
  ml <- crossprod(u) / nrow(u)
  if (qr(u)$rank != ncol(y) || !is.finite(determinant(ml, logarithm = TRUE)$modulus) || determinant(ml)$sign <= 0) {
    stop("The residual covariance is singular.")
  }
  list(fit = fit, x = x, residuals = u, covariance_ml = ml,
       covariance_df_adjusted = crossprod(u) / df, rank = rank, df = df,
       coefficients = vars::Acoef(fit), roots = vars::roots(fit, modulus = TRUE),
       eigenvalues = vars::roots(fit, modulus = FALSE))
}

var_select <- function(y, model) {
  n <- nrow(y)
  k <- ncol(y)
  if (!is.null(model$lags)) {
    p <- var_integer(model$lags, "model.lags", 1L)
    if (n - p <= k * p + 1L) stop("There are insufficient observations for the requested lags.")
    return(list(lags = p, table = data.frame()))
  }
  if (!identical(model$lag_selection %||% "BIC", "BIC")) stop("Only BIC lag selection is supported.")
  requested <- var_integer(model$max_lags %||% 12L, "model.max_lags", 1L)
  cap <- min(requested, floor((n - 2L) / (k + 1L)))
  if (cap < 1L) stop("There are insufficient observations for one VAR lag.")
  candidates <- lapply(seq_len(cap), function(p) {
    fit <- tryCatch(var_fit(y[seq.int(cap - p + 1L, n), , drop = FALSE], p), error = identity)
    if (inherits(fit, "error")) return(data.frame(lags = p, n = n - cap, parameters = k * k * p + k,
      log_determinant = NA_real_, AIC = NA_real_, BIC = NA_real_, estimable = FALSE, reason = conditionMessage(fit)))
    logdet <- as.numeric(determinant(fit$covariance_ml, logarithm = TRUE)$modulus)
    parameters <- k * k * p + k
    data.frame(lags = p, n = n - cap, parameters = parameters, log_determinant = logdet,
      AIC = logdet + 2 * parameters / (n - cap),
      BIC = logdet + log(n - cap) * parameters / (n - cap), estimable = TRUE, reason = "")
  })
  table <- do.call(rbind, candidates)
  if (!any(table$estimable)) stop("No lag candidate has an estimable VAR.")
  selected <- table$lags[which.min(replace(table$BIC, !table$estimable, Inf))]
  table$selected <- table$lags == selected
  list(lags = selected, table = table)
}

var_proxy <- function(fit, y, z, p, model) {
  mode <- model$proxy_residualization %||% "controls"
  if (identical(model$residualize_proxy, FALSE)) {
    if (!is.null(model$proxy_residualization) && mode != "none") stop("Proxy residualization settings conflict.")
    mode <- "none"
  }
  if (!mode %in% c("controls", "augmented_var", "none")) stop("Unknown model.proxy_residualization.")
  index <- seq.int(p + 1L, nrow(y))
  controls <- fit$x
  if (mode == "augmented_var") {
    lag_z <- vapply(seq_len(p), function(lag) z[index - lag], numeric(length(index)))
    controls <- cbind(controls, lag_z)
  }
  available <- is.finite(z[index])
  if (mode != "none") available <- available & apply(controls, 1L, function(row) all(is.finite(row)))
  selected <- index[available]
  u <- fit$residuals[available, , drop = FALSE]
  instrument <- z[selected]
  if (mode != "none") {
    x <- controls[available, , drop = FALSE]
    if (nrow(x) <= ncol(x) || qr(x)$rank != ncol(x)) stop("The proxy residualization design is not estimable.")
    instrument <- as.numeric(stats::lm.fit(x, instrument)$residuals)
  } else instrument <- instrument - mean(instrument)
  normalizer <- match(model$normalization_variable, colnames(y))
  if (length(instrument) < 3L || !is.finite(sum(instrument^2)) || sum(instrument^2) <= .Machine$double.eps * sum(z[selected]^2)) {
    stop("The available proxy sample has no instrument variation.")
  }
  covariance <- as.numeric(crossprod(u, instrument) / nrow(u))
  denominator <- covariance[normalizer]
  if (!is.finite(denominator) || abs(denominator) <= .Machine$double.eps * max(abs(covariance))) {
    stop("The proxy normalization denominator is zero.")
  }
  first <- stats::lm(u[, normalizer] ~ instrument)
  summary <- summary(first)
  f <- unname(summary$fstatistic[1L])
  list(impact = matrix(covariance / denominator * model$impact_target, ncol = 1L,
    dimnames = list(colnames(y), model$instrument)), diagnostics = list(
      residualization = mode, instrument_n = length(selected), instrument_rows = selected,
      instrument_sample_is_var_sample = identical(selected, index),
      first_stage_coefficient = unname(stats::coef(first)[2L]), first_stage_r_squared = summary$r.squared,
      first_stage_F = f, first_stage_df = unname(summary$fstatistic[2:3]),
      instrument_residual_correlation = stats::cor(instrument, u[, normalizer]),
      normalization_denominator = denominator), sample = data.frame(row = selected, instrument_residual = instrument))
}

var_impact <- function(fit, y, z, p, model) {
  variables <- colnames(y)
  k <- ncol(y)
  proxy <- NULL
  if (model$method == "reduced_form") {
    impact <- diag(k)
    dimnames(impact) <- list(variables, variables)
  } else if (model$method == "recursive") {
    sigma <- fit[[paste0("covariance_", model$covariance)]]
    impact <- t(chol(sigma[model$order, model$order, drop = FALSE]))
    impact <- impact[variables, , drop = FALSE]
  } else {
    proxy <- var_proxy(fit, y, z, p, model)
    impact <- proxy$impact
  }
  if (model$method != "proxy" && !is.null(model$impact_target)) {
    j <- match(model$normalization_variable, variables)
    shock <- match(model$normalization_shock %||% model$normalization_variable, colnames(impact))
    denominator <- impact[j, shock]
    if (!is.finite(denominator) || denominator == 0) stop("The impact normalization denominator is zero.")
    impact[, shock] <- impact[, shock] * model$impact_target / denominator
  }
  list(impact = impact, proxy = proxy)
}

var_irf <- function(coefficients, impact, horizons) {
  k <- nrow(impact)
  result <- array(0, c(k, ncol(impact), max(horizons) + 1L))
  result[, , 1L] <- impact
  if (max(horizons) > 0L) for (h in seq_len(max(horizons))) {
    for (lag in seq_len(min(h, length(coefficients)))) {
      result[, , h + 1L] <- result[, , h + 1L] + coefficients[[lag]] %*% matrix(result[, , h - lag + 1L], nrow = k)
    }
  }
  result[, , horizons + 1L, drop = FALSE]
}

var_bootstrap <- function(fit, y, p, model, inference, point) {
  draws <- inference$bootstrap_draws
  n <- nrow(fit$residuals)
  indices <- inference$resampling_indices
  if (!is.null(indices)) {
    if (is.list(indices) && !is.matrix(indices)) indices <- do.call(rbind, indices)
    indices <- as.matrix(indices)
    if (!identical(dim(indices), c(draws, n)) || anyNA(indices) || any(indices != floor(indices)) || any(indices < 1L | indices > n)) {
      stop("inference.resampling_indices must have bootstrap_draws rows and residual_n columns, with indices from 1 through residual_n.")
    }
  } else {
    set.seed(inference$seed)
    indices <- matrix(sample.int(n, n * draws, replace = TRUE), nrow = draws, byrow = TRUE)
  }
  residuals <- sweep(fit$residuals, 2L, colMeans(fit$residuals), "-")
  coefficients <- fit$coefficients
  intercept <- vars::Bcoef(fit$fit)[, "const"]
  paths <- matrix(NA_real_, nrow = length(point), ncol = draws)
  for (draw in seq_len(draws)) {
    paths[, draw] <- tryCatch({
      simulated <- y
      shocks <- residuals[indices[draw, ], , drop = FALSE]
      for (t in seq.int(p + 1L, nrow(y))) {
        value <- intercept + shocks[t - p, ]
        for (lag in seq_len(p)) value <- value + as.numeric(coefficients[[lag]] %*% simulated[t - lag, ])
        simulated[t, ] <- value
      }
      new_fit <- var_fit(simulated, p)
      impact <- var_impact(new_fit, simulated, NULL, p, model)$impact
      path <- as.numeric(var_irf(new_fit$coefficients, impact, model$horizons))
      if (any(!is.finite(path))) stop("The impulse response is not finite.")
      path
    }, error = function(error) stop("Bootstrap draw ", draw, " failed: ", conditionMessage(error), call. = FALSE))
  }
  alpha <- (1 - inference$level) / 2
  list(lower = apply(paths, 1L, stats::quantile, probs = alpha, type = 7L, names = FALSE),
       upper = apply(paths, 1L, stats::quantile, probs = 1 - alpha, type = 7L, names = FALSE))
}

run_var <- function(config, data) {
  if (!requireNamespace("vars", quietly = TRUE)) stop("Package vars is unavailable. Run the skill setup first.")
  model <- config$model
  variables <- unlist(model$variables, use.names = FALSE)
  if (length(variables) < 2L || anyDuplicated(variables) || anyNA(variables)) stop("model.variables needs at least two distinct names.")
  if (anyDuplicated(make.names(variables))) stop("Model variable names collide after R name conversion. Rename the input columns.")
  if (!is.null(config$data$unit)) stop("VAR supports one time series. Remove data.unit.")
  if (is.null(config$data$time) || !all(c(config$data$time, variables) %in% names(data))) stop("The time or model columns are missing.")
  var_time_index(data[[config$data$time]], config$data$frequency %||% "integer")
  if (!all(vapply(data[variables], is.numeric, logical(1L)))) stop("VAR variables must be numeric.")
  y <- as.matrix(data[variables])
  if (any(!is.finite(y))) stop("VAR variables must be complete and finite. Select a complete sample explicitly.")
  model$method <- model$method %||% "reduced_form"
  if (!model$method %in% c("reduced_form", "recursive", "proxy")) stop("Unknown model.method.")
  model$covariance <- model$covariance %||% "df_adjusted"
  if (!model$covariance %in% c("ml", "df_adjusted")) stop("model.covariance must be ml or df_adjusted.")
  model$horizons <- unlist(model$horizons %||% 0:10, use.names = FALSE)
  if (!length(model$horizons) || any(!is.finite(model$horizons)) || any(model$horizons < 0 | model$horizons != floor(model$horizons)) || anyDuplicated(model$horizons)) stop("Horizons must be distinct nonnegative integers.")
  model$order <- unlist(model$order, use.names = FALSE)
  if (model$method == "recursive" && (length(model$order) != length(variables) || anyDuplicated(model$order) || !setequal(model$order, variables))) {
    stop("Recursive identification needs model.order with every variable once.")
  }
  if (xor(is.null(model$normalization_variable), is.null(model$impact_target))) stop("Set normalization_variable and impact_target together.")
  if (!is.null(model$normalization_shock)) {
    if (model$method == "proxy") stop("Proxy VAR does not accept normalization_shock. Its instrument selects the only shock.")
    if (is.null(model$normalization_variable)) stop("normalization_shock needs normalization_variable and impact_target.")
    if (length(model$normalization_shock) != 1L || !model$normalization_shock %in% variables) stop("Unknown normalization_shock.")
  }
  if (!is.null(model$normalization_variable)) {
    if (length(model$normalization_variable) != 1L || !model$normalization_variable %in% variables) stop("Unknown normalization_variable.")
    if (length(model$impact_target) != 1L || !is.numeric(model$impact_target) || !is.finite(model$impact_target) || model$impact_target == 0) stop("impact_target must be finite and nonzero.")
    if (model$method != "proxy") model$normalization_shock <- model$normalization_shock %||% model$normalization_variable
  }
  inference <- config$inference %||% list()
  if (model$method == "proxy" && (isTRUE(inference$confidence_intervals) || isTRUE(inference$ci))) stop("Proxy VAR supports point estimates only. Confidence intervals are unavailable.")
  unknown <- setdiff(names(inference), c("level", "bootstrap_draws", "resampling_indices", "seed"))
  if (length(unknown)) stop("Unsupported inference setting: ", paste(unknown, collapse = ", "), ".")
  inference$level <- inference$level %||% 0.95
  if (length(inference$level) != 1L || !is.numeric(inference$level) || !is.finite(inference$level) || inference$level <= 0 || inference$level >= 1) stop("inference.level must be between zero and one.")
  inference$bootstrap_draws <- var_integer(inference$bootstrap_draws %||% if (model$method == "proxy") 0L else 1999L, "inference.bootstrap_draws")
  if (!is.null(inference$seed)) stop("Set the seed at the top level, not inference.seed.")
  config$seed <- var_integer(config$seed %||% 20261102L, "seed")
  inference$seed <- config$seed
  z <- NULL
  if (model$method == "proxy") {
    if (inference$bootstrap_draws > 0L || isTRUE(inference$confidence_intervals) || isTRUE(inference$ci)) stop("Proxy VAR supports point estimates only. Confidence intervals are unavailable.")
    if (is.null(model$normalization_variable)) stop("Proxy VAR needs normalization_variable and impact_target.")
    if (length(model$instrument) != 1L || !model$instrument %in% names(data) || model$instrument %in% variables) stop("Proxy VAR needs one separate instrument column.")
    z <- data[[model$instrument]]
    if (!is.numeric(z) || any(is.infinite(z))) stop("The instrument must be numeric. Only missing values may mark unavailable periods.")
  }
  selection <- var_select(y, model)
  p <- selection$lags
  model$lags <- p
  fit <- var_fit(y, p)
  stable <- all(fit$roots < 1)
  messages <- character()
  if (!stable) {
    messages <- "The VAR is unstable. Point estimates do not establish stationary responses."
    if (inference$bootstrap_draws > 0L) stop("The VAR is unstable. Stationary residual bootstrap is refused. Set bootstrap_draws to zero for point estimates.")
    warning(messages, call. = FALSE)
  }
  identification <- var_impact(fit, y, z, p, model)
  point <- var_irf(fit$coefficients, identification$impact, model$horizons)
  estimates <- expand.grid(response = variables, shock = colnames(identification$impact), horizon = model$horizons,
                           KEEP.OUT.ATTRS = FALSE, stringsAsFactors = FALSE)
  estimates$method <- model$method
  estimates$estimate <- as.numeric(point)
  estimates$lower <- estimates$upper <- NA_real_
  if (inference$bootstrap_draws > 0L) {
    interval <- var_bootstrap(fit, y, p, model, inference, point)
    estimates$lower <- interval$lower
    estimates$upper <- interval$upper
  }
  diagnostic <- list(method = model$method, variables = variables, lags = p, horizons = model$horizons,
    input_n = nrow(y), residual_n = nrow(fit$residuals), sample_start = as.character(data[[config$data$time]][p + 1L]),
    sample_end = as.character(tail(data[[config$data$time]], 1L)), rank = fit$rank, residual_df = fit$df,
    eigenvalue_moduli = fit$roots,
    eigenvalues = data.frame(real = Re(fit$eigenvalues), imaginary = Im(fit$eigenvalues), modulus = fit$roots),
    stable = stable, warnings = messages, covariance = model$covariance,
    normalization_variable = model$normalization_variable, normalization_shock = model$normalization_shock,
    impact_target = model$impact_target,
    bootstrap_draws = inference$bootstrap_draws, seed = inference$seed, level = inference$level,
    interval = if (inference$bootstrap_draws > 0L) "pointwise residual bootstrap percentile, quantile type 7" else "none",
    units = "Input units are preserved. No transformations are applied.", proxy = identification$proxy$diagnostics)
  config$model <- model
  inference$seed <- NULL
  config$inference <- inference
  covariance_table <- function(value) data.frame(response = rownames(value), value, check.names = FALSE, row.names = NULL)
  extra <- list(lag_selection = selection$table,
    residuals = data.frame(time = data[[config$data$time]][seq.int(p + 1L, nrow(y))], fit$residuals, check.names = FALSE),
    covariance_ml = covariance_table(fit$covariance_ml), covariance_df_adjusted = covariance_table(fit$covariance_df_adjusted),
    impact = covariance_table(identification$impact))
  if (!is.null(identification$proxy)) {
    extra$instrument_sample <- identification$proxy$sample
    extra$instrument_sample$time <- data[[config$data$time]][extra$instrument_sample$row]
  }
  list(estimates = estimates, diagnostics = diagnostic, extra = extra, resolved_config = config)
}
