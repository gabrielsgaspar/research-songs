"""Copy version folders between the local data folder and the bucket, and check them.

The bucket holds the data folder under the prefix `data/`, with the same paths.
An upload only creates objects: each one has the precondition "the object does
not exist", the MD5 of the file, and the SHA-256 of the file as the custom
metadata `sha256`. No code path deletes, moves or replaces an object. A check
of a folder in the bucket against its manifest then needs only a listing.

Code reaches the bucket only through a `Transport`. `GcloudTransport` runs the
`gcloud` program as it is signed in; tests use a fake that keeps objects in memory.

`docs/standards/data_layout.md` is the standard.
"""

import base64
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from songs.common import manifests, paths

BUCKET_PREFIX = "data/"
SHA256_KEY = "sha256"
CHUNK_BYTES = 8 * 1024 * 1024
# Without this, gcloud can split a large upload into a composite object, which has no MD5.
NO_COMPOSITE = {"CLOUDSDK_STORAGE_PARALLEL_COMPOSITE_UPLOAD_ENABLED": "False"}

Echo = Callable[[str], None]


class StorageError(RuntimeError):
    """A rule of the upload, the download or the check stops the command."""


@dataclass(frozen=True)
class LocalFile:
    """A local file with its size, SHA-256 (hex) and MD5 (base64, as the bucket gives it)."""

    path: Path
    bytes: int
    sha256: str
    md5: str


@dataclass(frozen=True)
class RemoteObject:
    """An object in the bucket. `md5` is None for a composite object, `sha256` without metadata."""

    name: str
    bytes: int
    md5: str | None
    generation: int
    sha256: str | None

    def line(self) -> str:
        return f"{self.name}\t{self.bytes}\t{self.generation}"


class Transport(Protocol):
    """The calls to the bucket. Every write creates an object and fails when it exists."""

    def versioning_enabled(self, bucket: str) -> bool: ...

    def list(self, bucket: str, prefix: str) -> list[RemoteObject]: ...

    def stat(self, bucket: str, name: str) -> RemoteObject | None: ...

    def upload(self, bucket: str, source: Path, name: str, *, md5: str, sha256: str) -> None: ...

    def download(self, bucket: str, name: str, generation: int, target: Path) -> None: ...

    def read(self, bucket: str, name: str, generation: int) -> bytes: ...


def _remote(record: dict) -> RemoteObject:
    return RemoteObject(
        name=record["name"],
        bytes=int(record["size"]),
        md5=record.get("md5_hash"),
        generation=int(record["generation"]),
        sha256=(record.get("custom_fields") or {}).get(SHA256_KEY),
    )


class GcloudTransport:
    """Reach the bucket through the `gcloud storage` program."""

    def __init__(self, program: str | None = None) -> None:
        found = program or shutil.which("gcloud")
        if not found:
            raise StorageError("gcloud is not on PATH; install the Google Cloud CLI")
        self.program = found

    def _run(self, *args: str, missing: str | None = None) -> bytes | None:
        """Run `gcloud storage <args>` and return its output; None when the error has `missing`."""
        done = subprocess.run(
            [self.program, "storage", *args],
            capture_output=True,
            env={**os.environ, **NO_COMPOSITE},
        )
        if done.returncode == 0:
            return done.stdout
        error = done.stderr.decode("utf-8", "replace").strip()
        if missing is not None and missing in error:
            return None
        raise StorageError(f"gcloud storage {args[0]} failed: {error[-500:]}")

    def versioning_enabled(self, bucket: str) -> bool:
        output = self._run("buckets", "describe", f"gs://{bucket}", "--format=json")
        return json.loads(output).get("versioning_enabled") is True

    def list(self, bucket: str, prefix: str) -> list[RemoteObject]:
        output = self._run("objects", "list", f"gs://{bucket}/{prefix}**", "--format=json")
        return [_remote(record) for record in json.loads(output or b"[]")]

    def stat(self, bucket: str, name: str) -> RemoteObject | None:
        output = self._run(
            "objects",
            "describe",
            f"gs://{bucket}/{name}",
            "--format=json",
            missing="not found: 404",
        )
        return None if output is None else _remote(json.loads(output))

    def upload(self, bucket: str, source: Path, name: str, *, md5: str, sha256: str) -> None:
        self._run(
            "cp",
            str(source),
            f"gs://{bucket}/{name}",
            "--if-generation-match=0",
            f"--content-md5={md5}",
            f"--custom-metadata={SHA256_KEY}={sha256}",
        )

    def download(self, bucket: str, name: str, generation: int, target: Path) -> None:
        self._run("cp", f"gs://{bucket}/{name}#{generation}", str(target))

    def read(self, bucket: str, name: str, generation: int) -> bytes:
        return self._run("cat", f"gs://{bucket}/{name}#{generation}")


def hash_file(path: Path) -> LocalFile:
    """Read a file once, in chunks, and return its size, SHA-256 and MD5.

    Raise StorageError when the size or the change time differs after the read: the file changed.
    """
    before = path.stat()
    sha256, md5 = hashlib.sha256(), hashlib.md5()
    with path.open(mode="rb") as handle:
        while chunk := handle.read(CHUNK_BYTES):
            sha256.update(chunk)
            md5.update(chunk)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise StorageError(f"{path} changed while it was read")
    return LocalFile(
        path, after.st_size, sha256.hexdigest(), base64.b64encode(md5.digest()).decode()
    )


def _matches(local: LocalFile, remote: RemoteObject) -> bool:
    return (remote.bytes, remote.md5, remote.sha256) == (local.bytes, local.md5, local.sha256)


def version_folder(text: str) -> str:
    """Return a folder as a manifest writes it: relative, with `/` between parts and at the end."""
    folder = text.replace("\\", "/").rstrip("/")
    if not manifests._is_relative(folder):
        raise StorageError(f"give the version folder relative to the data folder, got {text!r}")
    return folder + "/"


def upload_file(transport: Transport, bucket: str, local: LocalFile, name: str) -> RemoteObject:
    """Create one object from a hashed local file, verify it, and return it.

    An object that exists with the same size, MD5 and `sha256` metadata is kept as
    it is. An object that exists with other bytes raises StorageError: the function
    never replaces an object. The caller checks `require_versioning` before its
    first upload.
    """
    existing = transport.stat(bucket, name)
    if existing is not None:
        if not _matches(local, existing):
            raise StorageError(
                f"{name} exists in the bucket with other bytes; it is never replaced"
            )
        return existing
    transport.upload(bucket, local.path, name, md5=local.md5, sha256=local.sha256)
    created = transport.stat(bucket, name)
    if created is None or not _matches(local, created):
        raise StorageError(f"{name} does not match {local.path} after the upload")
    return created


def require_versioning(transport: Transport, bucket: str) -> None:
    """Raise StorageError when object versioning is off: then no command writes to the bucket."""
    if not transport.versioning_enabled(bucket):
        raise StorageError("object versioning is off in the bucket; nothing was uploaded")


def _local_names(folder: Path) -> set[str]:
    return {path.relative_to(folder).as_posix() for path in folder.rglob("*") if path.is_file()}


def upload_folder(
    transport: Transport, bucket: str, data: Path, folder: str, echo: Echo | None = None
) -> list[RemoteObject]:
    """Copy one complete version folder to the same path under `data/` in the bucket.

    The folder must have a valid manifest that lists every file in it, and each
    file must have the SHA-256 of the manifest. The bucket must have object
    versioning on, must not have the manifest of the folder, and must not hold an
    object of the folder with other bytes. When a rule fails, nothing is written.
    A second run keeps the objects that the first run made. The manifest goes
    last. Return the objects, and echo one line for each: name, bytes, generation.
    """
    folder = version_folder(folder)
    local = data / folder
    try:
        manifest = manifests.read_manifest(local)
    except (FileNotFoundError, ValueError) as error:
        raise StorageError(f"{folder} has no valid manifest: {error}") from error
    expected = {entry["path"]: entry for entry in manifest.files}
    found = _local_names(local) - {paths.MANIFEST_NAME}
    if found != set(expected):
        raise StorageError(
            f"{folder}: the files differ from the manifest; "
            f"missing {sorted(set(expected) - found)}, "
            f"not in the manifest {sorted(found - set(expected))}"
        )
    require_versioning(transport, bucket)
    prefix = BUCKET_PREFIX + folder
    remote = {item.name: item for item in transport.list(bucket, prefix)}
    if prefix + paths.MANIFEST_NAME in remote:
        raise StorageError(f"{folder} is complete in the bucket (it has a manifest)")

    plan = []
    for name in sorted(expected):
        file = hash_file(local / name)
        if (file.bytes, file.sha256) != (expected[name]["bytes"], expected[name]["sha256"]):
            raise StorageError(
                f"{folder}{name} differs from its manifest entry; nothing was uploaded"
            )
        plan.append((file, prefix + name))
    plan.append((hash_file(local / paths.MANIFEST_NAME), prefix + paths.MANIFEST_NAME))
    for file, name in plan:
        if name in remote and not _matches(file, remote[name]):
            raise StorageError(
                f"{name} exists in the bucket with other bytes; nothing was uploaded"
            )
    extra = set(remote) - {name for _, name in plan}
    if extra:
        raise StorageError(f"{folder} has objects that are not in the manifest: {sorted(extra)}")

    done = []
    for file, name in plan:
        done.append(upload_file(transport, bucket, file, name))
        if echo:
            echo(done[-1].line())
    return done


def _remote_manifest(
    transport: Transport, bucket: str, folder: str
) -> tuple[manifests.Manifest, bytes, dict[str, RemoteObject]]:
    """Read the manifest of a folder in the bucket. Return it, its bytes, and the folder objects."""
    prefix = BUCKET_PREFIX + folder
    remote = {item.name: item for item in transport.list(bucket, prefix)}
    item = remote.get(prefix + paths.MANIFEST_NAME)
    if item is None:
        raise StorageError(f"{folder} has no manifest in the bucket; it is absent or incomplete")
    content = transport.read(bucket, item.name, item.generation)
    try:
        manifest = manifests.parse_manifest(content.decode("utf-8"), item.name)
    except (UnicodeDecodeError, ValueError) as error:
        raise StorageError(f"{item.name} is not a valid manifest: {error}") from error
    if manifest.path != folder:
        raise StorageError(f"{item.name} is the manifest of {manifest.path}, not of {folder}")
    return manifest, content, remote


def _problems(
    folder: str, manifest: manifests.Manifest, content: bytes, remote: dict[str, RemoteObject]
) -> list[str]:
    prefix = BUCKET_PREFIX + folder
    wanted = {prefix + entry["path"]: entry for entry in manifest.files}
    wanted[prefix + paths.MANIFEST_NAME] = {
        "bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }
    problems = []
    for name, entry in sorted(wanted.items()):
        item = remote.get(name)
        if item is None:
            problems.append(f"{name}: missing")
            continue
        if item.bytes != entry["bytes"]:
            problems.append(f"{name}: {item.bytes} bytes, the manifest says {entry['bytes']}")
        if item.md5 is None:
            problems.append(f"{name}: no MD5 (a composite object)")
        if item.sha256 != entry["sha256"]:
            problems.append(f"{name}: sha256 metadata {item.sha256!r} differs from the manifest")
    problems += [f"{name}: not in the manifest" for name in sorted(set(remote) - set(wanted))]
    return problems


def check_folder(transport: Transport, bucket: str, folder: str) -> list[str]:
    """Return one line for each problem of a folder in the bucket. Empty means that it is complete.

    The check reads the listing and the manifest, and no data file. Each file of the
    manifest must have an object with the same size, an MD5, and the same `sha256`
    metadata, and the folder must hold no other object.
    """
    folder = version_folder(folder)
    manifest, content, remote = _remote_manifest(transport, bucket, folder)
    return _problems(folder, manifest, content, remote)


def download_folder(
    transport: Transport, bucket: str, data: Path, folder: str, echo: Echo | None = None
) -> list[RemoteObject]:
    """Copy one complete version folder from the bucket to the local data folder.

    The folder in the bucket must pass `check_folder`. The local folder must not
    have a manifest. A local file that exists with the SHA-256 of the manifest is
    kept; one with other bytes raises StorageError and is never replaced. Each
    download goes to `tmp/` first, and moves into place after its SHA-256 matches.
    The manifest goes last. Return the objects, and echo one line for each.
    """
    folder = version_folder(folder)
    local = data / folder
    if (local / paths.MANIFEST_NAME).exists():
        raise StorageError(f"{folder} is complete on this disk (it has a manifest)")
    manifest, content, remote = _remote_manifest(transport, bucket, folder)
    problems = _problems(folder, manifest, content, remote)
    if problems:
        raise StorageError(f"{folder} in the bucket does not match its manifest: {problems}")

    done = []
    scratch_root = data / "tmp"
    scratch_root.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=scratch_root) as scratch:
        for index, entry in enumerate(sorted(manifest.files, key=lambda item: item["path"])):
            item = remote[BUCKET_PREFIX + folder + entry["path"]]
            target = local / entry["path"]
            if target.exists():
                file = hash_file(target)
                if (file.bytes, file.sha256) != (entry["bytes"], entry["sha256"]):
                    raise StorageError(f"{target} exists with other bytes; it is never replaced")
            else:
                part = Path(scratch) / str(index)
                transport.download(bucket, item.name, item.generation, part)
                file = hash_file(part)
                if (file.bytes, file.sha256) != (entry["bytes"], entry["sha256"]):
                    raise StorageError(f"{item.name} downloaded with other bytes than its manifest")
                target.parent.mkdir(parents=True, exist_ok=True)
                part.rename(target)
            done.append(item)
            if echo:
                echo(item.line())

    extra = _local_names(local) - {entry["path"] for entry in manifest.files}
    if extra:
        raise StorageError(f"{folder} holds files that are not in the manifest: {sorted(extra)}")
    with (local / paths.MANIFEST_NAME).open(mode="xb") as handle:
        handle.write(content)
    manifests.read_manifest(local)
    done.append(remote[BUCKET_PREFIX + folder + paths.MANIFEST_NAME])
    if echo:
        echo(done[-1].line())
    return done
