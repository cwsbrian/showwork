---
name: showwork-save
description: Save explicitly requested project decisions and system architecture in the matching Obsidian project folder, grouped by frontend, backend, mobile, data, infrastructure, or shared area. Use only when the user invokes this command.
disable-model-invocation: true
---

# Showwork save

Save the decisions the user and assistant actually made, along with the resulting architecture, in the matching project folder of the configured Obsidian vault. This command is separate from the browser result walkthrough.

Identify the project from the conversation, repository, and vault folder. If it is ambiguous, ask which project before writing. The helper resolves projects exactly like the Obsidian search tool: a `showwork-set-location` mapping or alias, otherwise a folder under `03 Projects` with a unique matching name. If no location is set for the project, the helper saves to the default folder `<vault>/Showwork/<project>/`, which the search tool also reads; with no vault set at all it uses `~/Documents/Showwork/<project>/`, which Pluely cannot search. Tell the user when the default was used and that `showwork-set-location` can register a different folder. An ambiguous project name is still refused: ask which project instead of guessing. Choose one area: `frontend`, `backend`, `mobile`, `data`, `infrastructure`, or `shared`. A decision that crosses areas belongs in `shared` and should link the affected parts. The note is stored at `<project>/Architecture/Decisions/<area>/`.

Before writing, look at that area's existing decision notes and `Architecture/Current/<area>/Current.md`. If the same decision is already recorded, do not save a duplicate; report the existing note. If the new decision changes an older one, save a new note that names the older note as superseded.

Read relevant conversation and source evidence. Write concise Markdown in the user's language with a clear title, current architecture/data flow, the decision and why, consequences, and open questions. Distinguish confirmed decisions from proposals and unknowns. Include paths or links that substantiate technical claims. Do not invent agreement or describe a proposed design as deployed. When a decision supersedes an older one, name the older note and explain the replacement.

End every note with a **Related code** section that links the work behind it, when it exists:
- Repository and branch names, with the latest relevant commit hash and date.
- Pull requests as full clickable URLs with their state (open, merged, closed), for example `[#66 AN-717 Apple verification](https://github.com/org/repo/pull/66) — open`. Get them with `gh pr list --search <ticket or branch> --state all --json number,title,url,state,headRefName` or `gh pr view <branch> --json url,state`; if `gh` is unavailable, build the URL from `git remote get-url origin` and say the state was not checked.
- Issue tracker tickets (for example Jira keys) as links when the base URL is known, otherwise as plain keys.
Only link branches, commits and PRs you actually found; never guess a URL. If none exist, write that no related code was found.

Resolve `../showwork/scripts/obsidian_memory.py` relative to this SKILL.md and send the prepared Markdown to it on stdin:

```bash
python3 "<resolved helper path>" save --title "Decision title" --project "Janus Health" --area backend < /tmp/showwork-decision.md
```

Use `--status proposed` only for an explicit proposal. The helper creates a new note and never overwrites an older one. Read it back and report its project-relative location. Do not automatically publish or attach it to Pluely.

When the implemented architecture changed, also create or update a short **current architecture** summary for the affected area. This is the first place a quick-answer tool should look. Cover what exists now, how the main flow works, why the important choices were made, and links to the relevant decision notes and code. Read and merge an existing summary before replacing it; pass `--replace` only after doing that. The helper preserves the previous version as a `.md.bak` file.

```bash
python3 "<resolved helper path>" save --kind current --title "Backend architecture" --project "Janus Health" --area backend --replace < /tmp/showwork-current.md
```

If the Claude Code vault tool is unavailable in Pluely, the helper can create a project-specific attachment snapshot:

```bash
python3 "<resolved helper path>" export --project "Janus Health" --output /tmp/showwork-pluely-context.md
```

Only confirmed notes are included. Compare `included` and `eligible` and disclose omissions. Pluely reads an attachment snapshot, so regenerate and reattach it after decisions change. Do not claim live vault retrieval from an attachment.
