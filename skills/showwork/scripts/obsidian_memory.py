#!/usr/bin/env python3
"""Store Showwork decision notes in an Obsidian vault and build a Pluely snapshot."""

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import obsidian_mcp as search_tool  # noqa: E402  (shared project discovery)

CONFIG = Path.home() / ".config" / "showwork" / "obsidian.json"
MARKER = "type: showwork-decision"
DEFAULT_ROOT = Path.home() / "Documents" / "Showwork"  # used only when no vault is set


def fail(message):
    raise SystemExit(message)


def safe_folder(vault, folder):
    path = Path(folder)
    if path.is_absolute() or any(part in ("..", ".obsidian") for part in path.parts):
        fail("Folder must be a relative path inside the vault.")
    target = (vault / path).resolve()
    if not target.is_relative_to(vault):
        fail("Folder resolves outside the vault.")
    return target


def settings(config):
    if not config.exists():
        fail("No Obsidian destination set. Run showwork-set-location first.")
    data = json.loads(config.read_text(encoding="utf-8"))
    vault = Path(data["vault"]).expanduser().resolve()
    if not (vault / ".obsidian").is_dir():
        fail(f"Not an Obsidian vault: {vault}")
    return vault, data


def project_folder(vault, data, project):
    """Resolve exactly like the search tool: mappings, then folders under any `03 Projects`."""
    try:
        return search_tool.resolve_project(vault, data, project)
    except ValueError as error:
        fail(f"{error}. Use showwork-set-location --project {project!r} --path <vault folder> to map it.")


def default_name(project):
    name = project.strip()
    if not name or name.startswith(".") or any(mark in name for mark in ("/", "\\", "..")):
        fail(f"Project name cannot be used as a folder: {project!r}")
    return name


def save_folder(config, project):
    """Return (vault or None, project folder, used_default). Unset locations fall back to a default."""
    if not config.exists():
        return None, DEFAULT_ROOT / default_name(project), True
    vault, data = settings(config)
    try:
        return vault, search_tool.resolve_project(vault, data, project), False
    except ValueError as error:
        if not str(error).startswith("Project not found"):
            fail(f"{error}. Use showwork-set-location --project {project!r} --path <vault folder> to map it.")
    return vault, vault / search_tool.DEFAULT_FOLDER / default_name(project), True


def slug(value):
    result = re.sub(r"[^\w\-]+", "-", value.strip().lower(), flags=re.UNICODE).strip("-")
    return result[:60] or "decision"


def location(args):
    if args.vault is None:
        vault, data = settings(args.config)
    else:
        vault = Path(args.vault).expanduser().resolve()
        data = {"vault": str(vault), "projects": {}, "aliases": {}}
        if args.config.exists():
            existing = json.loads(args.config.read_text(encoding="utf-8"))
            if Path(existing["vault"]).expanduser().resolve() == vault:
                data["projects"] = existing.get("projects", {})
                data["aliases"] = existing.get("aliases", {})
    if not (vault / ".obsidian").is_dir():
        fail(f"Not an Obsidian vault: {vault}")
    if args.project and args.path:
        target = safe_folder(vault, args.path)
        if not target.is_dir():
            fail(f"Project folder does not exist: {target}")
        data.setdefault("projects", {})[args.project] = str(target.relative_to(vault))
    elif args.path:
        fail("--path requires --project")
    if args.alias:
        if not args.project:
            fail("--alias requires --project")
        project = project_folder(vault, data, args.project)
        for alias in args.alias:
            if len(alias.strip()) < 3:
                fail("Project aliases must be at least three characters")
            current = next((name for name in data.get("aliases", {}) if name.casefold() == alias.casefold()), None)
            if current and data["aliases"][current] != project.name:
                fail(f"Alias already belongs to another project: {alias}")
            data.setdefault("aliases", {})[alias] = project.name
    if args.vault is not None or args.path or args.alias:
        args.config.parent.mkdir(parents=True, exist_ok=True)
        args.config.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.project:
        target = project_folder(vault, data, args.project)
        print(json.dumps({"vault": str(vault), "project": target.name, "path": str(target), "aliases": [a for a, p in data.get("aliases", {}).items() if p == target.name]}, ensure_ascii=False))
    else:
        found = {name: str(path.relative_to(vault)) for name, path in sorted(search_tool.project_directories(vault, data).items())}
        print(json.dumps({"vault": str(vault), "projects": data.get("projects", {}), "aliases": data.get("aliases", {}), "discovered": found}, ensure_ascii=False))


def save(args):
    vault, project, used_default = save_folder(args.config, args.project)
    category = "Decisions" if args.kind == "decision" else "Current"
    relative = Path("Architecture") / category / args.area
    target = safe_folder(vault, str(project.relative_to(vault) / relative)) if vault else project / relative
    body = sys.stdin.read().strip()
    if not body:
        fail("No Markdown note received on stdin.")
    if args.kind == "current" and args.status != "confirmed":
        fail("Current architecture summaries must be confirmed.")
    target.mkdir(parents=True, exist_ok=True)
    now = datetime.now().astimezone()
    stamp = now.strftime("%Y-%m-%d-%H%M%S")
    frontmatter = (
        "---\n"
        f"type: showwork-{args.kind}\n"
        f"title: {json.dumps(args.title, ensure_ascii=False)}\n"
        f"project: {json.dumps(project.name, ensure_ascii=False)}\n"
        f"area: {args.area}\n"
        f"status: {args.status}\n"
        f"updated: {now.isoformat(timespec='seconds')}\n"
        "---\n\n"
    )
    if args.kind == "current":
        note = target / "Current.md"
        if note.exists() and not args.replace:
            fail(f"Current summary already exists: {note}. Read and merge it, then pass --replace.")
        if note.exists():
            backup = target / f".Current-{now.strftime('%Y-%m-%d-%H%M%S-%f')}.md.bak"
            backup.write_bytes(note.read_bytes())
    else:
        note = target / f"{stamp}-{slug(args.title)}.md"
        suffix = 2
        while note.exists():
            note = target / f"{stamp}-{slug(args.title)}-{suffix}.md"
            suffix += 1
    note.write_text(frontmatter + body + "\n", encoding="utf-8")
    if used_default:
        where = "no vault is set; Pluely cannot search it until a vault is set" if vault is None else "searchable by the Obsidian tool"
        print(f"No location set for {project.name!r}; saved in the default folder ({where}).", file=sys.stderr)
    print(str(note))


def export(args):
    vault, data = settings(args.config)
    project = project_folder(vault, data, args.project)
    target = project / "Architecture"
    docs = []
    for note in sorted(target.rglob("*.md"), reverse=True) if target.exists() else []:
        if note.is_symlink():
            continue
        content = note.read_text(encoding="utf-8")
        if content.startswith("---\n") and any(marker in content.split("---", 2)[1] for marker in (MARKER, "type: showwork-current")):
            docs.append((note, content))
    output = Path(args.output).expanduser().resolve()
    if output.is_relative_to(target):
        fail("Export must be outside the decision folder.")
    output.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"# {project.name} — Showwork context for Pluely", "", "Snapshot of confirmed current architecture and decisions. Refresh and reattach this file after changes.", ""]
    selected = 0
    eligible = 0
    docs.sort(key=lambda item: ("type: showwork-current" not in item[1][:300], -item[0].stat().st_mtime))
    for note, content in docs:
        metadata = content.split("---", 2)[1]
        if "status: confirmed" not in metadata:
            continue
        if f"project: {json.dumps(project.name, ensure_ascii=False)}" not in metadata:
            continue
        eligible += 1
        entry = f"## {note.stem}\nSource: {note.relative_to(vault)}\n\n{content.split('---', 2)[2].strip()}\n\n"
        if sum(map(len, lines)) + len(entry) > args.max_chars:
            continue
        lines.append(entry)
        selected += 1
    output.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"output": str(output), "included": selected, "eligible": eligible, "project": project.name}, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=CONFIG, help=argparse.SUPPRESS)
    sub = parser.add_subparsers(dest="command", required=True)
    where = sub.add_parser("location", help="Show or set the Obsidian destination")
    where.add_argument("vault", nargs="?")
    where.add_argument("--project", help="Project name to show or map")
    where.add_argument("--path", help="Existing vault-relative folder for this project")
    where.add_argument("--alias", action="append", help="Alternate project name used in conversation; repeatable")
    where.set_defaults(func=location)
    note = sub.add_parser("save", help="Save a Markdown decision note from stdin")
    note.add_argument("--title", required=True)
    note.add_argument("--project", required=True)
    note.add_argument("--area", choices=("shared", "frontend", "backend", "mobile", "data", "infrastructure"), default="shared")
    note.add_argument("--kind", choices=("decision", "current"), default="decision")
    note.add_argument("--replace", action="store_true", help="Replace a current summary after reading and merging it")
    note.add_argument("--status", choices=("confirmed", "proposed"), default="confirmed")
    note.set_defaults(func=save)
    bundle = sub.add_parser("export", help="Build a Pluely attachment snapshot")
    bundle.add_argument("--output", required=True)
    bundle.add_argument("--project", required=True, help="Include only this project's confirmed notes")
    bundle.add_argument("--max-chars", type=int, default=80000)
    bundle.set_defaults(func=export)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
