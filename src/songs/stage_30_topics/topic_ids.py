"""The single source for topic ids, short labels, families and display order.

Run `python -m songs.stage_30_topics.topic_ids --write` to rebuild docs/standards/topics.md.
"""

from __future__ import annotations

import sys
from pathlib import Path

TOPICS_VERSION = "topics-v3.0"
FAMILIES_VERSION = "topic-families-2026-09-15"

TOPIC_IDS: tuple[str, ...] = tuple(f"T{index:02d}" for index in range(1, 39))

TOPIC_LABELS: dict[str, str] = {
    "T01": "Romantic love & devotion",
    "T02": "Romantic longing & separation",
    "T03": "Heartbreak & separation",
    "T04": "Unrequited & hidden love",
    "T05": "Desire & casual relationships",
    "T06": "Betrayal, conflict & dysfunction",
    "T07": "Nostalgia & memory",
    "T08": "Loneliness & isolation",
    "T09": "Personal struggle & emotional pain",
    "T10": "Existential reflection & uncertainty",
    "T11": "Death & mortality",
    "T12": "Grief & mourning",
    "T13": "Religious faith & spirituality",
    "T14": "Resilience & hope",
    "T15": "Personal identity & self-discovery",
    "T16": "Personal freedom & empowerment",
    "T17": "Ambition, dreams & aspiration",
    "T18": "Self-confidence & bravado",
    "T19": "Artistic expression & creativity",
    "T20": "Rebellion & defiance",
    "T21": "Social injustice & inequality",
    "T22": "Political dissent & resistance",
    "T23": "Social criticism & corruption",
    "T24": "War, violence & conflict",
    "T25": "Poverty & hardship",
    "T26": "Urban street life & crime",
    "T27": "Wealth, status & fame",
    "T28": "Family bonds",
    "T29": "Friendship & companionship",
    "T30": "Community, peace & solidarity",
    "T31": "Cultural & national identity",
    "T32": "Migration, exile & homesickness",
    "T33": "Nature & landscape",
    "T34": "Everyday life & simple living",
    "T35": "Environmental concern",
    "T36": "Partying & celebration",
    "T37": "Escapism & fantasy",
    "T38": "Substance use & addiction",
}

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

TOPICS_PAGE = Path(__file__).resolve().parents[3] / "docs" / "standards" / "topics.md"


def render_topics_markdown() -> str:
    """Return the text of docs/standards/topics.md."""
    lines = [
        "# Topics",
        "",
        "This page is generated from `src/songs/stage_30_topics/topic_ids.py`. "
        "Do not edit it by hand.",
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
        lines += ["", f"## Family {family}: {label}", "", "| Id | Topic |", "| --- | --- |"]
        lines += [
            f"| {topic_id} | {TOPIC_LABELS[topic_id]} |" for topic_id in FAMILY_TOPIC_IDS[family]
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
