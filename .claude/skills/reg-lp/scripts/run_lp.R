lp_script_root <- function() {
  args <- commandArgs(trailingOnly = FALSE)
  file <- sub("^--file=", "", args[grepl("^--file=", args)])
  if (!length(file)) stop("Run this entry point with Rscript.")
  normalizePath(file.path(dirname(file[1]), ".."), mustWork = TRUE)
}

lp_main <- function(args = commandArgs(trailingOnly = TRUE)) {
  if (length(args) != 1L) stop("Usage: Rscript scripts/run_lp.R CONFIG.yml")
  skillroot <- lp_script_root()
  source(file.path(skillroot, "scripts", "runtime.R"))
  runtime_init(skillroot)
  source(file.path(skillroot, "scripts", "estimator.R"))
  config <- read_config(args[1])
  data <- read_input(config)
  result <- run_lp(config, data)
  write_outputs(skillroot, result$resolved_config, data, result$estimates, result$diagnostics, result$extra)
}

if (sys.nframe() == 0L) lp_main()
