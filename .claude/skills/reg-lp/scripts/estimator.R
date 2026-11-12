# Calendar-indexed local projections. No package installation occurs here.

`%||%` <- function(x, y) if (is.null(x)) y else x

lp_names <- function(x) {
  if (!length(x)) return(character())
  x <- unlist(x %||% character(), use.names = FALSE)
  if (!is.character(x) || anyNA(x) || any(!nzchar(x)) || any(grepl("[`\r\n]", x))) {
    stop("Column names must be nonempty strings without backticks or line breaks.")
  }
  unique(x)
}

lp_integer <- function(x, name, minimum = 0L) {
  if (!is.numeric(x) || !length(x) || anyNA(x) || any(!is.finite(x)) ||
      any(x != floor(x)) || any(x < minimum) || any(x > .Machine$integer.max)) stop(name, " must contain supported integers >= ", minimum, ".")
  as.integer(x)
}

lp_period <- function(x, frequency) {
  if (frequency %in% c("integer", "annual") && is.numeric(x)) {
    return(lp_integer(x, "Time", minimum = -2147483647L))
  }
  s <- as.character(x)
  if (anyNA(s)) stop("Time values cannot be missing.")
  if (frequency == "annual" && all(grepl("^[0-9]{4}$", s))) return(as.integer(s))
  if (frequency == "quarterly" && all(grepl("^[0-9]{4}-Q[1-4]$", s))) {
    return(as.integer(substr(s, 1, 4)) * 4L + as.integer(substr(s, 7, 7)) - 1L)
  }
  if (frequency == "monthly" && all(grepl("^[0-9]{4}-(0[1-9]|1[0-2])$", s))) {
    return(as.integer(substr(s, 1, 4)) * 12L + as.integer(substr(s, 6, 7)) - 1L)
  }
  if (frequency == "integer" || !all(grepl("^[0-9]{4}-[0-9]{2}-[0-9]{2}$", s))) {
    stop("Use integer periods, annual YYYY, quarterly YYYY-Qn, monthly YYYY-MM, or ISO dates.")
  }
  d <- suppressWarnings(as.Date(s, format = "%Y-%m-%d"))
  if (anyNA(d) || any(format(d, "%Y-%m-%d") != s)) stop("Invalid calendar date.")
  year <- as.integer(format(d, "%Y"))
  month <- as.integer(format(d, "%m"))
  switch(frequency, annual = year, quarterly = year * 4L + (month - 1L) %/% 3L,
         monthly = year * 12L + month - 1L)
}

lp_config <- function(config) {
  if (!is.null(config$runtime$seed)) stop("Use the top-level seed field, not runtime.seed.")
  config$seed <- lp_integer(config$seed %||% 20261102L, "seed")
  if (length(config$seed) != 1L) stop("seed must be a scalar.")
  d <- config$data %||% list()
  m <- config$model %||% list()
  inf <- config$inference %||% list()
  d$time <- lp_names(d$time)
  d$unit <- lp_names(d$unit)
  if (length(d$time) != 1L || length(d$unit) > 1L) stop("Set one time column and at most one unit column.")
  d$frequency <- match.arg(d$frequency %||% "integer", c("integer", "annual", "quarterly", "monthly"))
  m$outcome <- lp_names(m$outcome)
  m$shock <- lp_names(m$shock)
  m$instrument <- lp_names(m$instrument)
  if (length(m$outcome) != 1L || length(m$shock) != 1L) stop("Set one outcome and one shock.")
  m$method <- match.arg(m$method %||% "ordinary", c("ordinary", "lag_augmented", "iv", "pmw_ratio"))
  m$response <- match.arg(m$response %||% "level", c("level", "cumulative_change", "cumulative_sum"))
  m$controls <- lp_names(m$controls)
  m$lagged_controls <- lp_names(m$lagged_controls %||% c(m$outcome, m$shock))
  m$lags <- lp_integer(m$lags %||% 1L, "model.lags")
  if (length(m$lags) != 1L) stop("model.lags must be a scalar.")
  m$horizons <- sort(unique(lp_integer(unlist(m$horizons %||% 0:10), "model.horizons")))
  panel <- length(d$unit) == 1L
  m$fixed_effects <- lp_names(m$fixed_effects %||% if (panel) c(d$unit, d$time) else character())
  if (!panel && length(m$fixed_effects)) stop("Time-series fixed effects are not supported in v1.")
  instrumental <- m$method %in% c("iv", "pmw_ratio")
  if (instrumental && length(m$instrument) != 1L) stop("This method requires one model.instrument.")
  if (!instrumental && length(m$instrument)) stop("Use method iv or pmw_ratio with an instrument.")
  if (panel && m$method != "ordinary") stop("Panel v1 supports only ordinary local projections.")
  if (m$method == "pmw_ratio") {
    if (m$lags < 1L) stop("pmw_ratio requires at least one lag, including the instrument.")
    m$lagged_controls <- unique(c(m$lagged_controls, m$instrument))
  }
  if (m$shock %in% m$controls || (instrumental && m$instrument %in% c(m$controls, m$shock))) {
    stop("Shock, instrument, and contemporaneous controls must be distinct.")
  }
  inf$level <- inf$level %||% 0.95
  if (!is.numeric(inf$level) || length(inf$level) != 1L || is.na(inf$level) ||
      inf$level <= 0 || inf$level >= 1) stop("inference.level must be between zero and one.")
  inf$covariance <- match.arg(inf$covariance %||% "auto", c("auto", "NW", "HC1", "cluster", "iid"))
  if (inf$covariance == "auto") inf$covariance <- if (panel) "cluster" else if (m$method == "lag_augmented") "HC1" else "NW"
  if (panel && inf$covariance == "NW") stop("Panel Newey-West inference is not supported in v1.")
  if (!panel && inf$covariance == "cluster") stop("Cluster inference requires panel data.")
  if (m$method == "lag_augmented" && inf$covariance != "HC1") stop("lag_augmented requires HC1 inference.")
  inf$cluster <- lp_names(inf$cluster %||% if (panel) c(d$unit, d$time) else character())
  if (inf$covariance == "cluster" && !length(inf$cluster)) stop("Set cluster columns.")
  inf$small_sample <- inf$small_sample %||% FALSE
  if (!is.logical(inf$small_sample) || length(inf$small_sample) != 1L || is.na(inf$small_sample)) stop("inference.small_sample must be true or false.")
  inf$nw_lag <- inf$nw_lag %||% "horizon_plus_one"
  if (!identical(inf$nw_lag, "horizon_plus_one")) {
    inf$nw_lag <- lp_integer(inf$nw_lag, "inference.nw_lag")
    if (length(inf$nw_lag) != 1L) stop("inference.nw_lag must be a scalar.")
  }
  config$data <- d
  config$model <- m
  config$inference <- inf
  config
}

lp_formula <- function(dependent, regressors, effects = character(), instrument = NULL) {
  rhs <- if (length(regressors)) paste(regressors, collapse = " + ") else "1"
  formula <- paste(dependent, "~", rhs)
  if (length(effects)) formula <- paste(formula, "|", paste(effects, collapse = " + "))
  if (!is.null(instrument)) formula <- paste(formula, if (length(effects)) "|" else "| 0 |", "shock ~ instrument")
  stats::as.formula(formula)
}

lp_fit <- function(formula, frame) {
  plain_ols <- !grepl("|", paste(deparse(formula), collapse = " "), fixed = TRUE)
  response <- if (plain_ols) frame[[as.character(formula[[2]])]] else NULL
  if (plain_ols && length(unique(response)) == 1L) {
    # feols rejects constant responses, but its matrix estimator permits their full-rank designs.
    fit <- fixest::feols.fit(y = response, X = stats::model.matrix(formula, frame), notes = FALSE, warn = FALSE)
  } else fit <- fixest::feols(formula, data = frame, fixef.rm = "none", notes = FALSE, warn = FALSE)
  if (length(fit$collin.var)) stop("Collinear model columns: ", paste(fit$collin.var, collapse = ", "))
  if (stats::nobs(fit) != nrow(frame)) stop("The estimator changed the prepared sample.")
  if (nrow(frame) <= fit$nparams) stop("Insufficient observations for residual degrees of freedom.")
  if (any(!is.finite(stats::coef(fit)))) stop("Non-finite regression coefficients.")
  fit
}

lp_ts_vcov <- function(fit, frame, regressors, kind, bandwidth, correction, iv = FALSE) {
  X <- stats::model.matrix(stats::reformulate(regressors), frame)
  if (iv) {
    Z <- stats::model.matrix(stats::reformulate(c(setdiff(regressors, "shock"), "instrument")), frame)
    Xhat <- qr.fitted(qr(Z), X)
  } else Xhat <- X
  if (qr(Xhat)$rank != ncol(Xhat)) stop("Singular regressor matrix or zero first stage.")
  bread <- solve(crossprod(Xhat))
  u <- stats::residuals(fit)
  n <- nrow(Xhat)
  k <- ncol(Xhat)
  if (kind == "iid") return(bread * sum(u^2) / (n - k))
  scores <- Xhat * as.numeric(u)
  meat <- crossprod(scores)
  if (kind == "NW" && bandwidth > 0L) {
    for (lag in seq_len(bandwidth)) {
      previous <- match(frame$period - lag, frame$period)
      valid <- which(!is.na(previous))
      if (length(valid)) {
        gamma <- crossprod(scores[valid, , drop = FALSE], scores[previous[valid], , drop = FALSE])
        meat <- meat + (1 - lag / (bandwidth + 1)) * (gamma + t(gamma))
      }
    }
  }
  scale <- if (kind == "HC1" || correction) n / (n - k) else 1
  bread %*% meat %*% bread * scale
}

run_lp <- function(config, data) {
  if (!requireNamespace("fixest", quietly = TRUE)) stop("Run scripts/setup.R before estimation; fixest is missing.")
  config <- lp_config(config)
  set.seed(config$seed)
  d <- config$data
  m <- config$model
  inf <- config$inference
  panel <- length(d$unit) == 1L
  needed <- unique(c(d$time, d$unit, m$outcome, m$shock, m$instrument, m$controls,
                     m$lagged_controls, m$fixed_effects, if (inf$covariance == "cluster") inf$cluster))
  if (!is.data.frame(data) || anyDuplicated(names(data))) stop("Input must have unique column names.")
  if (length(setdiff(needed, names(data)))) stop("Missing columns: ", paste(setdiff(needed, names(data)), collapse = ", "))
  numeric_columns <- unique(c(m$outcome, m$shock, m$instrument, m$controls, m$lagged_controls))
  for (name in numeric_columns) {
    if (!is.numeric(data[[name]]) || any(is.infinite(data[[name]]))) stop("Use numeric values or NA in ", name, ".")
  }
  period <- lp_period(data[[d$time]], d$frequency)
  unit <- if (panel) as.character(data[[d$unit]]) else rep("series", nrow(data))
  if (anyNA(unit) || any(!nzchar(unit)) || any(grepl("\r", unit))) stop("Unit identifiers must be nonempty and cannot contain carriage returns.")
  key <- paste(unit, period, sep = "\r")
  if (anyDuplicated(key)) stop("Duplicate unit-period keys.")
  order <- order(unit, period)
  data <- data[order, , drop = FALSE]
  period <- period[order]
  unit <- unit[order]
  key <- key[order]
  lookup <- function(column, offset) data[[column]][match(paste(unit, period + offset, sep = "\r"), key)]
  frame <- data.frame(period = period, shock = data[[m$shock]])
  regressors <- "shock"
  for (j in seq_along(m$controls)) {
    name <- paste0("control", j)
    frame[[name]] <- data[[m$controls[j]]]
    regressors <- c(regressors, name)
  }
  actual_lags <- m$lags + as.integer(m$method == "lag_augmented")
  if (actual_lags > 0L) for (lag in seq_len(actual_lags)) for (j in seq_along(m$lagged_controls)) {
    name <- paste0("lag", lag, "_", j)
    frame[[name]] <- lookup(m$lagged_controls[j], -lag)
    regressors <- c(regressors, name)
  }
  effect_names <- if (length(m$fixed_effects)) paste0("effect", seq_along(m$fixed_effects)) else character()
  for (j in seq_along(effect_names)) {
    frame[[effect_names[j]]] <- if (m$fixed_effects[j] == d$time) period else data[[m$fixed_effects[j]]]
  }
  cluster_names <- if (inf$covariance == "cluster") paste0("cluster", seq_along(inf$cluster)) else character()
  for (j in seq_along(cluster_names)) {
    frame[[cluster_names[j]]] <- if (inf$cluster[j] == d$time) period else data[[inf$cluster[j]]]
  }
  instrumental <- m$method %in% c("iv", "pmw_ratio")
  if (instrumental) frame$instrument <- data[[m$instrument]]
  normalizer <- NULL
  first_stage <- list()
  if (m$method == "pmw_ratio") {
    fs_frame <- frame[stats::complete.cases(frame), , drop = FALSE]
    fs_regressors <- c("instrument", setdiff(regressors, "shock"))
    fs_fit <- lp_fit(lp_formula("shock", fs_regressors), fs_frame)
    normalizer <- unname(stats::coef(fs_fit)["instrument"])
    if (!is.finite(normalizer) || normalizer == 0) stop("Zero first-stage normalization coefficient.")
    first_stage$normalization <- list(estimate = normalizer, nobs = nrow(fs_frame),
                                     period = fs_frame$period, formula = deparse(stats::formula(fs_fit)))
  }
  estimates <- diagnostics <- samples <- formulas <- list()
  for (h in m$horizons) {
    fh <- frame
    fh$response <- switch(m$response, level = lookup(m$outcome, h),
      cumulative_change = lookup(m$outcome, h) - lookup(m$outcome, -1L),
      cumulative_sum = Reduce(`+`, lapply(0:h, function(offset) lookup(m$outcome, offset))))
    required <- if (m$method == "pmw_ratio") setdiff(names(fh), "shock") else names(fh)
    valid <- stats::complete.cases(fh[required])
    fh <- fh[valid, , drop = FALSE]
    if (!nrow(fh)) stop("No complete observations at horizon ", h, ".")
    rhs <- if (m$method == "iv") setdiff(regressors, "shock") else if (m$method == "pmw_ratio") c("instrument", setdiff(regressors, "shock")) else regressors
    formula <- lp_formula("response", rhs, effect_names, if (m$method == "iv") TRUE else NULL)
    iv_ols_limit <- FALSE
    if (m$method == "iv") {
      X <- stats::model.matrix(stats::reformulate(c("shock", rhs)), fh)
      Z <- stats::model.matrix(stats::reformulate(c("instrument", rhs)), fh)
      if (qr(Z)$rank == ncol(Z) && qr(X)$rank == ncol(X)) {
        projected <- qr.fitted(qr(Z), X)
        iv_ols_limit <- all(colSums((projected - X)^2) <= (100 * .Machine$double.eps)^2 * colSums(X^2))
      }
    }
    # A perfect full-rank first stage makes 2SLS equal OLS; feols rejects its IV formula.
    fit <- lp_fit(if (iv_ols_limit) lp_formula("response", c("shock", rhs)) else formula, fh)
    coefficient <- if (m$method == "iv" && !iv_ols_limit) "fit_shock" else if (m$method == "pmw_ratio") "instrument" else "shock"
    beta <- unname(stats::coef(fit)[coefficient])
    if (!length(beta) || !is.finite(beta)) stop("The shock coefficient is unavailable at horizon ", h, ".")
    bandwidth <- if (identical(inf$nw_lag, "horizon_plus_one")) h + 1L else inf$nw_lag
    df <- Inf
    if (m$method == "pmw_ratio") {
      beta <- beta / normalizer
      se <- lower <- upper <- pvalue <- NA_real_
      covariance <- "point_only"
    } else {
      covariance <- inf$covariance
      if (panel) {
        ssc <- fixest::ssc(K.adj = TRUE, K.fixef = "nonnested", G.adj = TRUE, G.df = "min", t.df = "min")
        if (covariance == "cluster") {
          counts <- vapply(fh[cluster_names], function(x) length(unique(x)), integer(1))
          if (any(counts < 2L)) stop("Each cluster dimension needs at least two groups.")
          vc <- stats::vcov(fit, cluster = stats::reformulate(cluster_names), ssc = ssc)
          df <- min(counts) - 1L
        } else {
          vc <- stats::vcov(fit, vcov = if (covariance == "HC1") "hetero" else "iid", ssc = ssc)
          df <- fixest::degrees_freedom(fit, type = "t", vcov = if (covariance == "HC1") "hetero" else "iid", ssc = ssc)
        }
        variance <- vc[coefficient, coefficient]
      } else {
        vc <- lp_ts_vcov(fit, fh, if (m$method == "iv") c("shock", rhs) else rhs,
                         covariance, bandwidth, inf$small_sample, m$method == "iv")
        variance <- vc[if (m$method == "iv") "shock" else coefficient, if (m$method == "iv") "shock" else coefficient]
      }
      if (h == 0L && m$response == "level" && m$outcome == m$shock &&
          m$method %in% c("ordinary", "lag_augmented")) {
        beta <- 1
        variance <- 0
      }
      if (!is.finite(variance) || variance < 0) stop("Invalid coefficient variance at horizon ", h, ".")
      se <- sqrt(variance)
      critical <- stats::qt((1 + inf$level) / 2, df = df)
      lower <- beta - critical * se
      upper <- beta + critical * se
      pvalue <- if (se == 0) NA_real_ else 2 * stats::pt(-abs(beta / se), df = df)
    }
    first_f <- first_partial_r2 <- NA_real_
    if (m$method == "iv") {
      fs_rhs <- c("instrument", rhs)
      fs_fit <- lp_fit(lp_formula("shock", fs_rhs), fh)
      fs_beta <- unname(stats::coef(fs_fit)["instrument"])
      if (!is.finite(fs_beta) || fs_beta == 0) stop("Zero first-stage coefficient at horizon ", h, ".")
      if (!iv_ols_limit) {
        fs_vc <- lp_ts_vcov(fs_fit, fh, fs_rhs, covariance, bandwidth, inf$small_sample)
        first_f <- fs_beta^2 / fs_vc["instrument", "instrument"]
      }
      restricted <- stats::lm(stats::reformulate(rhs, "shock"), fh)
      first_partial_r2 <- if (iv_ols_limit) 1 else 1 - sum(stats::residuals(fs_fit)^2) / sum(stats::residuals(restricted)^2)
      first_stage[[as.character(h)]] <- list(coefficient = fs_beta, robust_wald_f = first_f, partial_r2 = first_partial_r2,
                                            perfect_first_stage = iv_ols_limit, nobs = nrow(fh), formula = deparse(stats::formula(fs_fit)))
    }
    estimates[[length(estimates) + 1L]] <- data.frame(horizon = h, estimate = beta, std_error = se,
      lower = lower, upper = upper, p_value = pvalue, nobs = nrow(fh), method = m$method,
      response = m$response, covariance = covariance, nw_lag = if (covariance == "NW") bandwidth else NA_integer_,
      small_sample = if (covariance == "NW") inf$small_sample else NA, df = df)
    diagnostics[[length(diagnostics) + 1L]] <- data.frame(horizon = h, input_rows = nrow(data), nobs = nrow(fh),
      excluded_rows = sum(!valid), first_stage_wald_f = first_f, first_stage_partial_r2 = first_partial_r2,
      first_stage_perfect = if (m$method == "iv") iv_ols_limit else NA,
      normalizer = if (is.null(normalizer)) NA_real_ else normalizer, residual_df = nrow(fh) - fit$nparams,
      actual_lags = actual_lags)
    samples[[length(samples) + 1L]] <- data.frame(horizon = h, input_row = order[valid], unit = unit[valid],
      time = as.character(data[[d$time]][valid]), period = period[valid], stringsAsFactors = FALSE)
    formulas[[as.character(h)]] <- paste(deparse(formula), collapse = " ")
  }
  list(estimates = do.call(rbind, estimates), diagnostics = do.call(rbind, diagnostics),
       extra = list(sample_ids = do.call(rbind, samples), formulas = formulas, first_stage = first_stage),
       resolved_config = config)
}
