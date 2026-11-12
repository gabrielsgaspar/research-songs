validate_config <- function(config) {
  supported <- c(
    "callaway_santanna",
    "sun_abraham",
    "bjs",
    "dcdh",
    "twfe_dynamic"
  )

  required_fields <- c("estimator", "data_path", "outcome", "unit_id", "time_id", "output_dir")
  missing_fields <- required_fields[vapply(required_fields, function(x) is.null(config[[x]]) || identical(config[[x]], ""), logical(1))]
  if (length(missing_fields) > 0) {
    stopf("Missing required config fields: %s", paste(missing_fields, collapse = ", "))
  }

  if (!config$estimator %in% supported) {
    stopf("Unsupported estimator `%s`.", config$estimator)
  }

  numeric_nonnegative <- c("lead", "lag", "anticipation", "effects", "placebo")
  for (nm in numeric_nonnegative) {
    if (!is.null(config[[nm]]) && config[[nm]] < 0) {
      stopf("`%s` must be non-negative.", nm)
    }
  }

  if (config$estimator %in% c("callaway_santanna", "sun_abraham", "bjs") && is.null(config$group_id)) {
    stopf("Estimator `%s` requires `group_id`.", config$estimator)
  }

  if (config$estimator == "twfe_dynamic" && is.null(config$group_id) && is.null(config$event_time_var)) {
    stopf("`twfe_dynamic` requires either `group_id` or `event_time_var`.")
  }

  if (config$estimator == "dcdh" && is.null(config$group_id) && is.null(config$treatment_var)) {
    stopf("`dcdh` requires either `group_id` or `treatment_var`.")
  }

  if (!is.null(config$control_group) && !config$control_group %in% c("nevertreated", "notyettreated")) {
    stopf("`control_group` must be either `nevertreated` or `notyettreated`.")
  }

  if (!is.null(config$plot$latex_figure_format) && !tolower(config$plot$latex_figure_format) %in% c("pdf", "png", "svg", "eps")) {
    stopf("`plot.latex_figure_format` must be one of: pdf, png, svg, eps.")
  }

  if (!is.null(config$plot$ci_level) && (config$plot$ci_level <= 0 || config$plot$ci_level >= 1)) {
    stopf("`plot.ci_level` must lie in (0, 1).")
  }

  invisible(config)
}

prepare_analysis_data <- function(data, config) {
  require_packages(c("dplyr", "tibble"))
  validate_config(config)

  needed <- unique(c(
    config$outcome,
    config$unit_id,
    config$time_id,
    config$group_id,
    config$treatment_var,
    unlist(config$cluster_var %||% character(0)),
    config$weights_var,
    config$event_time_var,
    config$controls,
    config$extra_fixed_effects
  ))
  needed <- needed[!is.null(needed) & !is.na(needed) & nzchar(needed)]

  missing_cols <- setdiff(needed, names(data))
  if (length(missing_cols) > 0) {
    stopf("Input data is missing required columns: %s", paste(missing_cols, collapse = ", "))
  }

  out <- as.data.frame(data)
  out$.__unit_id__ <- out[[config$unit_id]]
  if (any(is.na(out$.__unit_id__))) {
    stopf("`unit_id` contains missing values.")
  }

  out$.__time_id__ <- safe_numeric_vector(out[[config$time_id]], config$time_id, allow_na = FALSE)
  out$.__outcome__ <- safe_numeric_vector(out[[config$outcome]], config$outcome, allow_na = TRUE)

  if (anyDuplicated(out[c(".__unit_id__", ".__time_id__")]) > 0) {
    dup_n <- sum(duplicated(out[c(".__unit_id__", ".__time_id__")]))
    stopf("Found %s duplicate unit-time rows. Resolve duplicates before estimation.", dup_n)
  }

  standardized_group <- FALSE
  if (!is.null(config$group_id)) {
    out$.__group_id__ <- coerce_group_timing(
      out[[config$group_id]],
      config$group_id,
      never_treated_value = config$never_treated_value %||% NULL
    )
    out$.__group_id_cs__ <- ifelse(is.na(out$.__group_id__), 0, out$.__group_id__)
    standardized_group <- any(is.na(out[[config$group_id]]) & out$.__group_id_cs__ == 0) ||
      any(stats::na.omit(safe_numeric_vector(out[[config$group_id]], config$group_id, TRUE)) == 0)

    treated_groups <- stats::na.omit(unique(out$.__group_id__))
    if (length(treated_groups) == 0 && config$estimator %in% c("callaway_santanna", "sun_abraham", "bjs", "twfe_dynamic")) {
      stopf("No treated groups remain after standardizing `group_id`.")
    }
    if (length(treated_groups) > 0 && any(!treated_groups %in% unique(out$.__time_id__))) {
      warnf("Some `group_id` values are not observed in `time_id`. Check treatment timing support.")
    }
  } else {
    out$.__group_id__ <- NA_real_
    out$.__group_id_cs__ <- 0
  }

  if (!is.null(config$treatment_var)) {
    out$.__treatment_input__ <- out[[config$treatment_var]]
  }

  if (!is.null(config$weights_var)) {
    out$.__weights__ <- coerce_weights(out[[config$weights_var]], config$weights_var)
  }

  if (!is.null(config$event_time_var)) {
    out$.__event_time_input__ <- safe_numeric_vector(out[[config$event_time_var]], config$event_time_var, allow_na = TRUE)
  }

  complete_outcome_rows <- sum(!is.na(out$.__outcome__))
  min_time <- min(out$.__time_id__, na.rm = TRUE)
  max_time <- max(out$.__time_id__, na.rm = TRUE)
  n_units <- dplyr::n_distinct(out$.__unit_id__)
  n_periods <- dplyr::n_distinct(out$.__time_id__)
  n_rows <- nrow(out)
  n_treated_units <- if (!is.null(config$group_id)) {
    dplyr::n_distinct(out$.__unit_id__[!is.na(out$.__group_id__)])
  } else {
    NA_integer_
  }
  n_never_treated_units <- if (!is.null(config$group_id)) {
    dplyr::n_distinct(out$.__unit_id__[is.na(out$.__group_id__)])
  } else {
    NA_integer_
  }

  if (config$estimator %in% c("sun_abraham", "twfe_dynamic", "bjs")) {
    if (!is.null(config$lead) && min_time == max_time) {
      stopf("Dynamic estimator requested but only one time period is present.")
    }
  }

  diagnostics <- tibble::tibble(
    metric = c(
      "n_rows",
      "n_complete_outcome_rows",
      "n_units",
      "n_periods",
      "min_time",
      "max_time",
      "n_treated_units",
      "n_never_treated_units",
      "group_id_standardized_from_zero_or_na"
    ),
    value = c(
      n_rows,
      complete_outcome_rows,
      n_units,
      n_periods,
      min_time,
      max_time,
      n_treated_units,
      n_never_treated_units,
      standardized_group
    ),
    notes = c(
      "Rows in the input analysis sample.",
      "Rows with non-missing outcome.",
      "Distinct units after validation.",
      "Distinct time periods after validation.",
      "Minimum observed time value.",
      "Maximum observed time value.",
      "Units with non-missing first-treatment timing.",
      "Units standardized as never treated.",
      "TRUE means the scripts converted 0 or NA into the internal never-treated representation."
    )
  )

  list(data = out, diagnostics = diagnostics)
}
