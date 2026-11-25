"""How well the topic scores of the current prompt agree with the scores of another prompt.

The request of a song holds only its country, decade and lyric text. Two songs of one
country with the same text and decade get the same request. When one of them has a score
from the current prompt and model and the other a score from another prompt or model,
the pair measures the agreement of the two at no cost.

`agreement` reads the newest songs folder and the newest scores folder of each country.
It keeps a score only when its song still has the scored text, because the decade comes
from the song. For each prompt and model, it keeps one score of each (country, text,
decade): the score of the lowest song id. Then it pairs the current score with each
other score of the same (country, text, decade).

For each other prompt it reports the pairs, the share of pairs with the same `text_kind`,
and, for each topic with a score on both sides, the Pearson correlation, the mean
difference (current minus other) and the mean absolute difference, in points from 0 to 100.
`write_agreement` writes these numbers to `docs/status/prompt_agreement.md`.
"""

from pathlib import Path
from typing import Any

import duckdb

from songs.common import schemas
from songs.common.paths import resolve_project_root
from songs.stage_30_topics.scoring_prompt import load_scoring_prompt
from songs.stage_30_topics.topic_ids import TOPIC_IDS, TOPIC_LABELS
from songs.stage_50_analysis import release

AGREEMENT_PAGE = Path("docs") / "status" / "prompt_agreement.md"
AGREEMENT_COMMAND = "uv run songs score agreement --write"
COUNT_NAMES = ("scores", "scores_text_changed", "texts_current", "texts_other")

_PAIRS = f"""
WITH s AS (
    SELECT p.prompt_sha256, p.model, p.song_id, p.lyrics_sha256, p.text_kind,
        coalesce(floor(c.year / 10)::INTEGER, -1) AS decade,
        {", ".join(f"t.{topic}" for topic in TOPIC_IDS)}
    FROM p
    JOIN t USING (song_id)
    JOIN c ON c.song_id = p.song_id AND c.lyrics_sha256 = p.lyrics_sha256
), one AS (
    SELECT *, (prompt_sha256 = $prompt AND model = $model) AS current FROM s
    QUALIFY row_number() OVER (
        PARTITION BY prompt_sha256, model, lyrics_sha256, decade ORDER BY song_id
    ) = 1
)
SELECT o.prompt_sha256, o.model, n.text_kind = o.text_kind AS same_kind,
    {", ".join(f"n.{topic} AS new_{topic}, o.{topic} AS old_{topic}" for topic in TOPIC_IDS)}
FROM one AS n JOIN one AS o USING (lyrics_sha256, decade)
WHERE n.current AND NOT o.current
"""


def agreement(data: Path, root: Path | None = None) -> dict[str, Any]:
    """Return the counts and, for each other prompt and model, the agreement of the scores.

    The counts: `scores` read, `scores_text_changed` left out because their song has
    other text now, and `texts_current` and `texts_other`, the (country, text, decade)
    keys with a score from the current prompt and from another prompt.
    """
    prompt = load_scoring_prompt(root)
    connection = duckdb.connect()
    new_old = ", ".join(f"new_{topic} INTEGER, old_{topic} INTEGER" for topic in TOPIC_IDS)
    connection.execute(
        f"CREATE TABLE pairs (prompt_sha256 VARCHAR, model VARCHAR, same_kind BOOLEAN, {new_old})"
    )
    counts = dict.fromkeys(COUNT_NAMES, 0)
    for _, songs_folder, scores_folder in release.country_folders(data):
        if scores_folder is None:
            continue
        schemas.read_table(schemas.COUNTRY_SONGS, songs_folder, connection).project(
            "song_id, lyrics_sha256, year"
        ).to_view("c")
        schemas.read_table(schemas.SCORE_PROVENANCE, scores_folder, connection).to_view("p")
        schemas.read_table(schemas.SCORE_TOPICS, scores_folder, connection).to_view("t")
        row = connection.execute(
            """SELECT count(*), count(*) FILTER (WHERE c.song_id IS NULL),
                count(DISTINCT (p.lyrics_sha256, coalesce(floor(c.year / 10)::INTEGER, -1)))
                    FILTER (WHERE c.song_id IS NOT NULL AND p.prompt_sha256 = $prompt
                        AND p.model = $model),
                count(DISTINCT (p.lyrics_sha256, coalesce(floor(c.year / 10)::INTEGER, -1)))
                    FILTER (WHERE c.song_id IS NOT NULL AND NOT (p.prompt_sha256 = $prompt
                        AND p.model = $model))
            FROM p LEFT JOIN c ON c.song_id = p.song_id AND c.lyrics_sha256 = p.lyrics_sha256""",
            {"prompt": prompt.sha256, "model": prompt.settings["model"]},
        ).fetchall()[0]
        for name, value in zip(COUNT_NAMES, row, strict=True):
            counts[name] += value
        connection.execute(
            f"INSERT INTO pairs {_PAIRS}",
            {"prompt": prompt.sha256, "model": prompt.settings["model"]},
        )
    others = {}
    for sha, model, pairs, same in connection.execute(
        "SELECT prompt_sha256, model, count(*), avg(same_kind::INTEGER) FROM pairs "
        "GROUP BY ALL ORDER BY 3 DESC, 1, 2"
    ).fetchall():
        topics = {}
        for topic in TOPIC_IDS:
            new, old = f"new_{topic}", f"old_{topic}"
            n, pearson, mean, absolute = connection.execute(
                f"SELECT count({new} - {old}), corr({new}, {old}), avg({new} - {old}), "
                f"avg(abs({new} - {old})) FROM pairs WHERE prompt_sha256 = ? AND model = ?",
                [sha, model],
            ).fetchall()[0]
            topics[topic] = {"pairs": n, "pearson": pearson, "mean_diff": mean}
            topics[topic]["mean_abs"] = absolute
        others[f"{sha}|{model}"] = {
            "prompt_sha256": sha,
            "model": model,
            "pairs": pairs,
            "same_text_kind": same,
            "topics": topics,
        }
    return {
        "prompt_sha256": prompt.sha256,
        "model": prompt.settings["model"],
        "counts": counts,
        "others": others,
    }


def _number(value: float | None, digits: int, sign: bool = False) -> str:
    if value is None:
        return "none"
    return f"{value:+.{digits}f}" if sign else f"{value:.{digits}f}"


def render_agreement(result: dict[str, Any]) -> str:
    """Return the agreement page: the counts, then one table for each other prompt."""
    counts = result["counts"]
    lines = [
        "# Agreement of the scoring prompts",
        "",
        f"Generated from the data folder by `{AGREEMENT_COMMAND}`. Do not edit by hand.",
        "",
        f"The current prompt has the hash `{result['prompt_sha256'][:12]}` and the model is "
        f"`{result['model']}`. A pair is two songs of one country with the same lyric text "
        "and decade: one has a score from the current prompt and model, the other a score "
        "from another prompt or model. Both got the same request. Differences are the "
        "current score minus the other score, in points from 0 to 100.",
        "",
        f"- Scores read: {counts['scores']}",
        f"- Scores left out because the song has other text now: {counts['scores_text_changed']}",
        f"- Texts (country, text, decade) with a current score: {counts['texts_current']}",
        f"- Texts (country, text, decade) with another score: {counts['texts_other']}",
        "",
    ]
    if not result["others"]:
        return "\n".join([*lines, "No pair has a score from another prompt.", ""])
    for other in result["others"].values():
        lines += [
            f"## Prompt `{other['prompt_sha256'][:12]}`, model `{other['model']}`",
            "",
            f"Pairs: {other['pairs']}. Same `text_kind`: "
            f"{100 * other['same_text_kind']:.1f}% of the pairs.",
            "",
            "| Topic | Label | Pairs | Pearson | Mean difference | Mean absolute difference |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        for topic, row in other["topics"].items():
            lines.append(
                f"| {topic} | {TOPIC_LABELS[topic]} | {row['pairs']} "
                f"| {_number(row['pearson'], 3)} | {_number(row['mean_diff'], 2, sign=True)} "
                f"| {_number(row['mean_abs'], 2)} |"
            )
        lines.append("")
    return "\n".join(lines)


def write_agreement(data: Path, root: Path | None = None) -> Path:
    """Write the agreement page to `docs/status/prompt_agreement.md` and return its path."""
    path = resolve_project_root(root) / AGREEMENT_PAGE
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(render_agreement(agreement(data, root)))
    return path
