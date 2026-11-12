# Shared portable input, output, and dependency helpers.
runtime_init <- function(skill_root) {
  cache <- Sys.getenv("REG_SKILLS_R_LIBRARY", unset = file.path(
    file.path(Sys.getenv("USERPROFILE", unset = path.expand("~")), ".cache"), "reg-skills", paste0("R-", getRversion())))
  .libPaths(c(cache, .libPaths()))
  lock_path <- file.path(skill_root, "renv.lock")
  if (!file.exists(lock_path)) stop("Dependency lock is missing. Run the setup command.")
  if (!requireNamespace("jsonlite", quietly = TRUE)) stop("Run scripts/setup.R to restore dependencies.")
  lock <- jsonlite::read_json(lock_path, simplifyVector = FALSE)
  if (as.character(getRversion()) != lock$R$Version) stop("R version differs from renv.lock.")
  for (p in names(lock$Packages)) {
    if (!requireNamespace(p, quietly = TRUE) ||
        utils::packageVersion(p) != package_version(lock$Packages[[p]]$Version)) {
      stop(sprintf("Dependency %s differs from renv.lock. Run scripts/setup.R.", p))
    }
  }
  if (requireNamespace("fixest", quietly = TRUE)) fixest::setFixest_nthreads(1)
  options(stringsAsFactors = FALSE, scipen = 999)
  invisible(cache)
}

absolute_path <- function(path, base) {
  if (!is.character(path) || length(path) != 1L || is.na(path) || !nzchar(path)) {
    stop("A nonempty file path is required.")
  }
  if (!grepl("^([A-Za-z]:[/\\\\]|/|~)", path)) path <- file.path(base, path)
  normalizePath(path.expand(path), winslash = "/", mustWork = FALSE)
}

read_config <- function(path) {
  path <- normalizePath(path, winslash = "/", mustWork = TRUE)
  config <- yaml::read_yaml(path)
  if (!is.list(config) || is.null(config$data$path) || is.null(config$output$dir)) {
    stop("The configuration must define data.path and output.dir.")
  }
  base <- dirname(path)
  config$data$path <- absolute_path(config$data$path, base)
  config$output$dir <- absolute_path(config$output$dir, base)
  if (identical(config$data$path, config$output$dir)) stop("Output cannot replace the input.")
  config$config_path <- path
  config
}

read_input <- function(config) {
  path <- config$data$path
  if (!file.exists(path)) stop("The input file does not exist.")
  extension <- tolower(tools::file_ext(path))
  data <- switch(extension,
    csv = utils::read.csv(path, check.names = FALSE, na.strings = c("", "NA")),
    parquet = as.data.frame(nanoparquet::read_parquet(path)),
    stop("Input must be CSV or Parquet."))
  if (!nrow(data) || anyDuplicated(names(data))) stop("Input needs rows and unique column names.")
  data
}

write_json <- function(value, path) {
  jsonlite::write_json(value, path, pretty = TRUE, auto_unbox = TRUE,
                       dataframe = "rows", null = "null", na = "null", digits = NA)
}

plot_estimates <- function(estimates, path, config) {
  if (!all(c("horizon", "estimate") %in% names(estimates)) || !nrow(estimates)) {
    stop("Estimates need horizon and estimate columns.")
  }
  grouping <- intersect(c("method", "shock", "response", "outcome"), names(estimates))
  labels <- if (length(grouping)) apply(estimates[grouping], 1L, paste, collapse = ": ") else rep("Response", nrow(estimates))
  groups <- unique(labels)
  columns <- min(3L, ceiling(sqrt(length(groups))))
  rows <- ceiling(length(groups) / columns)
  grDevices::png(path, width = 4.5 * columns, height = 3.5 * rows,
                units = "in", res = 300)
  on.exit(grDevices::dev.off(), add = TRUE)
  graphics::par(mfrow = c(rows, columns), mar = c(4, 4, 3, 1), oma = c(3, 0, 0, 0))
  for (label in groups) {
    frame <- estimates[labels == label, , drop = FALSE]
    frame <- frame[order(frame$horizon), , drop = FALSE]
    limits <- range(unlist(frame[intersect(c("estimate", "lower", "upper"), names(frame))]), finite = TRUE)
    if (!all(is.finite(limits))) stop("The response plot contains no finite estimates.")
    if (diff(limits) == 0) limits <- limits + c(-1, 1) * max(1, abs(limits[1]) * .1)
    title <- if (!is.null(config$model$outcome)) {
      paste(config$model$outcome, "response to", config$model$shock)
    } else paste(frame$response[1], "response to", frame$shock[1])
    units <- switch(config$data$frequency, annual = "years", quarterly = "quarters",
                    monthly = "months", "time periods")
    graphics::plot(frame$horizon, frame$estimate, type = "l", lwd = 2,
                   xlab = paste0("Horizon (", units, ")"), ylab = "Response (input units)",
                   main = title, ylim = limits, xaxt = "n")
    ticks <- if (max(frame$horizon) >= 5) seq(0, max(frame$horizon), by = 5) else unique(frame$horizon)
    graphics::axis(1, at = ticks)
    graphics::abline(h = 0, col = "gray70")
    if (all(c("lower", "upper") %in% names(frame)) && any(is.finite(frame$lower))) {
      graphics::lines(frame$horizon, frame$lower, lty = 2)
      graphics::lines(frame$horizon, frame$upper, lty = 2)
    }
  }
  graphics::mtext(paste("Source:", basename(config$data$path), "| Method:", config$model$method),
                  side = 1, outer = TRUE, cex = .7)
  if ("lower" %in% names(estimates) && any(is.finite(estimates$lower))) {
    graphics::mtext(paste0("Solid: estimate. Dashed: ", 100 * config$inference$level, "% pointwise interval."),
                    side = 1, line = 1.2, outer = TRUE, cex = .7)
  }
}

write_outputs <- function(skill_root, config, data, estimates, diagnostics, extra = list()) {
  output <- config$output$dir
  bundle <- normalizePath(skill_root, winslash = "/", mustWork = TRUE)
  normalized_output <- normalizePath(output, winslash = "/", mustWork = FALSE)
  if (identical(normalized_output, bundle) || startsWith(normalized_output, paste0(bundle, "/"))) {
    stop("Output must be outside the skill bundle.")
  }
  if (file.exists(output) && !dir.exists(output)) stop("Output must be a directory.")
  # Prepare every result before replacing any existing result file.
  staging <- tempfile("reg-skill-results-")
  dir.create(staging)
  utils::write.csv(estimates, file.path(staging, "estimates.csv"), row.names = FALSE, na = "")
  yaml::write_yaml(config, file.path(staging, "config_used.yml"))
  versions <- lapply(jsonlite::read_json(file.path(skill_root, "renv.lock"))$Packages,
                     function(p) p$Version)
  metadata <- list(skill = basename(skill_root), input = config$data$path,
                   input_sha256 = digest::digest(file = config$data$path, algo = "sha256"),
                   input_rows = nrow(data), R = as.character(getRversion()),
                   packages = versions, seed = config$seed,
                   created_utc = format(Sys.time(), tz = "UTC", usetz = TRUE))
  sources <- list.files(skill_root, recursive = TRUE, full.names = TRUE)
  sources <- sources[!file.info(sources)$isdir & !grepl("(__pycache__|\\.pyc$)", sources)]
  metadata$bundle_sha256 <- as.list(stats::setNames(vapply(sources,
    function(p) digest::digest(file = p, algo = "sha256"), character(1)),
    substring(sources, nchar(skill_root) + 2L)))
  for (name in names(extra)) {
    if (!grepl("^[A-Za-z][A-Za-z0-9_]*$", name)) stop("Invalid extra output name.")
    if (is.data.frame(extra[[name]])) {
      utils::write.csv(extra[[name]], file.path(staging, paste0(name, ".csv")), row.names = FALSE, na = "")
    } else write_json(extra[[name]], file.path(staging, paste0(name, ".json")))
  }
  write_json(list(metadata = metadata, config = config, estimates = estimates,
                  diagnostics = diagnostics), file.path(staging, "results.json"))
  plot_estimates(estimates, file.path(staging, "impulse_responses.png"), config)
  dir.create(output, recursive = TRUE, showWarnings = FALSE)
  for (path in list.files(staging, full.names = TRUE)) {
    target <- file.path(output, basename(path))
    if (normalizePath(target, winslash = "/", mustWork = FALSE) == config$data$path) {
      stop("A result file would replace the input.")
    }
  }
  if (!all(file.copy(list.files(staging, full.names = TRUE), output, overwrite = TRUE))) {
    stop("A result file could not be saved.")
  }
  message(sprintf("Results saved to %s", output))
  invisible(output)
}
