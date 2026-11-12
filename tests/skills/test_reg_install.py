"""Check the reg-lp and reg-var installers without touching real personal skill folders."""

import importlib.util
from pathlib import Path

import pytest

SKILLS = Path(__file__).resolve().parents[2] / ".claude" / "skills"


def load_installer(skill: str):
    """Import the installer script of one skill by path."""
    spec = importlib.util.spec_from_file_location(
        f"installer_{skill.replace('-', '_')}", SKILLS / skill / "scripts" / "install.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_source(base: Path, text: str = "skill\n") -> Path:
    """Build a minimal skill bundle that the installer accepts."""
    source = base / "source" / "example-skill"
    source.mkdir(parents=True)
    (source / "SKILL.md").write_text(text, encoding="utf-8")
    (source / "renv.lock").write_text("{}\n", encoding="utf-8")
    return source


@pytest.mark.parametrize("skill", ["reg-lp", "reg-var"])
def test_exact_copy_and_repeat(tmp_path, skill):
    installer = load_installer(skill)
    source = make_source(tmp_path)
    destinations = [tmp_path / "one", tmp_path / "two"]
    installer.install(source, destinations)
    installer.install(source, destinations)
    installer.install(source, destinations, verify=True)
    for destination in destinations:
        assert installer.payload(destination / source.name) == installer.payload(source)


@pytest.mark.parametrize("skill", ["reg-lp", "reg-var"])
def test_unknown_files_abort_before_any_copy(tmp_path, skill):
    installer = load_installer(skill)
    source = make_source(tmp_path)
    protected = tmp_path / "second" / source.name
    protected.mkdir(parents=True)
    (protected / "personal.txt").write_text("keep\n", encoding="utf-8")
    with pytest.raises(ValueError):
        installer.install(source, [tmp_path / "first", tmp_path / "second"])
    assert not (tmp_path / "first").exists()
    assert (protected / "personal.txt").read_text(encoding="utf-8") == "keep\n"


@pytest.mark.parametrize("skill", ["reg-lp", "reg-var"])
def test_verify_detects_changed_file(tmp_path, skill):
    installer = load_installer(skill)
    source = make_source(tmp_path)
    installer.install(source, [tmp_path / "destination"])
    (tmp_path / "destination" / source.name / "SKILL.md").write_text("changed\n", encoding="utf-8")
    with pytest.raises(ValueError):
        installer.install(source, [tmp_path / "destination"], verify=True)
