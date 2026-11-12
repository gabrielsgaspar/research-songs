"""Tests for songs.common: paths, configuration, repository facts, and years."""

from dataclasses import fields
from datetime import date
from pathlib import Path

import pytest

from songs.common import config, paths, repo, run_records, years

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


def seal(folder: Path) -> Path:
    """Make a version folder with a manifest file, so that `latest_*` counts it."""
    folder.mkdir(parents=True)
    (folder / paths.MANIFEST_NAME).write_text("{}\n", encoding="utf-8")
    return folder


def test_each_version_folder_has_one_path_function(tmp_path):
    day, run = "20261105", "20261105T140000Z"
    built = {
        paths.raw_dir(tmp_path, "lrclib", day): "raw/lrclib/20261105",
        paths.raw_manual_review_dir(tmp_path, "BRA", day): "raw/manual_review/BRA/20261105",
        paths.clean_dump_dir(tmp_path, "letras", day): "clean/dumps/letras/20261105",
        paths.clean_catalog_dir(tmp_path, "discogs", day): "clean/catalog/discogs/20261105",
        paths.clean_countries_dir(tmp_path, date(2026, 11, 5)): "clean/countries/20261105",
        paths.country_songs_dir(tmp_path, "BRA", run): "lyrics/BRA/songs/20261105T140000Z",
        paths.country_scores_dir(tmp_path, "BRA", run): "lyrics/BRA/scores/20261105T140000Z",
        paths.analysis_dir(tmp_path, day): "analysis/20261105",
    }
    assert {path.relative_to(tmp_path).as_posix() for path in built} == set(built.values())
    assert len(built) == 8


@pytest.mark.parametrize(
    ("build", "message"),
    [
        (lambda data: paths.country_songs_dir(data, "bra", "20261105T140000Z"), "iso3"),
        (lambda data: paths.country_songs_dir(data, "BRAZ", "20261105T140000Z"), "iso3"),
        (lambda data: paths.country_songs_dir(data, "BRA", "20261105"), "run_id"),
        (lambda data: paths.country_scores_dir(data, "BRA", "20261341T140000Z"), "run_id"),
        (lambda data: paths.clean_dump_dir(data, "Letras", "20261105"), "source"),
        (lambda data: paths.clean_catalog_dir(data, "../discogs", "20261105"), "source"),
        (lambda data: paths.clean_countries_dir(data, "2026-11-05"), "date"),
        (lambda data: paths.analysis_dir(data, "20261340"), "date"),
        (lambda data: paths.raw_dir(data, "lrclib", "20261105T140000Z"), "date"),
        (lambda data: paths.raw_dir(data, "manual_review", "20261105"), "not a source"),
        (lambda data: paths.raw_manual_review_dir(data, "BRA", 20261105), "date"),
        (lambda data: paths.latest_country_songs_dir(data, "bra"), "iso3"),
        (lambda data: paths.latest_clean_dump_dir(data, "Letras"), "source"),
    ],
)
def test_a_bad_part_of_a_version_folder_is_refused(tmp_path, build, message):
    with pytest.raises(ValueError, match=message):
        build(tmp_path)


def test_latest_is_the_newest_folder_that_has_a_manifest(tmp_path):
    assert paths.latest_country_songs_dir(tmp_path, "BRA") is None
    first = seal(paths.country_songs_dir(tmp_path, "BRA", "20261105T140000Z"))
    assert paths.latest_country_songs_dir(tmp_path, "BRA") == first
    second = seal(paths.country_songs_dir(tmp_path, "BRA", "20270203T083000Z"))
    # A folder without a manifest is incomplete, and a name outside the pattern is not a version.
    paths.country_songs_dir(tmp_path, "BRA", "20270301T000000Z").mkdir()
    seal(tmp_path / "lyrics" / "BRA" / "songs" / "retry_2")
    assert paths.latest_country_songs_dir(tmp_path, "BRA") == second
    assert paths.latest_country_songs_dir(tmp_path, "ARG") is None
    assert paths.latest_country_scores_dir(tmp_path, "BRA") is None


def test_every_kind_of_version_folder_has_a_latest_function(tmp_path):
    day, run = "20261105", "20261105T140000Z"
    pairs = [
        (paths.raw_dir(tmp_path, "lrclib", day), paths.latest_raw_dir(tmp_path, "lrclib")),
        (
            paths.raw_manual_review_dir(tmp_path, "BRA", day),
            paths.latest_raw_manual_review_dir(tmp_path, "BRA"),
        ),
        (
            paths.clean_dump_dir(tmp_path, "letras", day),
            paths.latest_clean_dump_dir(tmp_path, "letras"),
        ),
        (
            paths.clean_catalog_dir(tmp_path, "discogs", day),
            paths.latest_clean_catalog_dir(tmp_path, "discogs"),
        ),
        (paths.clean_countries_dir(tmp_path, day), paths.latest_clean_countries_dir(tmp_path)),
        (
            paths.country_scores_dir(tmp_path, "BRA", run),
            paths.latest_country_scores_dir(tmp_path, "BRA"),
        ),
        (paths.analysis_dir(tmp_path, day), paths.latest_analysis_dir(tmp_path)),
    ]
    assert [found for _, found in pairs] == [None] * len(pairs)
    for folder, _ in pairs:
        seal(folder)
    assert paths.latest_raw_dir(tmp_path, "lrclib") == pairs[0][0]
    assert paths.latest_raw_manual_review_dir(tmp_path, "BRA") == pairs[1][0]
    assert paths.latest_clean_dump_dir(tmp_path, "letras") == pairs[2][0]
    assert paths.latest_clean_catalog_dir(tmp_path, "discogs") == pairs[3][0]
    assert paths.latest_clean_countries_dir(tmp_path) == pairs[4][0]
    assert paths.latest_country_scores_dir(tmp_path, "BRA") == pairs[5][0]
    assert paths.latest_analysis_dir(tmp_path) == pairs[6][0]


def test_workbook_folders_count_without_a_manifest(tmp_path):
    assert paths.raw_manual_review_dirs(tmp_path, "TGO") == []
    newer = paths.raw_manual_review_dir(tmp_path, "TGO", "20261102")
    older = paths.raw_manual_review_dir(tmp_path, "TGO", "20261101")
    for folder in (newer, older, tmp_path / "raw" / "manual_review" / "TGO" / "notes"):
        folder.mkdir(parents=True)
    assert paths.raw_manual_review_dirs(tmp_path, "TGO") == [older, newer]
    assert paths.latest_raw_manual_review_dir(tmp_path, "TGO") is None


def test_a_path_in_a_record_is_relative_to_the_data_folder(tmp_path):
    folder = paths.country_songs_dir(tmp_path, "BRA", "20261105T140000Z")
    folder.mkdir(parents=True)
    (folder / "songs.parquet").write_bytes(b"")
    assert paths.data_relative(tmp_path, folder) == "lyrics/BRA/songs/20261105T140000Z/"
    assert (
        paths.data_relative(tmp_path, folder / "songs.parquet")
        == "lyrics/BRA/songs/20261105T140000Z/songs.parquet"
    )
    with pytest.raises(ValueError):
        paths.data_relative(tmp_path / "other", folder)


def test_run_records_use_the_patterns_of_the_paths():
    assert run_records.ISO3 is paths.ISO3
    assert run_records.RUN_ID is paths.RUN_ID
    assert run_records.SOURCE is paths.SOURCE
    assert paths.check_run_id(run_records.new_run_id())
    assert paths.MANUAL_REVIEW in run_records.ROUTES


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
