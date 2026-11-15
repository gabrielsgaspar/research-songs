"""Upload, download and check of version folders, with a fake bucket in memory."""

import base64
import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from songs.common import manifests, paths, storage
from songs.common.storage import RemoteObject, StorageError

BUCKET = "example-bucket"
FOLDER = "raw/example/20261114/"
PREFIX = "data/" + FOLDER
MANIFEST = PREFIX + paths.MANIFEST_NAME
ORIGIN = {"url": "https://data.example/files", "retrieved_utc": None, "license": None}


def b64_md5(data: bytes) -> str:
    return base64.b64encode(hashlib.md5(data).digest()).decode()


class FakeBucket:
    """A bucket in memory. An upload fails when the object exists (`--if-generation-match=0`)."""

    def __init__(self, versioning: bool = True) -> None:
        self.versioning = versioning
        self.objects: dict[str, tuple[bytes, str | None, int]] = {}
        self.writes: list[str] = []
        self.generation = 1000

    def put(self, name: str, data: bytes, sha256: str | None = None) -> None:
        self.generation += 1
        self.objects[name] = (data, sha256, self.generation)

    def _object(self, name: str) -> RemoteObject:
        data, sha256, generation = self.objects[name]
        return RemoteObject(name, len(data), b64_md5(data), generation, sha256)

    def versioning_enabled(self, bucket: str) -> bool:
        return self.versioning

    def list(self, bucket: str, prefix: str) -> list[RemoteObject]:
        return [self._object(name) for name in sorted(self.objects) if name.startswith(prefix)]

    def stat(self, bucket: str, name: str) -> RemoteObject | None:
        return self._object(name) if name in self.objects else None

    def upload(self, bucket: str, source: Path, name: str, *, md5: str, sha256: str) -> None:
        if name in self.objects:
            raise StorageError(f"{name}: precondition failed: 412")
        data = source.read_bytes()
        if b64_md5(data) != md5:
            raise StorageError(f"{name}: the MD5 does not match the data")
        self.put(name, data, sha256)
        self.writes.append(name)

    def download(self, bucket: str, name: str, generation: int, target: Path) -> None:
        assert self.objects[name][2] == generation
        target.write_bytes(self.objects[name][0])

    def read(self, bucket: str, name: str, generation: int) -> bytes:
        assert self.objects[name][2] == generation
        return self.objects[name][0]


def make_folder(data: Path) -> Path:
    """Write a version folder with two invented files and its manifest."""
    folder = paths.raw_dir(data, "example", "20261114")
    (folder / "pages").mkdir(parents=True)
    (folder / "first.txt").write_bytes(b"invented text one\n")
    (folder / "pages" / "second.txt").write_bytes(b"invented text two\n")
    manifests.write_manifest(data, folder, "raw", source="example", origin=ORIGIN)
    return folder


@pytest.fixture
def data(tmp_path: Path) -> Path:
    root = tmp_path / "local"
    make_folder(root)
    return root


def test_upload_creates_every_object_and_the_check_passes(data):
    bucket, lines = FakeBucket(), []
    done = storage.upload_folder(bucket, BUCKET, data, FOLDER, echo=lines.append)
    names = [PREFIX + "first.txt", PREFIX + "pages/second.txt", MANIFEST]
    assert [item.name for item in done] == names
    assert bucket.writes == names
    assert lines == [item.line() for item in done]
    assert lines[0] == f"{PREFIX}first.txt\t18\t1001"
    assert storage.check_folder(bucket, BUCKET, FOLDER) == []


def test_the_manifest_goes_last(data):
    bucket = FakeBucket()
    storage.upload_folder(bucket, BUCKET, data, FOLDER)
    assert bucket.writes[-1] == MANIFEST


def test_each_object_has_the_sha256_of_the_manifest_as_metadata(data):
    bucket = FakeBucket()
    storage.upload_folder(bucket, BUCKET, data, FOLDER)
    entry = next(
        e for e in manifests.read_manifest(data / FOLDER).files if e["path"] == "first.txt"
    )
    assert bucket.stat(BUCKET, PREFIX + "first.txt").sha256 == entry["sha256"]


def test_a_wrong_sha256_stops_before_any_write(data):
    (data / FOLDER / "pages" / "second.txt").write_bytes(b"invented text 2!\n")
    bucket = FakeBucket()
    with pytest.raises(StorageError, match="differs from its manifest entry"):
        storage.upload_folder(bucket, BUCKET, data, FOLDER)
    assert bucket.writes == []


def test_a_file_that_is_not_in_the_manifest_stops_the_upload(data):
    (data / FOLDER / "late.txt").write_bytes(b"invented\n")
    bucket = FakeBucket()
    with pytest.raises(StorageError, match="not in the manifest"):
        storage.upload_folder(bucket, BUCKET, data, FOLDER)
    assert bucket.writes == []


def test_a_folder_without_a_manifest_is_refused(tmp_path):
    (tmp_path / FOLDER).mkdir(parents=True)
    with pytest.raises(StorageError, match="no valid manifest"):
        storage.upload_folder(FakeBucket(), BUCKET, tmp_path, FOLDER)


def test_versioning_off_stops_before_any_write(data):
    bucket = FakeBucket(versioning=False)
    with pytest.raises(StorageError, match="versioning is off"):
        storage.upload_folder(bucket, BUCKET, data, FOLDER)
    assert bucket.writes == []


def test_an_object_with_other_bytes_is_an_error_and_is_kept(data):
    bucket = FakeBucket()
    bucket.put(PREFIX + "pages/second.txt", b"other bytes\n", "0" * 64)
    with pytest.raises(StorageError, match="other bytes"):
        storage.upload_folder(bucket, BUCKET, data, FOLDER)
    assert bucket.writes == []
    assert bucket.objects[PREFIX + "pages/second.txt"][0] == b"other bytes\n"


def test_an_object_that_is_not_in_the_manifest_stops_the_upload(data):
    bucket = FakeBucket()
    bucket.put(PREFIX + "stray.txt", b"invented\n")
    with pytest.raises(StorageError, match="not in the manifest"):
        storage.upload_folder(bucket, BUCKET, data, FOLDER)
    assert bucket.writes == []


def test_a_second_run_skips_what_is_done(data):
    bucket = FakeBucket()
    first = storage.hash_file(data / FOLDER / "first.txt")
    storage.upload_file(bucket, BUCKET, first, PREFIX + "first.txt")
    done = storage.upload_folder(bucket, BUCKET, data, FOLDER)
    assert bucket.writes == [PREFIX + "first.txt", PREFIX + "pages/second.txt", MANIFEST]
    assert len(done) == 3


def test_a_complete_folder_in_the_bucket_is_refused(data):
    bucket = FakeBucket()
    storage.upload_folder(bucket, BUCKET, data, FOLDER)
    with pytest.raises(StorageError, match="complete in the bucket"):
        storage.upload_folder(bucket, BUCKET, data, FOLDER)
    assert len(bucket.writes) == 3


def test_upload_file_verifies_the_object_after_the_upload(data):
    class Damaging(FakeBucket):
        def upload(self, bucket, source, name, *, md5, sha256):
            super().upload(bucket, source, name, md5=md5, sha256=sha256)
            data, _, generation = self.objects[name]
            self.objects[name] = (data, None, generation)

    local = storage.hash_file(data / FOLDER / "first.txt")
    with pytest.raises(StorageError, match="does not match"):
        storage.upload_file(Damaging(), BUCKET, local, PREFIX + "first.txt")


def test_the_check_names_each_problem(data):
    bucket = FakeBucket()
    storage.upload_folder(bucket, BUCKET, data, FOLDER)
    content, _, generation = bucket.objects[PREFIX + "first.txt"]
    bucket.objects[PREFIX + "first.txt"] = (content, "f" * 64, generation)
    del bucket.objects[PREFIX + "pages/second.txt"]
    bucket.put(PREFIX + "stray.txt", b"invented\n")
    assert storage.check_folder(bucket, BUCKET, FOLDER) == [
        f"{PREFIX}first.txt: sha256 metadata {'f' * 64!r} differs from the manifest",
        f"{PREFIX}pages/second.txt: missing",
        f"{PREFIX}stray.txt: not in the manifest",
    ]


def test_the_check_refuses_a_folder_without_a_manifest_in_the_bucket():
    with pytest.raises(StorageError, match="no manifest in the bucket"):
        storage.check_folder(FakeBucket(), BUCKET, FOLDER)


def test_download_round_trip(data, tmp_path):
    bucket = FakeBucket()
    storage.upload_folder(bucket, BUCKET, data, FOLDER)
    other = tmp_path / "other"
    other.mkdir()
    lines = []
    done = storage.download_folder(bucket, BUCKET, other, FOLDER, echo=lines.append)
    assert [item.name for item in done][-1] == MANIFEST
    assert len(lines) == 3
    for name in ("first.txt", "pages/second.txt", paths.MANIFEST_NAME):
        assert (other / FOLDER / name).read_bytes() == (data / FOLDER / name).read_bytes()
    assert manifests.read_manifest(other / FOLDER).path == FOLDER
    assert [path.name for path in (other / "tmp").iterdir()] == []


def test_download_keeps_a_local_file_with_the_same_bytes(data, tmp_path):
    bucket = FakeBucket()
    storage.upload_folder(bucket, BUCKET, data, FOLDER)
    other = tmp_path / "other"
    (other / FOLDER).mkdir(parents=True)
    (other / FOLDER / "first.txt").write_bytes((data / FOLDER / "first.txt").read_bytes())
    storage.download_folder(bucket, BUCKET, other, FOLDER)
    assert manifests.read_manifest(other / FOLDER).path == FOLDER


def test_download_never_replaces_a_local_file_with_other_bytes(data, tmp_path):
    bucket = FakeBucket()
    storage.upload_folder(bucket, BUCKET, data, FOLDER)
    other = tmp_path / "other"
    (other / FOLDER).mkdir(parents=True)
    (other / FOLDER / "first.txt").write_bytes(b"local invented text\n")
    with pytest.raises(StorageError, match="never replaced"):
        storage.download_folder(bucket, BUCKET, other, FOLDER)
    assert (other / FOLDER / "first.txt").read_bytes() == b"local invented text\n"
    assert not (other / FOLDER / paths.MANIFEST_NAME).exists()


def test_download_refuses_a_local_folder_with_a_manifest(data):
    bucket = FakeBucket()
    storage.upload_folder(bucket, BUCKET, data, FOLDER)
    with pytest.raises(StorageError, match="complete on this disk"):
        storage.download_folder(bucket, BUCKET, data, FOLDER)


def test_download_refuses_a_folder_that_fails_the_check(data, tmp_path):
    bucket = FakeBucket()
    storage.upload_folder(bucket, BUCKET, data, FOLDER)
    del bucket.objects[PREFIX + "first.txt"]
    other = tmp_path / "other"
    other.mkdir()
    with pytest.raises(StorageError, match="does not match its manifest"):
        storage.download_folder(bucket, BUCKET, other, FOLDER)
    assert not (other / FOLDER).exists()


@pytest.mark.parametrize("text", ["C:/data/raw/x/20261114", "/raw/x/20261114", "raw/../x"])
def test_a_folder_outside_the_data_folder_is_refused(text):
    with pytest.raises(StorageError, match="relative to the data folder"):
        storage.version_folder(text)


def test_version_folder_accepts_backslashes_and_a_missing_slash():
    assert storage.version_folder("raw\\example\\20261114") == FOLDER


def test_gcloud_upload_is_create_only_with_md5_and_sha256(monkeypatch):
    calls = []

    def run(args, **kwargs):
        calls.append((args, kwargs["env"]))
        return subprocess.CompletedProcess(args, 0, b"", b"")

    monkeypatch.setattr(storage.subprocess, "run", run)
    transport = storage.GcloudTransport(program="gcloud")
    transport.upload(BUCKET, Path("first.txt"), PREFIX + "first.txt", md5="bWQ1", sha256="ab" * 32)
    args, env = calls[0]
    assert args[:3] == ["gcloud", "storage", "cp"]
    assert "--if-generation-match=0" in args
    assert "--content-md5=bWQ1" in args
    assert f"--custom-metadata=sha256={'ab' * 32}" in args
    assert env["CLOUDSDK_STORAGE_PARALLEL_COMPOSITE_UPLOAD_ENABLED"] == "False"


def test_gcloud_reads_the_listing_fields(monkeypatch):
    record = {
        "name": PREFIX + "first.txt",
        "size": 18,
        "md5_hash": "bWQ1",
        "generation": "1794212358153865",
        "custom_fields": {"sha256": "ab" * 32},
    }
    output = json.dumps([record]).encode()
    monkeypatch.setattr(
        storage.subprocess,
        "run",
        lambda args, **_: subprocess.CompletedProcess(args, 0, output, b""),
    )
    [item] = storage.GcloudTransport(program="gcloud").list(BUCKET, PREFIX)
    assert item == RemoteObject(PREFIX + "first.txt", 18, "bWQ1", 1794212358153865, "ab" * 32)


def test_gcloud_stat_of_a_missing_object_is_none(monkeypatch):
    error = b"ERROR: (gcloud.storage.objects.describe) gs://b/x not found: 404.\n"
    monkeypatch.setattr(
        storage.subprocess,
        "run",
        lambda args, **_: subprocess.CompletedProcess(args, 1, b"", error),
    )
    assert storage.GcloudTransport(program="gcloud").stat(BUCKET, "data/x") is None


def test_gcloud_failure_raises(monkeypatch):
    error = b"ERROR: precondition failed: 412\n"
    monkeypatch.setattr(
        storage.subprocess,
        "run",
        lambda args, **_: subprocess.CompletedProcess(args, 1, b"", error),
    )
    with pytest.raises(StorageError, match="412"):
        storage.GcloudTransport(program="gcloud").upload(
            BUCKET, Path("first.txt"), "data/x", md5="bWQ1", sha256="ab" * 32
        )
