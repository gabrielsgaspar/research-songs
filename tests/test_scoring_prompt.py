import hashlib
import shutil

import pytest

from songs.stage_30_topics import scoring_prompt as s
from songs.stage_30_topics.topic_ids import TOPIC_IDS

# Invented text. The braces check that song text is never read as template code.
INVENTED = "Invented line {{ text }} {% x %}\nação, 2nd line"
# The hash of the prompt that jinja2 renders from the same template and inputs.
JINJA2_PROMPT_SHA256 = "74bee85cf3c72fdd5475561836b47279a2576516e6385018a667c664641a7045"


def test_the_prompt_is_the_one_that_scored_the_stored_songs():
    prompt = s.load_scoring_prompt()
    assert prompt.sha256 == s.PROMPT_SHA256
    assert tuple(prompt.attributes) == ("text_kind", *TOPIC_IDS)
    text = prompt.render("bra", "1990s", INVENTED)
    assert hashlib.sha256(text.encode("utf-8")).hexdigest() == JINJA2_PROMPT_SHA256


def test_the_request_names_the_fixed_model_and_no_sampling_settings():
    prompt = s.load_scoring_prompt()
    body = prompt.request_body("x")
    assert (body["model"], body["reasoning"]) == ("gpt-5.6-luna", {"effort": "medium"})
    assert body["text"]["format"]["strict"] is True
    assert body["store"] is False
    assert not {"temperature", "seed"} & set(body)


@pytest.mark.parametrize(
    ("file", "old", "new"),
    [
        ("model.toml", 'reasoning_effort = "medium"', 'reasoning_effort = "high"'),
        ("model.toml", 'model = "gpt-5.6-luna"', 'model = "another-model"'),
        ("topics/instructions.txt", "Use the full integer scale.", "Use the scale."),
        ("topics/definitions.json", "Mutual, fulfilling", "Fulfilling"),
        ("topics/template.jinja2", "Return datapoints only.", "Return data only."),
    ],
)
def test_a_changed_file_is_refused(tmp_path, file, old, new):
    root = s.resolve_project_root()
    shutil.copytree(root / s.SCORING_DIR, tmp_path / s.SCORING_DIR)
    shutil.copy(root / "pyproject.toml", tmp_path / "pyproject.toml")
    path = tmp_path / s.SCORING_DIR / file
    text = path.read_text(encoding="utf-8")
    assert text.count(old) == 1
    path.write_text(text.replace(old, new), encoding="utf-8")
    with pytest.raises(ValueError, match="changed"):
        s.load_scoring_prompt(tmp_path)
