args <- commandArgs(trailingOnly = FALSE)
script <- sub("^--file=", "", args[grepl("^--file=", args)])[1]
root <- normalizePath(file.path(dirname(script), ".."), mustWork = TRUE)
source(file.path(root, "scripts", "runtime.R"))
runtime_init(root)
source(file.path(root, "scripts", "estimator.R"))

near <- function(x, y, tolerance = 1e-8) stopifnot(isTRUE(all.equal(unname(x), unname(y), tolerance = tolerance)))
fails <- function(expr) {
  result <- NULL
  invisible(utils::capture.output(result <- tryCatch(force(expr), error = identity)))
  stopifnot(inherits(result, "error"))
}
set.seed(20261102)
n <- 240L
dat <- data.frame(t = seq_len(n), z = rnorm(n), w = rnorm(n))
dat$x <- 0.8 * dat$z + rnorm(n)
dat$y <- as.numeric(stats::filter(0.7 * dat$x + 0.2 * dat$w + rnorm(n), 0.5, method = "recursive"))
cfg <- list(data = list(time = "t", frequency = "integer"), model = list(outcome = "y", shock = "x", horizons = 0:3))
r <- run_lp(cfg, dat)
stopifnot(nrow(r$estimates) == 4L, all(r$estimates$nobs == n - 1L - (0:3)))
f <- data.frame(y = dat$y[-1], x = dat$x[-1], yl = dat$y[-n], xl = dat$x[-n])
ref <- stats::lm(y ~ x + yl + xl, f)
near(r$estimates$estimate[1], stats::coef(ref)["x"])
own <- cfg
own$model$outcome <- "x"
own_result <- run_lp(own, dat)
near(own_result$estimates$estimate[1], 1)
stopifnot(own_result$estimates$std_error[1] == 0,
          own_result$estimates$lower[1] == own_result$estimates$upper[1],
          is.na(own_result$estimates$p_value[1]), all(is.finite(own_result$estimates$estimate[-1])))
zero_outcome <- dat
zero_outcome$zero <- 0
zero_config <- cfg
zero_config$model$outcome <- "zero"
zero_config$model$lagged_controls <- "x"
zero_result <- run_lp(zero_config, zero_outcome)
stopifnot(all(zero_result$estimates$estimate == 0), all(zero_result$estimates$std_error == 0),
          all(zero_result$estimates$lower == 0), all(zero_result$estimates$upper == 0),
          all(is.na(zero_result$estimates$p_value)))
X <- stats::model.matrix(ref)
S <- X * stats::residuals(ref)
G <- crossprod(S) + 0.5 * (crossprod(S[-1, ], S[-nrow(S), ]) + crossprod(S[-nrow(S), ], S[-1, ]))
V <- solve(crossprod(X)) %*% G %*% solve(crossprod(X))
near(r$estimates$std_error[1], sqrt(V["x", "x"]))
corrected <- cfg
corrected$inference <- list(small_sample = TRUE)
rc <- run_lp(corrected, dat)
near(rc$estimates$std_error[1] / r$estimates$std_error[1], sqrt(nrow(f) / stats::df.residual(ref)))

for (response in c("cumulative_change", "cumulative_sum")) {
  c2 <- cfg
  c2$model$response <- response
  rr <- run_lp(c2, dat)
  ids <- rr$extra$sample_ids$input_row[rr$extra$sample_ids$horizon == 2]
  target <- if (response == "cumulative_change") dat$y[ids + 2] - dat$y[ids - 1] else dat$y[ids] + dat$y[ids + 1] + dat$y[ids + 2]
  rf <- stats::lm(target ~ dat$x[ids] + dat$y[ids - 1] + dat$x[ids - 1])
  near(rr$estimates$estimate[rr$estimates$horizon == 2], stats::coef(rf)[2])
}
gap <- dat[dat$t != 80, ]
rg <- run_lp(cfg, gap)
stopifnot(!79 %in% rg$extra$sample_ids$time[rg$extra$sample_ids$horizon == 1],
          !81 %in% rg$extra$sample_ids$time[rg$extra$sample_ids$horizon == 0])
ids <- rg$extra$sample_ids$input_row[rg$extra$sample_ids$horizon == 1]
times <- gap$t[ids]
gf <- data.frame(y = gap$y[match(times + 1, gap$t)], x = gap$x[ids],
                 yl = gap$y[match(times - 1, gap$t)], xl = gap$x[match(times - 1, gap$t)])
gm <- stats::lm(y ~ x + yl + xl, gf)
GX <- stats::model.matrix(gm)
GS <- GX * stats::residuals(gm)
GG <- crossprod(GS)
for (j in 1:2) {
  pair <- match(times - j, times)
  take <- which(!is.na(pair))
  C <- crossprod(GS[take, ], GS[pair[take], ])
  GG <- GG + (1 - j / 3) * (C + t(C))
}
GV <- solve(crossprod(GX)) %*% GG %*% solve(crossprod(GX))
near(rg$estimates$std_error[2], sqrt(GV["x", "x"]))
gapcfg <- cfg
gapcfg$model$response <- "cumulative_sum"
rs <- run_lp(gapcfg, gap)
stopifnot(!79 %in% rs$extra$sample_ids$time[rs$extra$sample_ids$horizon == 2])
shuffled <- dat[sample(n), ]
near(run_lp(cfg, shuffled)$estimates$estimate, r$estimates$estimate)

la <- cfg
la$model$method <- "lag_augmented"
rl <- run_lp(la, dat)
stopifnot(all(rl$estimates$covariance == "HC1"), all(rl$diagnostics$actual_lags == 2L))

iv <- cfg
iv$model$method <- "iv"
iv$model$instrument <- "z"
ri <- run_lp(iv, dat)
ids <- ri$extra$sample_ids$input_row[ri$extra$sample_ids$horizon == 2]
X <- cbind(1, dat$x[ids], dat$y[ids - 1], dat$x[ids - 1])
Z <- cbind(1, dat$z[ids], dat$y[ids - 1], dat$x[ids - 1])
Xh <- Z %*% solve(crossprod(Z), crossprod(Z, X))
b <- solve(crossprod(Xh), crossprod(Xh, dat$y[ids + 2]))
near(ri$estimates$estimate[ri$estimates$horizon == 2], b[2])
stopifnot(all(is.finite(ri$diagnostics$first_stage_wald_f)))
exact_iv <- iv
exact_data <- dat
exact_data$g <- exact_data$x
exact_iv$model$instrument <- "g"
exact_iv$model$response <- "cumulative_sum"
exact_ols <- exact_iv
exact_ols$model$method <- "ordinary"
exact_ols$model$instrument <- NULL
exact_result <- run_lp(exact_iv, exact_data)
ols_result <- run_lp(exact_ols, exact_data)
near(exact_result$estimates$estimate, ols_result$estimates$estimate)
near(exact_result$estimates$std_error, ols_result$estimates$std_error)
stopifnot(all(exact_result$estimates$method == "iv"),
          all(exact_result$diagnostics$first_stage_perfect),
          all(is.na(exact_result$diagnostics$first_stage_wald_f)),
          all(exact_result$diagnostics$first_stage_partial_r2 == 1))
ratio <- iv
ratio$model$method <- "pmw_ratio"
rr <- run_lp(ratio, dat)
ids <- 2:n
fs <- stats::lm(dat$x[ids] ~ dat$z[ids] + dat$y[ids - 1] + dat$x[ids - 1] + dat$z[ids - 1])
ids <- 2:(n - 2L)
rf <- stats::lm(dat$y[ids + 2] ~ dat$z[ids] + dat$y[ids - 1] + dat$x[ids - 1] + dat$z[ids - 1])
near(rr$estimates$estimate[rr$estimates$horizon == 2], stats::coef(rf)[2] / stats::coef(fs)[2])
stopifnot(all(is.na(rr$estimates$std_error)))
missing_shock <- dat
missing_shock$x[100] <- NA
rm <- run_lp(ratio, missing_shock)
stopifnot(100 %in% rm$extra$sample_ids$input_row[rm$extra$sample_ids$horizon == 0],
          !101 %in% rm$extra$sample_ids$input_row[rm$extra$sample_ids$horizon == 0])

panel <- do.call(rbind, lapply(1:8, function(i) {
  p <- dat
  p$unit <- paste0("u", i)
  p$x <- p$x + rnorm(n)
  p$y <- p$y + i + rnorm(n)
  p
}))
pc <- cfg
pc$data$unit <- "unit"
rp <- run_lp(pc, panel)
stopifnot(all(rp$estimates$covariance == "cluster"), all(rp$estimates$df == 7L))
ids <- which(panel$t > 1)
pf <- panel[ids, ]
pf$yl <- panel$y[ids - 1]
pf$xl <- panel$x[ids - 1]
manual <- fixest::feols(y ~ x + yl + xl | unit + t, pf, fixef.rm = "none")
near(rp$estimates$estimate[1], stats::coef(manual)["x"])
vc <- stats::vcov(manual, cluster = ~unit + t,
                 ssc = fixest::ssc(K.adj = TRUE, K.fixef = "nonnested", G.adj = TRUE, G.df = "min", t.df = "min"))
near(rp$estimates$std_error[1], sqrt(vc["x", "x"]))
quarterly <- panel
year <- 2000L + (panel$t - 1L) %/% 4L
quarter <- (panel$t - 1L) %% 4L + 1L
quarterly$t <- sprintf("%04d-Q%d", year, quarter)
dates <- quarterly
early <- as.integer(sub("u", "", panel$unit)) %% 2L == 1L
dates$t <- sprintf("%04d-%02d-%02d", year, (quarter - 1L) * 3L + ifelse(early, 1L, 3L),
                   ifelse(early, 1L, c(31L, 30L, 30L, 31L)[quarter]))
quarter_config <- pc
quarter_config$data$frequency <- "quarterly"
rq <- run_lp(quarter_config, quarterly)
rd <- run_lp(quarter_config, dates)
near(rd$estimates$estimate, rq$estimates$estimate)
near(rd$estimates$std_error, rq$estimates$std_error)
near(rd$estimates$df, rq$estimates$df)
pooled <- pc
pooled$model$fixed_effects <- list()
pooled$model$controls <- list()
stopifnot(nrow(run_lp(pooled, panel)$estimates) == 4L)

fails(run_lp(cfg, rbind(dat, dat[1, ])))
bad <- cfg
bad$model$controls <- "x"
fails(run_lp(bad, dat))
bad <- iv
bad$data$unit <- "unit"
fails(run_lp(bad, panel))
zero <- dat
zero$z <- 1
fails(run_lp(iv, zero))
short <- dat[1:4, ]
fails(run_lp(cfg, short))
near(lp_period(c("2000-12", "2001-01"), "monthly"), c(24011L, 24012L))
near(lp_period(c("2000-Q4", "2001-Q1"), "quarterly"), c(8003L, 8004L))
fails(lp_period("2020-02-31", "monthly"))
cat("Local projection self-checks passed.\n")
