# iOS Simulator Sessions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show and control an already-booted iOS Simulator inside the task's Showwork tabs, with no visible Simulator window.

**Architecture:** The Python companion starts one loopback relay per attached device; `idb` supplies MJPEG frames and receives discrete touch/text commands. The existing session store and Rust reader deliver a tagged iOS session to the webview, which polls frames, sends input, and reuses the existing tab and Split shell. Closing the Showwork session stops only the relay, not the Simulator.

**Tech Stack:** Python 3.11 stdlib, `idb` CLI and companion, Xcode Simulator, Rust/Tauri 2, TypeScript/Vite, HTTP long polling, Playwright for UI checks.

**Spec:** `docs/superpowers/specs/2026-11-07-ios-simulator-sessions-design.md`

## Global Constraints

- iOS Simulator only on macOS; Android, physical devices, video recording, and automatic app launch are separate work.
- Attach by explicit UDID to a booted device. The app does not boot, shut down, install into, or erase it.
- Python runtime remains stdlib-only; require an `idb` CLI/companion with `describe`, MJPEG `video-stream`, `ui tap`, `ui swipe`, and `ui text`.
- Relay: `127.0.0.1` ephemeral port, 10 fps MJPEG at scale 0.5, newest frame in memory, 8 MiB frame limit, two-second frame wait.
- Relay security: random session token on every actual request; CORS preflight validates Origin/requested headers; only `tauri://localhost` and `http://localhost:1420` origins, with `SHOWWORK_IOS_ORIGINS` override for tests; no wildcard CORS.
- Input: `tap`, `swipe` lasting 0.05–2 seconds, `text` at most 2048 characters, and `button: HOME`; reject out-of-bounds points, malformed requests, and JSON bodies over 4 KiB.
- Tests that write session state use a fresh `SHOWWORK_STORE` and `SHOWWORK_NO_APP=1`; captures and one-off scripts go in `/tmp`, never in the project.
- **Never commit or stage** code, documentation, plans, tests, or other files unless the user explicitly asks for a commit in the current task. Leave all changes uncommitted and review the working-tree diff.

## Review Focus

1. `idb` is absent, the UDID is invalid, or the device is shut down: Task 2 tests a clear error, no relay process, and no session file.
2. A relay exits or an agent dies: Tasks 1 and 2 test stream failure, stopped state, orphan cleanup, and no PID-reuse kill.
3. A long-polled frame or input request is unauthorized: Task 1 tests token, Origin, body limit, and coordinate bounds.
4. A portrait image is letterboxed or rotates to landscape: Task 4 tests tap/swipe point mapping using the visible image rectangle and current orientation dimensions.
5. A user switches task or closes an ended tab while frames arrive: Task 4 tests request cancellation and no stale repaint; Task 3 tests correct session deletion.

---

## File structure

- `skills/showwork/scripts/ios_relay.py` — bounded MJPEG reader, latest-frame HTTP service, authenticated input bridge to `idb`.
- `skills/showwork/scripts/ios_simulator.py` — booted-device validation, relay process ownership, session open/close/orphan cleanup.
- `skills/showwork/scripts/companion.py`, `store.py` — `simulator open|close` CLI and lifecycle hooks alongside browser cleanup.
- `tests/test_ios_relay.py`, `tests/test_ios_simulator.py` — relay protocol and CLI/process tests with fake `idb` and isolated store.
- `app/src-tauri/src/store.rs`, `watch.rs` — read both session kinds and report iOS session state changes; no new Tauri command.
- `app/src/model.ts`, `api.ts` — discriminated browser/iOS session types and mock support in the UI task.
- `app/src/views/iosSessionView.ts` — frame polling, display, touch/swipe/text/Home input, disposal.
- `app/src/views/tabs.ts`, `main.ts`, `styles.css`, `app/src-tauri/tauri.conf.json` — iOS label/render dispatch, image fit, and loopback/blob CSP.
- `app/tests/ios.cjs`, `app/tests/fixtures/ios-frame.jpg` — local fake relay and UI behavior; existing browser tests stay in place.
- `skills/showwork/references/companion.md`, `docs/installation.md` — attachment command and `idb` prerequisite; agent screenshots still come from device tools.

### Task 1: Local iOS frame and input relay

**Files:**
- Create: `skills/showwork/scripts/ios_relay.py`
- Test: `tests/test_ios_relay.py`

**Interfaces:**
- Produces: `MjpegFramer.feed(chunk: bytes) -> list[bytes]` (complete JPEGs, 8 MiB maximum); `jpeg_dimensions(jpeg: bytes) -> tuple[int, int]`; `RelayState(udid: str, token: str, origins: set[str], points_width: int, points_height: int, idb_path: str)` with `publish_frame(jpeg: bytes)`, `finish(reason: str)`, and `run_input(action: dict) -> None`; `make_server(state: RelayState) -> ThreadingHTTPServer` bound to `127.0.0.1:0`.
- `GET /health` returns readiness/dimensions; `GET /frame?after=N` returns a newer `image/jpeg` plus `X-Frame-Seq`, `X-Points-Width`, `X-Points-Height`, or `204` after two seconds, or `410` after stream failure. `POST /input` receives one action and returns `{"ok":true}` or a 4xx/5xx error. Actual requests check token and exact Origin; `OPTIONS` checks Origin plus `Access-Control-Request-Headers` and permits `X-Session-Token`/`Content-Type`. CORS exposes the three frame headers.
- Executed as `python3 ios_relay.py serve --udid U --session ID --points-width W --points-height H --idb-path PATH`; token and allowed origins arrive through process environment. It starts `idb video-stream --format mjpeg --fps 10 --scale-factor 0.5 --udid U`, waits for the first frame, prints one JSON ready line containing `port`, then serves. SIGTERM closes both the HTTP server and `idb` child.

- [ ] **Step 1: Write failing relay tests** in `tests/test_ios_relay.py`: `test_framer_reassembles_two_split_jpegs_and_rejects_over_8_mib`; `test_jpeg_dimensions` checks known portrait and landscape JPEG bytes; `test_frame_auth_and_long_poll` asserts authorized preflight, `403` for wrong token/Origin on actual requests, `200` with frame headers, `204` for unchanged sequence, and `410` after finish; `test_input_validation_and_argv` asserts `tap(201,286)` calls `idb ui tap 201 286 --udid U` without a shell and bad coordinates, 2049-character text, over-4-KiB body, or long swipe return `400`; `test_stream_exit_stops_relay` checks child cleanup. Use a fake runner/stream, not a real device.
- [ ] **Step 2: Run `python3 -m unittest tests.test_ios_relay -v`**; expect failure because `ios_relay` does not exist.
- [ ] **Step 3: Implement the interfaces in `ios_relay.py`**. Parse concatenated JPEG SOI/EOI boundaries across chunks; keep one frame and a sequence number under a condition variable; serialize `subprocess.run([...], timeout=5)` input actions. Determine portrait/landscape point dimensions from each JPEG's orientation and the device's portrait point pair. Never log the token or frame payload.
- [ ] **Step 4: Run `python3 -m unittest tests.test_ios_relay -v`**; expect all five tests to pass.
- [ ] **Step 5: Review uncommitted changes** with `git status --short` and `git diff -- tests/test_ios_relay.py skills/showwork/scripts/ios_relay.py` (plus `git diff --no-index /dev/null` for untracked files when needed).

### Task 2: Companion ownership and CLI

**Files:**
- Create: `skills/showwork/scripts/ios_simulator.py`
- Modify: `skills/showwork/scripts/companion.py`, `skills/showwork/scripts/store.py`
- Test: `tests/test_ios_simulator.py`, `tests/test_companion.py`

**Interfaces:**
- Consumes: Task 1 ready line and relay process.
- Produces: `open_simulator(project: Path, udid: str, title: str | None = None) -> dict`, `close_simulator(project_id: str, session_id: str) -> dict`, `close_run(project_id: str, run_id: str) -> None`, `close_orphans(project_id: str) -> None` in `ios_simulator.py`.
- `companion.py simulator open --project P --udid U [--title T]` prints `{"session":ID,"run":RUN,"endpoint":"http://127.0.0.1:PORT"}`; `simulator close --project P --session ID` prints `{"closed":ID}`. `start`, `stop`, and `store.save_report` close iOS orphans/run sessions as they do browser sessions.
- Session JSON has common `id, project_id, run, kind, title, width, height, pid, started_at, ended_at`, plus `kind: "ios-simulator"`, `udid`, `points_width`, `points_height`, `port`, `token`; no `url` or `ws`. `width/height` are native display pixels from `idb describe`; `title` defaults to its device name. Closing this record does not shut down the Simulator.

- [ ] **Step 1: Write failing lifecycle tests**: no run, missing `idb`, malformed UDID, shut-down device, and relay never ready each leave no session; same run/UDID returns the same session; another active run/UDID is refused; `stop` and `publish` end sessions and relay children while the booted device remains booted; orphan cleanup checks the relay command's session ID before signaling a PID. Use a fake `idb` executable and fake relay ready line in a fresh `SHOWWORK_STORE`.
- [ ] **Step 2: Run `python3 -m unittest tests.test_ios_simulator tests.test_companion -v`**; expect the new tests to fail because the CLI/module does not exist.
- [ ] **Step 3: Implement the four `ios_simulator.py` functions and CLI/hooks**. `idb describe --udid U --json` must say `target_type=simulator` and `state=Booted` and return positive pixel/point dimensions. Start the Task 1 relay with a random 32-byte URL-safe token; record a session only after its first-frame ready line. On every failure terminate the relay. On close, verify the PID still names this relay/session before signaling it, mark `ended_at`, and leave the device booted. Invoke both browser and iOS cleanup even when one raises, then report any cleanup error.
- [ ] **Step 4: Run `python3 -m unittest tests.test_ios_simulator tests.test_companion tests.test_browser tests.test_store -v`**; expect all related Python tests to pass.
- [ ] **Step 5: Review uncommitted changes** with `git status --short` and `git diff -- skills/showwork/scripts tests/test_ios_simulator.py tests/test_companion.py`.

### Task 3: Read tagged sessions in Rust

**Files:**
- Modify: `app/src-tauri/src/store.rs`, `app/src-tauri/src/watch.rs`
- Test: Rust unit tests in `store.rs`/`watch.rs`

**Interfaces:**
- Consumes: Task 2's exact on-disk iOS record and existing browser record.
- Produces: Rust `SessionItem` JSON tagged by `kind: "browser" | "ios-simulator"`. Shared fields are `id, projectId, run, title, width, height, pid, startedAt, endedAt, alive`; browser fields are `url, port, ws`; iOS fields are `udid, pointsWidth, pointsHeight, port, token`. Rust omits variant fields that do not apply. Unknown/malformed kinds are skipped, not shown as live tabs. Task 4 mirrors this shape as a TypeScript union.
- Existing `list_sessions`, `list_all_sessions`, `delete_session`, `all_sessions`, and `running-changed` names remain unchanged. A live relay PID makes an iOS session busy to delete; a dead or ended one can be removed.

- [ ] **Step 1: Write failing Rust tests** in `store.rs`/`watch.rs`: iOS JSON has camelCase point dimensions and `alive=true` for own PID; malformed iOS JSON and unknown `kind` are skipped; browser JSON is unchanged; ended/dead relay can be deleted but live relay cannot; watcher fires on new/ended iOS session.
- [ ] **Step 2: Run `cargo test --manifest-path app/src-tauri/Cargo.toml`**; expect the new cases to fail before the reader change.
- [ ] **Step 3: Extend Rust session parsing/serialization**. Keep one common record reader with kind-specific required fields; reject records with missing `udid`, `token`, or point dimensions. Preserve the current browser contract and watcher behavior.
- [ ] **Step 4: Run `cargo test --manifest-path app/src-tauri/Cargo.toml`**; expect all Rust tests to pass.
- [ ] **Step 5: Review uncommitted changes** with `git status --short` and `git diff -- app/src-tauri/src/store.rs app/src-tauri/src/watch.rs`.

### Task 4: iOS tab, input, and installed-app proof

**Files:**
- Create: `app/src/views/iosSessionView.ts`, `app/tests/ios.cjs`, `app/tests/fixtures/ios-frame.jpg`
- Modify: `app/src/model.ts`, `app/src/api.ts`, `app/src/views/tabs.ts`, `app/src/main.ts`, `app/src/styles.css`, `app/src-tauri/tauri.conf.json`, `skills/showwork/references/companion.md`, `docs/installation.md`

**Interfaces:**
- Consumes: Task 3 tagged Rust JSON and Task 1 HTTP API.
- Produces: TypeScript `SessionItem = BrowserSession | IosSession` discriminated by `kind: 'browser' | 'ios-simulator'`, matching Task 3's shared and variant fields; the mock API accepts both kinds.
- Produces: `createIosScreen(s: IosSession, interactive: boolean): HTMLElement & { dispose(): void }`. It long-polls `/frame?after=N` with `X-Session-Token`, renders one object URL per new JPEG and revokes the prior URL, aborts outstanding requests on dispose, and shares one poll per session across full and Split views. Only interactive views POST input. A `410`, relay failure, or repeated fetch failure shows an ended/error state instead of a live-looking frozen image.
- `main.ts` dispatches browser sessions to existing `createScreen` and iOS sessions to `createIosScreen`. `tabs.ts` uses device title or `iOS Simulator` as fallback and the existing Split/ended behavior. CSP adds `http://127.0.0.1:*` to `connect-src` and `blob:` to `img-src`.

- [ ] **Step 1: Write failing `app/tests/ios.cjs` checks** with a local fake relay and mock session: an untitled iOS session gets an `iOS Simulator` tab; frame displays with correct aspect ratio; a letterboxed click at the image center POSTs the correct point pair; a drag POSTs a bounded swipe; text Send and Home POST exact actions; Split displays two previews but sends no input; switching tasks aborts polling; an ended/restarted session shows a placeholder; simulated landscape frame swaps point dimensions. Keep the JPEG fixture tiny and non-sensitive.
- [ ] **Step 2: Run `cd app && NODE_PATH=/Users/brianchoi/personal/handeye/node_modules SHOWWORK_CHROMIUM='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' node tests/ios.cjs`**; expect failure because `createIosScreen` does not exist.
- [ ] **Step 3: Implement the TypeScript union/mock, iOS view, dispatch, styling/CSP, and companion/installation instructions**. Use the actual image rectangle for coordinate mapping, not the whole padded viewport. Keep the text field separate from the image's pointer handler. Document `simulator open|close`, the `idb` prerequisite, and that report screenshots still use the agent's device capture tool.
- [ ] **Step 4: Run `cd app && npm run build`**; expect TypeScript and Vite build success.
- [ ] **Step 5: Run `tests/ios.cjs`, `tests/live.cjs`, and `tests/ui.cjs` from `app/`** with `NODE_PATH=/Users/brianchoi/personal/handeye/node_modules` and `SHOWWORK_CHROMIUM='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'`; expect all three to pass.
- [ ] **Step 6: Run `cargo test --manifest-path app/src-tauri/Cargo.toml`, `python3 -m unittest tests.test_ios_relay tests.test_ios_simulator tests.test_browser tests.test_store tests.test_companion`, and `git diff --check`**; expect all to pass.
- [ ] **Step 7: Boot a generic iPhone Simulator by explicit UDID without opening `Simulator.app`; attach with `simulator open` to a temporary Showwork run**. In the installed app, expect a live iOS tab and a Split preview alongside a browser tab.
- [ ] **Step 8: Tap Safari through the Showwork image, swipe, and send text to a focused field**. Confirm each with a separate `idb screenshot` in `/tmp` (or `simctl io screenshot` if idb capture fails), recording device/OS/build and capture method.
- [ ] **Step 9: Rotate a rotation-capable app and retest pointer mapping**. The local `idb rotation` probe was inconclusive; record this gate as blocked rather than claim success if rotation cannot be exercised.
- [ ] **Step 10: Stop the test run and inspect cleanup**. Expect relay termination, the Simulator still booted, and an ended tab; delete only the test tabs and shut down only the generic test Simulator.
- [ ] **Step 11: Review uncommitted changes** with `git status --short`, `git diff --check`, and the full working-tree diff.

## Self-review record

- Spec coverage: attachment, ownership, secure relay, live and Split UI, input, orientation, end/error states, evidence, and platform limits each map to Tasks 1–4. Android stays out of scope by design.
- Interface check: the on-disk `ios-simulator` record in Task 2 matches Task 3's tagged JSON and Task 4's `IosSession`; Task 4 consumes Task 1's exact HTTP paths/headers. Browser records and Tauri command names remain intact.
- Review Focus tests: each of the five conditions above has a named test or installed-app check in its owning task.
- No implementation or commit is part of this planning task. The plan and companion spec remain uncommitted.
