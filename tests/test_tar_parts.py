"""The packer for loose files, on small invented files."""

import gzip
import hashlib
import io
import os
import socket
import subprocess
import tarfile
from pathlib import Path

import pytest

from songs.common import manifests, paths
from songs.common import tar_parts as t

DAY = "20261113"
ORIGIN = {"url": "https://pages.example/", "retrieved_utc": None, "license": None}
# A member name over 100 characters needs an extended tar header; Windows allows 260 for a path.
LONG = "a-long-folder-name-" * 5
# Member name -> invented content. 40 bytes each, so a limit of 100 bytes makes parts of 3 files.
FILES = {
    f"site/{name}": f"invented page {index:02d} ".ljust(40, "x").encode("utf-8")
    for index, name in enumerate(
        [
            "b.html",
            "a.html",
            "z/1.html",
            "a/2.html",
            "a/1.html",
            "ü/página.html",
            f"{LONG}/deep.html",
        ]
    )
}
# The stable order: in each folder its files by name, then its subfolders by name.
ORDER = [
    "site/a.html",
    "site/b.html",
    "site/a/1.html",
    "site/a/2.html",
    f"site/{LONG}/deep.html",
    "site/z/1.html",
    "site/ü/página.html",
]


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Fail any test of this module that opens a connection or runs the cloud program."""
    popen = subprocess.Popen

    def refuse(*args, **kwargs):
        raise AssertionError("a test of the packer opened a network connection")

    def local_only(command, *args, **kwargs):
        if any(word in str(command) for word in ("gcloud", "gsutil")):
            raise AssertionError("a test of the packer ran the cloud program")
        return popen(command, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(subprocess, "Popen", local_only)


def make_tree(root: Path, files: dict[str, bytes] = FILES) -> Path:
    for name, content in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_bytes(content)
    return root


def pack_all(root: Path, work: Path, **options) -> list[t.Part]:
    """Pack like a caller does: take each part before the next one starts."""
    return list(t.pack(root, work, **options))


def test_pack_then_verify_round_trips(tmp_path):
    root = make_tree(tmp_path / "old")
    parts = pack_all(root, tmp_path / "work", limit=100)
    assert [part.name for part in parts] == [
        "pages-00001.tar.gz",
        "pages-00002.tar.gz",
        "pages-00003.tar.gz",
    ]
    packed = []
    for part in parts:
        content = part.path.read_bytes()
        assert part.bytes == len(content)
        assert part.sha256 == hashlib.sha256(content).hexdigest()
        assert part.md5 == hashlib.md5(content).hexdigest()
        rows = t.read_members(part.index)
        assert t.verify_part(part.path, rows) == []
        with tarfile.open(part.path, mode="r:gz", encoding="utf-8") as tar:
            for info in tar:
                assert tar.extractfile(info).read() == FILES[info.name]
        for row in rows:
            assert row.part == part.name
            assert row.bytes == len(FILES[row.member])
            assert row.sha256 == hashlib.sha256(FILES[row.member]).hexdigest()
            assert row.modified_utc.endswith("Z")
        packed += [row.member for row in rows]
    assert packed == ORDER


def test_a_part_closes_when_its_source_bytes_reach_the_limit(tmp_path):
    root = make_tree(tmp_path / "old")
    parts = pack_all(root, tmp_path / "work", limit=100)
    assert [(part.members, part.source_bytes) for part in parts] == [(3, 120), (3, 120), (1, 40)]
    # A file larger than the limit makes a part of its own.
    assert [part.members for part in pack_all(root, tmp_path / "small", limit=1)] == [1] * 7
    assert [part.members for part in pack_all(root, tmp_path / "large")] == [7]
    with pytest.raises(ValueError, match="at least 1 byte"):
        pack_all(root, tmp_path / "zero", limit=0)


def test_the_same_input_makes_the_same_parts(tmp_path):
    root = make_tree(tmp_path / "old")
    first = pack_all(root, tmp_path / "first", limit=100)
    second = pack_all(root, tmp_path / "second", limit=100)
    assert [(p.name, p.sha256, p.members) for p in first] == [
        (p.name, p.sha256, p.members) for p in second
    ]
    assert [t.read_members(p.index) for p in first] == [t.read_members(p.index) for p in second]


def test_member_names_are_relative_to_the_root_and_folders_choose_what_is_packed(tmp_path):
    root = make_tree(tmp_path / "old")
    make_tree(root, {"other/x.html": b"invented other"})
    parts = pack_all(root, tmp_path / "work", folders=["site/z", "other"])
    assert [row.member for row in t.read_members(parts[0].index)] == [
        "other/x.html",
        "site/z/1.html",
    ]
    whole = pack_all(root / "site", tmp_path / "whole")
    assert [row.member for row in t.read_members(whole[0].index)][:2] == ["a.html", "b.html"]
    for bad in (["site", "site/a"], ["../site"], ["C:/site"], ["/site"], ["site\\a"]):
        with pytest.raises(ValueError, match="overlap|relative to the root"):
            pack_all(root, tmp_path / "bad", folders=bad)


def test_a_file_that_changes_while_it_is_read_is_skipped(tmp_path, monkeypatch):
    root = make_tree(tmp_path / "old")
    read = t._read

    class Grows:
        """A copy target that appends to the source file while the packer reads it."""

        def __init__(self, copy, path):
            self.copy, self.path, self.grown = copy, path, False

        def write(self, data):
            if not self.grown:
                with self.path.open(mode="ab") as handle:
                    handle.write(b"more")
                self.grown = True
            return self.copy.write(data)

    def changing_read(path, source, copy):
        if source.name == "site/a/1.html":
            return read(path, source, Grows(copy, path))
        if source.name == "site/b.html":
            path.unlink()
        return read(path, source, copy)

    monkeypatch.setattr(t, "_read", changing_read)
    parts = pack_all(root, tmp_path / "work")
    assert parts[0].skipped == ("site/b.html", "site/a/1.html")
    members = [row.member for row in t.read_members(parts[0].index)]
    assert members == [name for name in ORDER if name not in parts[0].skipped]
    assert t.verify_part(parts[0].path, t.read_members(parts[0].index)) == []
    assert t.read_part(tmp_path / "work", parts[0].name) == parts[0]


def rewrite_part(source: Path, target: Path, change) -> None:
    """Copy a part, and let `change(name, content)` return new content or None to drop a member."""
    with (
        tarfile.open(source, mode="r:gz", encoding="utf-8") as old,
        tarfile.open(target, mode="w:gz", encoding="utf-8") as new,
    ):
        for info in old:
            content = change(info.name, old.extractfile(info).read())
            if content is not None:
                info.size = len(content)
                new.addfile(info, io.BytesIO(content))


def test_a_wrong_member_fails_the_verification(tmp_path):
    root = make_tree(tmp_path / "old")
    (part,) = pack_all(root, tmp_path / "work")
    rows = t.read_members(part.index)
    first = rows[0].member

    flipped = tmp_path / "flipped.tar.gz"
    rewrite_part(part.path, flipped, lambda name, data: data.upper() if name == first else data)
    assert t.verify_part(flipped, rows) == [f"{first}: the SHA-256 differs from the index"]

    longer = tmp_path / "longer.tar.gz"
    rewrite_part(part.path, longer, lambda name, data: data + b"!" if name == first else data)
    assert t.verify_part(longer, rows) == [
        f"{first}: 41 bytes, the index has 40",
        f"{first}: the SHA-256 differs from the index",
    ]

    dropped = tmp_path / "dropped.tar.gz"
    rewrite_part(part.path, dropped, lambda name, data: None if name == first else data)
    assert t.verify_part(dropped, rows) == [f"{first}: in the index, not in the part"]
    assert t.verify_part(part.path, rows[1:]) == [f"{first}: in the part, not in the index"]

    cut = tmp_path / "cut.tar.gz"
    cut.write_bytes(part.path.read_bytes()[: part.bytes // 2])
    assert t.verify_part(cut, rows)
    broken = tmp_path / "broken.tar.gz"
    broken.write_bytes(b"\x1f\x8b" + bytes(range(256)) * 4)
    assert t.verify_part(broken, rows)[0].startswith("the part cannot be read")


def test_a_stream_from_elsewhere_is_verified_the_same_way(tmp_path):
    root = make_tree(tmp_path / "old")
    (part,) = pack_all(root, tmp_path / "work")
    rows = t.read_members(part.index)
    stream = io.BytesIO(part.path.read_bytes())
    assert t.verify_stream(stream, rows) == []
    assert t.verify_stream(io.BytesIO(gzip.compress(b"not a tar file")), rows)


def test_a_second_run_skips_the_done_parts_and_makes_the_rest(tmp_path):
    root = make_tree(tmp_path / "old")
    work = tmp_path / "work"
    run = t.pack(root, work, limit=100)
    first = next(run)
    run.close()  # the run stops after the caller kept the first part
    first.path.unlink()  # the caller uploaded the part and removed it
    rest = pack_all(root, work, limit=100, done={first.name})
    assert [part.name for part in rest] == ["pages-00002.tar.gz", "pages-00003.tar.gz"]
    fresh = pack_all(root, tmp_path / "fresh", limit=100)
    assert [(p.name, p.sha256, p.members) for p in t.read_parts(work)] == [
        (p.name, p.sha256, p.members) for p in fresh
    ]

    # A new file among the files of a done part: the packer refuses to continue.
    make_tree(root, {"site/a/0.html": b"invented new page"})
    with pytest.raises(ValueError, match="input changed"):
        pack_all(root, work, limit=100, done={first.name})
    with pytest.raises(ValueError, match="no record"):
        pack_all(root, tmp_path / "empty", limit=100, done={first.name})


def test_the_manifest_of_a_packed_folder_passes_read_manifest(tmp_path):
    data = tmp_path / "data"
    root = make_tree(tmp_path / "old")
    work = data / "staging" / "raw" / "invented" / DAY
    folder = paths.raw_dir(data, "invented", DAY)
    folder.mkdir(parents=True)
    parts = []
    for part in t.pack(root, work, limit=100):
        parts.append(part)
        part.path.unlink()  # after its upload, the part is gone from this disk
    t.write_members(work, folder)
    with pytest.raises(ValueError, match="disagree"):
        t.write_manifest(data, folder, parts[:-1], source="invented", origin=ORIGIN)
    manifest = t.write_manifest(data, folder, parts, source="invented", origin=ORIGIN)
    assert manifests.read_manifest(folder) == manifest
    assert sorted(entry["path"] for entry in manifest.files) == [
        "members.parquet",
        "pages-00001.tar.gz",
        "pages-00002.tar.gz",
        "pages-00003.tar.gz",
    ]
    by_name = {entry["path"]: entry for entry in manifest.files}
    assert by_name["members.parquet"]["rows"] == 7
    for part in parts:
        assert by_name[part.name] == part.entry()
    assert manifest.counts == {"parts": 3, "members": 7, "skipped": 0}
    assert sorted(path.name for path in folder.iterdir()) == ["_MANIFEST.json", "members.parquet"]
    assert t.read_members(folder, "pages-00002.tar.gz") == t.read_members(parts[1].index)


def test_a_part_left_in_the_version_folder_is_refused(tmp_path):
    data = tmp_path / "data"
    root = make_tree(tmp_path / "old")
    folder = paths.raw_dir(data, "invented", DAY)
    folder.mkdir(parents=True)
    (part,) = pack_all(root, tmp_path / "work")
    os.replace(part.path, folder / part.name)
    t.write_members(tmp_path / "work", folder)
    with pytest.raises(ValueError, match="appears twice"):
        t.write_manifest(data, folder, [part], source="invented", origin=ORIGIN)
    assert not (folder / paths.MANIFEST_NAME).exists()


def test_members_need_parts_without_a_gap(tmp_path):
    root = make_tree(tmp_path / "old")
    work = tmp_path / "work"
    pack_all(root, work, limit=100)
    for stale in (work / "pages-00002").iterdir():
        stale.unlink()
    with pytest.raises(ValueError, match="gap"):
        t.write_members(work, tmp_path)


def test_part_names():
    assert t.part_name(1) == "pages-00001.tar.gz"
    assert t.part_stem("pages-00042.tar.gz") == "pages-00042"
    with pytest.raises(ValueError):
        t.part_name(0)
    with pytest.raises(ValueError):
        t.part_stem("pages-1.tar.gz")
