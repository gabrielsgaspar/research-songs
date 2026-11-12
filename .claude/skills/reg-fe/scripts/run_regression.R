suppressPackageStartupMessages({
  library(yaml)
  library(jsonlite)
  library(fixest)
  library(broom)
})

args_all <- commandArgs(trailingOnly = FALSE)
file_arg <- grep("^--file=", args_all, value = TRUE)
if (length(file_arg) == 0) {
  stop("Could not determine script path.", call. = FALSE)
}
script_path <- normalizePath(sub("^--file=", "", file_arg[1]))
script_dir <- dirname(script_path)
source(file.path(script_dir, "helpers.R"))

args <- commandArgs(trailingOnly = TRUE)
if (length(args) < 1) {
  stop("Usage: Rscript scripts/run_regression.R path/to/config.yml", call. = FALSE)
}

config_path <- args[1]
if (!file.exists(config_path)) {
  stop(sprintf("Config file not found: %s", config_path), call. = FALSE)
}

config <- yaml::read_yaml(config_path)

data_path <- config$data$path
outcome <- config$regression$outcome
regressors <- normalize_to_char_vec(config$regression$regressors)
controls <- normalize_to_char_vec(config$regression$controls)
fixed_effects <- normalize_to_char_vec(config$regression$fixed_effects)
cluster <- normalize_to_char_vec(config$regression$cluster)
output_dir <- config$output$dir
conf_level <- config$regression$conf_level %||% 0.95

assert_scalar_string(data_path, "data.path")
assert_scalar_string(outcome, "regression.outcome")
assert_scalar_string(output_dir, "output.dir")
if (length(regressors) == 0) {
  stop("`regression.regressors` must contain at least one regressor.", call. = FALSE)
}

data <- load_data_file(data_path)
validate_columns(data, c(outcome, regressors, controls, fixed_effects, cluster), "required")

built <- build_feols_formula(
  outcome = outcome,
  regressors = regressors,
  controls = controls,
  fixed_effects = fixed_effects
)

vcov_arg <- NULL
if (length(cluster) == 1) {
  vcov_arg <- stats::as.formula(paste0("~", cluster))
} else if (length(cluster) > 1) {
  vcov_arg <- stats::as.formula(paste0("~", paste(cluster, collapse = " + ")))
}

model <- if (is.null(vcov_arg)) {
  fixest::feols(fml = built$formula, data = data)
} else {
  fixest::feols(fml = built$formula, data = data, vcov = vcov_arg)
}

dir.create(output_dir, recursive = TRUE, showWarnings = FALSE)
writeLines(built$formula_string, con = file.path(output_dir, "model_formula.txt"))

model_stats <- extract_model_stats(model)
coefficient_table <- extract_coefficients(model, conf_level = conf_level)
fixef_sizes <- extract_fixef_sizes(model)

summary_out <- list(
  estimator = "fixest::feols",
  data_path = normalizePath(data_path, winslash = "/", mustWork = FALSE),
  formula = built$formula_string,
  outcome = outcome,
  regressors = regressors,
  controls = controls,
  fixed_effects = fixed_effects,
  cluster = cluster,
  confidence_level = conf_level,
  model_stats = model_stats,
  fixed_effect_sizes = fixef_sizes,
  coefficients = coefficient_table
)

run_metadata <- list(
  config_path = normalizePath(config_path, winslash = "/", mustWork = FALSE),
  output_dir = normalizePath(output_dir, winslash = "/", mustWork = FALSE),
  timestamp_utc = format(Sys.time(), tz = "UTC", usetz = TRUE),
  r_version = paste(R.version$major, R.version$minor, sep = "."),
  package_versions = list(
    fixest = as.character(utils::packageVersion("fixest")),
    broom = as.character(utils::packageVersion("broom")),
    yaml = as.character(utils::packageVersion("yaml")),
    jsonlite = as.character(utils::packageVersion("jsonlite"))
  )
)

write_json_pretty(summary_out, file.path(output_dir, "results.json"))
write_json_pretty(run_metadata, file.path(output_dir, "run_metadata.json"))

cat(sprintf("Regression complete. Results written to %s\n", output_dir))
