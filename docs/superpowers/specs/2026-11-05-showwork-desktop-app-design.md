# Showwork desktop app — design (phase 1)

Date: 2026-11-05 · Status: draft for approval · Branch: `develop`

## Intent

Showwork exists to help one person **understand** work an AI agent did or plans to do: the plan made from a ticket, the review, the verification, and the finished result. Code is one part of that, not the whole.

Today every Showwork command starts a localhost server and opens a browser tab. Two problems:

1. Tabs pile up, one per session and project.
2. Old reports disappear. Each project keeps a single `page.json` that every publish overwrites, and it lives in `/tmp`, which is cleared on reboot.

Phase 1 replaces the browser tab with a macOS desktop app. It keeps every report, sorted by project, so earlier plans and results can be read again. Later phases may turn the app into a review tool closer to an IDE. Those are out of scope here, but phase 1 must not block them.

The primary user is the author, on a Mac. The app is published under the MIT license so others can use it.

## Goals (phase 1)

- Reports from the existing skills appear in the app instead of a browser tab: `/showwork`, `showwork-plan`, `showwork-review`, `showwork-verify` and `showwork-adverial-review`, used from Claude Code or Codex.
- `showwork-plan` and `showwork-review` publish their own report pages, so a plan and a review are kept and can be read again, not only left in chat (see design §2). Without this, Flow would show almost only results.
- Every report is kept until the user deletes it.
- Reports are grouped by **project = git repository**. All worktrees of one repository fall under the same project.
- Each report records its branch, report type, creation time and the agent that made it.
- Layout:
  - left: a project list
  - middle: a toggle between **List** and **Flow**
  - right: the report itself
- **List view:**
  - All reports of the selected project, newest first.
  - Filters for branch and type.
- **Flow view:**
  - One group per branch, with the most recently active branch first.
  - Inside a branch, its reports in time order, for example plan → review → result.
- Switching views keeps the selected report selected. The app remembers the last view.
- When a new report arrives, the app does **not** switch to it.
  - It shows a count badge next to the project.
  - It sends a macOS notification.
  - This applies to both handoff reports and decision screens.
- Decision screens work inside the app.
  - The user picks an option.
  - The agent reads the choice exactly as it does today, through the `events` command.
- If the app is installed but closed, a publish still saves the report and the app is opened in the background.
- Without the app, for example on Linux or before installing, the browser companion still works and reads the same stored reports.
- MIT `LICENSE` at the repository root. The license is also declared in `package.json` and the app's manifests.

## Non-goals (phase 1)

These are deferred, not rejected. Leave room for them.

- Generating a report from a button in the app. Phase 1 reports come only from the chat skills.
- Browsing git diffs or repository files in the app.
- Linking Jira or other tickets. The branch name usually carries the ticket key, which is enough for now.
- Split panel, meaning two reports side by side. Do not hard-wire the report view to a single fixed pane.
- Windows and Linux builds.
- Moving old `/tmp` reports into the app.
- Code signing, notarization and auto-update.

## Anti-goals

- **Stealing focus.** A new report or decision must not bring the app forward or replace what the user is reading.
- **Being heavy.** The app should be cheap to leave running all day.
- **Reaching the network.** No telemetry, no remote fonts or scripts.
- **Putting files in the project.** Reports, captures and state never go into the project directory or git.
- **Losing reports.** A publish must not fail or vanish just because the app is closed, busy or not installed.

## Constraints and facts from the current code

- **Companion:** `skills/showwork/scripts/companion.py` is Python 3.11+ with no dependencies.
  - Commands: `path`, `serve`, `publish`, `events`.
  - `publish` validates the page JSON, copies images into `assets/` by SHA-256 name, reads `files` code from the project and writes `page.json`.
  - `events` returns the decision choices for the current version.
- **Storage:** `skills/showwork/scripts/runtime.py` keys storage by the SHA-256 of the absolute project path under `/tmp/showwork-<uid>/`. Directories are 0700 and owner-checked.
- **Page:** `skills/showwork/assets/companion.html` is a single static page, served with a strict CSP.
  - Layout: title, summary, sections, files accordions and checks. Section HTML renders in a sandboxed iframe with no scripts.
  - The new files accordion has a built-in code view and highlighter.
  - This rendering is reused, not rewritten.
- **Report types:**
  - Pages carry only `mode` (`decision` or `handoff`) today, with no report type.
  - Every skill publishes through the same `companion.py`. The adversarial review uses handoff only; plan uses decision mode for visual choices.
- **Installer:** `scripts/install_codex.py` and `scripts/cli.cjs` (npm package `showwork`) copy the skills into `~/.claude/skills` and `~/.agents/skills`. Claude and Codex share the same skill files.
- **Machine:** Rust (cargo, rustc) is installed through Homebrew rustup. macOS 26.6.
- **Licensing:** the repository has no LICENSE today.

## Approaches considered

1. **Tauri 2 — chosen.**
   - Uses the system WebKit webview, so the app is about 10 MB and has a small footprint.
   - The existing HTML and JS rendering can be reused almost as is.
   - Ports to Windows and Linux later.
   - MIT-compatible.
   - Cost: a Rust backend.
2. **Electron.**
   - The richest ecosystem for later IDE-like features; VS Code is built on it.
   - All JavaScript.
   - Cost: about 150 MB and high memory, which conflicts with an always-running app.
3. **Native Swift (SwiftUI and WKWebView).**
   - Lightest option, and matches the existing `ProjectPicker` menu bar app.
   - Cost: Mac-only for good, and the list and flow screens must be rebuilt natively.

The user picked Tauri. Reasons: it is light enough to leave running and keeps the existing report rendering. Monaco and similar web editors still work in its webview if later phases need them.

## Design

### 1. Persistent report store (shared by the app, the browser and the skills)

The store replaces `/tmp` as the place reports live. Its root:

- macOS: `~/Library/Application Support/Showwork/`
- elsewhere: `$XDG_DATA_HOME/showwork` or `~/.local/share/showwork`

The root is 0700 and owner-checked, like `runtime.py` does today.

```
<root>/
  projects/<project-id>/
    project.json        # name, git common dir, remote URL (if any), worktree paths seen, last activity
    reports/<report-id>/
      report.json       # the validated page plus metadata (below)
      assets/           # images copied by hash, as today
      events.jsonl      # decision choices for this report
  state.json            # app UI state: last view, unread counts (owned by the app)
```

Project identity and metadata:

- **Project id:** a hash of the real path of `git rev-parse --git-common-dir` for the published project. Every worktree of a repository has the same common dir, so all of them land in one project. A folder outside git falls back to its own real path.
- **Project name:** the repository folder name, taken from the common dir's parent. If that name is already used by another project, add the remote's `owner/repo` to tell them apart.
- **report-id:** a sortable timestamp plus a short random suffix, for example `20261105-140212-a1b2`. A publish creates a new report folder and never overwrites another report.

Report metadata, added by `publish` next to the page:

- `type`: which command made it: `plan`, `review`, `verify`, `result` or `adversarial-review`.
  - The type is separate from the page `mode` (`decision` or `handoff`). For example, a decision raised while planning is type `plan`, mode `decision`.
  - Each skill passes `--type`. A missing type becomes `result`.
  - The type filter and the Flow order use `type`. The "needs your choice" tag and notification use `mode: decision`. *(builder-check call)*
- `branch`:
  - The current branch from `git rev-parse --abbrev-ref HEAD`.
  - A detached HEAD is recorded as `detached@<short sha>`.
  - A folder outside git gets no branch.
- `commit`: the short SHA of HEAD.
- `worktree`: the absolute project path the agent passed.
- `agent`: `claude`, `codex` or `unknown`.
  - The skill text tells the model to pass `--agent claude` in Claude Code and `--agent codex` in Codex. The model knows its host, and the skill files stay shared.
  - Without the flag, the publisher checks the host's own environment markers (for example `CLAUDECODE=1` in Claude Code). If neither is found, it records `unknown`.
  - This is a label for the reader, not a security boundary. *(builder-check call)*
- `created_at` and `version`, as today.

Writes and limits:

- **Atomic writes:** write to a temporary file, then `os.replace`, as `save_json` does today. A crash must never leave a half-written report that the app shows.
- **Size limits:** the 2 MiB page JSON and code limits stay. There is no retention limit in phase 1. Reports stay until the user deletes them in the app.

### 2. Companion changes (`companion.py`)

- **`publish`:**
  - Writes a new report into the store, using the layout above.
  - Takes new optional flags `--type` and `--agent`.
  - Prints the report id, project id and store path.
  - Validation, image copying and `files` reading behave exactly as today.
- **`events`:** takes `--report <id>`, which is the id printed by `publish`. Skills always pass it.
  - Without `--report`, it reads the latest decision report from the **same worktree** (the `--project` path). It never reads another worktree's report, so an agent can never act on a choice made for a different branch.
  - It returns only that report's events. *(builder-check call)*
- **When a decision closes:**
  - Reports are never overwritten, so the old "version no longer matches" rule no longer works. A new rule replaces it.
  - A decision is open until a newer report is published from the same worktree. Then it closes.
  - Choices sent to a closed decision are rejected; the Python and Rust checks use this same rule.
  - Until then, the user may change the choice, and the latest one wins, as today.
  - The "needs your choice" tag clears once a choice is saved or the decision closes. *(builder-check call)*
- **Opening the app:** after publishing, if the app is installed, run `open -g -a Showwork --args --background`.
  - In this background start, the app opens **no window** and takes no focus. It only scans the store, updates badges and sends notifications.
  - The window appears when the user clicks the notification or the dock icon.
  - If the app is missing or fails to open, nothing breaks, because the report is already saved. *(builder-check call)*
- **Browser fallback:**
  - `serve` keeps working for people without the app.
  - It shows the latest report **from the same worktree** and keeps its live update.
  - Report history stays an app feature in phase 1.
- **Plan and review reports:**
  - Today `showwork-plan` ends in chat, and opens a decision page only when a visual choice is needed. `showwork-review` never uses the companion.
  - Both now finish by publishing a handoff report, with `--type plan` or `--type review`.
  - **Plan report:** shows the outcome and acceptance criteria, the proposed behavior or visual, the decisions and assumptions, the steps, the risks, and how each criterion will be shown. The chat keeps only a short summary and the report link.
  - **Review report:** shows each finding with its severity, location and evidence, and the gaps that were not checked. A finding's code goes in the `files` accordions.
  - **Relaxed validation:** a handoff requires `checks` today. For type `plan` or `review`, `checks` may be empty, because nothing has been run yet.
  - A plan's proposed checks go in a section and never as `verified` checks. The rule "an unrun check is not proof" stays.
  - The other handoff types keep requiring checks.
- **Old storage:** `path` and `runtime.py` stay for screenshots and one-off scripts. Only reports move to the store.
- **Docs:** update `references/companion.md` and the skill files. They should say the app is the default viewer, the browser is the fallback, and each skill passes `--type`.
- **Storage policy:** the docs currently promise temporary storage. Replace that with the new policy:
  - Reports persist in the app folder and never go into the project.
  - They are deleted from the app.
  - Real code shown in reports is stored there too.

### 3. Desktop app (`app/` in this repository)

**Stack and data flow**

- Tauri 2 with a Rust backend.
- Web frontend:
  - TypeScript built with Vite.
  - Framework is the builder's call; prefer something small.
- Bundle id: `dev.showwork.app` (placeholder; change before any public release).
- The Rust backend:
  - Reads the store.
  - Watches `projects/` for new or changed reports (the `notify` crate).
  - Sends events to the frontend.
  - Sends macOS notifications with the Tauri notification plugin.
  - Writes decision choices to the report's `events.jsonl`.
  - Applies the same version check as today, so stale choices are rejected.
  - Owns `state.json`.
- The frontend never reads files directly. It only calls backend commands such as list projects, list reports, get report, submit choice, delete report, mark read and get or set the UI state.

**Report view**

- Built from the current `companion.html` rendering:
  - title, summary, decision options, sections, files accordions with the code view, and checks.
- Move that rendering into a shared module, used both by the app and by the browser fallback page, so the two never drift apart. Visual quality, the code view and the safety rules stay as they are now:
  - Section HTML in a sandboxed iframe with no scripts.
  - Text inserted as text, never as raw HTML.
  - No external resources.
- The app's webview CSP forbids remote content.

**Layout**

- **Left column: projects.**
  - Sorted by latest activity.
  - Each shows its unread count.
  - Context menu: reveal in Finder, delete project history.
- **Middle column: a segmented toggle between List and Flow.**
  - List: report cards with a type tag, title, branch and time, plus branch and type filters.
  - Flow: branch groups with their reports in time order; the newest branch is on top.
  - Selecting a report marks it read.
- **Right column: the report view.**
  - A header shows the type, branch, commit, agent and time.
  - Keep this pane a reusable component that is given one report id, so a second pane can be added later for the split panel.

**Arrivals**

- When a new report arrives:
  - The badge count goes up.
  - A notification is sent with the project name, type and title.
- Clicking the notification opens that report.
- Nothing else changes the selection.
- **On startup:** reports that arrived while the app was closed count as unread and get badges. If there are several, they share one summary notification instead of one each. *(builder-check call)*
- A decision report shows a clear "needs your choice" tag in the list and in the notification.

**Window**

- A single window.
- The app keeps running when the window is closed. Notifications and badges are the reason, so the dock icon stays.
- Whether to also add a menu bar icon is the builder's call.

### 4. Install and license

- **LICENSE:** add the MIT `LICENSE` to the repository root, with copyright "Brian Choi" and year 2026. Set `"license": "MIT"` in `package.json`, `Cargo.toml` and `tauri.conf.json`.
- **App build:** `npm`/`cargo tauri build` in `app/` produces an unsigned `.app` and `.dmg`. Personal use installs it into `/Applications`. Signing and notarization come in a later phase.
- **Skill installer:** unchanged, apart from shipping the updated companion and docs. It does not install the app.

### 5. Testing

- **Python:** extend `tests/test_companion.py` to cover:
  - Publishing creates a new report and never overwrites one.
  - Two worktrees of one repository map to one project, recording both branches.
  - Fallback identity for a folder outside git.
  - Inferred and explicit types.
  - `events` scoped to the right report.
  - Stale choices rejected.
  - Atomic writes.
  - A `plan` or `review` report publishes without checks, while a `result` report without checks is still refused.
  - No writes to the project.
  - Store permissions.
- **Rust:** unit tests for reading the store, watching it (a new report raises exactly one arrival event), choice writing with the version check, and deletion.
- **Frontend:** use Playwright against the frontend served by Vite in a browser, with the backend commands mocked. Tauri's WebDriver does not support macOS WKWebView. Cover:
  - The List and Flow toggle keeps the selection.
  - Filters.
  - The badge on arrival, without switching reports.
  - A decision submit.
  - The report view rendering, which reuses the existing browser test fixtures.
- **Manual check, then report:** build the app, publish from a real worktree in Claude Code and in Codex, and confirm:
  - The notification and badge appear.
  - Focus does not move.
  - A decision round-trip completes.
  - History survives an app restart and a reboot.

## Decided by the user

- A desktop app built with Tauri, for macOS only for now.
- MIT license.
- Phase 1 connects only through the existing Showwork skills.
- Reports are grouped by project and history is kept.
- No ticket linking for now.
- `showwork-plan` and `showwork-review` also publish reports into the app in phase 1. (Asked after the builder check; the user agreed.)
- A three-column layout with a List ⇄ Flow toggle in the middle.
- New reports and decision screens only notify; they never switch the view.
- A split panel may be needed later.
- Worktrees of one repository form one project; reports are tagged with branch, type and time. (This was proposed and then confirmed.)
- Reports live in the app folder, not in the repository, until deleted. The app opens in the background when closed. The browser remains the fallback. Old `/tmp` reports are not migrated. (Proposed and then confirmed.)

## Left to the builder (calls made in this doc are marked as such)

- The frontend framework and component structure.
- How to extract the shared renderer from `companion.html` without changing how it looks or behaves.
- Exact store schema field names, beyond those listed above.
- The notification text.
- Whether to add a menu bar icon.
- Empty states and error messages.
- The bundle id is a placeholder.
