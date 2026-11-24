"""The weekly sync, on small invented folders and the fake bucket of `test_storage`."""

from pathlib import Path

import duckdb
from test_storage import BUCKET, FakeBucket
from typer.testing import CliRunner

from songs import cli
from songs.common import manifests, paths, schemas, storage, sync
from songs.common.paths import DATA_ROOT_ENV
from songs.stage_50_analysis import countries_panel

OLD, NEW = "20261101T000000Z", "20261108T000000Z"


def tables(data: Path, folder: Path, kind: str, inputs: list[str], *names: schemas.Table) -> str:
    """Write a complete version folder of empty tables. Return its path in the data folder."""
    folder.mkdir(parents=True)
    for table in names:
        schemas.write_table(table, schemas.empty_table(table), folder)
    whose = {"country_iso3": folder.parts[-3], "run_id": folder.name} if "country" in kind else {}
    manifests.write_manifest(data, folder, kind, inputs=inputs, **whose)
    return paths.data_relative(data, folder)


def songs(data: Path, iso3: str, run_id: str) -> str:
    country = (schemas.COUNTRY_SONGS, schemas.COUNTRY_ARTISTS, schemas.COUNTRY_LINKS)
    folder = paths.country_songs_dir(data, iso3, run_id)
    return tables(data, folder, "country_songs", ["lyrics/old/"], *country)


def scores(data: Path, iso3: str, run_id: str, of: str) -> str:
    score = (schemas.SCORE_TOPICS, schemas.SCORE_PROVENANCE)
    return tables(
        data, paths.country_scores_dir(data, iso3, run_id), "country_scores", [of], *score
    )


def touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}\n", encoding="utf-8")


def test_the_sync_holds_guarded_songs_and_a_dry_run_writes_nothing(tmp_path):
    data, countries = tmp_path / "data", tmp_path / "countries"
    recorded = songs(data, "ISL", OLD)
    no_record = songs(data, "ISL", NEW)
    in_campaign = songs(data, "NOR", OLD)
    for name in (f"ISL/runs/{OLD}_old_layout_invented.json", f"NOR/runs/{OLD}_old_layout_x.json"):
        touch(countries / name)
    touch(countries / "NOR" / "campaigns" / f"{OLD}_open.json")
    of_recorded = scores(data, "ISL", NEW, recorded)
    of_held = scores(data, "NOR", NEW, in_campaign)
    for name in ("cache", "tmp", "staging"):
        touch(data / name / "dumps" / "20261101" / paths.MANIFEST_NAME)

    bucket = FakeBucket()
    result = sync.sync(bucket, BUCKET, data, countries=countries)
    assert bucket.writes == []
    assert result["uploaded"] == [recorded, of_recorded]
    assert result["held"] == {no_record: sync.NO_RECORD, in_campaign: sync.OPEN_CAMPAIGN}
    assert result["skipped"] == [of_held]
    text = sync.report(data, result, write=False)
    assert "dry run" in text and "- Would upload: 2 folders, 0 rows" in text
    assert "- Left out: 3 folders" in text
    assert f"- `{in_campaign}`: {sync.OPEN_CAMPAIGN}" in text
    assert f"- `{of_held}`: an input is left out" in text

    result = sync.sync(bucket, BUCKET, data, write=True, countries=countries)
    assert result["uploaded"] == [recorded, of_recorded]
    assert all(name.startswith("data/lyrics/ISL/") for name in bucket.writes)
    assert not [name for name in bucket.writes if no_record in name]
    assert "- Uploaded: 2 folders" in sync.report(data, result, write=True)

    touch(countries / "NOR" / "campaigns" / f"{OLD}_close.json")
    result = sync.sync(bucket, BUCKET, data, write=True, countries=countries)
    assert result["uploaded"] == [in_campaign, of_held]
    assert result["present"] == [recorded, of_recorded]
    assert result["held"] == {no_record: sync.NO_RECORD}


def test_a_derived_folder_with_a_newer_input_is_stale(tmp_path, monkeypatch):
    data = tmp_path
    assert sync.stale(data) == []
    old, held = songs(data, "ISL", OLD), scores(data, "ISL", OLD, "x/")
    panel = paths.clean_countries_dir(data, "20261101")
    panel.mkdir(parents=True)
    duckdb.sql("SELECT 1 AS x").write_parquet(str(panel / manifests.COUNTRIES_FILE))
    # The panel counts the eligible songs, so a songs folder is an input too.
    inputs = ["raw/gdp/20261001/gdp.csv", old]
    manifests.write_manifest(data, panel, "clean_countries", inputs=inputs)
    release = tables(
        data,
        paths.analysis_dir(data, "20261102"),
        "analysis",
        [paths.data_relative(data, panel), old, held],
        schemas.ANALYSIS_SONGS,
        schemas.ANALYSIS_COUNTRY_YEAR,
    )
    read = {"gdp": data / "raw" / "gdp" / "20261001" / "gdp.csv"}
    monkeypatch.setattr(countries_panel, "default_inputs", lambda data: read)
    touch(read["gdp"])
    assert sync.stale(data) == []

    new = songs(data, "ISL", NEW)
    other = songs(data, "NOR", OLD)
    read["gdp"] = data / "raw" / "gdp" / "20261101" / "gdp.csv"
    touch(read["gdp"])
    assert sync.stale(data) == [
        ("clean/countries/20261101/", f"a build now reads `{new}`", sync.PANEL_COMMAND),
        ("clean/countries/20261101/", f"a build now reads `{other}`", sync.PANEL_COMMAND),
        (
            "clean/countries/20261101/",
            "a build now reads `raw/gdp/20261101/gdp.csv`",
            sync.PANEL_COMMAND,
        ),
        (release, f"`{old}` has the newer folder `{new}`", sync.RELEASE_COMMAND),
        (release, "`lyrics/NOR/songs/` is not an input", sync.RELEASE_COMMAND),
    ]
    result = {key: [] for key in ("uploaded", "present", "missing_inputs", "skipped")}
    text = sync.report(data, result | {"held": {}, "stale": sync.stale(data)}, write=False)
    assert "- Stale: 2 folders" in text
    assert f"To build it again, run `{sync.RELEASE_COMMAND}`" in text


def test_the_command_prints_the_report_and_uploads_only_with_write(tmp_path, monkeypatch):
    monkeypatch.setenv(DATA_ROOT_ENV, str(tmp_path))
    seen = []
    answer = {key: [] for key in ("uploaded", "present", "missing_inputs", "skipped", "stale")}

    def fake(transport, bucket, data, *, write):
        seen.append(write)
        return answer | {"held": {}}

    monkeypatch.setattr(cli, "_bucket", lambda: (storage, object(), "invented-bucket"))
    monkeypatch.setattr(sync, "sync", fake)
    result = CliRunner().invoke(cli.app, ["data", "sync"])
    assert result.exit_code == 0, result.output
    assert "dry run" in result.output
    answer["missing_inputs"] = [("raw/b/20261102/", "raw/a/20261101/")]
    answer["skipped"] = ["raw/b/20261102/"]
    result = CliRunner().invoke(cli.app, ["data", "sync", "--write"])
    assert result.exit_code == 1
    assert "the input `raw/a/20261101/` is not on this disk" in result.output
    assert seen == [False, True]
