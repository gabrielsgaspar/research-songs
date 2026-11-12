"""Manifests of version folders, on small invented files."""

import hashlib
import json
from dataclasses import fields, replace
from pathlib import Path

import duckdb
import pytest

from songs.common import manifests as m
from songs.common import paths, schemas

ROOT = paths.resolve_project_root()
DAY, RUN = "20261105", "20261105T140000Z"
ORIGIN = {"url": "https://data.example/dump", "retrieved_utc": None, "license": None}
# Kind -> the arguments of its path function after the data folder, and the fields of a valid
# manifest. The file names of a kind with no fixed list are invented.
CASES = {
    "raw": (("lrclib", DAY), {"source": "lrclib", "origin": ORIGIN}, ("dump.txt",)),
    "raw_manual_review": (("BRA", DAY), {"country_iso3": "BRA"}, ("BRA_x_reviewed.txt",)),
    "clean_dump": (("letras", DAY), {"source": "letras", "inputs": ["raw/letras/20261101/"]}, None),
    "clean_catalog": (
        ("discogs", DAY),
        {"source": "discogs", "inputs": ["raw/discogs/20261101/"]},
        ("artists.parquet",),
    ),
    "clean_countries": ((DAY,), {"inputs": ["raw/hfd/20260921/tfrRR.txt"]}, None),
    "country_songs": (
        ("BRA", RUN),
        {"country_iso3": "BRA", "run_id": RUN, "inputs": ["clean/dumps/letras/20261105/"]},
        None,
    ),
    "country_scores": (
        ("BRA", RUN),
        {"country_iso3": "BRA", "run_id": RUN, "inputs": ["lyrics/BRA/songs/20261105T140000Z/"]},
        None,
    ),
    "analysis": ((DAY,), {"inputs": ["clean/countries/20261105/"]}, None),
}


def make_folder(data: Path, kind: str) -> tuple[Path, dict]:
    """Make the version folder of a kind with small invented files. Return it with its fields."""
    parts, settings, names = CASES[kind]
    folder = m.KINDS[kind].folder(data, *parts)
    folder.mkdir(parents=True)
    for row, name in enumerate(names or m.KINDS[kind].files, start=1):
        if name.endswith(".parquet"):
            duckdb.sql(f"SELECT * FROM range({row}) AS t(n)").write_parquet(str(folder / name))
        else:
            (folder / name).write_text("invented\n", encoding="utf-8")
    return folder, settings


def written(tmp_path: Path, kind: str = "country_songs") -> tuple[Path, m.Manifest]:
    folder, settings = make_folder(tmp_path, kind)
    return folder, m.write_manifest(tmp_path, folder, kind, **settings)


@pytest.mark.parametrize("kind", m.KINDS)
def test_a_manifest_round_trips_for_every_kind(tmp_path, kind):
    folder, settings = make_folder(tmp_path, kind)
    manifest = m.write_manifest(
        tmp_path, folder, kind, counts={"songs": 2}, notes="An invented note.", **settings
    )
    assert m.read_manifest(folder) == manifest
    assert manifest.path == paths.data_relative(tmp_path, folder) and manifest.path.endswith("/")
    assert (manifest.kind, manifest.schema_version) == (kind, 1)
    assert len(manifest.code_commit) == 40
    raw = (folder / paths.MANIFEST_NAME).read_bytes()
    assert raw.endswith(b"\n") and b"\r" not in raw
    payload = json.loads(raw)
    assert list(payload) == sorted(item.name for item in fields(m.Manifest))
    assert str(tmp_path) not in raw.decode("utf-8")  # no local folder goes into a manifest


def test_a_manifest_describes_every_file_but_itself(tmp_path):
    folder, manifest = written(tmp_path)
    assert [entry["path"] for entry in manifest.files] == [
        "artists.parquet",
        "links.parquet",
        "songs.parquet",
    ]
    assert [entry["rows"] for entry in manifest.files] == [1, 3, 2]
    for entry in manifest.files:
        content = (folder / entry["path"]).read_bytes()
        assert entry["bytes"] == len(content)
        assert entry["sha256"] == hashlib.sha256(content).hexdigest()
    # A file that is not a Parquet table has no row count.
    _, raw = written(tmp_path, "raw")
    assert [(entry["path"], entry["rows"]) for entry in raw.files] == [("dump.txt", None)]


def test_a_folder_gets_one_manifest_and_only_when_it_is_valid(tmp_path):
    folder, settings = make_folder(tmp_path, "country_songs")
    # The manifest is the last file: a refused manifest leaves the folder incomplete.
    with pytest.raises(ValueError, match="run_id must be set"):
        m.write_manifest(tmp_path, folder, "country_songs", **(settings | {"run_id": None}))
    assert not (folder / paths.MANIFEST_NAME).exists()
    assert paths.latest_country_songs_dir(tmp_path, "BRA") is None
    with pytest.raises(FileNotFoundError):
        m.read_manifest(folder)
    m.write_manifest(tmp_path, folder, "country_songs", **settings)
    assert paths.latest_country_songs_dir(tmp_path, "BRA") == folder
    before = (folder / paths.MANIFEST_NAME).read_bytes()
    with pytest.raises(FileExistsError, match="never changed"):
        m.write_manifest(tmp_path, folder, "country_songs", **settings)
    assert (folder / paths.MANIFEST_NAME).read_bytes() == before
    with pytest.raises(FileNotFoundError, match="not a folder"):
        m.write_manifest(tmp_path, tmp_path / "absent", "country_songs", **settings)


def entry(name: str, **changes) -> dict:
    return {"path": name, "bytes": 1, "sha256": "0" * 64, "rows": 1} | changes


SONG_FILES = [entry(name) for name in ("artists.parquet", "links.parquet", "songs.parquet")]


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"kind": "lyrics"}, "kind must be one of"),
        ({"schema_version": 2}, "schema_version"),
        ({"created_utc": "2026-11-05 14:00"}, "created_utc"),
        ({"code_commit": ""}, "code_commit"),
        ({"path": "gs://some-bucket/data/lyrics/BRA/songs/20261105T140000Z/"}, "no scheme"),
        ({"path": "C:/data/lyrics/BRA/songs/20261105T140000Z/"}, "drive letter"),
        ({"path": "/lyrics/BRA/songs/20261105T140000Z/"}, "relative to the data folder"),
        ({"path": "lyrics/BRA/songs/20261105T140000Z"}, "path must be"),
        ({"path": "lyrics/BRA/scores/20261105T140000Z/"}, "path must be"),
        ({"path": "lyrics/ARG/songs/20261105T140000Z/"}, "path must be"),
        ({"path": "lyrics/BRA/songs/20270203T083000Z/"}, "path must be"),
        ({"run_id": "20261105"}, "path does not fit"),
        ({"country_iso3": None}, "country_iso3 must be set"),
        ({"run_id": None}, "run_id must be set"),
        ({"inputs": []}, "inputs must be set"),
        ({"source": "lrclib"}, "source must be null"),
        ({"origin": ORIGIN}, "origin must be null"),
        ({"inputs": ["gs://some-bucket/data/raw/x/"]}, "inputs must be paths relative"),
        ({"inputs": ["../other/raw/x/"]}, "inputs must be paths relative"),
        ({"files": SONG_FILES[:2]}, "files must be exactly"),
        ({"files": [*SONG_FILES, entry("notes.txt")]}, "files must be exactly"),
        ({"files": [*SONG_FILES[:2], entry("songs.parquet", sha256="abc")]}, "64 hex characters"),
        ({"files": [*SONG_FILES[:2], entry("songs.parquet", rows=-1)]}, "rows of"),
        ({"files": [*SONG_FILES[:2], entry("songs.parquet", bytes="1")]}, "bytes of"),
        ({"files": [{"path": "songs.parquet"}]}, "files must be a list of entries"),
        ({"counts": {"songs": -1}}, "counts"),
        ({"counts": {"songs": 1.5}}, "counts"),
        ({"notes": None}, "notes"),
    ],
)
def test_a_bad_manifest_is_refused(tmp_path, changes, message):
    folder, manifest = written(tmp_path)
    assert manifest.problems() == []
    bad = replace(manifest, **changes)
    with pytest.raises(ValueError, match=message):
        bad.validate()
    # A reader refuses the same manifest on disk.
    payload = json.loads((folder / paths.MANIFEST_NAME).read_text(encoding="utf-8"))
    (folder / paths.MANIFEST_NAME).write_text(json.dumps(payload | changes), encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        m.read_manifest(folder)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"origin": None}, "origin must be set"),
        ({"origin": {"url": "https://data.example/dump"}}, "origin must hold"),
        ({"origin": ORIGIN | {"license": 1}}, "origin must hold"),
        ({"source": None}, "source must be set"),
        ({"source": "manual_review"}, "path does not fit"),
        ({"country_iso3": "BRA"}, "country_iso3 must be null"),
        ({"path": "raw/lrclib/2026-11-05/"}, "path does not fit"),
    ],
)
def test_a_bad_raw_manifest_is_refused(tmp_path, changes, message):
    _, manifest = written(tmp_path, "raw")
    with pytest.raises(ValueError, match=message):
        replace(manifest, **changes).validate()


def test_reading_refuses_unknown_fields_and_a_moved_folder(tmp_path):
    folder, _ = written(tmp_path)
    target = folder / paths.MANIFEST_NAME
    payload = json.loads(target.read_text(encoding="utf-8"))
    target.write_text(json.dumps(payload | {"extra": 1}), encoding="utf-8")
    with pytest.raises(ValueError, match=r"unknown fields \['extra'\]"):
        m.read_manifest(folder)
    del payload["notes"]
    target.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match=r"missing fields \['notes'\]"):
        m.read_manifest(folder)
    moved, _ = written(tmp_path / "second")
    moved.rename(moved.with_name("20270203T083000Z"))
    with pytest.raises(ValueError, match="not for this folder"):
        m.read_manifest(moved.with_name("20270203T083000Z"))


def test_the_standard_names_every_field_and_every_kind():
    page = (ROOT / schemas.LAYOUT_PAGE).read_text(encoding="utf-8")
    for item in fields(m.Manifest):
        assert f"| `{item.name}` |" in page, item.name
    for name, kind in m.KINDS.items():
        must_set = ", ".join(f"`{field}`" for field in kind.must_set)
        assert f"| `{name}` | `{kind.pattern}` | {must_set} |" in page, name
        for file in kind.files or ():
            assert f"`{file}`" in page, file
