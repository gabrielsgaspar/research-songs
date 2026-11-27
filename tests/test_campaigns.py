"""Campaign records, the new run record fields, the plan text and the repeat guard."""

import json
from itertools import count
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from songs.cli import app
from songs.common import campaigns, run_records
from songs.common.run_records import RunRecord

OLD_RECORD = {  # a record as schema version 1 wrote it
    "artist_limit": None,
    "artists_attempted": None,
    "backfilled": False,
    "bulk_file": None,
    "code_commit": "0" * 40,
    "deadline_utc": None,
    "ended_utc": "2026-01-31T13:05:00Z",
    "iso3": "BRA",
    "known_gaps": [],
    "notes": "",
    "request_delay_seconds": None,
    "route": "live",
    "rows_added": 42,
    "run_id": "20260131T120000Z",
    "schema_version": 1,
    "song_limit": None,
    "source": "genius",
    "started_utc": "2026-01-31T12:00:00Z",
    "state": "complete",
}


@pytest.fixture
def clock(monkeypatch):
    """Give each new run or campaign its own second, so ids differ inside one test."""
    seconds = count()
    monkeypatch.setattr(
        run_records, "new_run_id", lambda now=None: f"20260301T1200{next(seconds):02d}Z"
    )


def test_a_campaign_opens_takes_its_runs_and_closes(tmp_path, clock):
    opened = campaigns.open_campaign("BRA", " More songs before 1990 ", countries=tmp_path)
    assert (opened.goal, opened.songs_before, opened.is_open) == (
        "More songs before 1990",
        None,
        True,
    )
    with pytest.raises(FileExistsError, match="open campaign"):
        campaigns.open_campaign("BRA", "A second goal", countries=tmp_path)
    campaigns.open_campaign("ARG", "Another country may have its own", countries=tmp_path)

    with run_records.record_run("BRA", "live", "genius", countries=tmp_path, song_limit=5) as run:
        run.limits_hit = {"song_limit": 412}
    (record,) = run_records.read_run_records("BRA", tmp_path)
    assert (record.campaign_id, record.schema_version) == (opened.campaign_id, 2)

    closed = campaigns.close_campaign(
        "BRA", "complete", "Raise the song limit to 20.", songs_after=5930, countries=tmp_path
    )
    assert (closed.is_open, closed.outcome, closed.songs_after) == (False, "complete", 5930)
    assert run_records.open_campaign_id("BRA", tmp_path) is None
    assert run_records.open_campaign_id("ARG", tmp_path) is not None
    names = sorted(path.name for path in (tmp_path / "BRA" / "campaigns").iterdir())
    assert names == [f"{opened.campaign_id}_close.json", f"{opened.campaign_id}_open.json"]

    # A run after the close belongs to no campaign.
    with run_records.record_run("BRA", "live", "genius", countries=tmp_path, song_limit=20):
        pass
    assert run_records.read_run_records("BRA", tmp_path)[-1].campaign_id is None
    assert campaigns.format_campaigns(
        campaigns.read_campaigns("BRA", tmp_path), run_records.read_run_records("BRA", tmp_path)
    ).splitlines()[:6] == [
        f"BRA campaign {opened.campaign_id}: complete, closed {closed.closed_utc[:10]}",
        "    goal: More songs before 1990",
        "    songs before: not recorded, songs after: 5930",
        "    next time: Raise the song limit to 20.",
        "    runs: 1",
        f"        BRA {record.started_utc[:10]} live genius: complete, rows not recorded, "
        f"{run_records.duration_text(record)}; "
        f"song limit 5; campaign {opened.campaign_id}",
    ]


@pytest.mark.parametrize(
    ("outcome", "next_time", "reason", "message"),
    [
        ("complete", " ", "", "next_time is empty"),
        ("stopped", "Try the archive.", "", "needs a reason"),
        ("abandoned", "Try the archive.", " ", "needs a reason"),
        ("finished", "Try the archive.", "", "outcome must be one of"),
    ],
)
def test_close_refuses_a_campaign_with_no_lesson(tmp_path, outcome, next_time, reason, message):
    campaigns.open_campaign("BRA", "A goal", countries=tmp_path)
    with pytest.raises(ValueError, match=message):
        campaigns.close_campaign("BRA", outcome, next_time, reason=reason, countries=tmp_path)
    assert run_records.open_campaign_id("BRA", tmp_path) is not None


def test_open_and_close_refuse_what_does_not_exist(tmp_path):
    with pytest.raises(ValueError, match="needs a goal"):
        campaigns.open_campaign("BRA", " ", countries=tmp_path)
    with pytest.raises(ValueError, match="three capital letters"):
        campaigns.open_campaign("Brazil", "A goal", countries=tmp_path)
    with pytest.raises(FileNotFoundError, match="no open campaign"):
        campaigns.close_campaign("BRA", "complete", "Nothing more.", countries=tmp_path)
    assert campaigns.format_campaigns([], []) == "No campaigns recorded."


def test_a_changed_campaign_file_is_refused(tmp_path):
    opened = campaigns.open_campaign("BRA", "A goal", countries=tmp_path)
    path = tmp_path / "BRA" / "campaigns" / f"{opened.campaign_id}_open.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    path.write_text(json.dumps({**payload, "owner": "x"}), encoding="utf-8")
    with pytest.raises(ValueError, match="fields must be"):
        campaigns.read_campaigns("BRA", tmp_path)
    path.write_text(json.dumps({**payload, "iso3": "ARG"}), encoding="utf-8")
    with pytest.raises(ValueError, match="does not match"):
        campaigns.read_campaigns("BRA", tmp_path)


def test_a_record_of_schema_version_1_still_loads(tmp_path):
    path = tmp_path / "BRA" / "runs" / "20260131T120000Z_live_genius.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(OLD_RECORD), encoding="utf-8")
    (record,) = run_records.read_run_records("BRA", tmp_path)
    assert (record.schema_version, record.rows_added) == (1, 42)
    assert (record.campaign_id, record.requests_sent, record.songs_rejected) == (None, None, None)
    assert run_records.duration_text(record) == "1 h 5 min"
    with pytest.raises(ValueError, match="schema_version"):
        RunRecord(**{**OLD_RECORD, "schema_version": 3}).validate()
    with pytest.raises(ValueError, match="campaign_id"):
        RunRecord(**{**OLD_RECORD, "campaign_id": "spring"}).validate()


def test_the_same_job_does_not_run_twice_without_a_reason(tmp_path, clock):
    def run(**settings):
        with run_records.record_run("BRA", "live", "genius", countries=tmp_path, **settings):
            pass

    run(song_limit=5, request_delay_seconds=2.0)
    with pytest.raises(FileExistsError, match="already did this job"):
        run(song_limit=5, request_delay_seconds=2.0)
    assert len(run_records.read_run_records("BRA", tmp_path)) == 1  # refused before any work
    run(song_limit=20, request_delay_seconds=2.0)  # a changed limit is a new job
    run(song_limit=5, request_delay_seconds=2.0, repeat_reason="The site added an archive page.")
    assert run_records.read_run_records("BRA", tmp_path)[-1].notes == (
        "The site added an archive page."
    )

    # A run that failed is not a finished job, so it may run again.
    with pytest.raises(RuntimeError):
        with run_records.record_run("ARG", "live", "genius", countries=tmp_path):
            raise RuntimeError
    with run_records.record_run("ARG", "live", "genius", countries=tmp_path):
        pass


def test_the_plan_shows_the_last_run_of_each_source_and_the_last_advice(tmp_path, clock):
    campaigns.open_campaign("BRA", "More songs before 1990", songs_before=4210, countries=tmp_path)
    with run_records.record_run(
        "BRA", "live", "genius", countries=tmp_path, song_limit=5, request_delay_seconds=3.0
    ) as run:
        run.rows_added, run.requests_sent = 1720, 9000
        run.songs_attempted, run.songs_accepted = 2045, 1720
        run.songs_rejected = {"wrong language": 80, "duplicate": 245}
        run.limits_hit = {"song_limit": 412}
    campaigns.close_campaign(
        "BRA",
        "stopped",
        "Raise the song limit from 5 to 20.",
        reason="The time limit ended.",
        songs_after=5930,
        countries=tmp_path,
    )
    sources = [
        SimpleNamespace(id="genius", kind="bulk_dump", access="blocked"),
        SimpleNamespace(id="lrclib", kind="bulk_dump", access="blocked"),
    ]
    (campaign,) = campaigns.read_campaigns("BRA", tmp_path)
    text = campaigns.format_plan(
        "BRA", sources, run_records.read_run_records("BRA", tmp_path), [campaign]
    )
    day = campaign.opened_utc[:10]
    assert text.splitlines() == [
        "BRA: 2 sources apply, 1 already ran, 1 never ran.",
        "genius (bulk_dump, requests blocked): 1 runs",
        f"    last run {day} live: complete, 0 s, rows added 1720",
        "    settings: delay s 3.0, artist limit not recorded, song limit 5",
        "    requests sent: 9000; songs accepted: 1720 of 2045 attempted",
        "    rejected: duplicate: 245, wrong language: 80",
        "    limits hit: song_limit: 412",
        "lrclib (bulk_dump, requests blocked): never ran",
        f"Last closed campaign {campaign.campaign_id} (stopped): More songs before 1990",
        "    next time: Raise the song limit from 5 to 20.",
    ]
    assert campaigns.format_plan("ARG", sources, [], []).splitlines()[-1] == (
        "No campaigns recorded."
    )


def test_commands(tmp_path, monkeypatch, clock):
    monkeypatch.setattr(run_records, "countries_dir", lambda: tmp_path)
    runner = CliRunner()

    def invoke(*args):
        return runner.invoke(app, ["lyrics", *args], env={"COLUMNS": "200"})

    opened = invoke("campaign", "open", "bra", "--goal", "More songs", "--songs", "100")
    assert opened.exit_code == 0 and "opened campaign" in opened.output
    assert "never ran" in opened.output  # the plan follows, so it is read before a run
    assert invoke("campaign", "open", "BRA", "--goal", "Again").exit_code == 1
    refused = invoke("campaign", "close", "BRA", "--outcome", "stopped", "--next-time", "Try x.")
    assert refused.exit_code == 1 and "needs a reason" in refused.output
    closed = invoke(
        "campaign", "close", "BRA", "--outcome", "complete", "--next-time", "Try the archive."
    )
    assert closed.exit_code == 0 and "next time: Try the archive." in closed.output
    listed = invoke("campaign", "list", "BRA")
    assert listed.exit_code == 0 and "songs before: 100" in listed.output
    plan = invoke("plan", "BRA")
    assert plan.exit_code == 0 and "next time: Try the archive." in plan.output
    assert invoke("plan", "BRAZIL").exit_code != 0
    assert invoke("campaign", "list", "ARG").output.strip() == "No campaigns recorded."


def test_a_country_is_held_while_its_newest_campaign_stopped_after_it_added_songs(tmp_path, clock):
    def campaign(iso3: str, outcome: str, before: int | None, after: int | None) -> None:
        campaigns.open_campaign(iso3, "An invented goal", songs_before=before, countries=tmp_path)
        reason = "" if outcome == "complete" else "An invented reason"
        campaigns.close_campaign(
            iso3, outcome, "Try x.", reason=reason, songs_after=after, countries=tmp_path
        )

    campaign("BRA", "stopped", 10, 12)  # held
    campaign("ARG", "stopped", 10, 10)  # stopped, added nothing
    campaign("CHL", "stopped", 10, 12)
    campaign("CHL", "complete", 12, 15)  # a later campaign ends the hold
    campaign("PER", "complete", 10, 12)
    campaign("PER", "stopped", 12, 14)  # held
    campaign("URY", "stopped", None, 14)  # the counts are not recorded: held
    campaign("BOL", "abandoned", 10, 12)
    campaigns.open_campaign("ECU", "An open campaign", countries=tmp_path)
    assert campaigns.held_countries(tmp_path) == ["BRA", "PER", "URY"]


@pytest.mark.parametrize(
    "bulk_file",
    [
        "raw/reviewed_corrections/20261127/review.jsonl",
        "raw/artist_recording_review/20261127/correction.json",
    ],
)
def test_review_of_existing_fields_preserves_collection_hold(tmp_path, clock, bulk_file):
    campaigns.open_campaign("BRA", "Collect songs", songs_before=2, countries=tmp_path)
    campaigns.close_campaign(
        "BRA",
        "stopped",
        "Check the roster.",
        reason="Roster review.",
        songs_after=3,
        countries=tmp_path,
    )
    campaigns.open_campaign("BRA", "Correct existing songs", songs_before=3, countries=tmp_path)
    with run_records.record_run(
        "BRA",
        "manual_review",
        "genius",
        countries=tmp_path,
        bulk_file=bulk_file,
        rows_added=0,
    ):
        pass
    campaigns.close_campaign(
        "BRA", "complete", "Check the roster.", songs_after=3, countries=tmp_path
    )
    assert campaigns.held_countries(tmp_path) == ["BRA"]
