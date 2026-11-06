# Showwork Desktop App (Phase 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Showwork reports from the chat skills are kept per project in a persistent store and shown in a macOS Tauri app instead of a pile of browser tabs. The browser stays as a fallback.

**Architecture:**
- `companion.py publish` writes each report as a new folder in a shared store (`~/Library/Application Support/Showwork`).
- A Tauri 2 app watches that store, lists projects and reports, shows a badge and a macOS notification when a report arrives, and renders reports with the same renderer the browser page uses.
- Decision choices go back through each report's `events.jsonl`, exactly as the agent reads them today.

**Tech Stack:**
- Python 3.11+, standard library only (companion).
- Tauri 2 with a Rust backend, using the `notify` and `mac-notification-sys` crates.
- TypeScript and Vite, no UI framework.
- Playwright for browser tests. It is already used by `tests/browser_companion.cjs`.

**Spec:** `docs/superpowers/specs/2026-11-05-showwork-desktop-app-design.md`

**Commit policy:** Do not commit or stage anything unless the user explicitly asks in the current task. Each task ends by reviewing the uncommitted diff.

## Global Constraints

- **Store root:**
  - `SHOWWORK_STORE` if set, which tests always set.
  - Else on macOS `~/Library/Application Support/Showwork`.
  - Else `$XDG_DATA_HOME/showwork`, falling back to `~/.local/share/showwork`.
  - Store directories are mode 0700 and owner-checked.
- **Never** write reports, captures or state inside the project directory or git.
- **Report types:** `plan`, `review`, `verify`, `result`, `adversarial-review`. A missing type means `result`. Type is separate from `mode` (`decision` | `handoff`).
- **Agent label:** `claude`, `codex` or `unknown`. It is a label for the reader, not a security check.
- **Project id:** a hash of the real path of `git rev-parse --git-common-dir`. A folder outside git uses its own real path.
- **Reports are never overwritten.** A decision is open until a newer report is published from the same worktree.
- **Focus:** a new report or decision never changes the selection or brings the app forward. It only raises a badge and a notification.
- **No network:** no remote fonts, scripts or telemetry. The webview CSP forbids remote content.
- **Licensing:** MIT. Add `LICENSE` at the repo root with "Copyright (c) 2026 Brian Choi". Set `"license": "MIT"` in `package.json`, `app/package.json`, `Cargo.toml` and `tauri.conf.json`.
- **Bundle:** id `dev.showwork.app` (placeholder), product name `Showwork`, unsigned build. Not shipped in the npm package.
- **Limits:** the existing 2 MiB page JSON, 512 KiB per file and 1.5 MiB total code limits stay.
- **App chrome language:** English labels, matching the existing report page ("Files worth reviewing", "Checks and open questions"). This is a plan call; report content stays in the author's language.

## Review Focus

1. **Two agents publish at the same moment** from two worktrees of one repo.
   - Expected: both reports are kept with distinct, correctly ordered ids, and the app never shows a half-written one.
   - Tests: Task 1 `test_concurrent_publish_keeps_both`, Task 5 `skips_pending_and_broken_reports`.
2. **A damaged store entry**, such as a report folder missing `meta.json`, invalid JSON, or a stray file under `reports/`.
   - Expected: the app skips it and lists the rest without crashing.
   - Test: Task 5 `skips_pending_and_broken_reports`.
3. **Ids from the frontend used as paths.** A `project_id` or `report_id` like `../x` or `a/b` reaching a command.
   - Expected: rejected before touching the filesystem.
   - Test: Task 5 `rejects_path_like_ids`.
4. **Odd git states:** detached HEAD, a non-git folder, or a worktree whose `git` call fails.
   - Expected: the publish still succeeds with a fallback identity and a `null` or `detached@sha` branch.
   - Test: Task 1 `test_detached_and_non_git`.
5. **Clicking an old decision after a newer report arrived**, in the app or in a stale browser tab.
   - Expected: the choice is refused and the report shows as closed.
   - Tests: Task 2 `test_closed_decision_rejects_choice`, Task 5 `submit_rejects_closed_decision`.

---

## File Structure

```
LICENSE                                         (new) MIT
package.json                                    + license, + assets/*.js|*.css in "files"
.gitignore                                      + app/node_modules, app/dist, app/src-tauri/target, app/src-tauri/gen
skills/showwork/scripts/runtime.py              + ensure_private_dir() factored out of workspace()
skills/showwork/scripts/store.py                (new) store root, project identity, git state, save/list/open/events
skills/showwork/scripts/companion.py            publish/events/serve use the store; --type/--agent/--report; app launch
skills/showwork/assets/report-view.js           (new) renderReport(): shared by browser page and app
skills/showwork/assets/report-view.css          (new) report styles moved out of companion.html
skills/showwork/assets/companion.html           becomes a thin shell: header + poll + renderReport()
skills/showwork/references/companion.md         app-first viewing, flags, storage policy, plan/review reports
skills/showwork*/SKILL.md                       pass --type/--agent, events --report; plan & review publish
docs/installation.md, README.md                 app install + storage policy lines
tests/test_store.py                             (new)
tests/test_companion.py, tests/browser_companion.cjs, tests/install_cli.cjs   updated
app/                                            (new) Tauri app
  package.json, vite.config.ts, tsconfig.json, index.html
  src/main.ts            bootstrap and column wiring
  src/api.ts             ShowworkApi type + tauriApi + mockApi (fixture-driven, for tests)
  src/model.ts           pure: filterReports, branchGroups, typeLabel
  src/views/projects.ts  left column
  src/views/middle.ts    List / Flow toggle and lists
  src/views/reportPane.ts createReportPane(): one report per pane (split-ready)
  src/styles.css
  tests/model.test.ts    node --test (Node 24 runs .ts directly)
  tests/ui.cjs           Playwright against vite dev server with the mock API
  src-tauri/Cargo.toml, tauri.conf.json, build.rs, capabilities/default.json, icons/ (scaffold defaults)
  src-tauri/src/main.rs, lib.rs   commands, window lifecycle, background launch
  src-tauri/src/store.rs          read store, submit choice, delete
  src-tauri/src/state.rs          state.json: view, read ids, last-seen cursor
  src-tauri/src/watch.rs          notify watcher → new-report callback
  src-tauri/src/notify_mac.rs     macOS notifications with click callback
  src-tauri/tests/contract.rs     publishes with real companion.py, reads with store.rs
```

### Store layout

This is the contract shared by Python, the browser page and Rust. It refines the spec: `report.json` is split into two files so that listing reads only the small one.

```
<root>/projects/<project_id>/project.json     {"id","name","common_dir","remote"}   (remote may be null)
<root>/projects/<project_id>/reports/<report_id>/meta.json
    {"id","project_id","type","mode","title","branch","commit","worktree","agent","created_at","version"}
<root>/projects/<project_id>/reports/<report_id>/page.json    validated page (+ "version","published_at")
<root>/projects/<project_id>/reports/<report_id>/assets/<sha256>.<ext>
<root>/projects/<project_id>/reports/<report_id>/events.jsonl {"version","title","choice","time"} per line
<root>/state.json                                             owned by the app
```

- **`project_id`:** the first 16 hex characters of `sha256(realpath)`.
- **`report_id`:** `UTC %Y%m%d-%H%M%S-%f` followed by `-` and 4 random hex characters, for example `20261105-210212-123456-a1b2`.
  - The spec's example is extended with microseconds so that ids sort in time order.
  - Python and Rust both order reports by `report_id` string.
- **Writing a report:** it is written into `reports/.pending-<id>/`, then renamed to `reports/<id>/`. Dot-prefixed folders are never listed.
- **Images:** the paths inside `page.json` are relative, for example `assets/<sha>.png`.
- **Ids:** valid ids match `^[A-Za-z0-9-]+$`.

---

### Task 1: Persistent report store (Python)

**Files:**
- Create: `skills/showwork/scripts/store.py`
- Modify: `skills/showwork/scripts/runtime.py`. Extract the 0700 and owner check from `workspace()` into `ensure_private_dir(path: Path) -> None` and reuse it.
- Test: `tests/test_store.py`

**Interfaces:**
- Produces, all in `store.py`:
  - `store_root() -> Path`. Creates the root and `projects/` with `ensure_private_dir`.
  - `project_identity(project: Path) -> dict` returns `{"id","name","common_dir","remote"}`.
    - `name` is the common dir's parent folder name when the common dir ends in `.git`, else the folder name.
    - `remote` is `git config --get remote.origin.url`, or `None`.
  - `git_state(project: Path) -> dict` returns `{"branch": str|None, "commit": str|None}`. A detached HEAD gives `"detached@<short sha>"`.
  - `detect_agent(explicit: str|None) -> str`.
    - The explicit value wins.
    - Else `CLAUDECODE == "1"` gives `claude`.
    - Else any environment variable starting with `CODEX_` gives `codex`.
    - Else `unknown`.
  - `new_report_id(now: datetime) -> str`.
  - `save_report(project: Path, page: dict, images: list[tuple[Path, str]], report_type: str, agent: str) -> dict`.
    - Copies each `(source, "assets/<name>")` image, writes `page.json` and `meta.json` into the pending folder, renames it into place, and writes `project.json` atomically.
    - Returns the meta dict.
  - `list_reports(project_id: str) -> list[dict]` returns metas in id order. It skips dot folders and folders with a missing or invalid `meta.json`.
  - `latest_report(project: Path, mode: str|None = None) -> dict|None` returns the newest meta with `worktree == realpath(project)`, optionally of a given mode.
  - `is_open(meta: dict) -> bool` is true when `mode == "decision"` and no later report has the same `worktree`.
  - `report_dir(meta: dict) -> Path`.
  - `read_events(meta: dict) -> list[dict]` and `append_event(meta: dict, choice: str) -> dict`. Appending writes `{"version","title","choice","time"}`.

- [ ] **Step 1: Write the failing tests in `tests/test_store.py`.** Every test sets `SHOWWORK_STORE` to a temp directory with `patch.dict(os.environ)`. Helper `git(*args, cwd)` runs git with `-c user.email=t@t -c user.name=t`.
  - `test_worktrees_share_one_project`:
    - Init a repo with one commit, then `git worktree add ../wt -b feature/x`.
    - `project_identity` of both paths has the same `id` and `name == "<repo folder>"`.
    - Saving one report from each gives two metas, branches `main`/`master` and `feature/x`, with the same `project_id`.
  - `test_detached_and_non_git`:
    - After `git checkout --detach`, `git_state()["branch"]` starts with `"detached@"`.
    - For a plain temp folder, `git_state` gives `{"branch": None, "commit": None}` and `project_identity(folder)["id"]` is the hash of its real path.
  - `test_reports_are_never_overwritten`: two `save_report` calls give two distinct folders; `list_reports` returns both in creation order.
  - `test_concurrent_publish_keeps_both`: eight threads `save_report` into one project; eight distinct ids, all listed, no `.pending-*` left.
  - `test_broken_entries_are_skipped`: create `reports/.pending-x/`, `reports/bad/` with `meta.json` set to `"{"`, and a stray file `reports/note.txt`. `list_reports` returns only the valid report.
  - `test_store_is_private`: the root and `projects/` are mode `0o700`.
  - `test_decision_open_until_newer_report_from_same_worktree`:
    - A decision from worktree A is open.
    - A handoff from worktree B leaves it open.
    - A handoff from worktree A closes it (`is_open` False).
  - `test_agent_detection`:
    - `detect_agent("codex") == "codex"`.
    - With `CLAUDECODE=1`, `None` gives `"claude"`.
    - With only `CODEX_SANDBOX=1`, `None` gives `"codex"`.
    - With an empty environment, `None` gives `"unknown"`.

- [ ] **Step 2: Run** `python3 -m unittest tests.test_store -v`. **Expected:** errors on `import store` / `ModuleNotFoundError`.

- [ ] **Step 3: Implement `store.py`** with the interfaces above.
  - Run git through `subprocess.run(["git", "-C", str(project), ...], capture_output=True, text=True, timeout=5)`. Any failure means "no git".
  - Use `--path-format=absolute --git-common-dir`.
  - Write `project.json` with temp file + `os.replace`. Concurrent writes may race, but they write identical content.

- [ ] **Step 4: Run** `python3 -m unittest tests.test_store -v`. **Expected:** all pass.

- [ ] **Step 5: Review** with `git status --short && git diff -- skills/showwork/scripts tests/test_store.py`.

---

### Task 2: Companion publishes into the store

**Files:**
- Modify: `skills/showwork/scripts/companion.py`
- Test: `tests/test_companion.py`

**Interfaces:**
- Consumes: everything in Task 1's `store.py`.
- Produces:
  - `validate(page: dict, report_type: str = "result") -> dict`. A handoff still needs `sections`. `checks` may be empty only when `report_type in ("plan", "review")`.
  - `publish(project, source, report_type: str | None = None, agent: str | None = None) -> dict` returns the saved page plus `"report": meta`.
    - Image paths become `assets/<sha>.<ext>`.
    - `files` code is still read by `attach_code`.
  - CLI:
    - `publish --type {plan,review,verify,result,adversarial-review} --agent {claude,codex}` prints `{"published": version, "mode", "report": id, "project": project_id, "path": report_dir, "app": "opened"|"missing"|"disabled"}`.
    - `events [--report ID]` prints `{"report": id, "version", "open": bool, "events": [...]}`. Without `--report`, it uses `latest_report(project, "decision")`; with no report it prints `{"report": null, "events": []}`.
  - App launch:
    - `open_app() -> str` runs `open -g -a Showwork --args --background` on macOS with `capture_output`.
    - It returns `"disabled"` when `SHOWWORK_NO_APP=1` or the OS is not macOS, `"opened"` on exit code 0, and `"missing"` otherwise.
    - It never raises.
  - Server:
    - `GET /api/view` returns `{"page": page|null, "report": id|null}` for `latest_report(project)`.
    - `GET /assets/<name>` serves from that report's `assets/`.
    - `POST /api/choice {version, choice}` finds the report in this worktree whose `version` matches.
      - No match, or a closed decision, gives 409.
      - Otherwise it calls `append_event`.
    - `GET /report-view.js` and `GET /report-view.css` are served from `assets/`.
    - Keep the `server.json` and temp `workspace` behavior.

- [ ] **Step 1: Update and extend `tests/test_companion.py`.**
  - In `setUp`, patch the environment: `SHOWWORK_STORE` to a temp folder and `SHOWWORK_NO_APP=1`.
  - Keep every existing test passing with these adjustments:
    - The image test fetches `"/" + published["sections"][0]["image"]`.
    - The events CLI test expects the new keys.
  - Add these tests:
    - `test_each_publish_creates_a_new_report`: two publishes give two `report` ids, and `list_reports` has 2.
    - `test_plan_and_review_may_omit_checks`:
      - A handoff without `checks` publishes with `report_type="plan"` and with `"review"`.
      - It raises `ValueError` with `"result"`.
    - `test_type_and_agent_recorded`: `publish(..., report_type="verify", agent="codex")["report"]` has `type == "verify"` and `agent == "codex"`. With no type, `type == "result"`.
    - `test_events_scoped_to_worktree`:
      - Use two temp project folders under one fake repo (worktree setup as in Task 1).
      - A decision is published in A and a choice posted for it.
      - `events` for B prints `{"report": null, "events": []}`.
    - `test_closed_decision_rejects_choice`:
      - Publish decision D, then a handoff from the same project.
      - POST a choice with D's version returns 409.
      - The `events.jsonl` of D is absent.
    - `test_publish_never_writes_project`: after publishing, the project folder holds only the files the test created.
    - `test_publish_without_app_reports_disabled`: the CLI `publish` output has `"app": "disabled"`.

- [ ] **Step 2: Run** `python3 -m unittest tests.test_companion -v`. **Expected:** the new tests fail.

- [ ] **Step 3: Implement the changes in `companion.py`.**
  - Remove the single `page.json` write.
  - The images validated in `publish` become the `images` list for `save_report`.
  - The server needs the worktree path, so store `self.project = Path(project).resolve()` on `CompanionServer`.

- [ ] **Step 4: Run** `python3 -m unittest discover -s tests -p 'test_*.py' -v`. **Expected:** `test_companion` and `test_store` pass. The 4 pre-existing failures noted on this branch (`test_install` /var paths, `test_evidence` cwd, `move_after`) fail exactly as on `git stash` HEAD and no others.

- [ ] **Step 5: Review** with `git diff -- skills/showwork/scripts/companion.py tests/test_companion.py`.

---

### Task 3: Shared report renderer

**Files:**
- Create: `skills/showwork/assets/report-view.js`, `skills/showwork/assets/report-view.css`
- Modify:
  - `skills/showwork/assets/companion.html`
  - `package.json`: add `"skills/*/assets/*.js"` and `"skills/*/assets/*.css"` to `files`, and add `"license": "MIT"`.
  - `tests/browser_companion.cjs`
  - `tests/install_cli.cjs`: also assert that `assets/report-view.js` is installed.
- Create: `LICENSE`

**Interfaces:**
- Produces `report-view.js`, an ES module:
  ```js
  export function renderReport(root, page, hooks) // -> { destroy() }
  // hooks: { submitChoice(choiceId) -> Promise<void>, assetUrl(relativePath) -> string,
  //          connected() -> boolean, idPrefix?: string }
  ```
  - It builds the whole current report DOM inside `root`: mode eyebrow, title, summary, decision options and submit, contents nav, sections, files accordions with the code view, checks and footer.
  - Element ids are the current ones (`section-N`, `file-N`, `files`, `contents`, …) prefixed by `idPrefix`, which is empty by default.
  - It inserts text as text only. Section HTML stays in an `iframe sandbox="allow-same-origin"`.
  - `destroy()` disconnects the ResizeObservers.
- `companion.html` keeps:
  - the header and connection status
  - `poll()` against `/api/view`
  - `<script type="module">` that imports `/report-view.js`, links `/report-view.css`, and calls `renderReport` with `submitChoice` posting `/api/choice` and `assetUrl = p => "/" + p`.

- [ ] **Step 1: Run** `SHOWWORK_CHROMIUM="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" NODE_PATH=/Users/brianchoi/personal/handeye/node_modules node tests/browser_companion.cjs` before any change. **Expected:** `"passed": true`, the baseline.

- [ ] **Step 2: Update the browser test.** Set `SHOWWORK_STORE` and `SHOWWORK_NO_APP=1` in the spawned server and publish environments. Add these assertions:
  - The request for `/report-view.js` is same-origin, and no request leaves `127.0.0.1`. Use `page.on('request')` and collect hosts.
  - `await page.evaluate(() => typeof window.renderReport)` is `"undefined"`, which proves the module is not leaking globals.

- [ ] **Step 3: Move the CSS and JS.** Move them from `companion.html` into the two asset files with no change in behavior, then rewire the page as above. Add `LICENSE` (MIT, "Copyright (c) 2026 Brian Choi").

- [ ] **Step 4: Run** the browser test from Step 1, then `npm test`. **Expected:** `"passed": true` with every previous check plus the new ones. `npm test` passes.

- [ ] **Step 5: Review** with `git diff --stat` and confirm `companion.html` holds only the shell.

---

### Task 4: Skills and docs use the app and the new flags

**Files:**
- Modify:
  - `skills/showwork/references/companion.md`
  - `skills/showwork/SKILL.md`
  - `skills/showwork-plan/SKILL.md`
  - `skills/showwork-review/SKILL.md`
  - `skills/showwork-verify/SKILL.md`
  - `skills/showwork-adverial-review/SKILL.md`
  - `docs/installation.md`
  - `README.md`

**Interfaces:**
- Consumes the Task 2 CLI: `publish --type --agent`, its `report` and `app` output, and `events --report`.

- [ ] **Step 1: Edit `companion.md`.**
  - "Start the browser" becomes "Show the report":
    - Publish first.
    - If the output says `"app": "opened"`, tell the user the report is in the Showwork app and do not start `serve`.
    - Otherwise start `serve` as today and share the URL.
  - Pass `--agent claude` in Claude Code and `--agent codex` in Codex, plus the command's `--type`.
  - Read decisions with `events --report <id from publish>`.
  - Replace the temporary-storage policy paragraph and the Limits paragraph with the spec's wording:
    - Reports persist in the app folder until deleted from the app.
    - They are never put in the project.
    - Captures and scripts still go in the `companion.py path` temp folder.
  - Plan and review reports may omit `checks`. Proposed checks go in a section and are never `verified`.
- [ ] **Step 2: Edit the skills.**
  - Each skill's publish line names its `--type`: `result` for `showwork`, `plan`, `review`, `verify`, `adversarial-review`.
  - `showwork-plan` ends by publishing a plan report with these parts:
    - the outcome and acceptance criteria
    - the proposed behavior or visual
    - the decisions and assumptions
    - the steps
    - the risks
    - how each criterion will be demonstrated
  - `showwork-review` ends by publishing a review report: findings with severity, location and evidence, the unchecked gaps, and finding code in `files`.
  - The chat keeps a short summary.
- [ ] **Step 3: Docs.** Add an "App (macOS)" section to `docs/installation.md` (build in `app/` and copy `Showwork.app` to `/Applications`), and one line in `README.md`.
- [ ] **Step 4: Run** `npm test && python3 -m unittest tests.test_companion tests.test_store`. **Expected:** pass. Run `grep -n "\-\-type" skills/*/SKILL.md` and expect one hit per publishing skill (5).
- [ ] **Step 5: Review** with `git diff -- skills docs README.md`.

---

### Task 5: Tauri scaffold and Rust store reader

**Files:**
- Create: `app/` via `npm create tauri-app@latest app -- -t vanilla-ts -m npm -y`, run from the repo root. Then:
  - Set `productName: "Showwork"`, `identifier: "dev.showwork.app"`, `version: "0.1.0"` and `bundle.license: "MIT"` in `app/src-tauri/tauri.conf.json`.
  - Set `license = "MIT"` in `Cargo.toml` and `"license": "MIT"` in `app/package.json`.
  - Make the main window `visible: false` with title `Showwork`.
  - Set the CSP to `default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' asset: http://asset.localhost data:; frame-src 'self' about:; connect-src ipc: http://ipc.localhost`.
  - Enable `assetProtocol` with scope `$HOME/Library/Application Support/Showwork/projects/**`, and the `protocol-asset` feature on `tauri`.
  - Add the `.gitignore` lines from File Structure.
- Create: `app/src-tauri/src/store.rs`, `app/src-tauri/tests/contract.rs`

**Interfaces:**
- Produces (`store.rs`, serde types are `rename_all = "camelCase"` for output and read the snake_case store files):
  ```rust
  pub fn store_root() -> PathBuf                  // same rules as Python store_root (no dir creation)
  pub struct Store { pub root: PathBuf }
  #[derive(Serialize, Clone)] pub struct ProjectSummary { id, name, display_name, remote: Option<String>, last_activity: Option<String>, unread: usize }
  #[derive(Serialize, Clone)] pub struct ReportMeta { id, project_id, r#type, mode, title, branch: Option<String>, commit: Option<String>, worktree, agent, created_at, version, open: bool, chosen: bool }
  #[derive(Serialize)] pub struct ReportDetail { meta: ReportMeta, page: serde_json::Value, dir: String }
  pub enum StoreError { BadId, NotFound, NotADecision, Closed, StaleVersion, UnknownChoice, Io(String) } // Display -> short English message
  impl Store {
    pub fn list_projects(&self, read: &BTreeSet<String>) -> Result<Vec<ProjectSummary>, StoreError> // newest activity first
    pub fn list_reports(&self, project_id: &str) -> Result<Vec<ReportMeta>, StoreError>            // newest first
    pub fn get_report(&self, project_id: &str, report_id: &str) -> Result<ReportDetail, StoreError>
    pub fn submit_choice(&self, project_id: &str, report_id: &str, version: &str, choice: &str) -> Result<(), StoreError>
    pub fn delete_report(&self, project_id: &str, report_id: &str) -> Result<(), StoreError>
    pub fn delete_project(&self, project_id: &str) -> Result<(), StoreError>
    pub fn all_report_ids(&self) -> Vec<(String, String)>   // (project_id, report_id), for watcher/startup
  }
  ```
  - `display_name` is `name`, or `name (owner/repo)` when the name is shared and a remote exists. Parse `owner/repo` from the remote URL, or use the worktree parent folder when there is no remote.
  - `open` follows the same rule as Python `is_open`.
  - `chosen` is true when `events.jsonl` has a line with the current `version`.
  - `submit_choice` appends the same JSON line shape Python writes, `{"version","title","choice","time"}` with `time` in RFC 3339 UTC.

- [ ] **Step 1: Write failing tests.** Use `#[cfg(test)]` in `store.rs`, with fixtures written into `tempfile::TempDir` exactly per Store layout.
  - `lists_projects_newest_first_with_unread_counts`
  - `display_name_disambiguates_same_named_repos`
  - `lists_reports_newest_first_and_flags_open_decision`
  - `skips_pending_and_broken_reports`: covers `.pending-x`, invalid `meta.json`, a stray file, and a report whose `page.json` is invalid but `meta.json` is valid. That last one is still listed, and `get_report` returns `Io`.
  - `rejects_path_like_ids`: `"../x"`, `"a/b"` and `""` give `BadId` for every method.
  - `submit_rejects_closed_decision`, `submit_rejects_stale_version`, `submit_rejects_unknown_choice` and `submit_appends_event_line`.
  - `delete_report_removes_folder`
  - Contract test, `tests/contract.rs`:
    - With `SHOWWORK_STORE` set to a temp dir and `SHOWWORK_NO_APP=1`, run `python3 ../../skills/showwork/scripts/companion.py publish --project <temp git repo> --file <fixture decision json> --type plan --agent claude`.
    - Then `Store::list_projects` and `list_reports` see one project and one report with `type == "plan"`, `mode == "decision"`, `agent == "claude"` and `open == true`.
    - `submit_choice` succeeds, and `companion.py events --project <repo>` prints that choice.
- [ ] **Step 2: Run** `cd app/src-tauri && cargo test`. **Expected:** compile errors for the missing items.
- [ ] **Step 3: Implement `store.rs`.** Add the dev-dependency `tempfile` and the dependencies `serde`, `serde_json` and `chrono` (for `time`).
- [ ] **Step 4: Run** `cargo test`. **Expected:** all pass, including `contract`.
- [ ] **Step 5: Review** with `git status --short` (no `target/` or `node_modules/` listed) and `git diff -- .gitignore`.

---

### Task 6: App backend: state, watcher, notifications, window lifecycle

**Files:**
- Create: `app/src-tauri/src/state.rs`, `watch.rs`, `notify_mac.rs`
- Modify: `app/src-tauri/src/lib.rs`, `main.rs`, `capabilities/default.json`

**Interfaces:**
- Consumes: Task 5's `Store`, `ReportMeta` and `all_report_ids`.
- Produces:
  - `state.rs`:
    - `#[derive(Serialize, Deserialize, Default)] pub struct UiState { view: View /* "list" | "flow", default list */, read: BTreeSet<String>, last_seen: Option<String> /* max report_id seen */ }`
    - Functions:
      - `load(root) -> UiState`. A missing or invalid file gives the default.
      - `save(&self, root) -> io::Result<()>`, which writes atomically.
      - `mark_read(&mut self, id)`.
      - `unseen_since_last_run(&self, ids: &[(String, String)]) -> Vec<(String, String)>`, which returns ids greater than `last_seen`.
  - `watch.rs`: `pub fn start(store: Store, on_new: impl Fn(String, String) + Send + 'static) -> notify::Result<RecommendedWatcher>`.
    - It watches `<root>/projects` recursively.
    - On any event, it rescans `all_report_ids()` and calls `on_new` once for each id not seen before. The known set is seeded at start.
  - `notify_mac.rs`: `pub fn show(title: &str, body: &str, on_click: impl FnOnce() + Send + 'static)`.
    - Uses `mac_notification_sys`, with `set_application("dev.showwork.app")` once.
    - A background thread waits with `wait_for_click(true)` and calls `on_click` on `NotificationResponse::Click`.
  - Tauri commands, all returning `Result<_, String>`:
    - `list_projects() -> Vec<ProjectSummary>`, which applies `UiState.read`
    - `list_reports(project_id)`
    - `get_report(project_id, report_id)`
    - `submit_choice(project_id, report_id, version, choice)`
    - `mark_read(report_id)`
    - `get_state() -> { view }`
    - `set_view(view)`
    - `delete_report(project_id, report_id)`
    - `delete_project(project_id)`
    - `reveal_project(project_id)`, which runs `open -R <worktree of newest report>`
  - Events to the frontend:
    - `"report-arrived"` with `{ projectId, reportId }`
    - `"open-report"` with `{ projectId, reportId }`
  - Window behavior:
    - Show the main window in `setup` unless `std::env::args()` contains `--background`.
    - `RunEvent::Reopen` shows and focuses the window.
    - `WindowEvent::CloseRequested` hides the window and calls `prevent_close`, so the app keeps running.
  - Arrivals:
    - The notification title is `"{display_name} · {Type}"`.
    - The body is the report title, prefixed with `"Needs your choice: "` for an open decision.
    - A click shows and focuses the window and emits `open-report`.
  - Startup:
    - Compute `unseen_since_last_run`.
    - Exactly one unseen report gets its own notification. More than one gets one summary notification, `"Showwork"` / `"{n} new reports"`, whose click opens the newest.
    - Then set `last_seen` and save.

- [ ] **Step 1: Write failing tests.**
  - In `state.rs`:
    - `default_when_missing_or_invalid`
    - `roundtrip_keeps_view_read_and_cursor`
    - `unseen_returns_only_ids_after_cursor`
  - In `watch.rs`:
    - `new_report_fires_exactly_once`: renaming `.pending-a` to `a` fires one `on_new` within 3 s, and a later `meta.json` rewrite in `a` does not fire again.
    - `pending_folder_alone_does_not_fire`
- [ ] **Step 2: Run** `cargo test`. **Expected:** the new tests fail.
- [ ] **Step 3: Implement.** Add the dependencies `notify` and `mac-notification-sys`, at their current majors. Keep `UiState` in `Mutex` app state and `Store` in managed state.
- [ ] **Step 4: Run** `cargo test`. **Expected:** pass.
- [ ] **Step 5: Manual spike (mandatory, before Task 7).**
  - Run `npm run tauri build -- --debug` and launch the built `.app`, because notifications need a bundled app.
  - Publish a report with `companion.py publish` into the real store.
  - Confirm that:
    - The notification appears.
    - A click brings the window forward on that report. The `open-report` event can be logged with `console.log` for now.
  - If the click callback does not fire on this macOS version:
    - Fall back: the notification still shows.
    - `RunEvent::Reopen`, or the window becoming visible, opens the most recently notified unread report.
    - Write the outcome in the task report.
- [ ] **Step 6: Review** with `git diff --stat -- app/src-tauri`.

---

### Task 7: Frontend: projects, List/Flow, report pane

**Files:**
- Create: `app/src/api.ts`, `model.ts`, `views/projects.ts`, `views/middle.ts`, `views/reportPane.ts`, `styles.css`, `tests/model.test.ts`, `tests/ui.cjs`
- Modify:
  - `app/index.html`: the three column containers.
  - `app/src/main.ts`
  - `app/vite.config.ts`: `server.fs.allow` includes `../skills/showwork/assets`, and an alias `@report-view` points at `../skills/showwork/assets/report-view.js` and `.css`.

**Interfaces:**
- Consumes:
  - the Task 6 commands and events, through `@tauri-apps/api` `invoke` and `listen`, plus `convertFileSrc`
  - Task 3's `renderReport`
- Produces, in `api.ts`:
  ```ts
  export type View = 'list' | 'flow';
  export interface ShowworkApi {
    listProjects(): Promise<ProjectSummary[]>; listReports(projectId: string): Promise<ReportMeta[]>;
    getReport(projectId: string, reportId: string): Promise<ReportDetail>;
    submitChoice(projectId: string, reportId: string, version: string, choice: string): Promise<void>;
    markRead(reportId: string): Promise<void>; getState(): Promise<{ view: View }>; setView(view: View): Promise<void>;
    deleteReport(projectId: string, reportId: string): Promise<void>; deleteProject(projectId: string): Promise<void>;
    revealProject(projectId: string): Promise<void>;
    onArrival(cb: (p: { projectId: string; reportId: string }) => void): void;
    onOpenReport(cb: (p: { projectId: string; reportId: string }) => void): void;
    assetUrl(dir: string, relative: string): string;
  }
  export function createApi(): ShowworkApi // tauriApi when window.__TAURI_INTERNALS__ exists, else mockApi(window.__SHOWWORK_FIXTURE__)
  ```
  - The `mockApi` is in-memory. It exposes `window.__showworkMock.arrive(projectId, meta, page)` so tests can trigger arrivals.
- `model.ts`, pure with no imports:
  - `filterReports(reports, { branch?: string, type?: string }): ReportMeta[]`
  - `branchGroups(reports): { branch: string, latest: string, reports: ReportMeta[] }[]`.
    - Groups are ordered by newest report.
    - Reports inside a group are in time order.
    - A `null` branch is grouped as `"(no branch)"`.
  - `typeLabel(type): string` gives `Plan`, `Review`, `Verify`, `Result` or `Adversarial review`.
- `reportPane.ts`: `createReportPane(container: HTMLElement, api: ShowworkApi): { show(projectId: string, reportId: string): Promise<void> }`.
  - It shows one pane with a header (type, branch, commit, agent, time, and a "Needs your choice" tag when open and not chosen), then `renderReport(...)`.
  - The `idPrefix` is unique per pane, so a second pane can be added later.

- [ ] **Step 1: Write failing tests.**
  - `app/tests/model.test.ts` with `node:test` and `node:assert/strict`:
    - `filter by branch and type`
    - `flow groups newest branch first, items oldest→newest`
    - `null branch grouped as (no branch)`
  - `app/tests/ui.cjs`, a Playwright script with the same style and env as `tests/browser_companion.cjs`:
    - It starts `npx vite --port 5179 --strictPort` in `app/` and injects the fixture through `addInitScript`.
    - The fixture has two projects. One project has two branches with a plan → review → result chain and one open decision.
    - Assertions:
      - The project list shows unread counts.
      - Selecting a report renders its title and its files accordion.
      - Switching List → Flow keeps the same report selected (`aria-current="true"` on its item in both views).
      - The view choice survives a reload, because the mock persists `setView`.
      - `__showworkMock.arrive(...)` increases the badge but leaves the right pane's title unchanged.
      - The branch and type filters narrow the list.
      - Submitting the decision calls `submitChoice` with the right ids and version, then shows the saved state.
      - No request leaves `localhost`.
      - At a width of 390 px there is no horizontal overflow, and the page shows no errors.
- [ ] **Step 2: Run** `cd app && node --test tests/model.test.ts`, then `SHOWWORK_CHROMIUM=... NODE_PATH=... node tests/ui.cjs`. **Expected:** both fail.
- [ ] **Step 3: Implement the views and model.**
  - Selection is `{ projectId, reportId }` held in `main.ts`. Views only receive it and report changes, and selecting a report calls `markRead`.
  - Arrivals refresh the project list and the middle list without changing the selection.
  - `onOpenReport` is the only path that changes the selection from outside.
  - The project context menu (Reveal in Finder, Delete history) uses a small custom menu and calls the API.
- [ ] **Step 4: Run** both test commands from Step 2. **Expected:** pass.
- [ ] **Step 5: Review** with `git diff --stat -- app`.

---

### Task 8: Build, install, end-to-end check

**Files:** none new. Fixes go to the task that owns the code.

- [ ] **Step 1: Run every automated check.**
  - `python3 -m unittest discover -s tests -v`: only the 4 known pre-existing failures.
  - `npm test`
  - both browser scripts
  - `cd app/src-tauri && cargo test`
  - `cd app && node --test tests/model.test.ts && node tests/ui.cjs`

  **Expected:** all pass.
- [ ] **Step 2: Build and install.**
  - Run `cd app && npm run tauri build`, then copy `src-tauri/target/release/bundle/macos/Showwork.app` to `/Applications`.
  - Run `env -u CLAUDE_CONFIG_DIR python3 scripts/install_codex.py` to install the updated skills.
- [ ] **Step 3: Manual checks.** Record each one as pass or fail with what was observed.
  1. With the app quit, `/showwork` in Claude Code on a worktree of a real repo shows:
     - a notification
     - no window and no focus change
     - the badge on the project once the window is opened from the Dock
  2. The same from Codex in a second worktree of that repo lands under the same project with its own branch, and `agent` shows `codex`.
  3. While reading an older report, a new one arrives: the selection is unchanged and the badge increases.
  4. A `showwork-plan` decision is chosen in the app, and the agent's `events --report <id>` returns it. After a newer report from that worktree, the decision shows as closed.
  5. History is still listed after the app quits and relaunches, and after a reboot.
  6. Without the app (rename it temporarily), `publish` prints `"app": "missing"`, and `serve` shows the report in the browser.
- [ ] **Step 4: Review.** Run `git status --short` and report the changed files. Do not commit.
