"""Where things are: the repository root, the local data folder, and its version folders.

Data never lives in Git. Code asks `data_root()` for the data folder and never
builds `root / "data"` itself, so one data folder can serve several checkouts.

Inside the data folder, every saved table lives in a version folder:
`<layer>/<whose>/<when>/`. The functions below build these folders; no other
module builds them from strings. `docs/standards/data_layout.md` is the standard.
"""

import os
import re
from dataclasses import dataclass, fields
from datetime import date, datetime
from pathlib import Path

DATA_ROOT_ENV = "SONGS_DATA_ROOT"
MANIFEST_NAME = "_MANIFEST.json"
ISO3 = re.compile(r"[A-Z]{3}")
SOURCE = re.compile(r"[a-z0-9][a-z0-9_]*")
DAY = re.compile(r"\d{8}")
RUN_ID = re.compile(r"\d{8}T\d{6}Z")
# `raw/manual_review/<ISO3>/<YYYYMMDD>/` has its own function, so no source may take the name.
MANUAL_REVIEW = "manual_review"


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


def check_iso3(iso3: str) -> str:
    """Return a country code, or raise ValueError when it is not three capital letters."""
    if not isinstance(iso3, str) or not ISO3.fullmatch(iso3):
        raise ValueError(f"iso3 must be three capital letters, got {iso3!r}")
    return iso3


def check_source(source: str) -> str:
    """Return a source key, or raise ValueError when it is not a lower-case key."""
    if not isinstance(source, str) or not SOURCE.fullmatch(source):
        raise ValueError(f"source must be a lower-case key such as lrclib, got {source!r}")
    return source


def check_day(day: date | str) -> str:
    """Return a date as `YYYYMMDD`, or raise ValueError when it is not a calendar date."""
    if isinstance(day, date) and not isinstance(day, datetime):
        return f"{day:%Y%m%d}"
    try:
        if not isinstance(day, str) or not DAY.fullmatch(day):
            raise ValueError
        datetime.strptime(day, "%Y%m%d")
    except ValueError:
        raise ValueError(f"a date must look like 20260131, got {day!r}") from None
    return day


def check_run_id(run_id: str) -> str:
    """Return a run id, or raise ValueError when it is not a UTC second `YYYYMMDDTHHMMSSZ`."""
    try:
        if not isinstance(run_id, str) or not RUN_ID.fullmatch(run_id):
            raise ValueError
        datetime.strptime(run_id, "%Y%m%dT%H%M%SZ")
    except ValueError:
        raise ValueError(f"run_id must look like 20260131T235959Z, got {run_id!r}") from None
    return run_id


def _raw_source(source: str) -> str:
    if check_source(source) == MANUAL_REVIEW:
        raise ValueError(f"{MANUAL_REVIEW} is not a source; use raw_manual_review_dir")
    return source


def raw_dir(data: Path, source: str, day: date | str) -> Path:
    """Return `raw/<source>/<YYYYMMDD>/`: the files of one download, as received."""
    return data / "raw" / _raw_source(source) / check_day(day)


def raw_manual_review_dir(data: Path, iso3: str, day: date | str) -> Path:
    """Return `raw/manual_review/<ISO3>/<YYYYMMDD>/`: a review workbook from a person."""
    return data / "raw" / MANUAL_REVIEW / check_iso3(iso3) / check_day(day)


def clean_dump_dir(data: Path, source: str, day: date | str) -> Path:
    """Return `clean/dumps/<source>/<YYYYMMDD>/`: one lyric dump in the uniform format."""
    return data / "clean" / "dumps" / check_source(source) / check_day(day)


def clean_catalog_dir(data: Path, source: str, day: date | str) -> Path:
    """Return `clean/catalog/<source>/<YYYYMMDD>/`: the parsed tables of one catalog."""
    return data / "clean" / "catalog" / check_source(source) / check_day(day)


def clean_countries_dir(data: Path, day: date | str) -> Path:
    """Return `clean/countries/<YYYYMMDD>/`: one build of the country-year table."""
    return data / "clean" / "countries" / check_day(day)


def country_songs_dir(data: Path, iso3: str, run_id: str) -> Path:
    """Return `lyrics/<ISO3>/songs/<run id>/`: the full state of a country after a run."""
    return data / "lyrics" / check_iso3(iso3) / "songs" / check_run_id(run_id)


def country_scores_dir(data: Path, iso3: str, run_id: str) -> Path:
    """Return `lyrics/<ISO3>/scores/<run id>/`: the topic scores of one scoring run."""
    return data / "lyrics" / check_iso3(iso3) / "scores" / check_run_id(run_id)


def analysis_dir(data: Path, day: date | str) -> Path:
    """Return `analysis/<YYYYMMDD>/`: one release of the final files."""
    return data / "analysis" / check_day(day)


def _versions(parent: Path, name: re.Pattern[str], *, complete: bool) -> list[Path]:
    """Return the version folders under `parent`, oldest first.

    With `complete`, only the folders that hold a manifest count.
    """
    return sorted(
        path
        for path in parent.glob("*")
        if path.is_dir()
        and name.fullmatch(path.name)
        and (not complete or (path / MANIFEST_NAME).is_file())
    )


def _latest(parent: Path, name: re.Pattern[str]) -> Path | None:
    """Return the newest version folder under `parent` that has a manifest, or None."""
    versions = _versions(parent, name, complete=True)
    return versions[-1] if versions else None


def latest_raw_dir(data: Path, source: str) -> Path | None:
    """Return the newest complete `raw/<source>/<YYYYMMDD>/`, or None."""
    return _latest(data / "raw" / _raw_source(source), DAY)


def latest_raw_manual_review_dir(data: Path, iso3: str) -> Path | None:
    """Return the newest complete `raw/manual_review/<ISO3>/<YYYYMMDD>/`, or None."""
    return _latest(data / "raw" / MANUAL_REVIEW / check_iso3(iso3), DAY)


def raw_manual_review_dirs(data: Path, iso3: str) -> list[Path]:
    """Return every dated workbook folder of a country, oldest first, with or without a manifest.

    A person puts a workbook in its folder, and no command writes a manifest there yet.
    """
    return _versions(data / "raw" / MANUAL_REVIEW / check_iso3(iso3), DAY, complete=False)


def latest_clean_dump_dir(data: Path, source: str) -> Path | None:
    """Return the newest complete `clean/dumps/<source>/<YYYYMMDD>/`, or None."""
    return _latest(data / "clean" / "dumps" / check_source(source), DAY)


def latest_clean_catalog_dir(data: Path, source: str) -> Path | None:
    """Return the newest complete `clean/catalog/<source>/<YYYYMMDD>/`, or None."""
    return _latest(data / "clean" / "catalog" / check_source(source), DAY)


def latest_clean_countries_dir(data: Path) -> Path | None:
    """Return the newest complete `clean/countries/<YYYYMMDD>/`, or None."""
    return _latest(data / "clean" / "countries", DAY)


def latest_country_songs_dir(data: Path, iso3: str) -> Path | None:
    """Return the newest complete `lyrics/<ISO3>/songs/<run id>/`: the current state, or None."""
    return _latest(data / "lyrics" / check_iso3(iso3) / "songs", RUN_ID)


def latest_country_scores_dir(data: Path, iso3: str) -> Path | None:
    """Return the newest complete `lyrics/<ISO3>/scores/<run id>/`, or None."""
    return _latest(data / "lyrics" / check_iso3(iso3) / "scores", RUN_ID)


def latest_analysis_dir(data: Path) -> Path | None:
    """Return the newest complete `analysis/<YYYYMMDD>/`, or None."""
    return _latest(data / "analysis", DAY)


def data_relative(data: Path, path: Path) -> str:
    """Return a path as text relative to the data folder, with forward slashes.

    A folder ends with a slash. Manifests and run records hold only such paths, so
    they never name a drive, a user folder or a bucket.
    """
    text = path.relative_to(data).as_posix()
    return f"{text}/" if path.is_dir() else text
