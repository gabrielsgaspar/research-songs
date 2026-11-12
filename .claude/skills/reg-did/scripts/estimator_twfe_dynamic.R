run_twfe_dynamic <- function(data, config) {
  require_packages(c("fixest", "broom", "dplyr", "tibble", "ggplot2"))

  event_info <- build_event_time(data, config)
  data <- event_info$data
  reference_period <- config$reference_event_time %||% -1
  data$.__ever_treated__ <- ifelse(!is.na(data$.__group_id__), 1, 0)
  data$.__event_time_plot__[is.na(data$.__event_time_plot__) & data$.__ever_treated__ == 0] <- reference_period

  fixed_effects <- paste(c(".__unit_id__", ".__time_id__", config$extra_fixed_effects %||% character(0)), collapse = " + ")
  model_formula <- build_fixest_formula(
    outcome = config$outcome,
    treatment_term = sprintf("fixest::i(.__event_time_plot__, .__ever_treated__, ref = %s)", reference_period),
    controls = config$controls,
    fixed_effects = fixed_effects
  )

  feols_args <- list(fml = model_formula, data = data)
  if (!is.null(config$weights_var)) feols_args$weights <- as_weights_formula(config$weights_var)
  vcov_spec <- as_vcov_spec(config$cluster_var)
  if (!is.null(vcov_spec)) feols_args$vcov <- vcov_spec
  model <- do.call(fixest::feols, feols_args)

  estimates <- broom::tidy(model, conf.int = TRUE, conf.level = config$plot$ci_level)
  event_study <- subset(estimates, grepl("event_time_plot", term))
  supported_event_times <- sort(unique(stats::na.omit(data$.__event_time_plot__[data$.__ever_treated__ == 1])))
  if (nrow(event_study) > 0) {
    event_study$event_time <- extract_last_integer(event_study$term)
    event_study <- subset(event_study, event_time != reference_period)
    event_study <- merge(data.frame(event_time = supported_event_times), event_study, by = "event_time", all.x = TRUE, sort = TRUE)
    event_study <- event_study[order(event_study$event_time), ]
  } else {
    event_study <- data.frame(event_time = supported_event_times)
  }
  if (reference_period %in% supported_event_times) {
    ref_mask <- event_study$event_time == reference_period
    if (any(ref_mask)) {
      event_study$term[ref_mask] <- "(reference period)"
      event_study$estimate[ref_mask] <- 0
      event_study$std.error[ref_mask] <- NA_real_
      event_study$statistic[ref_mask] <- NA_real_
      event_study$p.value[ref_mask] <- NA_real_
      event_study$conf.low[ref_mask] <- NA_real_
      event_study$conf.high[ref_mask] <- NA_real_
    }
  }

  event_plot <- build_generic_event_plot(
    event_study,
    title = config$plot$title %||% sprintf("Dynamic TWFE: %s", config$outcome),
    subtitle = config$plot$subtitle,
    reference_event_time = reference_period,
    lead = config$lead,
    lag = config$lag,
    plot_options = config$plot
  )

  summary_text <- paste(
    "Estimator: Dynamic TWFE",
    sprintf("Outcome: %s", config$outcome),
    sprintf("Unit id: %s", config$unit_id),
    sprintf("Time id: %s", config$time_id),
    sprintf("Clustered SEs: %s", paste(config$cluster_var %||% "default", collapse = ", ")),
    sprintf("Event-time source: %s", event_info$source),
    sprintf("Reference event time: %s", reference_period),
    "Warning: dynamic TWFE can be misleading under staggered adoption with heterogeneous treatment effects.",
    sep = "\n"
  )

  list(
    estimates = estimates,
    event_study = event_study,
    tables = list(),
    plot = event_plot,
    summary_text = summary_text,
    model_stats = utils::modifyList(
      extract_model_stats(model, estimator_name = "twfe_dynamic"),
      list(reference_event_time = reference_period, event_time_source = event_info$source)
    )
  )
}
