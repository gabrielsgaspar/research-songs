suppressPackageStartupMessages({
  library(jsonlite)
  library(yaml)
  library(fixest)
  library(broom)
})

`%||%` <- function(x, y) {
  if (is.null(x)) y else x
}

normalize_to_char_vec <- function(x) {
  if (is.null(x)) return(character(0))
  if (length(x) == 0) return(character(0))
  as.character(unlist(x, use.names = FALSE))
}

assert_scalar_string <- function(x, field_name) {
  if (is.null(x) || length(x) != 1 || !is.character(x) || is.na(x) || nchar(x) == 0) {
    stop(sprintf("`%s` must be a non-empty string.", field_name), call. = FALSE)
  }
}

load_data_file <- function(path) {
  assert_scalar_string(path, "data.path")
  if (!file.exists(path)) {
    stop(sprintf("Data file not found: %s", path), call. = FALSE)
  }

  lower <- tolower(path)

  if (grepl("\\.parquet$", lower)) {
    if (!requireNamespace("arrow", quietly = TRUE)) {
      stop("Package `arrow` is required to read parquet files.", call. = FALSE)
    }
    return(as.data.frame(arrow::read_parquet(path)))
  }

  if (grepl("\\.feather$", lower)) {
    if (!requireNamespace("arrow", quietly = TRUE)) {
      stop("Package `arrow` is required to read feather files.", call. = FALSE)
    }
    return(as.data.frame(arrow::read_feather(path)))
  }

  if (grepl("\\.csv$", lower)) {
    if (!requireNamespace("readr", quietly = TRUE)) {
      stop("Package `readr` is required to read csv files.", call. = FALSE)
    }
    return(as.data.frame(readr::read_csv(path, show_col_types = FALSE)))
  }

  if (grepl("\\.rds$", lower)) {
    return(as.data.frame(readRDS(path)))
  }

  stop("Unsupported data format. Use .parquet, .feather, .csv, or .rds.", call. = FALSE)
}

validate_columns <- function(data, vars, label) {
  vars <- unique(vars[nzchar(vars)])
  if (length(vars) == 0) return(invisible(NULL))
  missing <- setdiff(vars, names(data))
  if (length(missing) > 0) {
    stop(sprintf("Missing %s column(s): %s", label, paste(missing, collapse = ", ")), call. = FALSE)
  }
}

build_feols_formula <- function(outcome, regressors, controls = character(0), fixed_effects = character(0)) {
  rhs_terms <- c(regressors, controls)
  rhs_terms <- rhs_terms[nzchar(rhs_terms)]
  if (length(rhs_terms) == 0) {
    rhs <- "1"
  } else {
    rhs <- paste(rhs_terms, collapse = " + ")
  }

  fe_terms <- fixed_effects[nzchar(fixed_effects)]
  if (length(fe_terms) > 0) {
    formula_string <- paste0(outcome, " ~ ", rhs, " | ", paste(fe_terms, collapse = " + "))
  } else {
    formula_string <- paste0(outcome, " ~ ", rhs)
  }

  list(
    formula = as.formula(formula_string),
    formula_string = formula_string
  )
}

extract_model_stats <- function(model) {
  fitstat_safe <- function(type) {
    out <- tryCatch(fixest::fitstat(model, type = type), error = function(e) NULL)
    if (is.null(out)) return(NULL)
    unname(as.numeric(out[[1]] %||% out))
  }

  list(
    nobs = tryCatch(stats::nobs(model), error = function(e) NULL),
    ncoefficients = tryCatch(length(stats::coef(model)), error = function(e) NULL),
    r2 = fitstat_safe("r2"),
    adj_r2 = fitstat_safe("ar2"),
    within_r2 = fitstat_safe("wr2"),
    adj_within_r2 = fitstat_safe("war2"),
    rmse = fitstat_safe("rmse")
  )
}

extract_fixef_sizes <- function(model) {
  sizes <- tryCatch(fixest::fixef_sizes(model), error = function(e) NULL)
  if (is.null(sizes)) return(list())
  as.list(sizes)
}

extract_coefficients <- function(model, conf_level = 0.95) {
  td <- broom::tidy(model, conf.int = TRUE, conf.level = conf_level)
  rows <- vector("list", nrow(td))
  if (nrow(td) == 0) return(rows)

  for (i in seq_len(nrow(td))) {
    rows[[i]] <- list(
      term = as.character(td$term[i]),
      estimate = unname(td$estimate[i]),
      std_error = unname(td$std.error[i]),
      statistic = if ("statistic" %in% names(td)) unname(td$statistic[i]) else NULL,
      p_value = if ("p.value" %in% names(td)) unname(td$p.value[i]) else NULL,
      conf_low = if ("conf.low" %in% names(td)) unname(td$conf.low[i]) else NULL,
      conf_high = if ("conf.high" %in% names(td)) unname(td$conf.high[i]) else NULL
    )
  }
  rows
}

write_json_pretty <- function(x, path) {
  jsonlite::write_json(x, path = path, pretty = TRUE, auto_unbox = TRUE, null = "null", digits = 16)
}
