"""Tests for songs.common: paths, configuration, repository facts, and years."""

from dataclasses import fields
from pathlib import Path

import pytest

from songs.common import config, paths, repo, years

ROOT = Path(__file__).resolve().parents[1]


def test_root_does_not_depend_on_the_working_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert paths.resolve_project_root() == ROOT


def test_root_raises_outside_a_project(tmp_path):
    with pytest.raises(FileNotFoundError):
        paths.resolve_project_root(tmp_path)


def test_data_root_defaults_to_the_data_folder_of_the_repository(monkeypatch):
    monkeypatch.delenv(paths.DATA_ROOT_ENV, raising=False)
    assert paths.data_root() == ROOT / "data"


def test_data_root_follows_the_environment_variable(tmp_path, monkeypatch):
    monkeypatch.setenv(paths.DATA_ROOT_ENV, str(tmp_path))
    assert paths.data_root() == tmp_path
    project = paths.project_paths()
    assert project.data == tmp_path
    assert project.layout.lyrics == tmp_path / "lyrics"
    assert {field.name for field in fields(paths.DataLayout)} >= {"raw", "clean", "analysis"}
    assert project.countries == ROOT / "countries"


def test_data_root_refuses_a_relative_path(monkeypatch):
    monkeypatch.setenv(paths.DATA_ROOT_ENV, "data")
    with pytest.raises(ValueError, match="absolute"):
        paths.data_root()


def test_data_root_refuses_a_missing_folder(tmp_path, monkeypatch):
    monkeypatch.setenv(paths.DATA_ROOT_ENV, str(tmp_path / "missing"))
    with pytest.raises(FileNotFoundError, match="does not exist"):
        paths.data_root()


@pytest.fixture
def clean_env(monkeypatch):
    for name in (config.GCP_PROJECT_ENV, config.GCS_BUCKET_ENV, config.OFFLINE_ENV):
        monkeypatch.delenv(name, raising=False)


def test_config_has_no_defaults_for_private_identifiers(tmp_path, clean_env):
    loaded = config.load_config(tmp_path / "absent.env")
    assert loaded == config.SongsConfig(gcp_project=None, gcs_bucket=None, offline=False)
    with pytest.raises(RuntimeError, match=config.GCS_BUCKET_ENV):
        loaded.require("gcs_bucket")


def test_config_reads_an_env_file_and_keeps_set_variables(tmp_path, clean_env, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        '# comment\n\nSONGS_GCP_PROJECT="from-file"\nSONGS_GCS_BUCKET=bucket-from-file\n'
        "SONGS_OFFLINE = yes\nnot a setting\n",
        encoding="utf-8",
    )
    monkeypatch.setenv(config.GCS_BUCKET_ENV, "already-set")
    # load_env_file writes to os.environ directly; register the keys so pytest restores them.
    monkeypatch.setenv(config.GCP_PROJECT_ENV, "")
    monkeypatch.delenv(config.GCP_PROJECT_ENV)
    monkeypatch.setenv(config.OFFLINE_ENV, "")
    monkeypatch.delenv(config.OFFLINE_ENV)
    loaded = config.load_config(env_file)
    assert loaded.gcp_project == "from-file"
    assert loaded.gcs_bucket == "already-set"
    assert loaded.offline is True
    assert loaded.require("gcp_project") == "from-file"


def test_git_sha_is_a_commit_here_and_unknown_elsewhere(tmp_path):
    sha = repo.git_sha(ROOT)
    assert len(sha) == 40 and all(char in "0123456789abcdef" for char in sha)
    assert repo.git_sha(tmp_path) == "unknown"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (1900, True),
        (2026, True),
        ("1975", True),
        (1975.4, True),
        (1899, False),
        (2027, False),
        (None, False),
        ("", False),
        ("n/a", False),
        (float("nan"), False),
        (float("inf"), False),
    ],
)
def test_admissible_year(value, expected):
    assert years.is_admissible_year(value) is expected
