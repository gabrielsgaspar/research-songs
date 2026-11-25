"""The scoring run on invented songs, with a fake Batch API. No test calls a model."""

import json
from pathlib import Path

import pytest
from test_release import artist_files, exceptions_file, frame, list_files, song, write_country

from songs.common import manifests, paths, schemas
from songs.stage_30_topics import scoring_run
from songs.stage_30_topics.scoring_prompt import FIELD_ORDER, load_scoring_prompt
from songs.stage_30_topics.topic_ids import TOPIC_IDS

PROMPT = load_scoring_prompt()
MODEL = PROMPT.settings["model"]
SHA = {name: name[0] * 64 for name in ("a", "b", "c", "d", "e")}
OLD_RUN = "20260102T000000Z"


def rule_files(tmp_path: Path) -> dict[str, Path]:
    suspect, quarantine = list_files(tmp_path)
    excluded, countries = artist_files(tmp_path)
    return {
        "exceptions": exceptions_file(tmp_path),
        "suspect": suspect,
        "quarantine": quarantine,
        "excluded_artists": excluded,
        "artist_countries": countries,
    }


def write_scores(data: Path, rows: list[tuple[str, str, str]]) -> None:
    """A complete scores folder with one row per (song id, lyrics hash, prompt hash)."""
    folder = paths.country_scores_dir(data, "TGO", OLD_RUN)
    folder.mkdir(parents=True)
    topics = [
        {"country_iso3": "TGO", "song_id": s, "lyrics_sha256": h, TOPIC_IDS[0]: 7}
        for s, h, _ in rows
    ]
    provenance = [
        {
            "country_iso3": "TGO",
            "song_id": s,
            "lyrics_sha256": h,
            "prompt_sha256": p,
            "model": MODEL,
            "text_kind": "song_lyrics",
            "status": "complete",
        }
        for s, h, p in rows
    ]
    schemas.write_table(schemas.SCORE_TOPICS, frame(schemas.SCORE_TOPICS, topics), folder)
    schemas.write_table(
        schemas.SCORE_PROVENANCE, frame(schemas.SCORE_PROVENANCE, provenance), folder
    )
    manifests.write_manifest(
        data, folder, "country_scores", country_iso3="TGO", run_id=OLD_RUN, inputs=["y/"]
    )


@pytest.fixture
def data(tmp_path):
    """s1 and s2 share text and decade; s4 is not eligible; s5 is scored; s6 has an old prompt."""
    data = tmp_path / "data"
    songs = [
        song("s1", lyrics_sha256=SHA["a"]),
        song("s2", lyrics_sha256=SHA["a"]),
        song("s3", lyrics_sha256=SHA["b"], year=1975),
        song("s4", lyrics_sha256=SHA["c"], year=1800),
        song("s5", lyrics_sha256=SHA["d"]),
        song("s6", lyrics_sha256=SHA["e"]),
    ]
    write_country(data, "TGO", songs, None)
    write_scores(data, [("s5", SHA["d"], PROMPT.sha256), ("s6", SHA["e"], "f" * 64)])
    return data


def prepared(data: Path, tmp_path: Path, **options) -> dict:
    options = {"max_requests": 10, "run_id": "20260201T000000Z"} | options
    return scoring_run.prepare(data, ["tgo"], rule_files=rule_files(tmp_path), **options)


def answer(kind: str = "song_lyrics", value: str = "40") -> dict:
    song = {"text_kind": kind} | {topic: value for topic in TOPIC_IDS}
    text = json.dumps({"song": song})
    body = {
        "status": "completed",
        "model": f"{MODEL}-2026-01-01",
        "output": [{"type": "message", "content": [{"type": "output_text", "text": text}]}],
    }
    return {"response": {"status_code": 200, "body": body}}


class FakeBatches:
    def __init__(self, status: str = "completed", lines: list[dict] | None = None) -> None:
        self.status, self.lines, self.calls = status, lines or [], []

    def upload(self, path: Path) -> str:
        self.calls.append(("upload", path.name))
        return "file-1"

    def create_batch(self, file_id: str, endpoint: str, metadata: dict[str, str]) -> str:
        self.calls.append(("create", file_id, endpoint))
        return "batch-1"

    def batch(self, batch_id: str) -> dict:
        return {"status": self.status, "output_file_id": "out-1", "error_file_id": None}

    def file_content(self, file_id: str) -> bytes:
        return "".join(json.dumps(line) + "\n" for line in self.lines).encode("utf-8")


def test_prepare_sends_one_request_per_text_and_decade_and_skips_the_scored_songs(data, tmp_path):
    plan = prepared(data, tmp_path)
    counts = plan["countries"]["TGO"]
    assert counts["songs"] == 6 and counts["eligible"] == 5 and counts["scored"] == 1
    assert counts["requests"] == 3 and counts["songs_to_score"] == 4
    folder = scoring_run.run_dir(data, "20260201T000000Z")
    lines = [
        json.loads(line)
        for line in (folder / "requests.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert {line["url"] for line in lines} == {PROMPT.settings["endpoint"]}
    assert any('"decade":"1970s"' in line["body"]["input"][0]["content"] for line in lines)
    groups = sorted(
        item["song_ids"] for item in scoring_run._read_lines(folder / "assignments.jsonl")
    )
    assert groups == [["s1", "s2"], ["s3"], ["s6"]]
    assert plan["estimate"]["usd"] > 0


def test_a_song_in_an_open_run_and_a_song_over_the_limit_wait(data, tmp_path):
    first = prepared(data, tmp_path, max_requests=1)
    assert first["countries"]["TGO"]["left_for_next_run"] == 3
    second = prepared(data, tmp_path, run_id="20260202T000000Z")
    assert second["countries"]["TGO"]["in_open_run"] == first["countries"]["TGO"]["songs_to_score"]
    assert second["requests"] == 2
    with pytest.raises(ValueError, match="max_requests"):
        prepared(data, tmp_path, max_requests=0)


def test_prepare_takes_only_the_songs_of_the_decades_asked(data, tmp_path):
    plan = prepared(data, tmp_path, decades=["1970s"])
    counts = plan["countries"]["TGO"]
    assert counts["requests"] == 1 and counts["songs_to_score"] == 1
    assert counts["other_decade"] == 3 and counts["scored"] == 1
    assert plan["decades"] == ["1970s"]
    with pytest.raises(ValueError, match="1980s"):
        prepared(data, tmp_path, decades=["1980"])


def test_submit_keeps_to_the_cost_limit_and_runs_one_time(data, tmp_path):
    plan = prepared(data, tmp_path)
    fake = FakeBatches()
    with pytest.raises(ValueError, match="above the limit"):
        scoring_run.submit(data, plan["run_id"], 0.0, fake)
    assert fake.calls == []
    batch = scoring_run.submit(data, plan["run_id"], 100.0, fake)
    assert batch["batch_id"] == "batch-1"
    assert fake.calls == [("upload", "requests.jsonl"), ("create", "file-1", "/v1/responses")]
    with pytest.raises(ValueError, match="submitted before"):
        scoring_run.submit(data, plan["run_id"], 100.0, fake)


def test_collect_writes_the_new_scores_over_the_old_ones_and_counts_each_failure(data, tmp_path):
    plan = prepared(data, tmp_path)
    run = plan["run_id"]
    items = scoring_run._read_lines(scoring_run.run_dir(data, run) / "assignments.jsonl")
    by_songs = {tuple(item["song_ids"]): item["custom_id"] for item in items}
    scoring_run.submit(data, run, 100.0, FakeBatches())
    assert scoring_run.collect(data, run, FakeBatches("in_progress")) == {
        "status": "in_progress",
        "written": [],
    }
    lines = [
        {"custom_id": by_songs[("s1", "s2")]} | answer(),
        {"custom_id": by_songs[("s6",)]} | answer("non_song", "unknown"),
        {"custom_id": by_songs[("s3",)]} | answer("non_song", "40"),
    ]
    result = scoring_run.collect(data, run, FakeBatches(lines=lines))
    counts = result["counts"]["TGO"]
    assert counts["requests"] == 3 and counts["answers"] == 2 and counts["bad_answer"] == 1
    folder = paths.latest_country_scores_dir(data, "TGO")
    assert result["written"] == [paths.data_relative(data, folder)]
    topics = schemas.read_table(schemas.SCORE_TOPICS, folder).order("song_id").fetchall()
    assert [(row[1], row[3]) for row in topics] == [("s1", 40), ("s2", 40), ("s5", 7), ("s6", None)]
    manifest = manifests.read_manifest(folder)
    assert manifest.counts["scores"] == 4 and manifest.counts["scores_carried"] == 1
    with pytest.raises(ValueError, match="collected"):
        scoring_run.collect(data, run, FakeBatches(lines=lines))
    again = prepared(data, tmp_path, run_id="20260203T000000Z")
    assert again["countries"]["TGO"]["scored"] == 4 and again["requests"] == 1


@pytest.mark.parametrize(
    ("record", "reason"),
    [
        ({"error": {"code": "x"}}, "request_error"),
        ({"response": {"status_code": 500}}, "http_error"),
        ({"response": {"status_code": 200, "body": {"status": "incomplete"}}}, "not_completed"),
        (answer("song_lyrics", "101"), "bad_answer"),
        (answer("song_lyrics", "unknown"), "bad_answer"),
        (answer("uncertain", "3"), "bad_answer"),
    ],
)
def test_read_answer_refuses_each_bad_line(record, reason):
    assert scoring_run.read_answer(record, MODEL) == (None, reason)


def test_read_answer_needs_the_model_and_the_field_order():
    good, _ = scoring_run.read_answer(answer("uncertain", "unknown"), MODEL)
    assert good == {"text_kind": "uncertain"} | dict.fromkeys(TOPIC_IDS)
    assert scoring_run.read_answer(answer(), "another-model")[1] == "bad_answer"
    record = answer()
    content = record["response"]["body"]["output"][0]["content"][0]
    song = json.loads(content["text"])["song"]
    content["text"] = json.dumps({"song": dict(reversed(list(song.items())))})
    assert tuple(song) == FIELD_ORDER
    assert scoring_run.read_answer(record, MODEL)[1] == "bad_answer"


def test_the_client_needs_an_api_key(monkeypatch):
    monkeypatch.delenv(scoring_run.API_KEY_ENV, raising=False)
    with pytest.raises(RuntimeError, match=scoring_run.API_KEY_ENV):
        scoring_run.OpenAIBatches(PROMPT.settings)


def test_submit_on_the_command_line_needs_the_run_id_typed(data, tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from songs import cli

    plan = prepared(data, tmp_path)
    monkeypatch.setenv(paths.DATA_ROOT_ENV, str(data))
    monkeypatch.delenv(scoring_run.API_KEY_ENV, raising=False)
    command = ["score", "submit", plan["run_id"], "--max-usd", "100"]
    result = CliRunner().invoke(cli.app, command, input="\n")
    assert result.exit_code == 1
    assert not (scoring_run.run_dir(data, plan["run_id"]) / scoring_run.STARTED_FILE).exists()


def test_prepare_copies_the_score_of_a_song_with_the_same_text_and_decade(tmp_path):
    data = tmp_path / "data"
    songs = [
        song("s5", lyrics_sha256=SHA["d"]),
        song("s7", lyrics_sha256=SHA["d"], year=1995),
        song("s8", lyrics_sha256=SHA["d"], year=1975),
    ]
    write_country(data, "TGO", songs, None)
    write_scores(data, [("s5", SHA["d"], PROMPT.sha256)])
    plan = prepared(data, tmp_path)
    counts = plan["countries"]["TGO"]
    assert counts["scored"] == 1 and counts["reused"] == 1 and counts["requests"] == 1
    folder = paths.latest_country_scores_dir(data, "TGO")
    assert plan["reused_written"] == [paths.data_relative(data, folder)]
    provenance = schemas.read_table(schemas.SCORE_PROVENANCE, folder)
    assert provenance.order("song_id").project("song_id, status").fetchall() == [
        ("s5", "complete"),
        ("s7", "reused"),
    ]
    topics = schemas.read_table(schemas.SCORE_TOPICS, folder).filter("song_id = 's7'")
    assert topics.project(f'"{TOPIC_IDS[0]}"').fetchall() == [(7,)]
    assert manifests.read_manifest(folder).counts["scores_reused"] == 1
    again = prepared(data, tmp_path, run_id="20260202T000000Z")
    assert again["countries"]["TGO"]["scored"] == 2 and again["countries"]["TGO"]["reused"] == 0
    assert again["countries"]["TGO"]["in_open_run"] == 1 and again["reused_written"] == []


def test_status_counts_the_eligible_songs_by_the_state_of_their_score(tmp_path):
    data = tmp_path / "data"
    songs = [
        song("s1", lyrics_sha256=SHA["a"]),
        song("s2", lyrics_sha256=SHA["b"]),
        song("s3", lyrics_sha256=SHA["c"]),
        song("s4", lyrics_sha256=SHA["d"]),
        song("s5", lyrics_sha256=SHA["e"], year=1800),
    ]
    write_country(data, "TGO", songs, None)
    write_scores(
        data,
        [
            ("s2", SHA["b"], PROMPT.sha256),
            ("s3", SHA["c"], "f" * 64),
            ("s4", SHA["e"], PROMPT.sha256),
        ],
    )
    prepared(data, tmp_path)
    counts = scoring_run.status(data, ["tgo"], rule_files=rule_files(tmp_path))
    assert counts == {
        "TGO": {
            "songs": 5,
            "eligible": 4,
            "scored": 1,
            "other_prompt": 1,
            "text_changed": 1,
            "not_scored": 1,
            "in_open_run": 3,
        }
    }
    page = scoring_run.render_status(counts)
    assert "| TGO | 5 | 4 | 1 | 25.0% | 1 | 1 | 1 | 3 |" in page
    assert "| All | 5 | 4 | 1 | 25.0% |" in page
    assert "No country has songs." in scoring_run.render_status({})
    assert scoring_run.status(data, ["ben"], rule_files=rule_files(tmp_path)) == {}


def test_status_counts_zero_for_a_country_with_no_eligible_songs(tmp_path):
    data = tmp_path / "data"
    write_country(data, "TGO", [song("s1", year=1800)], None)
    counts = scoring_run.status(data, rule_files=rule_files(tmp_path))
    assert counts["TGO"] == dict.fromkeys(scoring_run.STATUS_COUNTS, 0) | {"songs": 1}
    assert "| TGO | 1 | 0 | 0 | no eligible songs |" in scoring_run.render_status(counts)


def test_status_on_the_command_line_writes_the_page_only_for_all_countries():
    from typer.testing import CliRunner

    from songs import cli

    result = CliRunner().invoke(cli.app, ["score", "status", "TGO", "--write"])
    assert result.exit_code == 1 and "all countries" in result.output


def test_a_score_of_an_accepted_prompt_counts_as_scored_and_is_copied_with_its_hash(tmp_path):
    combined = next(iter(scoring_run.ACCEPTED_PROMPTS))
    data = tmp_path / "data"
    songs = [song("s5", lyrics_sha256=SHA["d"]), song("s7", lyrics_sha256=SHA["d"])]
    write_country(data, "TGO", songs, None)
    write_scores(data, [("s5", SHA["d"], combined)])
    assert scoring_run.status(data, ["tgo"], rule_files=rule_files(tmp_path))["TGO"]["scored"] == 1
    counts = prepared(data, tmp_path)["countries"]["TGO"]
    assert counts["scored"] == 1 and counts["reused"] == 1 and counts["requests"] == 0
    folder = paths.latest_country_scores_dir(data, "TGO")
    provenance = schemas.read_table(schemas.SCORE_PROVENANCE, folder).filter("song_id = 's7'")
    assert provenance.project("prompt_sha256, status").fetchall() == [(combined, "reused")]
