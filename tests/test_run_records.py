"""Tests for run records, the history text, the coverage page, and their commands."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from songs.cli import app
from songs.common import run_records
from songs.common.run_records import RunRecord

ROOT = Path(__file__).resolve().parents[1]


def make(**changes) -> RunRecord:
    values = {
        "iso3": "BRA",
        "run_id": "20260131T120000Z",
        "route": "live",
        "source": "example_site",
        "state": "complete",
        "started_utc": "2026-01-31T12:00:00Z",
        "ended_utc": "2026-01-31T13:00:00Z",
        "code_commit": "0" * 40,
    }
    return RunRecord(**{**values, **changes})


def test_a_record_round_trips_and_is_write_once(tmp_path):
    record = make(request_delay_seconds=0.25, artist_limit=100, rows_added=42, known_gaps=["x"])
    path = run_records.write_run_record(record, tmp_path)
    assert path == tmp_path / "BRA" / "runs" / "20260131T120000Z_live_example_site.json"
    assert b"\r" not in path.read_bytes()
    assert run_records.read_run_records("BRA", tmp_path) == [record]
    with pytest.raises(FileExistsError):
        run_records.write_run_record(record, tmp_path)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"iso3": "bra"}, "iso3"),
        ({"iso3": "BRAZ"}, "iso3"),
        ({"run_id": "2026-01-31"}, "run_id"),
        ({"route": "scrape"}, "route"),
        ({"source": "Example Site"}, "source"),
        ({"state": "done"}, "state"),
        ({"bulk_file": "gs://some-bucket/dumps/x.zip"}, "bulk_file"),
    ],
)
def test_a_bad_record_is_refused(tmp_path, changes, message):
    with pytest.raises(ValueError, match=message):
        run_records.write_run_record(make(**changes), tmp_path)
    assert not list(tmp_path.rglob("*.json"))


def test_reading_refuses_unknown_fields_and_misplaced_files(tmp_path):
    path = run_records.write_run_record(make(), tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    path.write_text(json.dumps({**payload, "extra": 1}), encoding="utf-8")
    with pytest.raises(ValueError, match="unknown fields"):
        run_records.read_run_records("BRA", tmp_path)
    path.write_text(json.dumps({**payload, "iso3": "ARG"}), encoding="utf-8")
    with pytest.raises(ValueError, match="does not match"):
        run_records.read_run_records(countries=tmp_path)


def test_record_run_writes_a_complete_record(tmp_path):
    with run_records.record_run(
        "NGA", "archive", "example_archive", countries=tmp_path, song_limit=500
    ) as run:
        run.rows_added = 7
    (record,) = run_records.read_run_records("NGA", tmp_path)
    assert (record.state, record.rows_added, record.song_limit) == ("complete", 7, 500)
    assert record.ended_utc >= record.started_utc
    assert record.code_commit


def test_record_run_writes_a_failed_record_and_raises_again(tmp_path):
    with pytest.raises(KeyboardInterrupt):
        with run_records.record_run("NGA", "live", "example_site", countries=tmp_path) as run:
            run.rows_added = 3
            raise KeyboardInterrupt
    (record,) = run_records.read_run_records("NGA", tmp_path)
    assert record.state == "failed"
    assert record.rows_added == 3
    assert "KeyboardInterrupt" in record.notes


def test_record_run_refuses_a_bad_route_before_any_work(tmp_path):
    with pytest.raises(ValueError, match="route"):
        with run_records.record_run("NGA", "scrape", "example_site", countries=tmp_path):
            pytest.fail("the block must not run")
    assert not list(tmp_path.rglob("*.json"))


def test_history_text():
    assert run_records.format_history([]) == "No runs recorded."
    text = run_records.format_history(
        [
            make(request_delay_seconds=0.25, artist_limit=100, rows_added=42, known_gaps=["a gap"]),
            make(run_id="20260201T120000Z", started_utc="2026-02-01T12:00:00Z", backfilled=True),
        ]
    )
    assert text.splitlines() == [
        "BRA 2026-01-31 live example_site: complete, 42 rows; delay s 0.25, artist limit 100",
        "    gap: a gap",
        "BRA 2026-02-01 live example_site: complete, rows not recorded (backfilled)",
    ]


def test_coverage_page_text():
    assert "No runs recorded yet." in run_records.render_coverage([])
    page = run_records.render_coverage(
        [
            make(rows_added=40),
            make(run_id="20260201T120000Z", started_utc="2026-02-01T12:00:00Z", route="archive"),
            make(iso3="ARG"),
        ]
    )
    rows = [line for line in page.splitlines() if line.startswith("| [")]
    assert rows == [
        "| [ARG](../../countries/ARG/) | 1 | 2026-01-31 | live | example_site | not recorded |",
        "| [BRA](../../countries/BRA/) | 2 | 2026-02-01 | archive, live | example_site | 40 |",
    ]


def test_the_committed_coverage_page_is_current():
    expected = run_records.render_coverage(
        run_records.read_run_records(countries=ROOT / "countries")
    )
    actual = (ROOT / run_records.COVERAGE_PAGE).read_text(encoding="utf-8")
    assert actual == expected, f"run: {run_records.COVERAGE_COMMAND}"


def test_commands(tmp_path, monkeypatch):
    monkeypatch.setattr(run_records, "countries_dir", lambda: tmp_path)
    run_records.write_run_record(make(rows_added=42), tmp_path)
    runner = CliRunner()
    shown = runner.invoke(app, ["lyrics", "history", "bra"])
    assert shown.exit_code == 0 and "42 rows" in shown.output
    filtered = runner.invoke(app, ["lyrics", "history", "BRA", "--route", "archive"])
    assert filtered.exit_code == 0 and "No runs recorded." in filtered.output
    assert runner.invoke(app, ["lyrics", "history", "BRAZIL"]).exit_code != 0
    assert runner.invoke(app, ["lyrics", "history", "BRA", "--route", "scrape"]).exit_code != 0
    table = runner.invoke(app, ["lyrics", "coverage"])
    assert table.exit_code == 0 and "[BRA]" in table.output


def test_history_refuses_a_bad_country_code(tmp_path, monkeypatch):
    monkeypatch.setattr(run_records, "countries_dir", lambda: tmp_path)
    result = CliRunner().invoke(app, ["lyrics", "history", "BRAZIL"], env={"COLUMNS": "200"})
    assert result.exit_code != 0
    assert "three-letter country code" in result.output
    assert "BRAZIL" in result.output


def test_history_refuses_an_unknown_route(tmp_path, monkeypatch):
    monkeypatch.setattr(run_records, "countries_dir", lambda: tmp_path)
    result = CliRunner().invoke(
        app, ["lyrics", "history", "BRA", "--route", "scrape"], env={"COLUMNS": "200"}
    )
    assert result.exit_code != 0
    assert "route must be one of" in result.output
    assert run_records.ROUTES[0] in result.output
