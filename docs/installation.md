# Install and update Showwork

Showwork 0.5.0 installs **for both Codex and Claude Code at the user level** by default. It requires Node.js 20 or newer (including npm/npx), Git, and Python 3.11 or newer.

## One command for installation and updates

Run from any directory:

```bash
npx --yes github:cwsbrian/showwork
```

The first run installs Showwork; later runs update it to the latest commit on GitHub's default branch. Open a **new chat or session** in the tool you want to use afterward. You do not need to install it separately in every project.

| Tool | User skills | Command-only guidance | Backup |
| --- | --- | --- | --- |
| Codex | `~/.agents/skills/showwork*` | `~/.codex/AGENTS.md` | `~/.agents/showwork-backups/` |
| Claude Code | `~/.claude/skills/showwork*` | `~/.claude/CLAUDE.md` | `~/.claude/showwork-backups/` |

Codex uses `CODEX_HOME` when set and updates a nonempty `AGENTS.override.md` when present. Claude installs skills and instructions under `CLAUDE_CONFIG_DIR` when set. Skill references in user instructions use absolute paths. Existing instructions outside the Showwork managed block and other skills are preserved. Claude's `settings.json`, credentials, MCP configuration, and existing hooks are not changed.

Claude user installation uses personal skills and `CLAUDE.md` instructions. It needs no plugin launch argument or prompt hook registration and does not appear in the native plugin list. Managed policies that disable user instructions or skills take precedence. [Claude skill locations](https://code.claude.com/docs/en/skills#choose-where-skills-load) · [Claude user instructions](https://code.claude.com/docs/en/memory) · [Codex skill locations](https://learn.chatgpt.com/docs/build-skills#where-codex-loads-local-skills) · [Codex instruction precedence](https://learn.chatgpt.com/docs/agent-configuration/agents-md)

## Install for one tool or one project

```bash
npx --yes github:cwsbrian/showwork --runtime claude
npx --yes github:cwsbrian/showwork --runtime codex
npx --yes github:cwsbrian/showwork --target /absolute/path/to/your-project
npx --yes github:cwsbrian/showwork --help
```

Choose `both` (default), `codex`, or `claude` with `--runtime`. With `--target`, installation is limited to that project. Explicit `--user` is equivalent to the default user installation and cannot be combined with `--target`.

| Project installation | Skills | Instructions |
| --- | --- | --- |
| Codex | `<project>/.agents/skills/showwork*` | `<project>/AGENTS.md` (active override takes precedence) |
| Claude Code | `<project>/.claude/skills/showwork*` | `<project>/.claude/CLAUDE.md` |

An existing root `CLAUDE.md` is preserved. The target project must already exist. Default user installation adds no files or npm dependencies to the current working directory.

You can clone the repository and use only Python. The installer filename remains for compatibility with older versions.

```bash
git clone https://github.com/cwsbrian/showwork.git
python3 /absolute/path/to/showwork/scripts/install_codex.py --user
```

The Python entry point also defaults to both tools and supports `--runtime` and `--target`. Update the source repository before running it to update an installation; it installs the contents of the bundle being run.

## Updates and recovery

Rerun the same npx command. An update of a Codex-only 0.2.x installation also adds the Claude user installation. Checking the latest commit requires network access. `--offline` and URLs pinned to a commit do not check for the latest version. Updating to a new Git commit with the same command and cache was verified on npm 10.

- For changed skill directories, the installer saves all previous contents under each tool's `showwork-backups/update-*/`, then replaces them with the new version. It prints the exact backup location.
- Modified or added personal files also remain in the backup. The active skill gets the distributed version, so reapply any needed personal edits by comparing with the backup. Files removed from the distribution also leave the active skill.
- Only the managed instruction block is updated, and the previous instruction file is backed up. Identical content is not recopied or backed up again.
- Paths, instructions, sources, and existing locks are checked for both tools before changes begin. Replacement and rollback happen separately for each tool. If the second tool has an unexpected write failure, the first tool's completed update remains. Fix the cause and rerun the same command.
- If skill replacement or instruction writing fails, previous files for that tool are restored. Automatic recovery from forced OS shutdown or power loss is not guaranteed. After an interruption, inspect the backup. Remove that tool's `.showwork-install.lock` directory only when no installer is running, then retry.

Backups are stored outside skill discovery paths and are never deleted automatically. To recover, ensure the installer is not running and restore the skill directory from the relevant backup to its original `skills/` location. Running the install command again then reapplies the latest distribution.

Until 0.2.1, the default installation was per project. The installer does not remove old project files or manually registered plugins automatically. To use only a user installation, back up and remove the old project's Showwork skill directories and managed instruction block. Avoid activating both the user skill and plugin copy of the same skill.

## Usage and checks

In a new session, work as usual and invoke a command when you want to see the result.

```text
# Codex
$showwork Show me the work you just finished

# Claude user installation
/showwork Show me the work you just finished
```

Ordinary requests do not activate Showwork. A result walkthrough focuses on what changed, how it works now, checks, and remaining issues. Unless the command separately asks for implementation, it does not change product code. Invoke `showwork-plan`, `showwork-review`, `showwork-verify`, and `showwork-adverial-review` directly with the same prefix.

Codex sets `allow_implicit_invocation: false` in each skill's `agents/openai.yaml`; Claude sets `disable-model-invocation: true` in `SKILL.md`. Updates replace older automatic instruction blocks with command-only guidance. The marker name `showwork:automatic` remains so old installations can be found; it does not mean automatic invocation. The plugin's `UserPromptSubmit` hook was removed. [Claude invocation controls](https://code.claude.com/docs/en/skills#control-who-invokes-a-skill)

Previously opened sessions may retain old instructions, so open a new session after updating. Update old project installations with `--target` from that project or clean up their managed blocks. The installer does not change other automatic rules written by users or managed policies.

`adverial-review` shows findings in the Showwork app (or the browser fallback) and requires simulator/emulator operation and real screen captures for mobile targets. With npx user installation, invoke Claude `/showwork-adverial-review` or Codex `$showwork-adverial-review`. The colon command `/showwork:adverial-review` is only for the plugin loading method below.

## App (macOS)

The Showwork app is the default place to read reports. It is optional: without it, `companion.py serve` shows the latest report in the browser. Reports are saved in `~/Library/Application Support/Showwork` (on other systems `$XDG_DATA_HOME/showwork` or `~/.local/share/showwork`), never in your project. Delete them from the app. `SHOWWORK_STORE` points the skills at a different folder for tests or advanced use; the app does not read it, so publishing with it set skips the app and uses the browser fallback.

Build it from the repository (needs Node.js and the Rust toolchain):

```bash
cd app
npm install && npm run tauri build
cp -R src-tauri/target/release/bundle/macos/Showwork.app /Applications/
```

The app is unsigned. A copy you built yourself opens directly. If macOS blocks a downloaded copy, open System Settings › Privacy & Security and click Open Anyway. If several Showwork.app copies exist (for example in build folders), macOS may launch the wrong one: install it to /Applications and remove or unregister the build copies (`lsregister -u <path>`). After a report is published, the skills start the app in the background with no window; click its notification or dock icon to read the report. Set `SHOWWORK_NO_APP=1` to stop the skills from starting it.

## Claude local plugin method (optional)

You do not need this if you use npx user installation. To load the repository directly as a plugin:

```bash
claude --plugin-dir /absolute/path/to/showwork
```

This loads the plugin into the session. No hook sends automatic guidance on ordinary requests. Use `/showwork:run`, `/showwork:plan`, `/showwork:review`, `/showwork:verify`, and `/showwork:adverial-review`. [Claude plugins](https://code.claude.com/docs/en/plugins)

## Removal and verification

In the chosen installation scope, remove only the Showwork skill directories and the `showwork:automatic:start` to `showwork:automatic:end` managed block in the instruction file. Do not delete a whole file that contains other instructions. The optional evidence recorder is not copied; the browser companion is part of the `showwork` skill.

Run development checks from the repository:

```bash
python3 -m unittest discover -s tests -v
npm test
claude plugin validate . --strict
```

Run `tests/browser_companion.cjs` in a development environment with Playwright and Chromium for a real browser check. See the [validation record](validation.md) for the scope and limits.

## Optional live iOS Simulator tabs

On macOS, install Xcode's Simulator tools and the `idb` CLI with `idb_companion`. The installation must support `describe`, MJPEG `video-stream`, and `ui tap`, `ui swipe`, `ui text`, and `ui button HOME`. Boot the chosen Simulator yourself by explicit UDID, start a Showwork task, then attach with `companion.py simulator open --project PROJECT --udid UDID [--title TITLE]`. Detach with `companion.py simulator close --project PROJECT --session SESSION`. Showwork keeps Simulator.app closed and leaves the device boot state alone when an attachment ends.

The iOS tab supports tap and swipe directly on the device image; it has no separate control bar. Use device tools such as `idb` for text and Home. Split previews accept no device input. Report screenshots still come from the agent's device capture tool and belong in `/tmp` with capture provenance. See the [companion guide](../skills/showwork/references/companion.md#live-ios-simulator-sessions-macos).
