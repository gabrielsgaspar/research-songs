"""Install or verify an exact copy of this portable skill bundle."""

import argparse
import hashlib
import os
from pathlib import Path


def payload(root):
    """Return the skill files, excluding generated interpreter caches."""
    return {
        path.relative_to(root): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
        and "__pycache__" not in path.parts
        and path.suffix != ".pyc"
        and path.name not in (".Rhistory", ".RData")
    }


def install(source, destinations, verify=False):
    """Copy files without deleting existing files and verify every file hash."""
    files = payload(source)
    if Path("SKILL.md") not in files or Path("renv.lock") not in files:
        raise ValueError("The bundle needs SKILL.md and renv.lock.")
    targets = [root.expanduser().resolve() / source.name for root in destinations]
    for target in targets:
        if target == source:
            continue
        existing = payload(target) if target.exists() else {}
        unexpected = set(existing) - set(files)
        if unexpected:
            raise ValueError(
                f"Destination contains unrelated files: {target}: {sorted(map(str, unexpected))}"
            )
        if verify and existing != files:
            raise ValueError(f"Installed files differ: {target}")
    for target in targets:
        if not verify and target != source:
            for relative, data in files.items():
                path = target / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                if not path.exists() or path.read_bytes() != data:
                    temporary = path.with_name(path.name + ".install-tmp")
                    temporary.write_bytes(data)
                    os.replace(temporary, path)
        actual = payload(target)
        if actual != files:
            raise RuntimeError(f"Installation verification failed: {target}")
        digest = hashlib.sha256(
            b"".join(
                str(path).encode() + hashlib.sha256(data).digest()
                for path, data in sorted(files.items())
            )
        ).hexdigest()
        print(f"Verified {target} ({len(files)} files; {digest})")


def main():
    """Install to personal app folders or check existing installations."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--roots", type=Path, nargs="+", help="Skill parent folders.")
    args = parser.parse_args()
    roots = args.roots or [
        Path.home() / name / "skills" for name in (".cursor", ".claude", ".agents", ".codex")
    ]
    install(Path(__file__).resolve().parents[1], roots, args.verify)


if __name__ == "__main__":
    main()
