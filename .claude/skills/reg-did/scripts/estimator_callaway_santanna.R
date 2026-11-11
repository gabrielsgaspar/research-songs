aggte_to_df <- function(obj, index_name = "term") {
  if (is.null(obj)) return(NULL)

  if (!is.null(obj$egt) && !is.null(obj$att.egt)) {
    out <- data.frame(
      term = obj$egt,
      estimate = obj$att.egt,
      std.error = obj$se.egt
    )
    names(out)[1] <- index_name
    ci <- compute_conf_int(out$estimate, out$std.error)
    out$conf.low <- ci$low
    out$conf.high <- ci$high
    return(out)
  }

  if (!is.null(obj$overall.att)) {
    out <- data.frame(term = "overall", estimate = obj$overall.att, std.error = obj$overall.se)
    ci <- compute_conf_int(out$estimate, out$std.error)
    out$conf.low <- ci$low
    out$conf.high <- ci$high
    return(out)
  }

  matrix_to_tidy_df(obj, index_name = index_name)
}

run_callaway_santanna <- function(data, config) {
  require_packages(c("did", "dplyr", "tibble", "ggplot2"))

  data$.__unit_id_numeric__ <- as.numeric(as.factor(data$.__unit_id__))
  clustervars <- config$cluster_var
  if (!is.null(clustervars)) {
    clustervars <- unlist(clustervars)
    clustervars[clustervars == config$unit_id] <- ".__unit_id_numeric__"
    clustervars[clustervars == ".__unit_id__"] <- ".__unit_id_numeric__"
    clustervars <- unique(clustervars)
  }

  att_args <- list(
    yname = config$outcome,
    tname = ".__time_id__",
    idname = ".__unit_id_numeric__",
    gname = ".__group_id_cs__",
    xformla = build_xformla(config$controls),
    data = data,
    panel = TRUE,
    allow_unbalanced_panel = !isTRUE(config$balanced_panel_required),
    control_group = config$control_group %||% "nevertreated",
    base_period = config$base_period %||% "varying",
    anticipation = as.integer(config$anticipation %||% 0),
    weightsname = config$weights_var %||% NULL,
    clustervars = clustervars
  )

  mp <- do.call(did::att_gt, att_args)

  group_time_tbl <- tibble::tibble(
    group = mp$group,
    time = mp$t,
    estimate = mp$att,
    std.error = mp$se
  )
  ci <- compute_conf_int(group_time_tbl$estimate, group_time_tbl$std.error, level = config$plot$ci_level)
  group_time_tbl$conf.low <- ci$low
  group_time_tbl$conf.high <- ci$high

  dynamic_args <- list(MP = mp, type = "dynamic")
  if (!is.null(config$lead)) dynamic_args$min_e <- -as.integer(config$lead)
  if (!is.null(config$lag)) dynamic_args$max_e <- as.integer(config$lag)
  dynamic_res <- do.call(did::aggte, dynamic_args)

  dynamic_tbl <- tibble::tibble(
    event_time = dynamic_res$egt,
    estimate = dynamic_res$att.egt,
    std.error = dynamic_res$se.egt
  )
  ci_dyn <- compute_conf_int(dynamic_tbl$estimate, dynamic_tbl$std.error, level = config$plot$ci_level)
  dynamic_tbl$conf.low <- ci_dyn$low
  dynamic_tbl$conf.high <- ci_dyn$high

  simple_tbl <- aggte_to_df(did::aggte(mp, type = "simple"))
  calendar_tbl <- aggte_to_df(did::aggte(mp, type = "calendar"))
  group_tbl <- aggte_to_df(did::aggte(mp, type = "group"))

  event_plot <- build_generic_event_plot(
    dynamic_tbl,
    title = config$plot$title %||% "Callaway-Sant'Anna event study",
    subtitle = config$plot$subtitle %||% sprintf("Control group: %s", config$control_group %||% "nevertreated"),
    reference_event_time = config$plot_reference_event_time %||% config$reference_event_time %||% -1,
    lead = config$lead,
    lag = config$lag,
    plot_options = config$plot
  )

  summary_text <- paste(
    "Estimator: Callaway-Sant'Anna",
    sprintf("Outcome: %s", config$outcome),
    sprintf("Unit id: %s", config$unit_id),
    sprintf("Time id: %s", config$time_id),
    sprintf("Group id: %s", config$group_id),
    sprintf("Control group: %s", config$control_group %||% "nevertreated"),
    sprintf("Base period: %s", config$base_period %||% "varying"),
    sprintf("Anticipation periods: %s", config$anticipation %||% 0),
    "Estimated group-time ATT(g,t) with did::att_gt() and dynamic, simple, calendar, and group aggregations via did::aggte().",
    sep = "\n"
  )

  list(
    estimates = group_time_tbl,
    event_study = dynamic_tbl,
    tables = list(
      group_time_att = group_time_tbl,
      aggregate_simple = simple_tbl,
      aggregate_calendar = calendar_tbl,
      aggregate_group = group_tbl
    ),
    plot = event_plot,
    summary_text = summary_text,
    model_stats = list(
      estimator = "callaway_santanna",
      nobs = nrow(stats::na.omit(data[c(config$outcome, ".__time_id__", ".__unit_id_numeric__", ".__group_id_cs__")])),
      control_group = config$control_group %||% "nevertreated",
      base_period = config$base_period %||% "varying",
      anticipation = config$anticipation %||% 0,
      clustervars = clustervars %||% NULL,
      overall_att = simple_tbl$estimate[[1]] %||% NA_real_,
      overall_se = simple_tbl$std.error[[1]] %||% NA_real_
    )
  )
}
