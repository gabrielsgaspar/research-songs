run_sun_abraham <- function(data, config) {
  require_packages(c("fixest", "broom", "dplyr", "tibble", "ggplot2", "stringr"))

  reference_period <- config$reference_event_time %||% -1
  treatment_term <- sprintf("sunab(.__group_id__, .__time_id__, ref.p = %s)", reference_period)
  fixed_effects <- paste(c(".__unit_id__", ".__time_id__", config$extra_fixed_effects %||% character(0)), collapse = " + ")
  model_formula <- build_fixest_formula(
    outcome = config$outcome,
    treatment_term = treatment_term,
    controls = config$controls,
    fixed_effects = fixed_effects
  )

  feols_args <- list(fml = model_formula, data = data)
  if (!is.null(config$weights_var)) feols_args$weights <- as_weights_formula(config$weights_var)
  vcov_spec <- as_vcov_spec(config$cluster_var)
  if (!is.null(vcov_spec)) feols_args$vcov <- vcov_spec

  model <- do.call(fixest::feols, feols_args)
  period_mat <- tryCatch(fixest::aggregate.fixest(model, agg = "period"), error = function(e) NULL)
  att_mat <- tryCatch(fixest::aggregate.fixest(model, agg = "att"), error = function(e) NULL)

  event_study <- matrix_to_tidy_df(period_mat, index_name = "term")
  if (!is.null(event_study)) {
    names(event_study)[1:min(4, ncol(event_study))] <- c("estimate", "std.error", "statistic", "p.value")[1:min(4, ncol(event_study))]
    event_study$event_time <- extract_last_integer(event_study$term)
    ci <- compute_conf_int(event_study$estimate, event_study$std.error, level = config$plot$ci_level)
    event_study$conf.low <- ci$low
    event_study$conf.high <- ci$high
    if (!is.null(config$lead)) event_study <- subset(event_study, is.na(event_time) | event_time >= -config$lead)
    if (!is.null(config$lag)) event_study <- subset(event_study, is.na(event_time) | event_time <= config$lag)
    event_study <- event_study[order(event_study$event_time), ]
  }

  aggregate_att <- matrix_to_tidy_df(att_mat, index_name = "term")
  if (!is.null(aggregate_att)) {
    names(aggregate_att)[1:min(4, ncol(aggregate_att))] <- c("estimate", "std.error", "statistic", "p.value")[1:min(4, ncol(aggregate_att))]
    ci <- compute_conf_int(aggregate_att$estimate, aggregate_att$std.error, level = config$plot$ci_level)
    aggregate_att$conf.low <- ci$low
    aggregate_att$conf.high <- ci$high
  }

  tidy_coefs <- broom::tidy(model, conf.int = TRUE, conf.level = config$plot$ci_level)
  if (is.null(event_study) || nrow(event_study) == 0) {
    event_study <- subset(tidy_coefs, grepl("\\.__time_id__::", term))
    if (nrow(event_study) > 0) {
      event_study$event_time <- extract_last_integer(event_study$term)
      if (!is.null(config$lead)) event_study <- subset(event_study, is.na(event_time) | event_time >= -config$lead)
      if (!is.null(config$lag)) event_study <- subset(event_study, is.na(event_time) | event_time <= config$lag)
      event_study <- event_study[order(event_study$event_time), ]
    }
  }

  event_plot <- build_generic_event_plot(
    event_study,
    title = config$plot$title %||% "Sun-Abraham event study",
    subtitle = config$plot$subtitle %||% "Estimated with fixest::feols() and fixest::sunab()",
    reference_event_time = reference_period,
    lead = config$lead,
    lag = config$lag,
    plot_options = config$plot
  )

  summary_text <- paste(
    "Estimator: Sun-Abraham",
    sprintf("Outcome: %s", config$outcome),
    sprintf("Unit id: %s", config$unit_id),
    sprintf("Time id: %s", config$time_id),
    sprintf("Group id: %s", config$group_id),
    "Estimated with unit and time fixed effects using fixest::feols() and fixest::sunab().",
    "Relative-period effects were extracted with fixest aggregate(period) and the overall ATT with aggregate(att) when available.",
    sep = "\n"
  )

  list(
    estimates = tidy_coefs,
    event_study = event_study,
    tables = list(aggregate_att = aggregate_att),
    plot = event_plot,
    summary_text = summary_text,
    model_stats = utils::modifyList(extract_model_stats(model, estimator_name = "sun_abraham"), list(reference_event_time = reference_period))
  )
}
