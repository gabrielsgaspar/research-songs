required_packages <- c(
  "yaml",
  "jsonlite",
  "fixest",
  "broom",
  "arrow",
  "readr"
)

installed <- rownames(installed.packages())
to_install <- setdiff(required_packages, installed)

if (length(to_install) > 0) {
  install.packages(to_install, repos = "https://cloud.r-project.org")
}

cat("Package installation check complete.\n")
