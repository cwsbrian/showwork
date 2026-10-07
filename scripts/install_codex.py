#!/usr/bin/env python3
"""Install Showwork for the current user, or an explicitly selected project."""

import argparse
import json
import os
from pathlib import Path
import shutil
import tempfile


SKILLS = ("showwork", "showwork-plan", "showwork-review", "showwork-verify")
SOURCE = Path(__file__).resolve().parents[1] / "skills"
TEMPLATE = SOURCE.parent / "instructions" / "automatic.md"
START = "<!-- showwork:automatic:start -->"
END = "<!-- showwork:automatic:end -->"


def project_instructions(target, skills_root=".agents/skills", runtime="codex"):
    # Codex uses an override instead of AGENTS.md when both exist at this level.
    override = target / "AGENTS.override.md"
    if runtime == "codex" and (override.is_symlink() or (override.exists() and not override.is_file())):
        raise ValueError(f"Expected a real instruction file: {override}")
    # Filling an empty override would hide the previously active AGENTS.md.
    path = target / "CLAUDE.md" if runtime == "claude" else (
        override if override.is_file() and override.read_bytes().strip() else target / "AGENTS.md"
    )
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


def install(target=None, source=SOURCE, runtime="codex", check_only=False):
    if runtime not in {"codex", "claude"}:
        raise ValueError(f"Unknown runtime: {runtime}")
    user_install = target is None
    target = (Path.home() if user_install else Path(target)).expanduser().resolve(strict=True)
    if not target.is_dir():
        raise ValueError(f"Target must be an existing project directory: {target}")
    if runtime == "claude":
        config = Path(os.environ.get("CLAUDE_CONFIG_DIR") or target / ".claude").expanduser().absolute() if user_install else target / ".claude"
        destination = config / "skills"
        instruction_directory = config
    else:
        destination = target / ".agents" / "skills"
        instruction_directory = (
            Path(os.environ.get("CODEX_HOME") or target / ".codex").expanduser().absolute()
            if user_install else target
        )
    skills_root = destination.as_posix() if user_install else (".claude/skills" if runtime == "claude" else ".agents/skills")
    for path in (destination.parent, destination, *destination.parents, instruction_directory, *instruction_directory.parents):
        if path.is_symlink() or (path.exists() and not path.is_dir()):
            raise ValueError(f"Expected a real directory: {path}")
    instruction_path, before, after = project_instructions(
        instruction_directory, skills_root, runtime
    )

    pending = []
    previous = {}
    for name in SKILLS:
        bundled = source / name
        expected = contents(bundled)
        if Path("SKILL.md") not in expected or expected[Path("SKILL.md")] is None:
            raise ValueError(f"Missing SKILL.md: {bundled}")
        installed = destination / name
        if installed.exists() or installed.is_symlink():
            previous[name] = contents(installed)
            if previous[name] != expected:
                pending.append(name)
        else:
            previous[name] = None
            pending.append(name)

    backup_root = destination.parent / "showwork-backups"
    if backup_root.is_symlink() or (backup_root.exists() and not backup_root.is_dir()):
        raise ValueError(f"Expected a real backup directory: {backup_root}")
    lock = destination.parent / ".showwork-install.lock"
    if lock.exists() or lock.is_symlink():
        raise ValueError(f"Another install is active. If it was interrupted, remove {lock} and retry.")
    if check_only:
        return len(pending)
    instruction_directory.mkdir(parents=True, exist_ok=True)
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        lock.mkdir()
    except FileExistsError:
        raise ValueError(f"Another install is active. If it was interrupted, remove {lock} and retry.") from None
    try:
        # Preflight ran before taking the lock: reject any intervening changes.
        for name, snapshot in previous.items():
            installed = destination / name
            current = contents(installed) if installed.exists() or installed.is_symlink() else None
            if current != snapshot:
                raise ValueError(f"Files changed during installation: {installed}; retry.")
        if project_instructions(instruction_directory, skills_root, runtime) != (instruction_path, before, after):
            raise ValueError("Instructions changed during installation; retry.")
        apply_update(destination, source, pending, previous, instruction_path, before, after)
    finally:
        lock.rmdir()
    return len(pending)


def apply_update(destination, source, pending, previous, instruction_path, before, after):
    """Stage first, retain old files outside skill discovery, roll back failed writes."""
    backup = None
    applied = []
    instruction_existed = instruction_path.exists()
    instruction_write_started = False
    with tempfile.TemporaryDirectory(prefix=".showwork-stage-", dir=destination.parent) as temporary:
        staged = Path(temporary)
        for name in pending:
            shutil.copytree(source / name, staged / name,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"))
        if any(previous[name] is not None for name in pending) or (instruction_existed and before != after):
            backup_root = destination.parent / "showwork-backups"
            if backup_root.is_symlink() or (backup_root.exists() and not backup_root.is_dir()):
                raise ValueError(f"Expected a real backup directory: {backup_root}")
            backup_root.mkdir(exist_ok=True)
            backup = Path(tempfile.mkdtemp(prefix="update-", dir=backup_root))
            if before != after and instruction_path.exists():
                shutil.copy2(instruction_path, backup / instruction_path.name)
            print(f"Previous files (including local edits) are backed up in: {backup}")
        destination.mkdir(exist_ok=True)
        try:
            for name in pending:
                applied.append(name)
                if previous[name] is not None:
                    os.replace(destination / name, backup / name)
                os.replace(staged / name, destination / name)
            if before != after:
                instruction_write_started = True
                write_instructions(instruction_path, after)
        except BaseException:
            for name in reversed(applied):
                installed = destination / name
                if previous[name] is not None:
                    if (backup / name).exists():
                        if installed.exists():
                            shutil.rmtree(installed)
                        os.replace(backup / name, installed)
                elif installed.exists():
                    shutil.rmtree(installed)
            if instruction_write_started:
                if instruction_existed:
                    os.replace(backup / instruction_path.name, instruction_path)
                else:
                    instruction_path.unlink(missing_ok=True)
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument("--target", type=Path, help="Install in this existing project instead of for the user")
    scope.add_argument("--user", action="store_true", help="Install for the current user (default)")
    parser.add_argument("--runtime", choices=("both", "codex", "claude"), default="both")
    args = parser.parse_args()
    try:
        runtimes = ("codex", "claude") if args.runtime == "both" else (args.runtime,)
        for runtime in runtimes:
            install(args.target, runtime=runtime, check_only=True)
        version = json.loads((SOURCE.parent / "package.json").read_text(encoding="utf-8"))["version"]
        scope_name = "project" if args.target is not None else "user"
        for runtime in runtimes:
            count = install(args.target, runtime=runtime)
            print(f"Showwork {version} ({runtime}): installed/updated {count} skills; automatic routing is configured in {scope_name} instructions.")
    except (OSError, ValueError) as error:
        parser.exit(1, f"showwork: {error}\n")
    print("Start a new session in the installed runtime(s) and describe your task normally.")


if __name__ == "__main__":
    main()
