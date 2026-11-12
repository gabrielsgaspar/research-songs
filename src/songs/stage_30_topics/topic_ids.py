"""The single source for topic ids, labels, definitions, families and display order.

Labels and definitions are read from `resources/topics.toml`.

Run `python -m songs.stage_30_topics.topic_ids --write` to rebuild docs/standards/topics.md.
"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TOPICS_FILE = ROOT / "resources" / "topics.toml"
_FILE = tomllib.loads(TOPICS_FILE.read_text(encoding="utf-8"))

TOPICS_VERSION: str = _FILE["version"]
FAMILIES_VERSION = "topic-families-2026-09-15"

TOPIC_IDS: tuple[str, ...] = tuple(f"T{index:02d}" for index in range(1, 39))
if tuple(topic["id"] for topic in _FILE["topic"]) != TOPIC_IDS:
    raise ValueError("resources/topics.toml must hold T01 to T38, each one time, in order")

TOPIC_LABELS: dict[str, str] = {topic["id"]: topic["label"] for topic in _FILE["topic"]}
TOPIC_DEFINITIONS: dict[str, str] = {topic["id"]: topic["definition"] for topic in _FILE["topic"]}

FAMILY_LABELS: dict[str, str] = {
    "A": "Romantic love, desire & conflict",
    "B": "Inner life, meaning & mortality",
    "C": "Selfhood, agency & aspiration",
    "D": "Society, power & material life",
    "E": "Social bonds, community & cultural identity",
    "F": "Home, place, nature & everyday life",
    "G": "Pleasure, escape & excess",
}

# The order inside a family is the display order. T27 sits last in family G.
FAMILY_TOPIC_IDS: dict[str, tuple[str, ...]] = {
    "A": TOPIC_IDS[:6],
    "B": TOPIC_IDS[6:13],
    "C": TOPIC_IDS[13:20],
    "D": TOPIC_IDS[20:26],
    "E": TOPIC_IDS[27:31],
    "F": TOPIC_IDS[31:35],
    "G": (*TOPIC_IDS[35:38], "T27"),
}
FAMILY_BY_TOPIC_ID: dict[str, str] = {
    topic_id: family for family, topics in FAMILY_TOPIC_IDS.items() for topic_id in topics
}
TOPIC_DISPLAY_IDS: tuple[str, ...] = tuple(
    topic_id for topics in FAMILY_TOPIC_IDS.values() for topic_id in topics
)

TOPICS_PAGE = ROOT / "docs" / "standards" / "topics.md"


def render_topics_markdown() -> str:
    """Return the text of docs/standards/topics.md."""
    lines = [
        "# Topics",
        "",
        "This page is generated from `resources/topics.toml` (labels and definitions) and "
        "`src/songs/stage_30_topics/topic_ids.py` (families). Do not edit it by hand.",
        "",
        "To rebuild it, run `python -m songs.stage_30_topics.topic_ids --write`.",
        "",
        f"The topic list has version `{TOPICS_VERSION}`. The family map has version "
        f"`{FAMILIES_VERSION}`.",
        "",
        f"There are {len(TOPIC_IDS)} topics in {len(FAMILY_LABELS)} families. "
        "Topic ids keep their numeric order in the data. The tables show the display order.",
    ]
    for family, label in FAMILY_LABELS.items():
        lines += [
            "",
            f"## Family {family}: {label}",
            "",
            "| Id | Topic | Definition |",
            "| --- | --- | --- |",
        ]
        lines += [
            f"| {topic_id} | {TOPIC_LABELS[topic_id]} | {TOPIC_DEFINITIONS[topic_id]} |"
            for topic_id in FAMILY_TOPIC_IDS[family]
        ]
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    """Print the page, or write it with --write."""
    text = render_topics_markdown()
    if argv == ["--write"]:
        with TOPICS_PAGE.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
