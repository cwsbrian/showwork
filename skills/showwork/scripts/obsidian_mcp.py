#!/usr/bin/env python3
"""Read-only Obsidian search tools for Claude Code over MCP stdio."""

import json
import re
import sys
from pathlib import Path

CONFIG = Path.home() / ".config" / "showwork" / "obsidian.json"
SELECTION = Path.home() / ".config" / "showwork" / "project-selection.json"
DEFAULT_FOLDER = "Showwork"  # <vault>/Showwork/<project> when a project has no location


def vault_settings():
    data = json.loads(CONFIG.read_text(encoding="utf-8"))
    vault = Path(data["vault"]).expanduser().resolve()
    if not (vault / ".obsidian").is_dir():
        raise ValueError("Configured Obsidian vault is unavailable")
    return vault, data


def resolve_project(vault, data, name):
    name = str(name or "").strip()
    if not name:
        raise ValueError("project is required; use list_projects if unclear")
    name = next((canonical for alias, canonical in data.get("aliases", {}).items() if alias.casefold() == name.casefold()), name)
    mapped = next((value for key, value in data.get("projects", {}).items() if key.casefold() == name.casefold()), None)
    if mapped:
        target = (vault / mapped).resolve()
        if target.is_relative_to(vault) and target.is_dir():
            return target
        raise ValueError("Mapped project folder is unavailable")
    known = list(project_directories(vault, data).values())
    matches = [path for path in known if path.name.casefold() == name.casefold()]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise ValueError("Project name is ambiguous; configure a project mapping")
    if len(name) >= 4:
        prefixes = [path for path in known if path.name.casefold().split(" ")[0] == name.casefold()]
        if len(prefixes) == 1:
            return prefixes[0]
        if prefixes:
            raise ValueError("Project prefix is ambiguous; configure an alias")
    raise ValueError("Project not found; use list_projects or configure a project mapping")


def project_directories(vault, data):
    projects = {}
    for name, relative in data.get("projects", {}).items():
        path = (vault / relative).resolve()
        if path.is_relative_to(vault) and path.is_dir():
            projects[path.name] = path
    # Project folders under `03 Projects`, plus the default folder used when no location was set.
    for root in [*vault.rglob("03 Projects"), vault / DEFAULT_FOLDER]:
        if root.is_dir() and not root.is_symlink() and root.resolve().is_relative_to(vault) and ".obsidian" not in root.parts:
            for folder in root.iterdir():
                if folder.is_dir() and not folder.is_symlink() and folder.resolve().is_relative_to(vault):
                    projects.setdefault(folder.name, folder)
    return projects


def active_projects(vault, data):
    """Return verified manual selections; an absent or empty selection means Auto."""
    if not SELECTION.exists():
        return []
    selection = json.loads(SELECTION.read_text(encoding="utf-8"))
    if selection.get("mode") != "manual":
        return []
    names = selection.get("projects", [])
    if not isinstance(names, list):
        raise ValueError("Project selection is invalid")
    paths = []
    for name in names:
        path = resolve_project(vault, data, name)
        if path not in paths:
            paths.append(path)
    return paths


def get_active_projects(_args):
    vault, data = vault_settings()
    paths = active_projects(vault, data)
    return json.dumps({"mode": "manual" if paths else "auto", "projects": [
        {"name": path.name, "path": str(path.relative_to(vault))} for path in paths
    ]}, ensure_ascii=False)


def list_projects(_args):
    vault, data = vault_settings()
    projects = project_directories(vault, data)
    return "\n".join(f"{name}: {path.relative_to(vault)}" for name, path in sorted(projects.items())) or "No project folders registered."


def resolve_project_context(args):
    vault, data = vault_settings()
    context = str(args.get("context", "")).strip().casefold()
    if not context:
        raise ValueError("context is required")
    projects = project_directories(vault, data)
    active = active_projects(vault, data)
    if active:
        selected = [{"project": path.name, "path": str(path.relative_to(vault))} for path in active]
        explicit_selected = [entry for entry in selected if re.search(
            r"(?<![a-z0-9_])" + re.escape(entry["project"].casefold()) + r"(?![a-z0-9_])", context
        )]
        if len(explicit_selected) == 1:
            return json.dumps({"status": "selected", "confidence": "manual", "project": explicit_selected[0]["project"], "active_projects": selected}, ensure_ascii=False)
        if len(selected) == 1:
            return json.dumps({"status": "selected", "confidence": "manual", "project": selected[0]["project"], "active_projects": selected}, ensure_ascii=False)
        return json.dumps({"status": "selected_multi", "confidence": "manual", "projects": selected}, ensure_ascii=False)
    aliases = data.get("aliases", {})
    first_words = {}
    for name in projects:
        first = name.split(" ")[0]
        if len(first) >= 4:
            first_words.setdefault(first.casefold(), []).append(name)
    explicit = []
    for name, path in projects.items():
        names = [name] + [alias for alias, canonical in aliases.items() if canonical.casefold() == name.casefold()]
        names.extend(key for key, relative in data.get("projects", {}).items() if (vault / relative).resolve() == path)
        first = name.split(" ")[0]
        if len(first) >= 4 and len(first_words.get(first.casefold(), [])) == 1:
            names.append(first)
        hits = [candidate for candidate in names if re.search(r"(?<![a-z0-9_])" + re.escape(candidate.casefold()) + r"(?![a-z0-9_])", context)]
        if hits:
            explicit.append({"project": name, "path": str(path.relative_to(vault)), "matched": hits})
    if len(explicit) == 1:
        return json.dumps({"status": "selected", "confidence": "high", "project": explicit[0]["project"], "evidence": explicit}, ensure_ascii=False)
    if len(explicit) > 1:
        return json.dumps({"status": "ambiguous", "candidates": explicit}, ensure_ascii=False)
    previous = str(args.get("previous_project", "")).strip()
    if previous:
        try:
            path = resolve_project(vault, data, previous)
            return json.dumps({"status": "selected", "confidence": "session", "project": path.name, "evidence": "previously verified project in this conversation"}, ensure_ascii=False)
        except ValueError:
            pass
    terms = [term for term in re.findall(r"[\w-]{4,}", context) if term not in {"what", "does", "this", "that", "with", "from", "about", "project", "프로젝트", "아키텍처", "기능은", "어떻게"}]
    suggestions = []
    for name, path in projects.items():
        title_hits = []
        for note in path.rglob("*.md"):
            if "Architecture" in note.parts and "Current" in note.parts:
                continue
            hits = [term for term in terms if term in note.stem.casefold()]
            if hits:
                title_hits.extend(hits)
        if title_hits:
            suggestions.append({"project": name, "title_matches": sorted(set(title_hits)), "matching_titles": len(title_hits)})
    suggestions.sort(key=lambda item: item["matching_titles"], reverse=True)
    return json.dumps({"status": "suggested" if suggestions else "unresolved", "candidates": suggestions[:3]}, ensure_ascii=False)


def note_files(vault):
    for path in vault.rglob("*.md"):
        if ".obsidian" in path.parts or path.is_symlink():
            continue
        resolved = path.resolve()
        if resolved.is_relative_to(vault):
            yield path


def search_notes(args):
    vault, data = vault_settings()
    project = resolve_project(vault, data, args.get("project"))
    active = active_projects(vault, data)
    if active and project not in active:
        raise ValueError("Project is outside the manual menu bar selection")
    query = str(args.get("query", "")).strip()
    if not query:
        raise ValueError("query is required")
    limit = max(1, min(int(args.get("limit", 5)), 10))
    terms = [term for term in re.split(r"\s+", query.casefold()) if term]
    matches = []
    for path in note_files(project):
        relative = str(path.relative_to(vault))
        content = path.read_text(encoding="utf-8", errors="replace")
        lower = content.casefold()
        title = path.stem.casefold()
        score = sum((12 if term in title else 0) + min(lower.count(term), 4) for term in terms)
        if score == 0:
            continue
        if query.casefold() in title:
            score += 20
        if "type: showwork-current" in content[:500] and "status: confirmed" in content[:500]:
            score += 20
        elif "type: showwork-decision" in content[:500] and "status: confirmed" in content[:500]:
            score += 8
        positions = [lower.find(term) for term in terms if term in lower]
        start = max(0, min(positions) - 180) if positions else 0
        snippet = content[start:start + max(200, min(int(args.get("snippet", 1100)), 4000))].replace("\n", " ")
        matches.append((score, path.stat().st_mtime, relative, snippet))
    matches.sort(reverse=True)
    if not matches:
        return "No matching notes found. Do not infer a decision from the vault."
    return "\n\n".join(f"[{relative}] score={score}\n{snippet}" for score, _, relative, snippet in matches[:limit])


def search_active_notes(args):
    vault, data = vault_settings()
    active = active_projects(vault, data)
    if not active:
        raise ValueError("Auto is active; resolve the project from conversation first, then use search_notes")
    query = str(args.get("query", "")).strip()
    if not query:
        raise ValueError("query is required")
    limit = max(1, min(int(args.get("limit", 5)), 10))
    results = []
    for project in active:
        text = search_notes({"project": project.name, "query": query, "limit": limit})
        if text != "No matching notes found. Do not infer a decision from the vault.":
            results.append(f"# {project.name}\n{text}")
    return "\n\n".join(results) or "No matching notes found in selected projects. Do not infer a decision from the vault."


STOPWORDS = {
    "what", "does", "this", "that", "with", "from", "about", "are", "the", "and", "for", "how", "why",
    "our", "using", "use", "which", "who", "when", "where", "still", "remains", "there", "any", "have",
    "has", "you", "they", "can", "should", "will", "would", "did",
}


def project_mentioned(text, name, data, first_words):
    candidates = [name] + [alias for alias, canonical in data.get("aliases", {}).items() if canonical.casefold() == name.casefold()]
    first = name.split(" ")[0]
    if len(first) >= 4 and len(first_words.get(first.casefold(), [])) == 1:
        candidates.append(first)
    return any(re.search(r"(?<![a-z0-9_])" + re.escape(candidate.casefold()) + r"(?![a-z0-9_])", text) for candidate in candidates)


def named_unselected(vault, data, question, selected):
    """Projects named in the question itself but outside the manual selection."""
    names = list(project_directories(vault, data))
    first_words = {}
    for name in names:
        first_words.setdefault(name.split(" ")[0].casefold(), []).append(name)
    text = question.casefold()
    return [name for name in names if name not in selected and project_mentioned(text, name, data, first_words)]


def answer_context(args):
    """One call for live meetings: resolve the project(s), then return the best snippets."""
    vault, data = vault_settings()
    question = str(args.get("question", "")).strip()
    if not question:
        raise ValueError("question is required")
    context = (str(args.get("recent", "")) + " " + question).strip()
    resolved = json.loads(resolve_project_context({"context": context, "previous_project": args.get("previous_project", "")}))
    status = resolved.get("status")
    if status == "selected":
        projects = [resolved["project"]]
    elif status == "selected_multi":
        projects = [entry["project"] for entry in resolved["projects"]]
    elif status == "ambiguous":
        # Auto mode with several projects named explicitly: search each named project.
        projects = [entry["project"] for entry in resolved["candidates"]]
        resolved["confidence"] = "named"
    else:
        return json.dumps({"status": status, "candidates": resolved.get("candidates", []),
                           "note": "Project unclear. Ask which project, or answer only if a candidate is obvious and say it is an assumption."}, ensure_ascii=False)
    terms = [term for term in re.findall(r"[\w-]+", question.casefold()) if term not in STOPWORDS and len(term) > 2]
    query = str(args.get("query", "")).strip() or " ".join(terms) or question
    limit = max(1, min(int(args.get("limit", 3)), 5))
    parts = [f"status={status} confidence={resolved.get('confidence')} projects={projects} query={query!r}"]
    if resolved.get("confidence") == "manual":
        missing = named_unselected(vault, data, question, projects)
        if missing:
            parts.append(f"NOT SELECTED: the question names {', '.join(missing)}, which is not selected in the menu bar. "
                         f"Start the answer by saying that {', '.join(missing)} is not selected, so you only checked {', '.join(projects)}. "
                         "Do not describe the unselected project beyond what these notes say.")
    for project in projects:
        parts.append(f"# {project}\n" + search_notes({"project": project, "query": query, "limit": limit, "snippet": 2500}))
    return "\n\n".join(parts)


def read_note(args):
    vault, data = vault_settings()
    project = resolve_project(vault, data, args.get("project"))
    active = active_projects(vault, data)
    if active and project not in active:
        raise ValueError("Project is outside the manual menu bar selection")
    relative = Path(str(args.get("path", "")))
    if relative.is_absolute() or ".obsidian" in relative.parts:
        raise ValueError("path must be a Markdown note inside the vault")
    path = (vault / relative).resolve()
    if not path.is_relative_to(project) or ".obsidian" in path.relative_to(vault).parts or path.suffix.lower() != ".md" or not path.is_file():
        raise ValueError("note not found inside the selected project")
    content = path.read_text(encoding="utf-8", errors="replace")
    return f"[{relative}]\n{content[:40000]}" + ("\n[truncated]" if len(content) > 40000 else "")


TOOLS = [
    {"name": "answer_context", "description": "FAST PATH for live meetings. One call: resolves the project (honoring the manual menu bar selection, including multiple projects) and returns the best matching note snippets with source paths.", "inputSchema": {"type": "object", "properties": {"question": {"type": "string"}, "query": {"type": "string", "description": "3-6 search keywords, English plus Korean equivalents (notes are mostly Korean)"}, "recent": {"type": "string", "description": "A few recent transcript lines, for project detection"}, "previous_project": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 5}}, "required": ["question"]}},
    {"name": "list_projects", "description": "List known Obsidian project folders so a project can be selected before searching.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "get_active_projects", "description": "Read the macOS menu bar project selection. Auto means detect from conversation; manual may contain multiple projects.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "resolve_project_context", "description": "Identify a project from recent conversation text, honoring manual projects selected in the macOS menu bar. Auto returns high confidence only for an explicit name, alias, or previously verified project; filename matches are suggestions only.", "inputSchema": {"type": "object", "properties": {"context": {"type": "string"}, "previous_project": {"type": "string", "description": "Only a project already verified earlier in this same conversation"}}, "required": ["context"]}},
    {"name": "search_notes", "description": "Search Markdown notes inside one selected project, prioritizing confirmed Showwork decisions. Results include source paths and snippets.", "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}, "project": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 10}}, "required": ["query", "project"]}},
    {"name": "search_active_notes", "description": "Search only the manually selected project folders from the macOS menu bar. Supports multiple projects; use after get_active_projects reports manual mode.", "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 10}}, "required": ["query"]}},
    {"name": "read_note", "description": "Read one Markdown note by its vault-relative path inside the selected project after search. Read-only.", "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}, "project": {"type": "string"}}, "required": ["path", "project"]}},
]


def result(request):
    method = request.get("method")
    if method == "initialize":
        return {"protocolVersion": request.get("params", {}).get("protocolVersion", "2025-06-18"), "capabilities": {"tools": {}}, "serverInfo": {"name": "showwork-obsidian", "version": "0.1.0"}}
    if method == "tools/list":
        return {"tools": TOOLS}
    if method == "tools/call":
        params = request.get("params", {})
        name = params.get("name")
        args = params.get("arguments", {})
        try:
            if name == "answer_context":
                content = answer_context(args)
            elif name == "list_projects":
                content = list_projects(args)
            elif name == "get_active_projects":
                content = get_active_projects(args)
            elif name == "resolve_project_context":
                content = resolve_project_context(args)
            elif name == "search_notes":
                content = search_notes(args)
            elif name == "search_active_notes":
                content = search_active_notes(args)
            elif name == "read_note":
                content = read_note(args)
            else:
                raise ValueError("Unknown tool")
            return {"content": [{"type": "text", "text": content}]}
        except (ValueError, OSError, KeyError, json.JSONDecodeError) as error:
            return {"content": [{"type": "text", "text": str(error)}], "isError": True}
    raise ValueError("Unsupported method")


def main():
    for line in sys.stdin:
        try:
            request = json.loads(line)
            if "id" not in request:
                continue
            response = {"jsonrpc": "2.0", "id": request["id"], "result": result(request)}
        except Exception as error:
            response = {"jsonrpc": "2.0", "id": request.get("id") if isinstance(request, dict) else None, "error": {"code": -32603, "message": str(error)}}
        sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
