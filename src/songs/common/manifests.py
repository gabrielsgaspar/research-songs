"""Manifests: one `_MANIFEST.json` in every version folder of the data folder.

A manifest says which files a version folder holds: the size, the SHA-256 and
the row count of each file, the code that wrote them, and the folders or files
that they were built from. A writer calls `write_manifest` last, so a folder
without a manifest is incomplete, and a folder with one is never changed.

The run record says what a run collected. The manifest says which files exist
and what they hold. Neither holds the other; a `country_songs` manifest joins
to its run record by `country_iso3` and `run_id`.

`docs/standards/data_layout.md` is the standard.
"""

import hashlib
import json
import re
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

import duckdb

from songs.common import paths, schemas
from songs.common.repo import git_sha
from songs.common.run_records import utc_now

SCHEMA_VERSION = 1
COUNTRIES_FILE = "countries.parquet"
ANALYSIS_FILES = ("country_year.parquet", "songs.parquet")
ORIGIN_KEYS = ("url", "retrieved_utc", "license")
FILE_KEYS = ("path", "bytes", "sha256", "rows")
# The fields that are null for the kinds that they do not apply to.
OPTIONAL_FIELDS = ("country_iso3", "source", "run_id", "origin")
UTC_TIME = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
SHA256 = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True)
class Kind:
    """One kind of version folder.

    `whose` is the manifest field that names the source or the country of the
    folder, when the path has one. `when` says what the last part of the path
    is: a date (`day`) or the run id (`run_id`). `files` is the fixed file list,
    for the kinds that have one.
    """

    pattern: str
    folder: Callable[..., Path]
    whose: str | None
    when: str
    must_set: tuple[str, ...]
    files: tuple[str, ...] | None = None


def _files(group: str) -> tuple[str, ...]:
    return tuple(table.file for table in schemas.GROUPS[group])


KINDS: dict[str, Kind] = {
    "raw": Kind("raw/<source>/<YYYYMMDD>/", paths.raw_dir, "source", "day", ("source", "origin")),
    "raw_manual_review": Kind(
        "raw/manual_review/<ISO3>/<YYYYMMDD>/",
        paths.raw_manual_review_dir,
        "country_iso3",
        "day",
        ("country_iso3",),
    ),
    "clean_dump": Kind(
        schemas.DUMP_FOLDER,
        paths.clean_dump_dir,
        "source",
        "day",
        ("source", "inputs"),
        _files("dump_tables"),
    ),
    "clean_catalog": Kind(
        "clean/catalog/<source>/<YYYYMMDD>/",
        paths.clean_catalog_dir,
        "source",
        "day",
        ("source", "inputs"),
    ),
    "clean_countries": Kind(
        "clean/countries/<YYYYMMDD>/",
        paths.clean_countries_dir,
        None,
        "day",
        ("inputs",),
        (COUNTRIES_FILE,),
    ),
    "country_songs": Kind(
        schemas.COUNTRY_FOLDER,
        paths.country_songs_dir,
        "country_iso3",
        "run_id",
        ("country_iso3", "run_id", "inputs"),
        _files("country_tables"),
    ),
    "country_scores": Kind(
        schemas.SCORES_FOLDER,
        paths.country_scores_dir,
        "country_iso3",
        "run_id",
        ("country_iso3", "run_id", "inputs"),
        _files("score_tables"),
    ),
    "analysis": Kind(
        "analysis/<YYYYMMDD>/", paths.analysis_dir, None, "day", ("inputs",), ANALYSIS_FILES
    ),
}


def _is_count(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _is_relative(text: object) -> bool:
    """True for a path under the data folder: no scheme, drive letter, leading slash or `..`."""
    return (
        isinstance(text, str)
        and bool(text)
        and "://" not in text
        and "\\" not in text
        and not re.match(r"[A-Za-z]:|/", text)
        and ".." not in text.split("/")
    )


@dataclass
class Manifest:
    """The content of one `_MANIFEST.json`. The standard gives the meaning of each field."""

    kind: str
    path: str
    created_utc: str
    code_commit: str
    files: list[dict]
    country_iso3: str | None = None
    source: str | None = None
    run_id: str | None = None
    inputs: list[str] = field(default_factory=list)
    origin: dict | None = None
    counts: dict[str, int] = field(default_factory=dict)
    notes: str = ""
    schema_version: int = SCHEMA_VERSION

    def problems(self) -> list[str]:
        """Return one line for each rule that the manifest breaks. Empty means it is valid."""
        problems = []
        if self.schema_version != SCHEMA_VERSION:
            problems.append(f"schema_version must be {SCHEMA_VERSION}, got {self.schema_version!r}")
        if not isinstance(self.created_utc, str) or not UTC_TIME.fullmatch(self.created_utc):
            problems.append(
                f"created_utc must look like 2026-01-31T23:59:59Z: {self.created_utc!r}"
            )
        if not isinstance(self.code_commit, str) or not self.code_commit:
            problems.append("code_commit must name a commit")
        if not isinstance(self.notes, str):
            problems.append("notes must be text")
        if not isinstance(self.counts, dict) or not all(
            isinstance(name, str) and _is_count(value) for name, value in self.counts.items()
        ):
            problems.append("counts must map a name to a whole number that is not negative")
        if not isinstance(self.inputs, list) or not all(_is_relative(item) for item in self.inputs):
            problems.append("inputs must be paths relative to the data folder")
        problems += self._file_problems()
        if self.kind not in KINDS:
            return [*problems, f"kind must be one of {tuple(KINDS)}, got {self.kind!r}"]
        return problems + self._kind_problems(KINDS[self.kind])

    def _file_problems(self) -> list[str]:
        if not isinstance(self.files, list) or not all(
            isinstance(entry, dict) and tuple(sorted(entry)) == tuple(sorted(FILE_KEYS))
            for entry in self.files
        ):
            return [f"files must be a list of entries with the fields {FILE_KEYS}"]
        problems = []
        for entry in self.files:
            name = entry["path"]
            if not _is_relative(name) or name == paths.MANIFEST_NAME:
                problems.append(f"files: {name!r} is not a file path relative to the folder")
            if not isinstance(entry["sha256"], str) or not SHA256.fullmatch(entry["sha256"]):
                problems.append(f"files: sha256 of {name!r} must be 64 hex characters")
            if not _is_count(entry["bytes"]):
                problems.append(f"files: bytes of {name!r} must be a whole number")
            if entry["rows"] is not None and not _is_count(entry["rows"]):
                problems.append(f"files: rows of {name!r} must be a whole number or null")
        names = [entry["path"] for entry in self.files]
        if len(set(map(str, names))) != len(names):
            problems.append("files: a file appears twice")
        return problems

    def _kind_problems(self, kind: Kind) -> list[str]:
        problems = []
        for name in OPTIONAL_FIELDS:
            value = getattr(self, name)
            if name in kind.must_set and not value:
                problems.append(f"{name} must be set for the kind {self.kind}")
            if name not in kind.must_set and value is not None:
                problems.append(f"{name} must be null for the kind {self.kind}")
        if "inputs" in kind.must_set and not self.inputs:
            problems.append(f"inputs must be set for the kind {self.kind}")
        if isinstance(self.origin, dict) and (
            tuple(sorted(self.origin)) != tuple(sorted(ORIGIN_KEYS))
            or not all(value is None or isinstance(value, str) for value in self.origin.values())
        ):
            problems.append(f"origin must hold {ORIGIN_KEYS}, each one text or null")
        if not _is_relative(self.path):
            problems.append(
                "path is relative to the data folder, with no scheme, bucket name or drive "
                f"letter: {self.path!r}"
            )
        else:
            # The path function of the kind builds the path from the other fields,
            # so the patterns of the layout live in one place.
            version = self.path.rstrip("/").rsplit("/", 1)[-1]
            parts = [getattr(self, kind.whose)] if kind.whose else []
            parts.append(self.run_id if kind.when == "run_id" else version)
            try:
                expected = kind.folder(Path(), *parts).as_posix() + "/"
            except ValueError as error:
                problems.append(f"path does not fit {kind.pattern}: {error}")
            else:
                if self.path != expected:
                    problems.append(f"path must be {expected} ({kind.pattern}), got {self.path!r}")
        if kind.files is not None and isinstance(self.files, list):
            found = sorted(
                str(entry.get("path")) for entry in self.files if isinstance(entry, dict)
            )
            if found != sorted(kind.files):
                problems.append(f"files must be exactly {sorted(kind.files)}, found {found}")
        return problems

    def validate(self) -> None:
        """Raise ValueError when the manifest breaks a rule."""
        problems = self.problems()
        if problems:
            raise ValueError("; ".join(problems))


def _describe(folder: Path, path: Path) -> dict:
    """Return the manifest entry of one file: path, bytes, SHA-256, and rows of a Parquet file."""
    with path.open(mode="rb") as handle:
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
    rows = len(duckdb.read_parquet(str(path))) if path.suffix == ".parquet" else None
    return {
        "path": path.relative_to(folder).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": digest,
        "rows": rows,
    }


def write_manifest(
    data: Path,
    folder: Path,
    kind: str,
    *,
    country_iso3: str | None = None,
    source: str | None = None,
    run_id: str | None = None,
    inputs: Iterable[str] = (),
    origin: dict | None = None,
    counts: dict[str, int] | None = None,
    notes: str = "",
    uploaded_files: Iterable[dict] = (),
) -> Manifest:
    """Write the manifest of a version folder, as the last file of the folder, and return it.

    The function lists every file in the folder with its size, SHA-256 and row
    count. `uploaded_files` adds the entries of files of the folder that are in
    the bucket and no longer on this disk, such as the parts of a packed source
    (`tar_parts`). It refuses a folder that has a manifest (FileExistsError) and
    a manifest that breaks a rule (ValueError); then it writes nothing.
    """
    target = folder / paths.MANIFEST_NAME
    if not folder.is_dir():
        raise FileNotFoundError(f"{folder} is not a folder")
    if target.exists():
        raise FileExistsError(f"{target} exists; a version folder is never changed")
    manifest = Manifest(
        kind=kind,
        path=paths.data_relative(data, folder),
        created_utc=utc_now(),
        code_commit=git_sha(paths.resolve_project_root()),
        files=[_describe(folder, path) for path in sorted(folder.rglob("*")) if path.is_file()]
        + [dict(entry) for entry in uploaded_files],
        country_iso3=country_iso3,
        source=source,
        run_id=run_id,
        inputs=list(inputs),
        origin=origin,
        counts=dict(counts or {}),
        notes=notes,
    )
    manifest.validate()
    text = json.dumps(asdict(manifest), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    with target.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    return manifest


def read_manifest(folder: Path) -> Manifest:
    """Read and check the manifest of a version folder.

    Raise FileNotFoundError when the folder has no manifest: it is incomplete.
    Raise ValueError when the manifest breaks a rule or names another folder.
    """
    target = folder / paths.MANIFEST_NAME
    payload = json.loads(target.read_text(encoding="utf-8"))
    known = {item.name for item in fields(Manifest)}
    if not isinstance(payload, dict) or set(payload) != known:
        found = set(payload) if isinstance(payload, dict) else set()
        raise ValueError(
            f"{target}: missing fields {sorted(known - found)}, "
            f"unknown fields {sorted(found - known)}"
        )
    manifest = Manifest(**payload)
    problems = manifest.problems()
    if not problems and not folder.resolve().as_posix().endswith("/" + manifest.path.rstrip("/")):
        problems.append(f"the manifest is for {manifest.path}, not for this folder")
    if problems:
        raise ValueError(f"{target}: " + "; ".join(problems))
    return manifest
