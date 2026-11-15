"""Tar parts: a source that arrived as many loose files, packed into `tar.gz` parts.

The layout keeps raw files as received, with one exception: a source that
arrived as many loose pages is packed. A packed `raw/<source>/<YYYYMMDD>/`
folder holds the parts `pages-00001.tar.gz`, `pages-00002.tar.gz`, ..., one
`members.parquet` with the size and the SHA-256 of each packed file, and the
manifest. `docs/standards/data_layout.md` is the standard.

The packer writes one part at a time to a work folder outside the version
folder, and gives it to the caller before it starts the next part, so that the
caller can upload the part and remove it. For each part, the work folder keeps
`<part stem>/members.parquet` (the rows of the part) and `<part stem>/part.json`
(the record of the part). A second run with the same input makes the same parts
in the same order and skips the parts that the caller names as done.

This module has no upload code; it never touches the bucket.
"""

import gzip
import hashlib
import json
import os
import re
import tarfile
import tempfile
import zlib
from collections.abc import Collection, Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import BinaryIO, NamedTuple

import duckdb
import pandas as pd

from songs.common import manifests, schemas

MEMBERS = schemas.RAW_MEMBERS
PART_LIMIT = 1024**3
PART_NAME = re.compile(r"pages-(\d{5})\.tar\.gz")
RECORD_FILE = "part.json"
CHUNK = 1024**2
# A file above this size waits in a temporary file, not in memory, while it is checked.
SPOOL_LIMIT = 64 * 1024**2
GZIP_LEVEL = 6


class Member(NamedTuple):
    """One row of `members.parquet`, in the order of its columns."""

    part: str
    member: str
    bytes: int
    sha256: str
    modified_utc: str


@dataclass(frozen=True)
class Part:
    """One finished part in the work folder.

    `bytes`, `sha256` and `md5` describe the part file. `source_bytes` is the sum
    of the sizes of its members. `skipped` names the files that were planned for
    the part and changed or disappeared while they were read; they are not in it.
    """

    name: str
    path: Path
    bytes: int
    sha256: str
    md5: str
    members: int
    source_bytes: int
    skipped: tuple[str, ...]

    @property
    def index(self) -> Path:
        """The folder of the work folder that holds `members.parquet` of this part."""
        return self.path.parent / part_stem(self.name)

    def entry(self) -> dict:
        """Return the manifest entry of the part."""
        return {"path": self.name, "bytes": self.bytes, "sha256": self.sha256, "rows": None}


class _Source(NamedTuple):
    """One file to pack, with its size and change time from before the read."""

    name: str
    bytes: int
    mtime_ns: int


class _HashingWriter:
    """Write to a binary file and compute the size, SHA-256 and MD5 of what passes."""

    def __init__(self, handle: BinaryIO) -> None:
        self.handle = handle
        self.bytes = 0
        self.sha256 = hashlib.sha256()
        self.md5 = hashlib.md5(usedforsecurity=False)

    def write(self, data: bytes) -> int:
        self.handle.write(data)
        self.sha256.update(data)
        self.md5.update(data)
        size = memoryview(data).nbytes
        self.bytes += size
        return size

    def flush(self) -> None:
        self.handle.flush()


def part_name(number: int) -> str:
    """Return the name of part `number`, counted from 1: `pages-00001.tar.gz`."""
    if not 1 <= number <= 99_999:
        raise ValueError(f"a part number is from 1 to 99999, got {number}")
    return f"pages-{number:05d}.tar.gz"


def part_stem(name: str) -> str:
    """Return a part name without `.tar.gz`."""
    if not PART_NAME.fullmatch(name):
        raise ValueError(f"a part name looks like pages-00001.tar.gz, got {name!r}")
    return name.removesuffix(".tar.gz")


def _prefixes(folders: Iterable[str]) -> list[str]:
    """Return the folders as sorted path prefixes that end with a slash; the root is `""`."""
    unique = set()
    for folder in folders:
        parts = PurePosixPath(folder).parts
        if "\\" in folder or ".." in parts or (parts and (parts[0] == "/" or ":" in parts[0])):
            raise ValueError(f"a folder to pack is relative to the root, got {folder!r}")
        unique.add("".join(f"{part}/" for part in parts))
    prefixes = sorted(unique)
    for outer in prefixes:
        if any(inner != outer and inner.startswith(outer) for inner in prefixes):
            raise ValueError(f"the folders to pack overlap: {outer!r} holds another one")
    return prefixes


def _walk(root: Path, prefix: str) -> Iterator[_Source]:
    """Yield the files under `root/prefix`: in each folder its files by name, then its subfolders.

    Symbolic links are not followed and not packed.
    """
    with os.scandir(root / prefix) as listing:
        entries = sorted(listing, key=lambda entry: entry.name)
    subfolders = []
    for entry in entries:
        if entry.is_file(follow_symlinks=False):
            stat = entry.stat(follow_symlinks=False)
            yield _Source(prefix + entry.name, stat.st_size, stat.st_mtime_ns)
        elif entry.is_dir(follow_symlinks=False):
            subfolders.append(entry.name)
    for name in subfolders:
        yield from _walk(root, f"{prefix}{name}/")


def plan_parts(root: Path, folders: Iterable[str], limit: int) -> Iterator[list[_Source]]:
    """Yield the files of each part, in the stable order of `_walk`.

    A part closes after the file that makes its source bytes reach `limit`.
    """
    if limit < 1:
        raise ValueError(f"the part limit must be at least 1 byte, got {limit}")
    part: list[_Source] = []
    total = 0
    for prefix in _prefixes(folders):
        for source in _walk(root, prefix):
            part.append(source)
            total += source.bytes
            if total >= limit:
                yield part
                part, total = [], 0
    if part:
        yield part


def _utc(mtime_ns: int) -> str:
    return datetime.fromtimestamp(mtime_ns // 10**9, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read(path: Path, source: _Source, copy: BinaryIO) -> str | None:
    """Copy one file into `copy` and return its SHA-256.

    Return None when the file is gone, or when its size or change time differs
    from `source` after the read: then the copy is not valid.
    """
    digest = hashlib.sha256()
    read = 0
    try:
        with path.open(mode="rb") as handle:
            while chunk := handle.read(CHUNK):
                digest.update(chunk)
                copy.write(chunk)
                read += len(chunk)
        after = path.stat()
    except FileNotFoundError:
        return None
    if (read, after.st_size, after.st_mtime_ns) != (source.bytes, source.bytes, source.mtime_ns):
        return None
    return digest.hexdigest()


def _tar_info(source: _Source) -> tarfile.TarInfo:
    """Return a tar header that depends only on the name, the size and the change time."""
    info = tarfile.TarInfo(source.name)
    info.size = source.bytes
    info.mtime = source.mtime_ns // 10**9
    info.mode = 0o644
    return info


def _members_relation(rows: list[Member]) -> duckdb.DuckDBPyRelation:
    if not rows:
        return schemas.empty_table(MEMBERS)
    return schemas.cast_to_schema(MEMBERS, pd.DataFrame(rows, columns=list(Member._fields)))


def _write_part(root: Path, work: Path, name: str, sources: list[_Source]) -> Part:
    """Pack the files of one part into `work/<name>`, then write its index and its record."""
    index = work / part_stem(name)
    index.mkdir(exist_ok=True)
    # Files of an earlier run that stopped before the caller finished this part.
    for stale in (index / RECORD_FILE, index / MEMBERS.file):
        stale.unlink(missing_ok=True)
    rows: list[Member] = []
    skipped: list[str] = []
    with (work / name).open(mode="wb") as handle:
        out = _HashingWriter(handle)
        with (
            gzip.GzipFile(
                filename="", mode="wb", fileobj=out, compresslevel=GZIP_LEVEL, mtime=0
            ) as packed,
            tarfile.open(
                fileobj=packed, mode="w", format=tarfile.PAX_FORMAT, encoding="utf-8"
            ) as tar,
        ):
            for source in sources:
                with tempfile.SpooledTemporaryFile(max_size=SPOOL_LIMIT) as copy:
                    sha256 = _read(root / source.name, source, copy)
                    if sha256 is None:
                        skipped.append(source.name)
                        continue
                    copy.seek(0)
                    tar.addfile(_tar_info(source), copy)
                rows.append(Member(name, source.name, source.bytes, sha256, _utc(source.mtime_ns)))
    schemas.write_table(MEMBERS, _members_relation(rows), index)
    part = Part(
        name=name,
        path=work / name,
        bytes=out.bytes,
        sha256=out.sha256.hexdigest(),
        md5=out.md5.hexdigest(),
        members=len(rows),
        source_bytes=sum(row.bytes for row in rows),
        skipped=tuple(skipped),
    )
    record = {key: value for key, value in vars(part).items() if key != "path"}
    with (index / RECORD_FILE).open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    return part


def read_part(work: Path, name: str) -> Part:
    """Read the record of one finished part from the work folder."""
    record = json.loads((work / part_stem(name) / RECORD_FILE).read_text(encoding="utf-8"))
    return Part(**(record | {"path": work / name, "skipped": tuple(record["skipped"])}))


def read_parts(work: Path) -> list[Part]:
    """Read the records of all finished parts in the work folder, in the order of their numbers."""
    names = sorted(
        f"{folder.name}.tar.gz"
        for folder in work.glob("pages-*")
        if folder.is_dir() and (folder / RECORD_FILE).is_file()
    )
    return [read_part(work, name) for name in names]


def read_members(folder: Path, part: str | None = None) -> list[Member]:
    """Read `members.parquet` of a folder, checked against its schema; only one part when named."""
    relation = schemas.read_table(MEMBERS, folder)
    if part is not None:
        relation = relation.filter(f"part = '{part_stem(part)}.tar.gz'")
    return [Member(*row) for row in relation.fetchall()]


def _check_done(work: Path, name: str, sources: list[_Source]) -> None:
    """Raise ValueError when a done part was made from other files than the plan names now."""
    try:
        part = read_part(work, name)
    except FileNotFoundError:
        raise ValueError(f"{name} is done, but the work folder has no record of it") from None
    made = sorted([row.member for row in read_members(part.index)] + list(part.skipped))
    if made != sorted(source.name for source in sources):
        raise ValueError(
            f"{name} is done, but the files planned for it now differ from the files it was "
            "made from: the input changed since then. Pack into a new version folder."
        )


def pack(
    root: Path,
    work: Path,
    *,
    folders: Iterable[str] = ("",),
    limit: int = PART_LIMIT,
    done: Collection[str] = (),
) -> Iterator[Part]:
    """Pack the files under `root/<folder>` into parts in `work`, and yield each finished part.

    The member name is the path of the file relative to `root`, with forward
    slashes. The packer starts the next part only when the caller asks for it,
    so the caller can upload a part and remove `part.path` first. A file that
    changes or disappears while it is read is not packed; `Part.skipped` names it.

    `done` names the parts that an earlier run made and the caller kept. The
    packer checks that each of them was made from the files that the plan gives
    it now, and does not make it again.
    """
    work.mkdir(parents=True, exist_ok=True)
    for number, sources in enumerate(plan_parts(root, folders, limit), start=1):
        name = part_name(number)
        if name in done:
            _check_done(work, name, sources)
        else:
            yield _write_part(root, work, name, sources)


def verify_stream(stream: BinaryIO, members: Iterable[Member]) -> list[str]:
    """Read a part as a stream and compare each member with the index rows of the part.

    Return one line for each problem: a member that is missing, extra, twice in
    the part, not a plain file, or that has other bytes. Empty means the part is
    right. The stream can be a local file or the output of a download.
    """
    expected = {row.member: row for row in members}
    seen: set[str] = set()
    problems = []
    try:
        with tarfile.open(fileobj=stream, mode="r|gz", encoding="utf-8") as tar:
            for info in tar:
                if info.name in seen:
                    problems.append(f"{info.name}: twice in the part")
                    continue
                seen.add(info.name)
                row = expected.get(info.name)
                if row is None:
                    problems.append(f"{info.name}: in the part, not in the index")
                    continue
                handle = tar.extractfile(info) if info.isfile() else None
                if handle is None:
                    problems.append(f"{info.name}: not a plain file")
                    continue
                sha256 = hashlib.file_digest(handle, "sha256").hexdigest()
                if info.size != row.bytes:
                    problems.append(f"{info.name}: {info.size} bytes, the index has {row.bytes}")
                if sha256 != row.sha256:
                    problems.append(f"{info.name}: the SHA-256 differs from the index")
    except (tarfile.TarError, OSError, EOFError, zlib.error) as error:
        problems.append(f"the part cannot be read to its end: {error}")
    problems += [f"{name}: in the index, not in the part" for name in expected if name not in seen]
    return problems


def verify_part(path: Path, members: Iterable[Member]) -> list[str]:
    """Read a local part as a stream and compare it with its index rows; see `verify_stream`."""
    with path.open(mode="rb") as handle:
        return verify_stream(handle, members)


def write_members(work: Path, folder: Path) -> Path:
    """Write `members.parquet` of the version folder from the index of each part in `work`.

    Raise ValueError when the parts are not numbered 1, 2, 3, ... without a gap.
    """
    parts = read_parts(work)
    names = [part.name for part in parts]
    if names != [part_name(number) for number in range(1, len(parts) + 1)]:
        raise ValueError(f"the parts in the work folder have a gap: {names}")
    if not parts:
        return schemas.write_table(MEMBERS, schemas.empty_table(MEMBERS), folder)
    indexes = [str(part.index / MEMBERS.file) for part in parts]
    return schemas.write_table(MEMBERS, duckdb.read_parquet(indexes), folder)


def write_manifest(
    data: Path,
    folder: Path,
    parts: list[Part],
    *,
    source: str,
    origin: dict,
    notes: str = "",
) -> manifests.Manifest:
    """Write the manifest of a packed `raw` folder, after each part is in the bucket.

    The folder holds `members.parquet` and any file that is kept as received.
    The manifest lists these files and the recorded entry of each part. Raise
    ValueError when `members.parquet` and the parts do not agree on the members
    of each part.
    """
    rows = read_members(folder)
    found: dict[str, int] = {}
    for row in rows:
        found[row.part] = found.get(row.part, 0) + 1
    expected = {part.name: part.members for part in parts if part.members}
    if found != expected:
        raise ValueError(
            f"members.parquet and the parts disagree: members by part {found}, "
            f"the parts hold {expected}"
        )
    counts = {
        "parts": len(parts),
        "members": len(rows),
        "skipped": sum(len(part.skipped) for part in parts),
    }
    return manifests.write_manifest(
        data,
        folder,
        "raw",
        source=source,
        origin=origin,
        counts=counts,
        notes=notes,
        uploaded_files=[part.entry() for part in parts],
    )
