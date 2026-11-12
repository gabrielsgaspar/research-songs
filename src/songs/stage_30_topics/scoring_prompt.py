"""The topics-only scoring prompt and the model settings, read from `prompts/scoring/`.

Decision 0005 fixes both. `load_scoring_prompt` refuses files that differ from the
ones that produced the stored scores, so a new score is comparable with an old one.
"""

import hashlib
import json
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from songs.common.paths import resolve_project_root
from songs.stage_30_topics.topic_ids import TOPIC_IDS, TOPIC_LABELS

SCORING_DIR = Path("prompts") / "scoring"
PROMPT_VERSION = "lyrics-topics-v1"
# The identity that every stored topics-only score records in `instrument_sha256`.
PROMPT_SHA256 = "c51d257f2d6be1f2117aee6e9684117ae61c693c8752517d8d4e36bcb30e4793"
FIELD_ORDER = ("text_kind", *TOPIC_IDS)
_DEFINITIONS_LOOP = "{% for key in field_order %}{{ key }}: {{ attributes[key] }}\n{% endfor %}"


@dataclass(frozen=True)
class ScoringPrompt:
    """Everything one scoring request needs, already checked against the pinned identity."""

    settings: dict[str, Any]
    attributes: dict[str, str]
    instructions: str
    template: str
    schema: dict[str, Any]
    sha256: str

    def render(self, country: str, decade: str | None, lyrics: str) -> str:
        """Return the exact prompt text for one song."""
        source = json.dumps(
            {"country": country.upper(), "decade": decade, "lyrics": lyrics},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        definitions = "".join(f"{key}: {self.attributes[key]}\n" for key in FIELD_ORDER)
        # shortcut: three literal replacements stand in for jinja2, which is not a dependency.
        # A test pins the result against a jinja2 render; use jinja2 if the template gains logic.
        # The song text goes in last, so nothing in it is replaced.
        return (
            self.template.replace(_DEFINITIONS_LOOP, definitions)
            .replace("{{ additional_instructions }}", self.instructions)
            .replace("{{ text }}", source)
        )

    def request_body(self, prompt: str) -> dict[str, Any]:
        """Return the body of one OpenAI Responses API request."""
        return {
            "model": self.settings["model"],
            "input": [{"role": "user", "content": prompt}],
            "reasoning": {"effort": self.settings["reasoning_effort"]},
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": self.settings["answer_format_name"],
                    "strict": True,
                    "schema": self.schema,
                }
            },
            "truncation": self.settings["truncation"],
            "store": self.settings["store"],
            "prompt_cache_key": f"songs-{self.sha256[:58]}",
        }


def _answer_schema() -> dict[str, Any]:
    """A song is lyrics with 38 scores from 0 to 100, or not lyrics with 38 times "unknown"."""

    def song(kinds: list[str], score: str) -> dict[str, Any]:
        properties: dict[str, Any] = {"text_kind": {"type": "string", "enum": kinds}}
        properties |= {topic: {"$ref": f"#/$defs/{score}"} for topic in TOPIC_IDS}
        return {
            "type": "object",
            "properties": properties,
            "required": list(FIELD_ORDER),
            "additionalProperties": False,
        }

    return {
        "type": "object",
        "properties": {
            "song": {
                "anyOf": [
                    song(["song_lyrics"], "numeric_topic_score"),
                    song(["non_song", "uncertain"], "unknown_string"),
                ]
            }
        },
        "required": ["song"],
        "additionalProperties": False,
        "$defs": {
            "numeric_topic_score": {"type": "string", "enum": [str(n) for n in range(101)]},
            "unknown_string": {"type": "string", "enum": ["unknown"]},
        },
    }


def load_scoring_prompt(root: Path | None = None) -> ScoringPrompt:
    """Read the model settings and the prompt. Raise ValueError if either one changed."""
    folder = resolve_project_root(root) / SCORING_DIR
    settings = tomllib.loads((folder / "model.toml").read_text(encoding="utf-8"))
    topics = folder / "topics"
    definitions = json.loads((topics / "definitions.json").read_text(encoding="utf-8"))
    if tuple(definitions) != FIELD_ORDER:
        raise ValueError("definitions.json must hold text_kind and then every topic id, in order")
    attributes = {"text_kind": definitions["text_kind"]} | {
        topic: f"{TOPIC_LABELS[topic]}: {definitions[topic]}" for topic in TOPIC_IDS
    }
    instructions = (topics / "instructions.txt").read_text(encoding="utf-8").removesuffix("\n")
    template = (topics / "template.jinja2").read_text(encoding="utf-8").removesuffix("\n")
    schema = _answer_schema()
    identity = {
        "instrument_version": PROMPT_VERSION,
        "model": settings["model"],
        "reasoning_effort": settings["reasoning_effort"],
        "field_order": FIELD_ORDER,
        "attributes": attributes,
        "additional_instructions": instructions,
        "response_schema": schema,
        "extract_template": template,
    }
    encoded = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    sha256 = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    if sha256 != PROMPT_SHA256:
        raise ValueError(
            f"The scoring prompt or model changed: its hash is {sha256}, not {PROMPT_SHA256}. "
            "The cause is an edit in prompts/scoring/ or to a topic label. "
            "A change needs a new decision (see decision 0005)."
        )
    return ScoringPrompt(settings, attributes, instructions, template, schema, sha256)
