"""Settings read from environment variables, and from `.env` when it exists.

This repository is public, so no identifier of a private resource has a default
here. A setting that is not set is `None`; `require` turns that into a clear error
at the point of use.
"""

import os
from dataclasses import dataclass
from pathlib import Path

from songs.common.paths import resolve_project_root

GCP_PROJECT_ENV = "SONGS_GCP_PROJECT"
GCS_BUCKET_ENV = "SONGS_GCS_BUCKET"
OFFLINE_ENV = "SONGS_OFFLINE"
TRUE_WORDS = {"1", "true", "yes", "y", "on"}
QUOTES = ('"', "'")


@dataclass(frozen=True)
class SongsConfig:
    """Resolved settings. `None` means the variable is not set."""

    gcp_project: str | None
    gcs_bucket: str | None
    offline: bool

    def require(self, name: str) -> str:
        """Return a setting that the caller cannot work without, or raise naming its variable."""
        value = getattr(self, name)
        if not value:
            variable = {"gcp_project": GCP_PROJECT_ENV, "gcs_bucket": GCS_BUCKET_ENV}[name]
            raise RuntimeError(f"{variable} is not set; add it to .env (see .env.example)")
        return value


def load_env_file(path: Path) -> None:
    """Copy `KEY=VALUE` lines of a `.env` file into the environment.

    A variable that is already set keeps its value. Blank lines and lines that start
    with `#` are skipped. Quotes around a value are removed.
    """
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in QUOTES:
            value = value[1:-1]
        os.environ.setdefault(key.strip(), value)


def load_config(env_file: Path | None = None) -> SongsConfig:
    """Load `.env` from the repository root (or `env_file`) and return the settings."""
    load_env_file(env_file or resolve_project_root() / ".env")
    return SongsConfig(
        gcp_project=os.environ.get(GCP_PROJECT_ENV, "").strip() or None,
        gcs_bucket=os.environ.get(GCS_BUCKET_ENV, "").strip() or None,
        offline=os.environ.get(OFFLINE_ENV, "").strip().lower() in TRUE_WORDS,
    )
