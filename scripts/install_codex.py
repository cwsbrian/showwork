#!/usr/bin/env python3
"""Install Showwork for the current user, or an explicitly selected project."""

import argparse
import os
from pathlib import Path
import shutil
import tempfile


SKILLS = ("showwork", "showwork-plan", "showwork-review", "showwork-verify")
SOURCE = Path(__file__).resolve().parents[1] / "skills"
TEMPLATE = SOURCE.parent / "instructions" / "automatic.md"
START = "<!-- showwork:automatic:start -->"
END = "<!-- showwork:automatic:end -->"


def project_instructions(target, skills_root=".agents/skills"):
    # Codex uses an override instead of AGENTS.md when both exist at this level.
    override = target / "AGENTS.override.md"
    if override.is_symlink() or (override.exists() and not override.is_file()):
        raise ValueError(f"Expected a real instruction file: {override}")
    # Filling an empty override would hide the previously active AGENTS.md.
    path = override if override.is_file() and override.read_bytes().strip() else target / "AGENTS.md"
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ValueError(f"Expected a real instruction file: {path}")
    before = path.read_bytes().decode("utf-8") if path.exists() else ""
    newline = "\r\n" if "\r\n" in before else "\n"
    guidance = TEMPLATE.read_text(encoding="utf-8").replace("{{SKILLS_ROOT}}", skills_root).strip()
    block = f"{START}\n{guidance}\n{END}".replace("\n", newline)
    if START in before or END in before:
        if before.count(START) != 1 or before.count(END) != 1 or before.index(START) > before.index(END):
            raise ValueError(f"Malformed Showwork markers in {path}; no existing files were changed")
        start, end = before.index(START), before.index(END) + len(END)
        after = before[:start] + block + before[end:]
    else:
        separator = "" if not before else (newline if before.endswith("\n") else newline * 2)
        after = before + separator + block + newline
    return path, before, after


def write_instructions(path, content):
    fd, temporary = tempfile.mkstemp(prefix=".showwork-instructions-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content.encode("utf-8"))
        if path.exists():
            os.chmod(temporary, path.stat().st_mode & 0o777)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def contents(directory):
    """Compare bytes and empty directories; never follow links outside the bundle."""
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError(f"Expected a real directory: {directory}")
    entries = {}
    for path in directory.rglob("*"):
        if "__pycache__" in path.relative_to(directory).parts or path.suffix in {".pyc", ".pyo"}:
            continue
        if path.is_symlink():
            raise ValueError(f"Refusing symbolic link: {path}")
        if not path.is_dir() and not path.is_file():
            raise ValueError(f"Refusing special file: {path}")
        entries[path.relative_to(directory)] = None if path.is_dir() else path.read_bytes()
    return entries


def install(target=None, source=SOURCE):
    user_install = target is None
    target = (Path.home() if user_install else Path(target)).expanduser().resolve(strict=True)
    if not target.is_dir():
        raise ValueError(f"Target must be an existing project directory: {target}")
    destination = target / ".agents" / "skills"
    instruction_directory = (
        Path(os.environ.get("CODEX_HOME") or target / ".codex").expanduser().absolute()
        if user_install else target
    )
    for path in (target / ".agents", destination, instruction_directory, *instruction_directory.parents):
        if path.is_symlink() or (path.exists() and not path.is_dir()):
            raise ValueError(f"Expected a real directory: {path}")
    instruction_path, before, after = project_instructions(
        instruction_directory, destination.as_posix() if user_install else ".agents/skills"
    )

    pending = []
    for name in SKILLS:
        bundled = source / name
        expected = contents(bundled)
        if Path("SKILL.md") not in expected or expected[Path("SKILL.md")] is None:
            raise ValueError(f"Missing SKILL.md: {bundled}")
        installed = destination / name
        if installed.exists() or installed.is_symlink():
            if contents(installed) != expected:
                raise ValueError(
                    f"Existing install differs: {installed}. "
                    "Back up or move the four Showwork skill directories before reinstalling. "
                    "No existing files were changed."
                )
        else:
            pending.append(name)

    instruction_directory.mkdir(parents=True, exist_ok=True)
    if pending:
        destination.mkdir(parents=True, exist_ok=True)
        for name in pending:
            # copytree refuses an existing target; it never merges user files.
            shutil.copytree(source / name, destination / name,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"))
    if before != after:
        write_instructions(instruction_path, after)
    return len(pending)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument("--target", type=Path, help="Install in this existing project instead of for the user")
    scope.add_argument("--user", action="store_true", help="Install for the current user (default)")
    args = parser.parse_args()
    try:
        count = install(args.target)
    except (OSError, ValueError) as error:
        parser.exit(1, f"showwork: {error}\n")
    scope_name = "project" if args.target is not None else "user"
    print(f"Copied {count} Showwork skills; automatic routing is configured in {scope_name} instructions.")
    print("Start a new Codex session and describe your task normally.")


if __name__ == "__main__":
    main()
