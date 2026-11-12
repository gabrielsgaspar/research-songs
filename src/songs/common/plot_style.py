"""The one visual style of every paper figure. The rules are in docs/standards/figures.md."""

from __future__ import annotations

import shutil
import subprocess
import warnings
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any

PAPER_FONT_FAMILY = "Latin Modern Roman"
FALLBACK_FONT_FAMILY = "STIXGeneral"
PAPER_TEXT_COLOR = "black"
LATIN_MODERN_FILES: tuple[str, ...] = (
    "lmroman10-regular.otf",
    "lmroman10-bold.otf",
    "lmroman10-italic.otf",
    "lmroman10-bolditalic.otf",
)

DPI = 300

# Sizes in inches, width then height.
SIZE_STANDARD: tuple[float, float] = (8.0, 5.0)
SIZE_LARGE: tuple[float, float] = (8.5, 6.0)
SIZE_WIDE: tuple[float, float] = (12.0, 5.0)
SIZE_TALL: tuple[float, float] = (7.0, 8.0)

# One color and one marker per topic family. Seven colors cannot all be told apart,
# so the marker is a second, redundant code.
FAMILY_COLORS: dict[str, str] = {
    "A": "#2a78d6",
    "B": "#eb6834",
    "C": "#1baf7a",
    "D": "#eda100",
    "E": "#e87ba4",
    "F": "#008300",
    "G": "#7a4fa3",
}
FAMILY_MARKERS: dict[str, str] = {
    "A": "o",
    "B": "s",
    "C": "^",
    "D": "D",
    "E": "v",
    "F": "P",
    "G": "X",
}
CATEGORICAL: tuple[str, ...] = (
    "#2a78d6",
    "#eb6834",
    "#1baf7a",
    "#eda100",
    "#e87ba4",
    "#008300",
)

PAPER_MATPLOTLIB_RCPARAMS: dict[str, Any] = {
    "font.family": PAPER_FONT_FAMILY,
    "font.serif": [PAPER_FONT_FAMILY, "LM Roman 10", "Computer Modern Roman", "DejaVu Serif"],
    "mathtext.fontset": "cm",
    "font.size": 10,
    "axes.titlesize": 11,
    "axes.titleweight": "regular",
    "axes.labelsize": 10,
    "xtick.labelsize": 9,
    "ytick.labelsize": 9,
    "legend.fontsize": 9,
    "legend.frameon": False,
    "text.color": PAPER_TEXT_COLOR,
    "axes.labelcolor": PAPER_TEXT_COLOR,
    "axes.titlecolor": PAPER_TEXT_COLOR,
    "axes.edgecolor": PAPER_TEXT_COLOR,
    "xtick.color": PAPER_TEXT_COLOR,
    "ytick.color": PAPER_TEXT_COLOR,
    "legend.labelcolor": PAPER_TEXT_COLOR,
    "axes.facecolor": "white",
    "figure.facecolor": "white",
    "figure.dpi": DPI,
    "savefig.dpi": DPI,
    "savefig.facecolor": "white",
    "axes.formatter.useoffset": False,
    "axes.formatter.use_mathtext": False,
}


def _installed() -> bool:
    """Return True when matplotlib can find the paper font."""
    from matplotlib import font_manager

    try:
        font_manager.findfont(PAPER_FONT_FAMILY, fallback_to_default=False)
    except ValueError:
        return False
    return True


def _register_from_tex() -> None:
    """Add the Latin Modern files that a TeX installation reports, if there is one."""
    from matplotlib import font_manager

    kpsewhich = shutil.which("kpsewhich")
    if not kpsewhich:
        return
    for filename in LATIN_MODERN_FILES:
        try:
            result = subprocess.run(
                [kpsewhich, filename], check=False, capture_output=True, text=True, timeout=30
            )
        except OSError, subprocess.SubprocessError:
            return
        lines = result.stdout.strip().splitlines()
        if result.returncode == 0 and lines and Path(lines[0]).is_file():
            font_manager.fontManager.addfont(lines[0])


@lru_cache(maxsize=1)
def paper_font_family() -> str:
    """Return Latin Modern Roman when found, else STIX with one warning. Never raises."""
    if not _installed():
        _register_from_tex()
    if _installed():
        return PAPER_FONT_FAMILY
    warnings.warn(
        f"{PAPER_FONT_FAMILY} not found; figures use {FALLBACK_FONT_FAMILY}.",
        stacklevel=2,
    )
    return FALLBACK_FONT_FAMILY


def apply_paper_matplotlib(plt: Any, *, overrides: Mapping[str, Any] | None = None) -> None:
    """Apply the paper style to matplotlib. Call it once before you draw."""
    params = dict(PAPER_MATPLOTLIB_RCPARAMS)
    family = paper_font_family()
    params["font.family"] = family
    params["mathtext.fontset"] = "cm" if family == PAPER_FONT_FAMILY else "stix"
    if overrides:
        params.update(overrides)
    plt.rcParams.update(params)


def thousands(value: float) -> str:
    """Format a number as 1, 100, 1,000, 10,000."""
    return f"{value:,.0f}"


def percent(value: float) -> str:
    """Format a fraction as a whole percent: 0%, 10%, 100%."""
    return f"{round(value * 100)}%"


def save_png(fig: Any, path: str | Path) -> Path:
    """Save a figure as PNG at DPI with a white background. Refuse any other suffix."""
    target = Path(path)
    if target.suffix.lower() != ".png":
        raise ValueError(f"Figures are PNG only; got {target.suffix or 'no suffix'}: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(target, dpi=DPI, facecolor="white", bbox_inches="tight")
    return target
