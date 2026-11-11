#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -lt 1 ]; then
  echo "Usage: bash scripts/run_reg_fe.sh path/to/config.yml"
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
Rscript "$SCRIPT_DIR/install_packages.R"
Rscript "$SCRIPT_DIR/run_regression.R" "$1"
