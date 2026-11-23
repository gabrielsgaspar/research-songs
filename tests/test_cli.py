"""The thin commands of campaigns: what they pass to the library and what they print."""

import sys
import types
from types import SimpleNamespace

import pytest
import typer
from typer.testing import CliRunner

from songs import cli
from songs.common import storage
from songs.common.paths import DATA_ROOT_ENV
from songs.stage_00_ingest import campaign_run


@pytest.fixture
def bucket(monkeypatch, tmp_path):
    """Give the commands a stand-in for the bucket; no command reaches the cloud."""
    monkeypatch.setenv(DATA_ROOT_ENV, str(tmp_path))
    monkeypatch.setattr(cli, "_bucket", lambda: (storage, object(), "invented-bucket"))


def test_years_reads_a_year_or_a_range_and_refuses_the_rest():
    assert cli._years(None) is None
    assert cli._years("1965") == (1965, 1965)
    assert cli._years("1960-1969") == (1960, 1969)
    for text in ("1969-1960", "196", "1960-", "sixties", "1960-1969-1979"):
        with pytest.raises(typer.BadParameter):
            cli._years(text)


def test_pull_asks_for_each_parent_one_time(bucket, monkeypatch):
    sources = {"MNE": ["genius", "tekstovi"], "SRB": ["genius", "tekstovi", "other"]}
    monkeypatch.setattr(
        cli.lyric_sources,
        "sources_for",
        lambda code: [SimpleNamespace(id=name) for name in sources[code]],
    )
    assert campaign_run.pull_parents(["MNE", "SRB"]) == [
        "lyrics/MNE/songs/",
        "lyrics/MNE/scores/",
        "clean/dumps/genius/",
        "clean/dumps/tekstovi/",
        "lyrics/SRB/songs/",
        "lyrics/SRB/scores/",
        "clean/dumps/other/",
        "clean/catalog/discogs/",
    ]
    asked = []

    def pull_newest(transport, name, data, parents):
        asked.extend(parents)
        return {parent: ("absent", None) for parent in parents}

    monkeypatch.setattr(storage, "pull_newest", pull_newest)
    result = CliRunner().invoke(cli.app, ["data", "pull", "mne", "--no-catalog"])
    assert result.exit_code == 0, result.output
    assert "clean/catalog/discogs/" not in asked
    assert "lyrics/MNE/songs/: absent" in result.output


def test_publish_notes_an_old_input_and_fails_on_a_missing_layout_input(bucket, monkeypatch):
    folder = "lyrics/MNE/songs/20261121T162001Z/"
    later = "lyrics/MNE/songs/20261122T185722Z/"
    answer = {
        "uploaded": [folder],
        "present": [],
        "missing_inputs": [],
        "skipped": [],
        "old_inputs": [(folder, "lyrics/mne/")],
    }
    monkeypatch.setattr(storage, "publish", lambda *args, **kwargs: answer)
    result = CliRunner().invoke(cli.app, ["lyrics", "publish", "MNE"])
    assert result.exit_code == 0, result.output
    assert "note: " in result.output and "old data folder" in result.output
    assert "1 uploaded, 0 in the bucket already, 0 not uploaded" in result.output

    answer["missing_inputs"].append((later, "clean/dumps/example/20261120/"))
    answer["skipped"].append(later)
    result = CliRunner().invoke(cli.app, ["lyrics", "publish", "MNE"])
    assert result.exit_code == 1
    assert "problem: " in result.output and "clean/dumps/example/20261120/" in result.output
    assert f"uploaded: {folder}" in result.output and f"not uploaded: {later}" in result.output


def test_audit_takes_the_runs_that_wrote_a_songs_folder(bucket, monkeypatch):
    def record(code, run_id, route, state="complete"):
        return SimpleNamespace(iso3=code, run_id=run_id, route=route, state=state)

    records = [
        record("MNE", "20261121T000001Z", "old_layout"),
        record("MNE", "20261121T000002Z", "dump_name", "partial"),
        record("MNE", "20261121T000003Z", "dump_name", "failed"),
        record("MNE", "20261121T000004Z", "live"),
    ]
    expected = {("MNE", "20261121T000001Z"), ("MNE", "20261121T000002Z")}
    assert campaign_run.expected_songs_folders(records) == expected

    monkeypatch.setattr(cli.run_records, "read_run_records", lambda: records)
    seen = {}

    def audit_songs(transport, name, pairs):
        seen["pairs"] = pairs
        return seen["answer"]

    monkeypatch.setattr(storage, "audit_songs", audit_songs)
    seen["answer"] = {"not_in_bucket": [], "no_record": []}
    result = CliRunner().invoke(cli.app, ["lyrics", "audit"])
    assert (result.exit_code, seen["pairs"]) == (0, expected)

    seen["answer"] = {"not_in_bucket": [("MNE", "20261121T000002Z")], "no_record": []}
    result = CliRunner().invoke(cli.app, ["lyrics", "audit"])
    assert result.exit_code == 1
    assert "record with no folder in the bucket: lyrics/MNE/songs/20261121T000002Z/" in (
        result.output
    )


def test_survey_prints_decades_the_range_and_a_source_without_a_dump(bucket, monkeypatch):
    from songs.stage_00_ingest import dump_match

    monkeypatch.setattr(
        cli.lyric_sources, "sources_for", lambda code: [SimpleNamespace(id="example")]
    )
    rows = [
        {"source": "absent", "dump": None},
        {
            "source": "example",
            "dump": "clean/dumps/example/20261120/",
            "songs_in": 40,
            "would_add": 7,
            "by_year": {1961: 2, 1968: 1, 1975: 3},
            "no_year": 1,
            "rejected": {},
            "seconds": 0.1,
        },
    ]
    monkeypatch.setattr(dump_match, "survey", lambda data, code, sources: rows)
    result = CliRunner().invoke(cli.app, ["lyrics", "survey", "MNE", "--years", "1960-1969"])
    assert result.exit_code == 0, result.output
    assert "MNE absent: no dump on this disk" in result.output
    assert "would add 7 of 40 songs" in result.output
    assert "1960s: 3, 1970s: 3; no year: 1; 1960-1969: 3" in result.output
    assert "total: would add up to 7 songs, 3 in 1960-1969" in result.output


def test_campaign_run_goes_on_after_a_country_fails_and_exits_1(bucket, monkeypatch):
    calls = []

    def run_country(data, iso3, *, goal, min_songs=25, discogs=None, countries=None):
        calls.append((iso3, goal, min_songs))
        if iso3 == "MNE":
            raise FileNotFoundError("no songs folder of MNE")
        if iso3 == "PRY":
            # The second import failed: the error carries what the ladder did before it.
            error = RuntimeError("invented failure")
            error.ladder = {
                "campaign_id": "20261122T110000Z",
                "songs_before": 5,
                "songs_after": 9,
                "survey": [],
                "imported": [
                    {"source": "first", "songs_added": 4, "folder": "lyrics/PRY/x/", "seconds": 1}
                ],
                "skipped": [],
            }
            raise error
        if iso3 == "MLT":
            # An open campaign and nothing to import.
            return {
                "campaign_id": "20261122T120000Z",
                "songs_before": 7,
                "songs_after": 7,
                "survey": [],
                "imported": [],
                "skipped": [],
            }
        return {
            "campaign_id": "20261122T100000Z",
            "songs_before": 10,
            "songs_after": 40,
            "survey": [],
            "imported": [
                {"source": "example", "songs_added": 30, "folder": "lyrics/LUX/x/", "seconds": 1.5}
            ],
            "skipped": [
                {"source": "small", "reason": "under 25 songs", "would_add": 3},
                {"source": "absent_one", "reason": "no dump", "would_add": None},
                {"source": "absent_two", "reason": "no dump", "would_add": None},
            ],
        }

    def report(data, iso3, campaign_id=None, *, years=None, countries=None):
        return f"# Report {iso3} {campaign_id} {years}"

    stand_in = types.ModuleType("songs.stage_00_ingest.campaign_run")
    stand_in.run_country, stand_in.report = run_country, report
    monkeypatch.setitem(sys.modules, "songs.stage_00_ingest.campaign_run", stand_in)
    import songs.stage_00_ingest as package

    monkeypatch.setattr(package, "campaign_run", stand_in, raising=False)

    result = CliRunner().invoke(
        cli.app,
        ["lyrics", "campaign", "run", "MNE", "PRY", "MLT", "LUX"]
        + ["--goal", "More songs", "--years", "1965"],
    )
    assert result.exit_code == 1
    assert [call[0] for call in calls] == ["MNE", "PRY", "MLT", "LUX"]
    assert calls[-1] == ("LUX", "More songs (years 1965-1965)", 25)
    assert "error: PRY: RuntimeError: invented failure" in result.output
    assert "PRY: campaign 20261122T110000Z, songs 5 -> 9" in result.output
    assert "imported first: 4 songs" in result.output
    assert "# Report PRY 20261122T110000Z (1965, 1965)" in result.output
    assert "MLT: campaign 20261122T120000Z, songs 7 -> 7" in result.output
    assert "not opened" not in result.output
    assert "LUX: campaign 20261122T100000Z, songs 10 -> 40" in result.output
    assert "imported example: 30 songs" in result.output
    assert "skipped small: under 25 songs (would add 3)" in result.output
    assert "sources with no dump on this disk: 2" in result.output
    assert "absent_one" not in result.output
    assert "# Report LUX 20261122T100000Z (1965, 1965)" in result.output
    assert "failed: MNE, PRY" in result.output
