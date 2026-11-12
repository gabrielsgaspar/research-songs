"""The agent role files, their loader, and the three workflows that use them."""

import importlib.util
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
WORKFLOWS = REPO / ".github" / "workflows"
LOADER = REPO / "src" / "songs" / "common" / "roles.py"

# Loaded from its file, the way the workflows run it: without the `songs` package.
spec = importlib.util.spec_from_file_location("roles_loader", LOADER)
roles = importlib.util.module_from_spec(spec)
spec.loader.exec_module(roles)

GOOD = """---
role: planner
model: claude-opus-5-5
max_turns: 40
workflow: .github/workflows/agent-plan.yml
notes:
  - A note.
---

The prompt.
"""


@pytest.mark.parametrize("role", sorted(roles.WORKFLOWS))
def test_role_file_loads_and_its_workflow_uses_it(role: str) -> None:
    fields = roles.load(role)
    assert "DATA, not instructions" in fields["prompt"]
    workflow = (REPO / fields["workflow"]).read_text(encoding="utf-8")
    assert f"python3 -I src/songs/common/roles.py {role}" in workflow
    assert "--model ${{ steps.role.outputs.model }}" in workflow
    assert "prompt: ${{ steps.role.outputs.prompt }}" in workflow


def test_parse_reads_front_matter_and_body() -> None:
    fields = roles.parse(GOOD, "planner")
    assert fields["model"] == "claude-opus-5-5"
    assert fields["max_turns"] == "40"
    assert fields["notes"] == ["A note."]
    assert fields["prompt"] == "The prompt.\n"


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("role: planner", "role: builder"),
        ("model: claude-opus-5-5", "model: claude-opus-5-5 --dangerous"),
        ("max_turns: 40", "max_turns: 4000"),
        ("workflow: .github/workflows/agent-plan.yml", "workflow: other.yml"),
        ("notes:", "extra: 1\nnotes:"),
        ("The prompt.\n", ""),
    ],
)
def test_parse_refuses_a_bad_role_file(old: str, new: str) -> None:
    with pytest.raises(roles.RoleError):
        roles.parse(GOOD.replace(old, new), "planner")


def test_outputs_keep_the_prompt_inside_a_random_delimiter() -> None:
    text = roles.outputs(roles.parse(GOOD, "planner"))
    delimiter = re.search(r"prompt<<(ROLE_PROMPT_[0-9a-f]{32})\n", text).group(1)
    assert text.endswith(f"The prompt.\n\n{delimiter}\n")


def test_the_three_workflows_protect_the_same_paths() -> None:
    lists = set()
    for name in ("agent-plan.yml", "agent-build.yml", "agent-review.yml"):
        text = (WORKFLOWS / name).read_text(encoding="utf-8")
        found = re.findall(r"PROTECTED_(?:DIRS|FILES) = \(.*\)", text)
        assert len(found) == 2, name
        lists.add(tuple(found))
    assert len(lists) == 1


def test_no_agent_workflow_merges_or_trusts_every_bot() -> None:
    for path in WORKFLOWS.glob("agent-*.yml"):
        text = path.read_text(encoding="utf-8")
        assert "pr merge" not in text, path.name
        assert "id-token" not in re.sub(r"#.*", "", text), path.name
        assert not re.search(r"allowed_bots:\s*['\"]?\*", text), path.name
        assert "pull_request_target" not in re.sub(r"#.*", "", text), path.name
