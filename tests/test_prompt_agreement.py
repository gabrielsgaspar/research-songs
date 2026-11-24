"""The agreement of two prompts on invented songs. No test calls a model."""

from pathlib import Path

import pytest
from test_release import frame, song, write_country

from songs.common import manifests, paths, schemas
from songs.stage_30_topics import prompt_agreement
from songs.stage_30_topics.scoring_prompt import load_scoring_prompt
from songs.stage_30_topics.topic_ids import TOPIC_IDS

PROMPT = load_scoring_prompt()
MODEL = PROMPT.settings["model"]
OTHER = "f" * 64
SHA = {name: name * 64 for name in "abcde"}
RUN = "20260102T000000Z"


def write_scores(data: Path, rows: list[tuple[str, str, str, str, int | None]]) -> None:
    """One scores folder; each row is (song id, lyrics hash, prompt hash, text kind, T01)."""
    folder = paths.country_scores_dir(data, "TGO", RUN)
    folder.mkdir(parents=True)
    topics = [
        {"country_iso3": "TGO", "song_id": s, "lyrics_sha256": h, TOPIC_IDS[0]: t01}
        for s, h, _, _, t01 in rows
    ]
    provenance = [
        {
            "country_iso3": "TGO",
            "song_id": s,
            "lyrics_sha256": h,
            "prompt_sha256": p,
            "model": MODEL,
            "text_kind": kind,
            "status": "complete",
        }
        for s, h, p, kind, _ in rows
    ]
    schemas.write_table(schemas.SCORE_TOPICS, frame(schemas.SCORE_TOPICS, topics), folder)
    schemas.write_table(
        schemas.SCORE_PROVENANCE, frame(schemas.SCORE_PROVENANCE, provenance), folder
    )
    manifests.write_manifest(
        data, folder, "country_scores", country_iso3="TGO", run_id=RUN, inputs=["y/"]
    )


@pytest.fixture
def data(tmp_path):
    """Two pairs (a, b), one text of two decades (c), one text with no pair (d), one change."""
    data = tmp_path / "data"
    songs = [
        song("s1", lyrics_sha256=SHA["a"]),
        song("s2", lyrics_sha256=SHA["a"]),
        song("s3", lyrics_sha256=SHA["b"]),
        song("s4", lyrics_sha256=SHA["b"]),
        song("s5", lyrics_sha256=SHA["c"], year=1975),
        song("s6", lyrics_sha256=SHA["c"]),
        song("s7", lyrics_sha256=SHA["d"]),
        song("s8", lyrics_sha256=SHA["e"]),
    ]
    write_country(data, "TGO", songs, None)
    write_scores(
        data,
        [
            ("s1", SHA["a"], PROMPT.sha256, "song_lyrics", 40),
            ("s2", SHA["a"], OTHER, "song_lyrics", 50),
            ("s3", SHA["b"], PROMPT.sha256, "song_lyrics", 60),
            ("s4", SHA["b"], OTHER, "non_song", 80),
            ("s5", SHA["c"], PROMPT.sha256, "song_lyrics", 10),
            ("s6", SHA["c"], OTHER, "song_lyrics", 90),
            ("s7", SHA["d"], OTHER, "song_lyrics", 30),
            ("s8", SHA["a"], OTHER, "song_lyrics", 99),
        ],
    )
    return data


def test_pairs_need_the_same_text_and_decade(data):
    result = prompt_agreement.agreement(data)
    assert result["counts"] == {
        "scores": 8,
        "scores_text_changed": 1,
        "texts_current": 3,
        "texts_other": 4,
    }
    (other,) = result["others"].values()
    assert other["prompt_sha256"] == OTHER and other["pairs"] == 2
    assert other["same_text_kind"] == 0.5
    first = other["topics"][TOPIC_IDS[0]]
    assert first["pairs"] == 2 and first["mean_diff"] == -15 and first["mean_abs"] == 15
    assert first["pearson"] == pytest.approx(1.0)
    assert other["topics"][TOPIC_IDS[1]]["pairs"] == 0


def test_the_page_shows_each_topic_and_says_when_no_pair_exists(data, tmp_path):
    page = prompt_agreement.render_agreement(prompt_agreement.agreement(data))
    assert "| T01 |" in page and "| -15.00 |" in page and "Same `text_kind`: 50.0%" in page
    empty = prompt_agreement.agreement(tmp_path / "nothing")
    assert "No pair has a score" in prompt_agreement.render_agreement(empty)
