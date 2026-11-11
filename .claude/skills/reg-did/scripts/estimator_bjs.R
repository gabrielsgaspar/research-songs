run_bjs <- function(data, config) {
  require_packages(c("didimputation", "dplyr", "tibble", "ggplot2"))

  event_time_step <- as.numeric(config$event_time_step %||% 1)
  horizon <- if (!is.null(config$horizon)) config$horizon else if (!is.null(config$lag)) seq(0, as.integer(config$lag), by = event_time_step) else NULL
  pretrends <- if (!is.null(config$pretrends)) config$pretrends else if (!is.null(config$lead)) seq(event_time_step, as.integer(config$lead), by = event_time_step) else NULL

  fit <- didimputation::did_imputation(
    data = data,
    yname = config$outcome,
    gname = ".__group_id_cs__",
    tname = ".__time_id__",
    idname = ".__unit_id__",
    first_stage = build_first_stage_formula(config$controls),
    cluster_var = config$cluster_var %||% NULL,
    wname = config$weights_var %||% NULL,
    horizon = horizon,
    pretrends = pretrends
  )

  estimates <- ensure_standard_columns(as.data.frame(fit), conf_level = config$plot$ci_level)
  if (!"event_time" %in% names(estimates)) {
    maybe_term <- intersect(c("term", "horizon", "k"), names(estimates))
    if (length(maybe_term) > 0) {
      term_vals <- estimates[[maybe_term[1]]]
      estimates$event_time <- if (is.numeric(term_vals) || is.integer(term_vals)) as.numeric(term_vals) else extract_last_integer(as.character(term_vals))
    }
  }
  event_study <- subset(estimates, !is.na(estimate) & !is.na(event_time))

  event_plot <- build_generic_event_plot(
    event_study,
    title = config$plot$title %||% "Borusyak-Jaravel-Spiess event study",
    subtitle = config$plot$subtitle %||% "Estimated with didimputation::did_imputation()",
    reference_event_time = config$plot_reference_event_time %||% config$reference_event_time %||% -1,
    lead = config$lead,
    lag = config$lag,
    plot_options = config$plot
  )

  summary_text <- paste(
    "Estimator: Borusyak-Jaravel-Spiess",
    sprintf("Outcome: %s", config$outcome),
    sprintf("Unit id: %s", config$unit_id),
    sprintf("Time id: %s", config$time_id),
    sprintf("Group id: %s", config$group_id),
    sprintf("Horizons requested: %s", if (is.null(horizon)) "none" else paste(horizon, collapse = ", ")),
    sprintf("Pretrends requested: %s", if (is.null(pretrends)) "none" else paste(pretrends, collapse = ", ")),
    "Estimated with didimputation::did_imputation() and a first-stage specification that includes unit and time fixed effects.",
    sep = "\n"
  )

  list(
    estimates = estimates,
    event_study = event_study,
    tables = list(),
    plot = event_plot,
    summary_text = summary_text,
    model_stats = list(estimator = "bjs", nobs = nrow(data), horizon = horizon, pretrends = pretrends)
  )
}
