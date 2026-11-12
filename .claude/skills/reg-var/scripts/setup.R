# Restore dependencies only when this explicit setup command is executed.
args_all <- commandArgs(trailingOnly = FALSE)
script <- sub("^--file=", "", grep("^--file=", args_all, value = TRUE)[1])
root <- dirname(dirname(normalizePath(script, winslash = "/", mustWork = TRUE)))
cache <- Sys.getenv("REG_SKILLS_R_LIBRARY", unset = file.path(
  file.path(Sys.getenv("USERPROFILE", unset = path.expand("~")), ".cache"), "reg-skills", paste0("R-", getRversion())))
dir.create(cache, recursive = TRUE, showWarnings = FALSE)
.libPaths(c(cache, .libPaths()))
options(repos = c(CRAN = "https://cloud.r-project.org"), timeout = 300)
if (!requireNamespace("renv", quietly = TRUE)) utils::install.packages("renv", lib = cache)
renv::restore(project = root, lockfile = file.path(root, "renv.lock"), library = cache, prompt = FALSE)
source(file.path(root, "scripts", "runtime.R"))
runtime_init(root)
message("Locked dependencies are ready.")
