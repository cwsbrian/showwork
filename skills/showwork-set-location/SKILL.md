---
name: showwork-set-location
description: Set or inspect the Obsidian vault and per-project folders used by explicit Showwork decision notes. Use only when the user invokes this command.
disable-model-invocation: true
---

# Showwork set location

Set the Obsidian vault once, then map a project name to its existing folder when the folder name differs or is ambiguous. Showwork notes live inside each project, not in a shared vault-wide decisions folder. This command does not write a decision note.

Resolve `../showwork/scripts/obsidian_memory.py` relative to this SKILL.md and use its absolute path in these commands:

```bash
python3 "<resolved helper path>" location "/absolute/path/to/vault"
python3 "<resolved helper path>" location --project "Janus Health" --path "247 Labs/03 Projects/Janus Health"
python3 "<resolved helper path>" location --project "Janus Health" --alias "Janus"
python3 "<resolved helper path>" location --project "Janus Health"
```

The first command stores the vault root. The second records an explicit vault-relative project folder; it must already exist. The third registers a conversational alias, and the fourth shows the resolved project folder. Folders directly under any `03 Projects` folder are found automatically, by exact name or a unique first word, so they need no mapping. Map a project only when its documents live elsewhere or the name is ambiguous; the save command and the Obsidian search tool both use the same mappings. Never pick among multiple matches silently. If the user gives no arguments, show the configured vault, mappings, aliases and discovered projects.

The helper stores configuration in `~/.config/showwork/obsidian.json`. Changing the vault changes where the Claude Code Obsidian search tool looks on its next call. Report the resolved location and do not save a note merely because the location was set.
