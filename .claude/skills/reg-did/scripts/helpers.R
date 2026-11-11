`%||%` <- function(x, y) {
  if (is.null(x)) y else x
}

DID_EVENT_PLOT_COLOR <- "#2C5A8A"
DID_EVENT_GRID_COLOR <- "#D9D9D9"
DID_EVENT_Y_STEP <- 0.05
DID_EVENT_MIN_ABS_Y <- 0.15

stopf <- function(fmt, ...) {
  stop(sprintf(fmt, ...), call. = FALSE)
}

warnf <- function(fmt, ...) {
  warning(sprintf(fmt, ...), call. = FALSE)
}

null_if_empty <- function(x) {
  if (is.null(x)) return(NULL)
  if (length(x) == 0) return(NULL)
  if (is.character(x) && all(!nzchar(trimws(x)))) return(NULL)
  x
}

resolve_script_dir <- function() {
  env_dir <- Sys.getenv("DID_SKILL_DIR", unset = "")
  if (nzchar(env_dir) && file.exists(file.path(env_dir, "helpers.R"))) {
    return(normalizePath(env_dir, winslash = "/", mustWork = TRUE))
  }

  args <- commandArgs(trailingOnly = FALSE)
  file_arg <- grep("^--file=", args, value = TRUE)
  if (length(file_arg) > 0) {
    script_path <- sub("^--file=", "", file_arg[[1]])
    return(normalizePath(dirname(script_path), winslash = "/", mustWork = TRUE))
  }

  cwd_candidate <- normalizePath("scripts", winslash = "/", mustWork = FALSE)
  if (file.exists(file.path(cwd_candidate, "helpers.R"))) {
    return(cwd_candidate)
  }

  stopf("Could not resolve the skill scripts directory. Set DID_SKILL_DIR or run from the skill root.")
}

resolve_plot_font_family <- local({
  cached_family <- NULL

  function() {
    if (!is.null(cached_family)) {
      return(cached_family)
    }

    cached_family <<- "serif"
    if (requireNamespace("systemfonts", quietly = TRUE)) {
      fonts <- try(systemfonts::system_fonts(), silent = TRUE)
      if (!inherits(fonts, "try-error") && "family" %in% names(fonts)) {
        if (any(fonts$family == "Latin Modern Roman")) {
          cached_family <<- "Latin Modern Roman"
        } else {
          lm_candidates <- unique(fonts$family[grepl("^LM Roman", fonts$family)])
          if (length(lm_candidates) > 0) {
            cached_family <<- lm_candidates[[1]]
          }
        }
      }
    }

    cached_family
  }
})

paper_plot_theme <- function(base_size = 11) {
  require_packages("ggplot2")
  plot_family <- resolve_plot_font_family()

  ggplot2::theme_minimal(base_size = base_size, base_family = plot_family) +
    ggplot2::theme(
      text = ggplot2::element_text(family = plot_family),
      panel.grid.minor = ggplot2::element_blank(),
      panel.grid.major = ggplot2::element_line(color = DID_EVENT_GRID_COLOR, linewidth = 0.4),
      panel.border = ggplot2::element_rect(color = "black", fill = NA, linewidth = 0.6),
      axis.line = ggplot2::element_blank(),
      plot.title = ggplot2::element_text(family = plot_family),
      plot.subtitle = ggplot2::element_text(family = plot_family),
      axis.title = ggplot2::element_text(family = plot_family),
      axis.text = ggplot2::element_text(family = plot_family)
    )
}

require_packages <- function(pkgs) {
  missing_pkgs <- pkgs[!vapply(pkgs, requireNamespace, logical(1), quietly = TRUE)]
  if (length(missing_pkgs) > 0) {
    stopf(
      "Missing R packages: %s. Run install_packages.R first.",
      paste(missing_pkgs, collapse = ", ")
    )
  }
}

parse_config <- function(config_path) {
  require_packages("yaml")
  if (!file.exists(config_path)) {
    stopf("Config file does not exist: %s", config_path)
  }

  cfg <- yaml::read_yaml(config_path)
  if (is.null(cfg) || !is.list(cfg)) {
    stopf("Config file did not parse into a list: %s", config_path)
  }

  plot_defaults <- list(
    width = 8,
    height = 5,
    dpi = 320,
    color = DID_EVENT_PLOT_COLOR,
    show_grid = TRUE,
    show_border = TRUE,
    show_points = TRUE,
    show_line = TRUE,
    show_ci = TRUE,
    ci_geom = "linerange",
    ci_level = 0.95,
    zero_line = TRUE,
    zero_line_width = 1.1,
    zero_line_color = "gray35",
    reference_line = TRUE,
    reference_line_type = "dashed",
    reference_line_width = 0.7,
    reference_line_color = "gray50",
    box = TRUE,
    x_label = "Distance to treatment",
    y_label = NULL,
    title = NULL,
    subtitle = NULL,
    omit_title = TRUE,
    x_breaks = NULL,
    y_breaks = NULL,
    x_limits = NULL,
    y_limits = NULL,
    tick_format = "%.2f",
    latex_figure_format = "pdf",
    save_tight_png = TRUE,
    save_png = FALSE,
    background = "white"
  )

  defaults <- list(
    file_format = NULL,
    treatment_var = NULL,
    controls = character(0),
    cluster_var = NULL,
    weights_var = NULL,
    event_time_var = NULL,
    event_time_never_value = NULL,
    lead = NULL,
    lag = NULL,
    reference_event_time = -1,
    plot_reference_event_time = NULL,
    anticipation = 0,
    control_group = "nevertreated",
    base_period = NULL,
    balanced_panel_required = FALSE,
    output_dir = file.path("resources", "did", "run"),
    notes = NULL,
    effects = NULL,
    placebo = NULL,
    horizon = NULL,
    pretrends = NULL,
    event_time_step = 1,
    dcdh_mode = "dyn",
    never_treated_value = NULL,
    trends_nonparam = NULL,
    trends_lin = FALSE,
    seed = NULL,
    extra_fixed_effects = character(0),
    output = list(
      save_csv = TRUE,
      save_parquet = FALSE,
      save_json = TRUE,
      save_yaml_metadata = TRUE,
      save_model_summary = TRUE
    ),
    plot = plot_defaults
  )

  cfg <- modifyList(defaults, cfg)
  cfg$plot <- modifyList(plot_defaults, cfg$plot %||% list())

  if (is.null(cfg$file_format)) {
    ext <- tools::file_ext(cfg$data_path %||% "")
    cfg$file_format <- tolower(ext)
  }

  cfg$controls <- unlist(cfg$controls %||% character(0))
  cfg$cluster_var <- null_if_empty(unlist(cfg$cluster_var %||% character(0)))
  cfg$extra_fixed_effects <- null_if_empty(unlist(cfg$extra_fixed_effects %||% character(0)))
  cfg$plot$x_breaks <- null_if_empty(unlist(cfg$plot$x_breaks %||% NULL))
  cfg$plot$y_breaks <- null_if_empty(unlist(cfg$plot$y_breaks %||% NULL))
  cfg$plot$x_limits <- null_if_empty(unlist(cfg$plot$x_limits %||% NULL))
  cfg$plot$y_limits <- null_if_empty(unlist(cfg$plot$y_limits %||% NULL))

  cfg
}

ensure_output_dir <- function(path) {
  dir.create(path, recursive = TRUE, showWarnings = FALSE)
  normalizePath(path, winslash = "/", mustWork = FALSE)
}

read_input_data <- function(path, file_format = NULL) {
  if (!file.exists(path)) {
    stopf("Data file does not exist: %s", path)
  }

  fmt <- tolower(file_format %||% tools::file_ext(path))
  if (fmt == "csv") {
    require_packages("data.table")
  } else if (fmt %in% c("parquet", "feather")) {
    require_packages("arrow")
  }
  out <- switch(
    fmt,
    csv = data.table::fread(path, data.table = FALSE),
    parquet = as.data.frame(arrow::read_parquet(path)),
    feather = as.data.frame(arrow::read_feather(path)),
    rds = readRDS(path),
    stopf("Unsupported file format: %s", fmt)
  )

  as.data.frame(out)
}

build_controls_rhs <- function(controls) {
  controls <- controls %||% character(0)
  controls <- controls[nzchar(controls)]
  if (length(controls) == 0) {
    "1"
  } else {
    paste(controls, collapse = " + ")
  }
}

build_xformla <- function(controls) {
  stats::as.formula(paste("~", build_controls_rhs(controls)))
}

build_fixest_formula <- function(outcome, treatment_term, controls, fixed_effects) {
  rhs_terms <- c(treatment_term, controls)
  rhs_terms <- rhs_terms[!is.null(rhs_terms) & nzchar(rhs_terms)]
  rhs <- if (length(rhs_terms) == 0) "1" else paste(rhs_terms, collapse = " + ")
  stats::as.formula(sprintf("%s ~ %s | %s", outcome, rhs, fixed_effects))
}

build_first_stage_formula <- function(controls, unit_fe = ".__unit_id__", time_fe = ".__time_id__") {
  rhs <- build_controls_rhs(controls)
  stats::as.formula(sprintf("~ %s | %s + %s", rhs, unit_fe, time_fe))
}

as_vcov_spec <- function(cluster_var = NULL) {
  if (is.null(cluster_var) || identical(cluster_var, "") || identical(cluster_var, FALSE)) {
    return(NULL)
  }
  cluster_var <- unlist(cluster_var)
  cluster_var <- cluster_var[!is.na(cluster_var) & nzchar(cluster_var)]
  if (length(cluster_var) == 0) {
    return(NULL)
  }
  stats::as.formula(paste0("~", paste(cluster_var, collapse = " + ")))
}

as_weights_formula <- function(weights_var = NULL) {
  if (is.null(weights_var) || identical(weights_var, "")) {
    return(NULL)
  }
  stats::as.formula(paste0("~", weights_var))
}

safe_numeric_vector <- function(x, var_name, allow_na = TRUE) {
  if (is.numeric(x) || is.integer(x)) {
    return(as.numeric(x))
  }

  x_chr <- as.character(x)
  x_chr <- trimws(x_chr)
  x_chr[x_chr == ""] <- NA_character_

  suppressWarnings(x_num <- as.numeric(x_chr))
  bad <- !is.na(x_chr) & is.na(x_num)
  if (any(bad)) {
    stopf("Variable `%s` could not be safely coerced to numeric.", var_name)
  }
  if (!allow_na && any(is.na(x_num))) {
    stopf("Variable `%s` contains missing values after coercion.", var_name)
  }

  x_num
}

coerce_group_timing <- function(x, var_name = "group_id", never_treated_value = NULL) {
  g <- safe_numeric_vector(x, var_name = var_name, allow_na = TRUE)
  g[g == 0] <- NA_real_
  if (!is.null(never_treated_value)) {
    g[g == never_treated_value] <- NA_real_
  }
  g
}

coerce_binary_treatment <- function(x, var_name = "treatment_var") {
  if (is.logical(x)) {
    return(as.integer(x))
  }

  if (is.factor(x)) {
    x <- as.character(x)
  }

  if (is.character(x)) {
    xl <- tolower(trimws(x))
    out <- rep(NA_real_, length(xl))
    out[xl %in% c("1", "true", "treated", "yes")] <- 1
    out[xl %in% c("0", "false", "untreated", "no")] <- 0
    if (any(is.na(out) & !is.na(xl) & nzchar(xl))) {
      stopf("Treatment variable `%s` is not safely coercible to binary 0/1.", var_name)
    }
    return(out)
  }

  x_num <- safe_numeric_vector(x, var_name = var_name, allow_na = TRUE)
  values <- sort(unique(stats::na.omit(x_num)))
  if (!all(values %in% c(0, 1))) {
    stopf("Treatment variable `%s` must be binary 0/1 for this pathway.", var_name)
  }
  x_num
}

coerce_weights <- function(x, var_name = "weights_var") {
  w <- safe_numeric_vector(x, var_name = var_name, allow_na = TRUE)
  if (any(w < 0, na.rm = TRUE)) {
    stopf("Weights variable `%s` contains negative values.", var_name)
  }
  w
}

extract_last_integer <- function(x) {
  require_packages("stringr")
  out <- stringr::str_extract(x, "-?\\d+(?!.*-?\\d)")
  suppressWarnings(as.numeric(out))
}

make_reference_event_row <- function(event_df, reference_event_time) {
  ref_row <- event_df[1, , drop = FALSE]
  for (nm in names(ref_row)) {
    if (is.numeric(ref_row[[nm]]) || is.integer(ref_row[[nm]])) {
      ref_row[[nm]] <- NA_real_
    } else {
      ref_row[[nm]] <- NA
    }
  }
  ref_row$event_time <- reference_event_time
  ref_row$estimate <- 0
  if ("std.error" %in% names(ref_row)) ref_row$std.error <- NA_real_
  if ("conf.low" %in% names(ref_row)) ref_row$conf.low <- NA_real_
  if ("conf.high" %in% names(ref_row)) ref_row$conf.high <- NA_real_
  ref_row
}

compute_conf_int <- function(estimate, std.error, level = 0.95) {
  alpha <- 1 - level
  z <- stats::qnorm(1 - alpha / 2)
  list(low = estimate - z * std.error, high = estimate + z * std.error)
}

normalize_event_study_table <- function(event_df, ci_level = 0.95) {
  if (is.null(event_df) || nrow(event_df) == 0) return(NULL)
  if (!"event_time" %in% names(event_df) || !"estimate" %in% names(event_df)) return(NULL)

  out <- as.data.frame(event_df)
  out$event_time <- safe_numeric_vector(out$event_time, "event_time", allow_na = TRUE)
  out$estimate <- safe_numeric_vector(out$estimate, "estimate", allow_na = TRUE)

  if (!all(c("conf.low", "conf.high") %in% names(out))) {
    if ("std.error" %in% names(out)) {
      ci <- compute_conf_int(out$estimate, out$std.error, level = ci_level)
      out$conf.low <- ci$low
      out$conf.high <- ci$high
    } else {
      out$conf.low <- NA_real_
      out$conf.high <- NA_real_
    }
  }

  out <- add_test_statistics(out)
  out <- out[order(out$event_time), , drop = FALSE]
  out
}

build_generic_event_plot <- function(event_df,
                                     title = NULL,
                                     subtitle = NULL,
                                     reference_event_time = -1,
                                     lead = NULL,
                                     lag = NULL,
                                     plot_options = list()) {
  require_packages(c("ggplot2", "dplyr"))
  if (is.null(event_df) || nrow(event_df) == 0) {
    return(NULL)
  }

  opts <- modifyList(list(
    color = DID_EVENT_PLOT_COLOR,
    show_grid = TRUE,
    show_border = TRUE,
    show_points = TRUE,
    show_line = TRUE,
    show_ci = TRUE,
    ci_geom = "linerange",
    ci_level = 0.95,
    zero_line = TRUE,
    zero_line_width = 1.1,
    zero_line_color = "gray35",
    reference_line = TRUE,
    reference_line_type = "dashed",
    reference_line_width = 0.7,
    reference_line_color = "gray50",
    box = TRUE,
    x_label = "Distance to treatment",
    y_label = NULL,
    omit_title = TRUE,
    x_breaks = NULL,
    y_breaks = NULL,
    x_limits = NULL,
    y_limits = NULL,
    tick_format = "%.2f"
  ), plot_options %||% list())

  event_df <- normalize_event_study_table(event_df, ci_level = opts$ci_level)
  event_df <- subset(event_df, !is.na(event_time) & !is.na(estimate))
  if (nrow(event_df) == 0) return(NULL)

  if (!is.null(lead)) event_df <- subset(event_df, event_time >= -as.integer(lead))
  if (!is.null(lag)) event_df <- subset(event_df, event_time <= as.integer(lag))
  if (nrow(event_df) == 0) return(NULL)

  if (!is.null(reference_event_time) && is.finite(reference_event_time) && !(reference_event_time %in% event_df$event_time)) {
    event_df <- rbind(event_df, make_reference_event_row(event_df, reference_event_time))
  }
  event_df <- event_df[order(event_df$event_time), , drop = FALSE]
  ci_event_df <- subset(event_df, !is.na(conf.low) & !is.na(conf.high))

  x_breaks <- opts$x_breaks
  if (is.null(x_breaks)) {
    if (!is.null(lead) && !is.null(lag)) {
      x_breaks <- seq(-as.integer(lead), as.integer(lag), by = 1)
    } else {
      x_breaks <- pretty(range(c(event_df$event_time, reference_event_time), na.rm = TRUE), n = 8)
    }
  }

  y_limits <- opts$y_limits
  if (is.null(y_limits)) {
    max_abs_y <- max(abs(c(ci_event_df$conf.low, ci_event_df$conf.high, event_df$estimate)), na.rm = TRUE)
    if (!is.finite(max_abs_y)) max_abs_y <- DID_EVENT_MIN_ABS_Y
    max_abs_y <- max(DID_EVENT_MIN_ABS_Y, ceiling(max_abs_y / DID_EVENT_Y_STEP) * DID_EVENT_Y_STEP)
    y_limits <- c(-max_abs_y, max_abs_y)
  }

  y_breaks <- opts$y_breaks
  if (is.null(y_breaks)) {
    y_breaks <- seq(y_limits[1], y_limits[2], by = DID_EVENT_Y_STEP)
  }

  p <- ggplot2::ggplot(event_df, ggplot2::aes(x = event_time, y = estimate))

  if (isTRUE(opts$zero_line)) {
    p <- p + ggplot2::geom_hline(
      yintercept = 0,
      linetype = "solid",
      color = opts$zero_line_color,
      linewidth = opts$zero_line_width
    )
  }

  if (isTRUE(opts$reference_line) && !is.null(reference_event_time) && is.finite(reference_event_time)) {
    p <- p + ggplot2::geom_vline(
      xintercept = reference_event_time,
      linetype = opts$reference_line_type,
      color = opts$reference_line_color,
      linewidth = opts$reference_line_width
    )
  }

  if (isTRUE(opts$show_ci) && nrow(ci_event_df) > 0) {
    if (identical(opts$ci_geom, "errorbar")) {
      p <- p + ggplot2::geom_errorbar(
        data = ci_event_df,
        ggplot2::aes(ymin = conf.low, ymax = conf.high),
        width = 0.08,
        color = opts$color,
        linewidth = 0.9
      )
    } else {
      p <- p + ggplot2::geom_linerange(
        data = ci_event_df,
        ggplot2::aes(ymin = conf.low, ymax = conf.high),
        color = opts$color,
        linewidth = 1.0
      )
    }
  }

  if (isTRUE(opts$show_line)) {
    p <- p + ggplot2::geom_line(color = opts$color, linewidth = 1.0)
  }
  if (isTRUE(opts$show_points)) {
    p <- p + ggplot2::geom_point(color = opts$color, size = 2.2)
  }

  p <- p +
    ggplot2::scale_x_continuous(breaks = x_breaks, limits = opts$x_limits) +
    ggplot2::scale_y_continuous(
      breaks = y_breaks,
      limits = y_limits,
      labels = function(x) sprintf(opts$tick_format, x)
    ) +
    ggplot2::labs(
      title = if (isTRUE(opts$omit_title)) NULL else title,
      subtitle = if (isTRUE(opts$omit_title)) NULL else subtitle,
      x = opts$x_label,
      y = opts$y_label
    ) +
    paper_plot_theme(base_size = 11)

  p <- p + ggplot2::theme(
    panel.grid.major = if (isTRUE(opts$show_grid)) ggplot2::element_line(color = DID_EVENT_GRID_COLOR, linewidth = 0.4) else ggplot2::element_blank(),
    panel.border = if (isTRUE(opts$show_border) || isTRUE(opts$box)) ggplot2::element_rect(color = "black", fill = NA, linewidth = 0.6) else ggplot2::element_blank(),
    plot.title = if (isTRUE(opts$omit_title)) ggplot2::element_blank() else ggplot2::element_text(family = resolve_plot_font_family()),
    plot.subtitle = if (isTRUE(opts$omit_title)) ggplot2::element_blank() else ggplot2::element_text(family = resolve_plot_font_family())
  )

  p
}

save_plot_exports <- function(plot, outdir, stem, plot_options = list()) {
  require_packages("ggplot2")
  opts <- modifyList(list(
    width = 8,
    height = 5,
    dpi = 320,
    latex_figure_format = "pdf",
    save_tight_png = TRUE,
    save_png = FALSE,
    background = "white"
  ), plot_options %||% list())

  device_ext <- tolower(opts$latex_figure_format %||% "pdf")
  if (!device_ext %in% c("pdf", "png", "svg", "eps")) {
    stopf("Unsupported latex_figure_format `%s`. Use one of: pdf, png, svg, eps.", device_ext)
  }

  base_path <- file.path(outdir, stem)
  latex_path <- paste0(base_path, ".", device_ext)
  plot_family <- resolve_plot_font_family()

  if (device_ext == "pdf") {
    ggplot2::ggsave(latex_path, plot = plot, device = grDevices::cairo_pdf, family = plot_family,
      width = opts$width, height = opts$height, bg = opts$background)
  } else if (device_ext == "png") {
    ggplot2::ggsave(latex_path, plot = plot, device = grDevices::png,
      width = opts$width, height = opts$height, dpi = opts$dpi, type = "cairo", bg = opts$background)
  } else if (device_ext == "svg") {
    ggplot2::ggsave(latex_path, plot = plot, device = grDevices::svg,
      width = opts$width, height = opts$height, bg = opts$background)
  } else if (device_ext == "eps") {
    ggplot2::ggsave(latex_path, plot = plot, device = grDevices::cairo_ps,
      width = opts$width, height = opts$height, bg = opts$background, fallback_resolution = opts$dpi)
  }

  png_path <- NULL
  if (isTRUE(opts$save_png) || isTRUE(opts$save_tight_png)) {
    png_path <- file.path(outdir, paste0(stem, ".png"))
    if (!identical(normalizePath(png_path, winslash = "/", mustWork = FALSE), normalizePath(latex_path, winslash = "/", mustWork = FALSE))) {
      ggplot2::ggsave(png_path, plot = plot, device = grDevices::png,
        width = opts$width, height = opts$height, dpi = opts$dpi, type = "cairo", bg = opts$background)
    }
  }

  invisible(list(latex_figure = latex_path, png = png_path))
}

mirror_regression_plot_exports <- function(outdir, stem, latex_figure_format = "pdf") {
  normalized_outdir <- normalizePath(outdir, winslash = "/", mustWork = FALSE)
  did_anchor <- "/resources/did/"
  if (!grepl(did_anchor, normalized_outdir, fixed = TRUE)) {
    return(invisible(NULL))
  }

  relative_dir <- sub(paste0("^.*", did_anchor), "", normalized_outdir)
  mirror_dir <- file.path(dirname(dirname(dirname(normalized_outdir))), "images", "regressions", relative_dir)
  dir.create(mirror_dir, recursive = TRUE, showWarnings = FALSE)

  exts <- unique(c(latex_figure_format, "png"))
  outputs <- list()
  for (ext in exts) {
    src <- file.path(normalized_outdir, paste0(stem, ".", ext))
    dst <- file.path(mirror_dir, basename(src))
    if (file.exists(src)) {
      file.copy(src, dst, overwrite = TRUE)
      outputs[[ext]] <- dst
    }
  }

  invisible(outputs)
}

matrix_to_tidy_df <- function(x, index_name = "term") {
  if (is.null(x)) return(NULL)
  if (is.data.frame(x) || is.matrix(x)) {
    out <- as.data.frame(x)
  } else {
    return(NULL)
  }

  if (is.null(rownames(out))) {
    out[[index_name]] <- seq_len(nrow(out))
  } else {
    out[[index_name]] <- rownames(out)
    rownames(out) <- NULL
  }
  out
}

extract_tables_from_object <- function(x) {
  out <- list()
  if (!is.list(x)) return(out)
  for (nm in names(x)) {
    obj <- x[[nm]]
    if (is.data.frame(obj) || is.matrix(obj)) {
      out[[nm]] <- as.data.frame(obj)
    }
  }
  out
}

safe_r2 <- function(model) {
  if (!requireNamespace("fixest", quietly = TRUE)) return(list(r2 = NA_real_, adj_r2 = NA_real_, within_r2 = NA_real_))
  out <- list(r2 = NA_real_, adj_r2 = NA_real_, within_r2 = NA_real_)
  for (tp in c("r2", "ar2", "wr2")) {
    val <- tryCatch(fixest::fitstat(model, tp), error = function(e) NA_real_)
    if (tp == "r2") out$r2 <- suppressWarnings(as.numeric(val))
    if (tp == "ar2") out$adj_r2 <- suppressWarnings(as.numeric(val))
    if (tp == "wr2") out$within_r2 <- suppressWarnings(as.numeric(val))
  }
  out
}

extract_model_stats <- function(model, estimator_name = NULL) {
  if (is.null(model)) return(list(estimator = estimator_name))
  out <- list(estimator = estimator_name)
  out$nobs <- tryCatch(stats::nobs(model), error = function(e) NA_integer_)
  out$logLik <- tryCatch(as.numeric(stats::logLik(model)), error = function(e) NA_real_)

  if (inherits(model, "fixest")) {
    out <- utils::modifyList(out, safe_r2(model))
  } else {
    out$r2 <- tryCatch(summary(model)$r.squared, error = function(e) NA_real_)
    out$adj_r2 <- tryCatch(summary(model)$adj.r.squared, error = function(e) NA_real_)
  }
  out
}

ensure_standard_columns <- function(df, conf_level = 0.95) {
  if (is.null(df) || nrow(df) == 0) return(df)
  out <- as.data.frame(df)

  rename_map <- c(
    estimate = "estimate",
    Estimate = "estimate",
    att = "estimate",
    ATT = "estimate",
    coef = "estimate",
    coefficient = "estimate",
    std.error = "std.error",
    std_error = "std.error",
    se = "std.error",
    Std..Error = "std.error",
    statistic = "statistic",
    stat = "statistic",
    t = "statistic",
    p.value = "p.value",
    p_value = "p.value",
    pval = "p.value",
    conf.low = "conf.low",
    conf.low. = "conf.low",
    conf_high = "conf.high",
    conf.high = "conf.high",
    ci_low = "conf.low",
    ci_high = "conf.high"
  )
  for (nm in names(rename_map)) {
    if (nm %in% names(out) && !(rename_map[[nm]] %in% names(out))) {
      names(out)[names(out) == nm] <- rename_map[[nm]]
    }
  }

  if (!"term" %in% names(out)) {
    out$term <- rownames(out) %||% seq_len(nrow(out))
  }

  if ("estimate" %in% names(out) && "std.error" %in% names(out) && !all(c("conf.low", "conf.high") %in% names(out))) {
    ci <- compute_conf_int(out$estimate, out$std.error, level = conf_level)
    out$conf.low <- ci$low
    out$conf.high <- ci$high
  }
  add_test_statistics(out)
}

add_test_statistics <- function(df) {
  if (is.null(df) || nrow(df) == 0) return(df)
  out <- as.data.frame(df)
  if (all(c("estimate", "std.error") %in% names(out))) {
    if (!"statistic" %in% names(out)) {
      out$statistic <- out$estimate / out$std.error
      out$statistic[!is.finite(out$statistic)] <- NA_real_
    }
    if (!"p.value" %in% names(out)) {
      out$p.value <- 2 * stats::pnorm(-abs(out$statistic))
      out$p.value[!is.finite(out$p.value)] <- NA_real_
    }
  }
  out
}

make_run_metadata <- function(config, result, diagnostics) {
  list(
    timestamp = format(Sys.time(), "%Y-%m-%d %H:%M:%S %Z"),
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
    notes = config$notes,
    n_estimates = if (!is.null(result$estimates)) nrow(result$estimates) else 0L,
    n_event_study = if (!is.null(result$event_study)) nrow(result$event_study) else 0L,
    diagnostics = diagnostics,
    model_stats = result$model_stats %||% NULL,
    output_files = result$output_files %||% NULL
  )
}

write_summary_text <- function(path, text) {
  cat(text, file = path)
}
