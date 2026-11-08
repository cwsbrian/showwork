# Live Sessions (tabs + in-app browser) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Each Showwork task gets tabs in the app's right pane — Report, one live tab per headless browser the agent opens, and a Split preview — so captures happen inside the app instead of in windows on the user's desktop.

**Architecture:** The Python companion owns processes: `start` gives each task a unique run id, `browser open` launches headless system Chrome for the current run and records a session file, and publish/stop close the run's browsers. The Rust app only reads run markers and session files and tells the webview when they change. The webview connects to each live browser over CDP from JavaScript: `Page.startScreencast` for frames, `Input.dispatch*Event` for the user's clicks and keys.

**Tech Stack:** Python 3.11 stdlib (companion), Rust + Tauri 2 (app backend), TypeScript + Vite (app UI), Chrome DevTools Protocol, Playwright (agent side and tests).

**Spec:** `docs/superpowers/specs/2026-11-06-live-sessions-design.md`

## Global Constraints

- Commit policy: never commit; leave every change uncommitted; do not stage.
- Tests never touch the real store: every test/run that writes uses `SHOWWORK_STORE=<fresh temp dir>` and `SHOWWORK_NO_APP=1`. Never launch, kill or reinstall `/Applications/Showwork.app`.
- Browser is the system Chrome, headless: path from `SHOWWORK_CHROMIUM`, else `/Applications/Google Chrome.app/Contents/MacOS/Google Chrome`, else `/Applications/Chromium.app/Contents/MacOS/Chromium`.
- Chrome args, exactly: `--headless=new --remote-debugging-port=0 --remote-allow-origins=<origins> --user-data-dir=<temp profile> --window-size=<w>,<h> --no-first-run --no-default-browser-check --disable-background-networking --hide-scrollbars --mute-audio <url>`. `<origins>` = `SHOWWORK_BROWSER_ORIGINS` or `tauri://localhost,http://localhost:1420`.
- Default browser size 1280×800.
- Store layout additions: `projects/<pid>/running/<run_id>.json` (marker file named by the unique run id) and `projects/<pid>/sessions/<session_id>.json`. Ids match `\A[A-Za-z0-9-]+\Z`.
- Session file fields (snake_case on disk): `id, project_id, run, kind ("browser"), title (str|null), url, width, height, port, ws, pid, profile, started_at, ended_at (null while open)`.
- Report `meta.json` gains `run` (str|null): the run id of the task that published it.
- The app never starts or kills browsers. Python writes session files; Rust only reads them and deletes an ended one on the user's request.
- UI copy (exact): tab `Report`; split tab `Split`; running-task report placeholder `Working on it. The report appears here when it is ready.`; ended tab label suffix ` · ended`; connection failure `Could not connect to this browser.`
- Test env for UI: `SHOWWORK_CHROMIUM="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" NODE_PATH=/Users/brianchoi/personal/handeye/node_modules`.

## Review Focus

- Chrome not installed or exits at once → `browser open` fails with a clear message and leaves no session file or profile folder (Task 2 test `test_open_fails_cleanly_without_chrome`).
- The agent dies mid-task, so its browsers are never closed → the next `start` in that project closes sessions whose run marker is gone (Task 2 test `test_start_closes_orphaned_browsers`).
- A browser that died without `ended_at` → the app shows the tab as ended instead of a frozen screen (Task 3 test `sessions_report_dead_processes_as_ended`; Task 5 shows `Could not connect to this browser.` on a dead socket).
- Clicks on a scaled-down screen land on the right element in the page (Task 5 test clicks a button in the page through the app and checks the page saw it).
- Switching tasks quickly must close the old task's sockets so its frames never paint into the new task (Task 5 test checks `window.__showworkLiveCount` drops to 0).

---

## File Structure

- `skills/showwork/scripts/store.py` — run markers with unique ids; `meta.run`; session file helpers (`sessions_dir`, `list_sessions`, `write_session`).
- `skills/showwork/scripts/browser.py` (new) — find/launch/close headless Chrome; owns process lifetime.
- `skills/showwork/scripts/companion.py` — `start`/`stop` changes, new `browser open|close` CLI; publish closes the run's browsers.
- `app/src-tauri/src/store.rs` — `ReportMeta.run`, `SessionItem`, `list_sessions`, `delete_session`, `all_sessions`.
- `app/src-tauri/src/watch.rs`, `lib.rs` — emit `running-changed` on session changes too; new commands; `tauri.conf.json` CSP.
- `app/src/model.ts`, `api.ts` — `SessionItem`, `listSessions`, `deleteSession`, mock support.
- `app/src/views/tabs.ts` (new) — tab bar, per-task active tab, split grid.
- `app/src/cdp.ts` (new) — minimal CDP screencast + input client.
- `app/src/views/sessionView.ts` (new) — one live screen, interactive or preview.
- `app/src/main.ts`, `views/middle.ts`, `index.html`, `styles.css` — running items selectable, tab host.
- `skills/showwork/references/companion.md` and the command `SKILL.md` files — use the in-app browser for web captures.

---

### Task 1: Unique run ids and `meta.run`

**Files:**
- Modify: `skills/showwork/scripts/store.py` (`run_path`, `start_run`, `finish_run`, `save_report`)
- Modify: `skills/showwork/scripts/companion.py` (`start`, `stop` actions)
- Test: `tests/test_store.py`, `tests/test_companion.py::test_start_shows_a_working_marker_until_publish_or_stop`

**Interfaces:**
- Produces: `store.start_run(project, report_type, agent, title=None) -> dict` (marker; `id` is a fresh `new_report_id`), `store.current_run(project_id, worktree, report_type) -> dict | None` (newest matching marker), `store.finish_run(project_id, worktree, report_type) -> str | None` (deletes all matching markers, returns the newest one's id). `save_report` sets `meta["run"]`.
- Remove `run_path`. Marker file = `running/<id>.json`; `start_run` deletes other markers with the same `worktree` and `type` before writing.

- [ ] **Step 1: Write the failing tests** in `tests/test_store.py`

```python
def test_each_start_gets_a_new_run_and_replaces_the_same_kind(self):
    repo = self.repo()
    a = STORE.start_run(repo, "review", "claude")
    b = STORE.start_run(repo, "review", "claude")
    STORE.start_run(repo, "plan", "claude")
    self.assertNotEqual(a["id"], b["id"])
    running = STORE.store_root() / "projects" / a["project_id"] / "running"
    self.assertEqual(sorted(p.stem for p in running.glob("*.json")), sorted([b["id"], STORE.current_run(a["project_id"], a["worktree"], "plan")["id"]]))

def test_published_report_records_its_run_and_ends_it(self):
    repo = self.repo()
    run = STORE.start_run(repo, "review", "claude")
    meta = STORE.save_report(repo, page(), [], "review", "claude")
    self.assertEqual(meta["run"], run["id"])
    self.assertIsNone(STORE.current_run(meta["project_id"], meta["worktree"], "review"))
    self.assertIsNone(STORE.save_report(repo, page(), [], "review", "claude")["run"])
```

In `tests/test_companion.py`, change the "starting the same type again" assertion to: a second `start --type review` returns a different `run` and the `running` folder still holds exactly one review marker.

- [ ] **Step 2: Run them to verify they fail**

Run: `SHOWWORK_NO_APP=1 python3 -m unittest tests.test_store tests.test_companion`
Expected: FAIL (`current_run` missing; ids equal).

- [ ] **Step 3: Implement** the Interfaces above. `stop` calls `finish_run` (Task 2 adds closing its browsers).

- [ ] **Step 4: Run the tests to verify they pass** (same command). Expected: OK.

- [ ] **Step 5: Review** `git diff -- skills/showwork/scripts tests`.

---

### Task 2: Headless browser sessions in the companion

**Files:**
- Create: `skills/showwork/scripts/browser.py`
- Modify: `skills/showwork/scripts/store.py` (session helpers), `skills/showwork/scripts/companion.py` (CLI, publish/stop/start hooks)
- Test: `tests/test_browser.py` (new; `@unittest.skipUnless(chrome found)`)

**Interfaces:**
- Consumes: `store.current_run` / `finish_run` from Task 1.
- Produces:
  - `store.sessions_dir(project_id) -> Path`, `store.list_sessions(project_id, run_id=None) -> list[dict]`, `store.write_session(session: dict) -> None` (atomic via `write_json`).
  - `browser.find_chrome() -> str` (raises `ValueError("Chrome not found; set SHOWWORK_CHROMIUM")`).
  - `browser.open_browser(project, url, title=None, width=1280, height=800) -> dict` — uses the newest run marker of the project's worktree (any type); raises `ValueError("Run companion.py start first")` when none.
  - `browser.close_browser(project_id, session_id) -> dict` — SIGTERM, then SIGKILL after 3 s; deletes the profile folder; sets `ended_at`. Closing an already ended session is a no-op.
  - `browser.close_run(project_id, run_id) -> None`, `browser.close_orphans(project_id) -> None` (open sessions whose `run` has no marker).
  - CLI: `companion.py browser open --project P --url U [--title T] [--width N] [--height N]` prints `{"session", "run", "cdp": "http://127.0.0.1:<port>", "ws"}`; `companion.py browser close --project P --session S` prints `{"closed": S}`.
  - `save_report` → after the rename, `browser.close_run(project_id, meta["run"])` when `run` is set. `stop` closes the stopped run's browsers. `start` calls `close_orphans` first.

Launch details: profile = `tempfile.mkdtemp(prefix="showwork-browser-")`; `subprocess.Popen(args, stdin/stdout/stderr=DEVNULL, start_new_session=True)`; poll up to 15 s for `<profile>/DevToolsActivePort` (port on line 1) and then for a `type == "page"` entry with `webSocketDebuggerUrl` from `http://127.0.0.1:<port>/json/list`. On any failure: kill the process, delete the profile, write no session file, raise `ValueError` with the reason.

- [ ] **Step 1: Write the failing tests** in `tests/test_browser.py` (setUp: temp git repo as project, temp `SHOWWORK_STORE`, `SHOWWORK_NO_APP=1`; tearDown closes any open sessions)

```python
def test_open_requires_a_started_task(self):
    with self.assertRaisesRegex(ValueError, "start first"):
        BROWSER.open_browser(self.project, "about:blank")

def test_open_starts_headless_chrome_and_close_ends_it(self):
    run = STORE.start_run(self.project, "result", "claude")
    s = BROWSER.open_browser(self.project, "data:text/html,<h1>hi</h1>", width=800, height=600)
    self.assertEqual((s["kind"], s["run"], s["width"], s["height"], s["ended_at"]), ("browser", run["id"], 800, 600, None))
    self.assertTrue(s["ws"].startswith(f"ws://127.0.0.1:{s['port']}/devtools/page/"))
    urlopen(f"http://127.0.0.1:{s['port']}/json/version", timeout=3).close()
    self.assertEqual([x["id"] for x in STORE.list_sessions(s["project_id"], run["id"])], [s["id"]])
    ended = BROWSER.close_browser(s["project_id"], s["id"])
    self.assertIsNotNone(ended["ended_at"])
    self.assertFalse(Path(s["profile"]).exists())
    self.assertTrue(wait_until(lambda: not pid_alive(s["pid"]), 5))

def test_publish_and_stop_close_the_tasks_browsers(self):
    STORE.start_run(self.project, "review", "claude")
    a = BROWSER.open_browser(self.project, "about:blank")
    STORE.save_report(self.project, page(), [], "review", "claude")
    self.assertIsNotNone(STORE.list_sessions(a["project_id"])[0]["ended_at"])
    STORE.start_run(self.project, "plan", "claude")
    b = BROWSER.open_browser(self.project, "about:blank")
    self.assertEqual(cli("stop", "--project", str(self.project), "--type", "plan").returncode, 0)
    self.assertTrue(wait_until(lambda: not pid_alive(b["pid"]), 5))

def test_start_closes_orphaned_browsers(self):
    run = STORE.start_run(self.project, "review", "claude")
    s = BROWSER.open_browser(self.project, "about:blank")
    (STORE.store_root() / "projects" / s["project_id"] / "running" / f"{run['id']}.json").unlink()  # agent died
    STORE.start_run(self.project, "plan", "claude")  # via companion start in real use
    BROWSER.close_orphans(s["project_id"])
    self.assertTrue(wait_until(lambda: not pid_alive(s["pid"]), 5))

def test_open_fails_cleanly_without_chrome(self):
    STORE.start_run(self.project, "result", "claude")
    with patch.dict(os.environ, {"SHOWWORK_CHROMIUM": "/nonexistent/chrome"}):
        with self.assertRaises(ValueError):
            BROWSER.open_browser(self.project, "about:blank")
    self.assertEqual(STORE.list_sessions(STORE.project_identity(self.project)["id"]), [])

def test_cli_open_prints_the_cdp_endpoint(self):
    cli("start", "--project", str(self.project), "--type", "result")
    out = json.loads(cli("browser", "open", "--project", str(self.project), "--url", "about:blank").stdout)
    self.assertTrue(out["cdp"].startswith("http://127.0.0.1:"))
    self.assertEqual(json.loads(cli("browser", "close", "--project", str(self.project), "--session", out["session"]).stdout), {"closed": out["session"]})
```

`pid_alive(pid)`: `os.kill(pid, 0)` succeeds and `os.waitpid(pid, os.WNOHANG)` does not reap it. `wait_until(fn, seconds)` polls every 0.1 s.

- [ ] **Step 2: Run to verify they fail**: `SHOWWORK_NO_APP=1 python3 -m unittest tests.test_browser -v` → FAIL (`browser` module missing).

- [ ] **Step 3: Implement** the Interfaces in `browser.py`, `store.py`, `companion.py`.

- [ ] **Step 4: Run** `SHOWWORK_NO_APP=1 python3 -m unittest tests.test_browser tests.test_store tests.test_companion` → OK, and `ps aux | grep -c "showwork-browser-"` shows no leftover Chrome from the tests.

- [ ] **Step 5: Review** `git diff -- skills/showwork/scripts tests`.

---

### Task 3: App backend reads sessions

**Files:**
- Modify: `app/src-tauri/src/store.rs`, `app/src-tauri/src/watch.rs`, `app/src-tauri/src/lib.rs`, `app/src-tauri/tauri.conf.json`
- Test: unit tests in `store.rs` and `watch.rs`

**Interfaces:**
- Consumes: session file fields from Global Constraints; `meta.json` `run`.
- Produces:
  - `ReportMeta.run: Option<String>` (serialized `run`).
  - `SessionItem { id, project_id, run, kind, title: Option<String>, url, width: u32, height: u32, port: u16, ws, pid: i32, started_at, ended_at: Option<String>, alive: bool }` — deserializes snake_case, serializes camelCase; `alive` is computed: `ended_at.is_none()` and `libc::kill(pid, 0) == 0` (or errno `EPERM`).
  - `Store::list_sessions(project_id, run_id) -> Result<Vec<SessionItem>, StoreError>`: only files `<id>.json` whose `id` and `project_id` match, `run == run_id`; oldest first by `started_at` then `id`.
  - `Store::delete_session(project_id, session_id) -> Result<(), StoreError>`: `StoreError::Busy` ("This browser is still running") when alive; already gone = Ok.
  - `Store::all_sessions() -> BTreeSet<(String, String, Option<String>)>` (project, id, ended_at). The watcher fires `on_running` when running markers **or** this set change (event name stays `running-changed`).
  - Tauri commands `list_sessions(project_id, run_id)` and `delete_session(project_id, session_id)`.
  - CSP `connect-src`: append `ws://127.0.0.1:*`.

- [ ] **Step 1: Write the failing tests** in `store.rs`

```rust
#[test]
fn sessions_list_by_run_oldest_first() { /* two sessions of run r1 (started_at "…:01" and "…:00"), one of r2, one broken file, one id mismatch → list_sessions("p1","r1") ids == ["s0","s1"]; JSON has "startedAt", "endedAt", "alive" keys */ }

#[test]
fn sessions_report_dead_processes_as_ended() { /* session with pid = a spawned `sleep 0` child that already exited and was reaped → alive == false; session with pid = std::process::id() and ended_at null → alive == true; ended_at set → alive == false */ }

#[test]
fn delete_session_refuses_a_live_browser() { /* live (own pid) → Err(StoreError::Busy); ended → Ok and file gone; again → Ok; "../x" → Err(BadId) */ }

#[test]
fn report_meta_carries_its_run() { /* meta.json with "run":"r1" → list_reports()[0].run == Some("r1"); without it → None */ }
```

In `watch.rs`, extend `working_items_fire_when_they_appear_and_go` with a session file write (fires) and an `ended_at` rewrite (fires again).

- [ ] **Step 2: Run** `cd app/src-tauri && cargo test` → FAIL to compile (missing items).

- [ ] **Step 3: Implement** the Interfaces.

- [ ] **Step 4: Run** `cargo test` → all pass (previous 27 + new).

- [ ] **Step 5: Review** `git diff -- app/src-tauri`.

---

### Task 4: Task tabs shell (selection, tab bar, split with stand-in frames)

**Files:**
- Create: `app/src/views/tabs.ts`
- Modify: `app/src/model.ts`, `app/src/api.ts`, `app/src/main.ts`, `app/src/views/middle.ts`, `app/src/styles.css`, `app/index.html`
- Test: `app/tests/ui.cjs`

**Interfaces:**
- Consumes: Task 3 commands.
- Produces:
  - `model.ts`: `SessionItem` (camelCase of the Rust struct); `ReportMeta.run?: string | null`.
  - `api.ts`: `listSessions(projectId, runId): Promise<SessionItem[]>`, `deleteSession(projectId, sessionId): Promise<void>`. Mock: fixture `sessions?: SessionItem[]`; `__showworkMock.addSession(s)`, `__showworkMock.endSession(id)` (sets `endedAt`, `alive=false`) — both fire `onRunningChanged` listeners.
  - `views/tabs.ts`: `createTabs(container: HTMLElement, h: { reportHost: HTMLElement; screen(s: SessionItem, interactive: boolean): HTMLElement; closeSession(id: string): void })` returning `{ render(ctx: { key: string; running: boolean } | null, sessions: SessionItem[]): void }`. Remembers the active tab per `ctx.key` (default `report`). Tabs: `Report`, one per session (label `title || host of url`, plus ` · ended` and a `×` close button when `!alive`), `Split` when ≥ 2 sessions. A tab whose session vanished falls back to `Report`. In this task `h.screen` is a stand-in that returns a box showing the session label; Task 5 replaces it.
  - Split: CSS grid `repeat(auto-fit, minmax(320px, 1fr))`; each tile has the session label and a box with `aspect-ratio: <width> / <height>` holding `h.screen(s, false)`; clicking a tile activates that session's tab.
  - `main.ts`: new selection `runId: string | null` beside `reportId` (selecting one clears the other). Task context: `{ key: runId, running: true }` for a run, `{ key: meta.run ?? 'report:' + id, running: false }` for a report. Sessions load with the report list refresh and on `running-changed`. When the selected run disappears and a report with `run == runId` exists, select that report and keep the active tab.
  - `middle.ts`: working items become `<button>`s calling `h.selectRun(id)`, with `aria-current` when selected.
  - Report tab for a run shows `Working on it. The report appears here when it is ready.`

- [ ] **Step 1: Write the failing UI tests** (replace the old "not openable" assertion)

```js
// a running task opens its tabs; the report tab waits for the report
await page.evaluate(() => window.__showworkMock.start({id: 'run3', projectId: 'a', type: 'result', title: null, branch: 'main', worktree: '/w', agent: 'claude', startedAt: '2026-02-02T10:00:00Z'}));
await page.locator('.item.running[data-run-id="run3"]').click();
assert.deepEqual(await page.locator('.tab').allTextContents(), ['Report']);
await page.getByText('Working on it. The report appears here when it is ready.').waitFor();
const s = (id, title) => ({id, projectId: 'a', run: 'run3', kind: 'browser', title, url: 'http://localhost:3000/', width: 1280, height: 800, port: 1, ws: 'ws://127.0.0.1:1/x', pid: 1, startedAt: '2026-02-02T10:01:0' + id.slice(-1) + 'Z', endedAt: null, alive: true});
await page.evaluate(x => window.__showworkMock.addSession(x), s('s1', 'Login page'));
await page.locator('.tab', {hasText: 'Login page'}).waitFor();
assert.equal(await page.locator('.tab', {hasText: 'Split'}).count(), 0);
await page.evaluate(x => window.__showworkMock.addSession(x), s('s2', null));
await page.locator('.tab', {hasText: 'Split'}).click();
assert.equal(await page.locator('.split-tile').count(), 2);
assert.equal(await page.locator('.split-tile').nth(1).locator('.split-label').textContent(), 'localhost:3000');
await page.locator('.split-tile').first().click();
assert.equal(await page.locator('.tab[aria-selected="true"]').textContent(), 'Login page');
// ended session: marked, closable
await page.evaluate(() => window.__showworkMock.endSession('s1'));
await page.locator('.tab', {hasText: 'Login page · ended'}).waitFor();
await page.getByRole('button', {name: 'Close Login page'}).click();
await page.waitForFunction(() => ![...document.querySelectorAll('.tab')].some(t => t.textContent.includes('Login page')));
// another task has its own tabs; coming back restores the active tab
await item('c-result1').click();
assert.deepEqual(await page.locator('.tab').allTextContents(), ['Report']);
```

Add: publishing the run (mock `arrive` with `run: 'run3'` then `finish('a','run3')`) auto-selects the new report and the session tab stays.

- [ ] **Step 2: Run** `node app/tests/ui.cjs` (test env from Global Constraints) → FAIL.

- [ ] **Step 3: Implement** the Interfaces.

- [ ] **Step 4: Run** `npx tsc --noEmit` and `node tests/ui.cjs` → `ui ok`.

- [ ] **Step 5: Review** `git diff -- app/src app/index.html app/tests`.

---

### Task 5: Live screens over CDP

**Files:**
- Create: `app/src/cdp.ts`, `app/src/views/sessionView.ts`
- Modify: `app/src/main.ts` (pass the real `screen`), `app/src/views/tabs.ts`, `app/src/styles.css`
- Test: `app/tests/ui.cjs` (new section that launches a real headless Chrome)

**Interfaces:**
- Consumes: `SessionItem.ws`, `width`, `height`; `createTabs` `screen` hook.
- Produces:
  - `cdp.ts`: `connect(ws: string, on: { frame(jpegBase64: string, deviceWidth: number, deviceHeight: number): void; url(url: string): void; closed(): void }): Promise<Cdp>` where `Cdp = { mouse(type: 'mousePressed'|'mouseReleased'|'mouseMoved', x: number, y: number, clickCount: number): void; wheel(x: number, y: number, dx: number, dy: number): void; key(type: 'rawKeyDown'|'keyUp', e: { key: string; code: string; keyCode: number }): void; text(s: string): void; close(): void }`. On open it sends `Page.enable` and `Page.startScreencast {format: 'jpeg', quality: 70, everyNthFrame: 1}`, acks every `Page.screencastFrame` with `Page.screencastFrameAck {sessionId}`, and reports top-frame `Page.frameNavigated` URLs.
  - `sessionView.ts`: `createScreen(s: SessionItem, interactive: boolean): HTMLElement` — an `<img class="session-frame">` (`object-fit: contain`) inside `.session-screen`; a bar with the current URL and `width×height` (interactive only); `Could not connect to this browser.` when the socket fails or closes while `alive`; an ended session shows its last frame dimmed. One connection per session is shared between its tab and its split tile (a small registry keyed by session id; closing the last view closes the socket). `window.__showworkLiveCount` = open sockets.
  - Input (interactive only): map client coords to page coords with the contain-scale of the image (`scale = min(boxW / dw, boxH / dh)`, centered offsets); mouse down/up/move (move throttled with `requestAnimationFrame`), wheel, and keys while the screen is focused (`tabIndex = 0`): printable single characters without Cmd/Ctrl → `text`, everything else → `key` down/up. `preventDefault` on handled events.
  - Switching tasks closes every socket of the previous task.

- [ ] **Step 1: Write the failing UI test.** In `ui.cjs`, spawn `SHOWWORK_CHROMIUM` headless with the Global Constraints args, `--remote-allow-origins=http://localhost:5179`, `--window-size=800,600`, and a `data:` page whose button sets `document.title = 'clicked'` when clicked; read `DevToolsActivePort`; get the page `ws` from `/json/list`; create a second page with `PUT /json/new?about:blank`. Feed both as live sessions (`addSession`) of a running task, then:

```js
await page.locator('.tab', {hasText: 'Live page'}).click();
await page.waitForFunction(() => document.querySelector('.session-frame')?.src.startsWith('data:image/jpeg'));
const box = await page.locator('.session-frame').boundingBox();
// the button sits at page (40, 40) of an 800×600 page; click it through the scaled screen
const scale = Math.min(box.width / 800, box.height / 600), ox = (box.width - 800 * scale) / 2, oy = (box.height - 600 * scale) / 2;
await page.mouse.click(box.x + ox + 60 * scale, box.y + oy + 55 * scale);
assert.equal(await waitForTitle(chromeWs, 'clicked'), true); // via Playwright connectOverCDP to the test Chrome
await page.locator('.tab', {hasText: 'Split'}).click();
await page.waitForFunction(() => document.querySelectorAll('.split-tile .session-frame[src^="data:image/jpeg"]').length === 2);
assert.equal(await page.evaluate(() => window.__showworkLiveCount), 2);
await item('c-result1').click();
await page.waitForFunction(() => window.__showworkLiveCount === 0);
// a dead socket says so
await page.evaluate(x => window.__showworkMock.addSession(x), {...deadSession, ws: 'ws://127.0.0.1:9/x'});
await page.getByText('Could not connect to this browser.').waitFor();
```

Kill the test Chrome and delete its profile in a `finally`.

- [ ] **Step 2: Run** `node app/tests/ui.cjs` → FAIL.

- [ ] **Step 3: Implement** the Interfaces.

- [ ] **Step 4: Run** `npx tsc --noEmit`, `node tests/ui.cjs` → `ui ok`; `cd src-tauri && cargo test` still passes.

- [ ] **Step 5: Manual check in the dev app** (`npm run tauri dev`, real store is fine for this): in a scratch git folder run `companion.py start --project <scratch> --type result`, then `companion.py browser open --project <scratch> --url https://example.com`; select the task in the app, watch the live tab, click a link, then `companion.py stop --project <scratch> --type result` and confirm the tab turns ended. Record the result in the task report; do not leave Chrome running.

- [ ] **Step 6: Review** `git diff -- app/src app/tests`.

---

### Task 6: Tell agents to use the in-app browser

**Files:**
- Modify: `skills/showwork/references/companion.md` (new section `## Capture web pages in the app` after `## Show that work started`)
- Modify: `skills/showwork/SKILL.md`, `skills/showwork-verify/SKILL.md`, `skills/showwork-review/SKILL.md`, `skills/showwork-adverial-review/SKILL.md` (one sentence each where web capture is mentioned, linking that section)
- Modify: `README.md` (one line under the app section)
- Test: `tests/test_install.py` passes as before (only its 4 known pre-existing failures)

**Interfaces:**
- Section content, in this order: after `start`, open a browser with `companion.py browser open --project … --url …` (one per page or role you need at the same time; add `--title`); connect Playwright with `chromium.connectOverCDP(<cdp>)` and use `browser.contexts()[0].pages()[0]`; take screenshots with Playwright into the temporary directory; never open the user's own browser or a visible window for captures; close with `browser close` when a browser is no longer needed (publish and `stop` close the rest). Simulators are unchanged for now.

- [ ] **Step 1: Write the section and sentences.**
- [ ] **Step 2: Run** `SHOWWORK_NO_APP=1 python3 -m unittest discover -s tests` → only the 4 known failures (`test_install` ×3, `test_evidence` cwd).
- [ ] **Step 3: Review** `git diff -- skills README.md`.
