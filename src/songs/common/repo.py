"""Facts about the checkout, for records of how an output was made."""

import subprocess
from pathlib import Path


def git_sha(root: Path) -> str:
    """Return the current commit of the checkout at `root`, or "unknown". Never raises."""
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=15,
            check=False,
        )
    except OSError, subprocess.TimeoutExpired:
        return "unknown"
    sha = result.stdout.strip()
    return sha if result.returncode == 0 and sha else "unknown"
