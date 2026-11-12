build_event_time <- function(data, config) {
  out <- as.data.frame(data)

  if (!is.null(config$event_time_var)) {
    out$.__event_time__ <- safe_numeric_vector(out[[config$event_time_var]], config$event_time_var, allow_na = TRUE)
    if (!is.null(config$event_time_never_value)) {
      out$.__event_time__[out$.__event_time__ == config$event_time_never_value] <- NA_real_
    }
    event_source <- "existing_event_time_var"
  } else if (!is.null(config$group_id)) {
    out$.__event_time__ <- ifelse(
      is.na(out$.__group_id__),
      NA_real_,
      out$.__time_id__ - out$.__group_id__
    )
    event_source <- "constructed_from_group_id"
  } else {
    out$.__event_time__ <- NA_real_
    event_source <- "missing"
  }

  if (!is.null(config$treatment_var)) {
    out$.__treated__ <- coerce_binary_treatment(out[[config$treatment_var]], config$treatment_var)
  } else if (!is.null(config$group_id)) {
    out$.__treated__ <- ifelse(!is.na(out$.__group_id__) & out$.__time_id__ >= out$.__group_id__, 1, 0)
  } else {
    out$.__treated__ <- NA_real_
  }

  out$.__event_time_plot__ <- out$.__event_time__
  if (!is.null(config$lead)) {
    out$.__event_time_plot__ <- ifelse(out$.__event_time_plot__ < -config$lead, -config$lead, out$.__event_time_plot__)
  }
  if (!is.null(config$lag)) {
    out$.__event_time_plot__ <- ifelse(out$.__event_time_plot__ > config$lag, config$lag, out$.__event_time_plot__)
  }

  list(
    data = out,
    event_time_var = ".__event_time__",
    event_time_plot_var = ".__event_time_plot__",
    treated_var = ".__treated__",
    source = event_source
  )
}
