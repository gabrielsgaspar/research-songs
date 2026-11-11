write_table_outputs <- function(df, stem, output_dir, save_csv = TRUE, save_parquet = FALSE) {
  require_packages("readr")
  if (is.null(df) || nrow(df) == 0) {
    return(invisible(NULL))
  }

  out <- list()
  if (isTRUE(save_csv)) {
    csv_path <- file.path(output_dir, paste0(stem, ".csv"))
    readr::write_csv(df, csv_path)
    out$csv <- csv_path
  }

  if (isTRUE(save_parquet) && requireNamespace("arrow", quietly = TRUE)) {
    parquet_path <- file.path(output_dir, paste0(stem, ".parquet"))
    arrow::write_parquet(df, parquet_path)
    out$parquet <- parquet_path
  }

  invisible(out)
}

json_ready <- function(x) {
  if (is.data.frame(x)) {
    return(lapply(seq_len(nrow(x)), function(i) json_ready(as.list(x[i, , drop = FALSE]))))
  }
  if (is.list(x)) {
    return(lapply(x, json_ready))
  }
  if (inherits(x, c("POSIXct", "POSIXt", "Date"))) {
    return(as.character(x))
  }
  if (length(x) == 1 && is.na(x)) {
    return(NULL)
  }
  x
}

build_results_json <- function(result, config, diagnostics) {
  estimates <- ensure_standard_columns(result$estimates %||% NULL, conf_level = config$plot$ci_level)
  event_study <- normalize_event_study_table(result$event_study %||% NULL, ci_level = config$plot$ci_level)
  extra_tables <- result$tables %||% list()
  if (length(extra_tables) > 0) {
    extra_tables <- lapply(extra_tables, ensure_standard_columns, conf_level = config$plot$ci_level)
  }

  list(
    run = list(
      estimator = config$estimator,
      data_path = config$data_path,
      output_dir = config$output_dir,
      outcome = config$outcome,
      unit_id = config$unit_id,
      time_id = config$time_id,
      group_id = config$group_id %||% NULL,
      treatment_var = config$treatment_var %||% NULL,
      controls = config$controls,
      cluster_var = config$cluster_var %||% NULL,
      weights_var = config$weights_var %||% NULL,
      notes = config$notes %||% NULL
    ),
    model_stats = result$model_stats %||% NULL,
    diagnostics = diagnostics,
    estimates = estimates,
    event_study = event_study,
    extra_tables = extra_tables
  )
}

save_run_outputs <- function(result, config, diagnostics) {
  require_packages(c("yaml", "ggplot2", "readr", "jsonlite"))

  outdir <- ensure_output_dir(config$output_dir)
  files_written <- list()

  yaml::write_yaml(config, file.path(outdir, "config_used.yml"))
  files_written$config_used_yml <- file.path(outdir, "config_used.yml")

  if (!is.null(result$estimates)) {
    files_written$tidy_estimates <- write_table_outputs(
      ensure_standard_columns(result$estimates, conf_level = config$plot$ci_level),
      "tidy_estimates",
      outdir,
      save_csv = isTRUE(config$output$save_csv),
      save_parquet = isTRUE(config$output$save_parquet)
    )
  }

  if (!is.null(result$event_study)) {
    files_written$event_study <- write_table_outputs(
      normalize_event_study_table(result$event_study, ci_level = config$plot$ci_level),
      "event_study_estimates",
      outdir,
      save_csv = isTRUE(config$output$save_csv),
      save_parquet = isTRUE(config$output$save_parquet)
    )
  }

  if (!is.null(result$tables) && length(result$tables) > 0) {
    files_written$tables <- list()
    for (nm in names(result$tables)) {
      files_written$tables[[nm]] <- write_table_outputs(
        ensure_standard_columns(result$tables[[nm]], conf_level = config$plot$ci_level),
        nm,
        outdir,
        save_csv = isTRUE(config$output$save_csv),
        save_parquet = isTRUE(config$output$save_parquet)
      )
    }
  }

  if (is.null(diagnostics)) {
    diagnostics <- data.frame(metric = character(0), value = character(0), notes = character(0))
  }
  readr::write_csv(diagnostics, file.path(outdir, "sample_diagnostics.csv"))
  files_written$sample_diagnostics <- file.path(outdir, "sample_diagnostics.csv")

  summary_text <- result$summary_text %||% sprintf("Estimator run completed for `%s`.", config$estimator)
  if (isTRUE(config$output$save_model_summary)) {
    write_summary_text(file.path(outdir, "model_summary.txt"), summary_text)
    files_written$model_summary <- file.path(outdir, "model_summary.txt")
  }

  if (!is.null(result$plot)) {
    plot_files <- save_plot_exports(
      plot = result$plot,
      outdir = outdir,
      stem = "event_study_plot",
      plot_options = config$plot
    )
    files_written$event_study_plot <- plot_files
    mirror_regression_plot_exports(
      outdir = outdir,
      stem = "event_study_plot",
      latex_figure_format = config$plot$latex_figure_format %||% "pdf"
    )
  }

  result$output_files <- files_written
  metadata <- make_run_metadata(config, result, diagnostics)
  if (isTRUE(config$output$save_yaml_metadata)) {
    yaml::write_yaml(metadata, file.path(outdir, "run_metadata.yml"))
    files_written$run_metadata <- file.path(outdir, "run_metadata.yml")
  }

  if (isTRUE(config$output$save_json)) {
    json_payload <- build_results_json(result, config, diagnostics)
    jsonlite::write_json(
      json_ready(json_payload),
      path = file.path(outdir, "results.json"),
      pretty = TRUE,
      auto_unbox = TRUE,
      null = "null",
      na = "null",
      digits = 16
    )
    files_written$results_json <- file.path(outdir, "results.json")
  }

  invisible(files_written)
}
