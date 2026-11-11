"""Check portable installation without changing real personal skill folders."""

import importlib.util
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "install.py"
SPEC = importlib.util.spec_from_file_location("skill_installer", SCRIPT)
INSTALLER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(INSTALLER)


class InstallTests(unittest.TestCase):
    """Exercise installation, repeatability, verification, and preflight failure."""

    def test_exact_copy_and_repeat(self):
        """Install and verify the same files twice."""
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source = base / "source" / "example-skill"
            source.mkdir(parents=True)
            (source / "SKILL.md").write_text("name: example-skill\n", encoding="utf-8")
            (source / "renv.lock").write_text("{}\n", encoding="utf-8")
            destinations = [base / "cursor", base / "codex"]
            INSTALLER.install(source, destinations)
            INSTALLER.install(source, destinations)
            INSTALLER.install(source, destinations, verify=True)
            for destination in destinations:
                self.assertEqual(
                    INSTALLER.payload(destination / source.name), INSTALLER.payload(source)
                )

    def test_unknown_files_abort_before_any_copy(self):
        """Preserve existing files when any destination has unrelated contents."""
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source = base / "source" / "example-skill"
            source.mkdir(parents=True)
            (source / "SKILL.md").write_text("skill\n", encoding="utf-8")
            (source / "renv.lock").write_text("{}\n", encoding="utf-8")
            protected = base / "second" / source.name
            protected.mkdir(parents=True)
            (protected / "personal.txt").write_text("keep\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                INSTALLER.install(source, [base / "first", base / "second"])
            self.assertFalse((base / "first").exists())
            self.assertEqual((protected / "personal.txt").read_text(encoding="utf-8"), "keep\n")

    def test_verify_detects_changed_file(self):
        """Reject an edited installed bundle during verification."""
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source = base / "source" / "example-skill"
            source.mkdir(parents=True)
            (source / "SKILL.md").write_text("skill\n", encoding="utf-8")
            (source / "renv.lock").write_text("{}\n", encoding="utf-8")
            INSTALLER.install(source, [base / "destination"])
            (base / "destination" / source.name / "SKILL.md").write_text(
                "changed\n", encoding="utf-8"
            )
            with self.assertRaises(ValueError):
                INSTALLER.install(source, [base / "destination"], verify=True)


if __name__ == "__main__":
    unittest.main()
