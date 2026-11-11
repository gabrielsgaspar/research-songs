"""Where things are: the repository root and the local data folder.

Data never lives in Git. Code asks `data_root()` for the data folder and never
builds `root / "data"` itself, so one data folder can serve several checkouts.
"""

import os
from dataclasses import dataclass, fields
from pathlib import Path

DATA_ROOT_ENV = "SONGS_DATA_ROOT"


@dataclass(frozen=True)
class DataLayout:
    """The tiers of the local data folder. Each field is `<data root>/<field name>`."""

    raw: Path
    interim: Path
    clean: Path
    extraction: Path
    lyrics: Path
    processed: Path
    analysis: Path
    cache: Path
    restricted: Path
    staging: Path
    manifests: Path
    rankings: Path
    matching: Path
    tmp: Path


@dataclass(frozen=True)
class ProjectPaths:
    """The folders that code reads or writes."""

    root: Path
    data: Path
    countries: Path
    resources: Path
    prompts: Path
    docs: Path
    outputs: Path
    layout: DataLayout


def resolve_project_root(start: Path | None = None) -> Path:
    """Return the repository root: the nearest folder at or above `start` with `pyproject.toml`.

    `start` defaults to this file, so the answer does not depend on the working directory.
    """
    current = (start or Path(__file__)).resolve()
    if current.is_file():
        current = current.parent
    for candidate in (current, *current.parents):
        if (candidate / "pyproject.toml").is_file():
            return candidate
    raise FileNotFoundError(f"no pyproject.toml at or above {current}")


def data_root(root: Path | None = None) -> Path:
    """Return the local data folder.

    `SONGS_DATA_ROOT` names it when set, and must then be an existing absolute folder.
    Without the variable, the folder is `<repository root>/data` (ignored by Git).
    """
    value = os.environ.get(DATA_ROOT_ENV, "").strip()
    if not value:
        return resolve_project_root(root) / "data"
    path = Path(value)
    if not path.is_absolute():
        raise ValueError(f"{DATA_ROOT_ENV} must be an absolute path, got {value!r}")
    if not path.is_dir():
        raise FileNotFoundError(f"{DATA_ROOT_ENV} points to a folder that does not exist: {path}")
    return path


def project_paths(root: Path | None = None) -> ProjectPaths:
    """Return every project folder for a repository root."""
    resolved = resolve_project_root(root)
    data = data_root(resolved)
    return ProjectPaths(
        root=resolved,
        data=data,
        countries=resolved / "countries",
        resources=resolved / "resources",
        prompts=resolved / "prompts",
        docs=resolved / "docs",
        outputs=resolved / "outputs",
        layout=DataLayout(**{field.name: data / field.name for field in fields(DataLayout)}),
    )
