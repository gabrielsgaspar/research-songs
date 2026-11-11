# Skills

Four regression skills for Claude Code. Each skill has a `SKILL.md` that says how to use it.

| Skill | What it estimates | Language | What must be installed |
|---|---|---|---|
| `reg-fe` | Linear and fixed-effects regressions with `fixest::feols` | R | R, `Rscript`, packages from `scripts/install_packages.R` |
| `reg-did` | Difference-in-differences and event studies: Callaway-Sant'Anna, Sun-Abraham, imputation (BJS), de Chaisemartin-D'Haultfoeuille, dynamic TWFE | R | R, `Rscript`, packages from `scripts/install_packages.R` |
| `reg-lp` | Local projection impulse responses: time series, panel, lag-augmented, IV | R | R, `Rscript`, packages from `renv.lock` (run `scripts/setup.R`) |
| `reg-var` | Vector autoregression impulse responses: reduced form, recursive, proxy | R | R, `Rscript`, packages from `renv.lock` (run `scripts/setup.R`) |

All four skills run R through `Rscript`. Python is used only for the `install.py` helper in `reg-lp` and `reg-var`.

The tests for the skills are in `tests/skills/`. They cover only the Python installer. The R code is not tested in this repository, and any R test is skipped where R is not installed. The R code was not run when these skills were added to this repository.
