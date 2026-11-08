# Android Emulator Sessions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show and control an already running Android Emulator in Showwork's task tabs without opening an emulator window.

**Architecture:** `adb` supplies bounded PNG screenshots and receives tap/swipe commands through one authenticated loopback relay per attached serial. The existing session store, Rust reader, and tab shell gain an Android variant; the iOS and Android views share frame polling and pointer mapping while retaining their distinct frame headers.

**Tech Stack:** Python 3.11 standard library, Android SDK Platform Tools `adb`, Rust/Tauri 2, TypeScript/Vite, Playwright UI checks.

**Spec:** `docs/superpowers/specs/2026-11-08-android-emulator-sessions-design.md`

## Global Constraints

- macOS Showwork app, Python 3.11+, and Android SDK Platform Tools `adb`; explicit `emulator-<digits>` serial only. `adb devices -l` must show `device`, and `sys.boot_completed` and `ro.kernel.qemu` must both be `1`.
- At most four `adb -s SERIAL exec-out screencap -p` captures per second, no overlap, five-second deadline, 8 MiB output cap, and only the newest PNG in memory. Three consecutive failures end the relay; first valid frame must arrive within 20 seconds.
- `GET /health`, `GET /frame?after=N` (two-second wait), and `POST /input`; PNG frames carry `X-Frame-Seq`, `X-Pixels-Width`, `X-Pixels-Height`, `204` means unchanged and `410` means ended. Preserve iOS JPEG and `X-Points-*` behavior.
- `/input` accepts only tap and swipe; finite integer pixels inside the current frame, swipe duration 0.05–2 seconds mapped to 50–2000 milliseconds, 4 KiB body limit, five-second `adb` command timeout, serialized input, and no shell execution.
- Bind `127.0.0.1` on an ephemeral port. Token and exact Origin (`tauri://localhost`, `http://localhost:1420`, or `SHOWWORK_ANDROID_ORIGINS` in tests) are required; preflight validates method and requested headers. No wildcard CORS, token/frame logging, or preview files.
- Showwork never boots, stops, wipes, installs into, or resets an emulator. Its tab has tap/swipe only; agent-side `adb` handles text/Home. Split is view-only; report evidence is a separately captured image in `/tmp` with provenance.
- **Never commit or stage** code, documents, plans, or tests unless the user explicitly asks for a commit in the current task. Leave changes uncommitted and inspect the working-tree diff.

## Review Focus

1. Offline, unauthorized, booting, or physical serial: Task 3's preflight tests reject it with no relay and no session file.
2. Oversized, malformed, hung, or repeatedly failing PNG capture: Task 2's bounded-capture tests stop the child and surface an ended/error state.
3. Wrong Origin/token, oversized body, or invalid tap/swipe: Tasks 1–2's HTTP tests reject the request without invoking `adb`.
4. Two runs claim one serial, or publish races with attach: Task 3's ownership tests keep one owner and terminate the relay when the run ends.
5. Rotation, letterboxing, Split, or task switch: Task 5's UI tests use current frame pixels, send no preview input, and cancel stale polling.

---

## File structure

- `skills/showwork/scripts/device_relay.py` — common authenticated HTTP frame/input protocol; `ios_relay.py` keeps iOS capture/input and delegates its HTTP server here.
- `skills/showwork/scripts/android_relay.py` — bounded PNG capture loop, PNG dimensions, Android tap/swipe input, relay process.
- `skills/showwork/scripts/android_emulator.py` — preflight, serial ownership, relay startup/cleanup, session records.
- `skills/showwork/scripts/companion.py`, `store.py` — `emulator open|close` CLI and stop/publish/orphan hooks.
- `app/src-tauri/src/store.rs`, `watch.rs` — Android tagged session and watcher tests; no new Tauri command.
- `app/src/model.ts`, `main.ts`, `views/tabs.ts`, `styles.css` — Android type and tab routing.
- `app/src/views/deviceSessionView.ts` — shared image polling, touch mapping, and disposal; `iosSessionView.ts` and new `androidSessionView.ts` are thin adapters.
- `tests/test_device_relay.py`, `test_android_relay.py`, `test_android_emulator.py`, `app/tests/android.cjs`, `app/tests/fixtures/android-frame.png` — protocol, ownership, and UI proof.
- `README.md`, `docs/installation.md`, `skills/showwork/references/companion.md` — availability, commands, limits, and capture provenance.

### Task 1: Shared authenticated frame server

**Files:** Create `skills/showwork/scripts/device_relay.py`, `tests/test_device_relay.py`; modify `skills/showwork/scripts/ios_relay.py`.

**Interfaces:** Produce `make_server(state: RelayHttpState) -> ThreadingHTTPServer`. `RelayHttpState` has `token`, `origins`, `condition`, `frame`, `seq`, `reason`, `content_type`, `width_header`, `height_header`, `frame_dimensions() -> tuple[int,int]`, `health_payload() -> dict`, and `run_input(action: dict) -> None`. The health payload includes `ready` plus current input dimensions: `points_width/height` for iOS, `pixels_width/height` for Android. iOS re-exports `make_server` and supplies `image/jpeg` plus `X-Points-Width/Height`; its current public `RelayState` and response contract remain usable by existing tests. Task 2 supplies the same protocol with PNG and pixel headers.

- [ ] **Step 1: Write `tests/test_device_relay.py`** with a fake state. Assert authorized preflight; `403` for wrong Origin/token; `200` PNG with sequence and pixel headers; `204` after the same sequence; `410` after finish; `400` for a body over 4 KiB or a state-rejected action; and no input call for rejected HTTP requests.
- [ ] **Step 2: Run `TMPDIR=/private/tmp python3 -m unittest tests.test_device_relay -v`**; expect import failure because `device_relay.py` does not exist.
- [ ] **Step 3: Extract `make_server` into `device_relay.py`** with the exact interface above, preserving the current token, Origin, CORS, body-size, long-poll, and error behavior. Adapt `ios_relay.RelayState` to implement the interface without changing its existing JPEG/points API.
- [ ] **Step 4: Run `TMPDIR=/private/tmp python3 -m unittest tests.test_device_relay tests.test_ios_relay -v`**; expect all new and existing relay tests to pass.
- [ ] **Step 5: Review uncommitted changes** with `git status --short` and `git diff -- skills/showwork/scripts/device_relay.py skills/showwork/scripts/ios_relay.py tests/test_device_relay.py tests/test_ios_relay.py` (use `git diff --no-index /dev/null FILE` for new files).

### Task 2: Android screenshot and input relay

**Files:** Create `skills/showwork/scripts/android_relay.py`, `tests/test_android_relay.py`.

**Interfaces:** Produce `png_dimensions(png: bytes) -> tuple[int,int]`, `capture_png(adb_path: str, serial: str, stop: threading.Event) -> bytes`, `AndroidRelayState(serial: str, token: str, origins: set[str], adb_path: str)` implementing Task 1's `RelayHttpState`, and `serve --serial SERIAL --session ID --adb-path PATH`. The process prints one ready JSON line `{port,width,height}` after its first valid capture. Task 3 consumes that line and the relay PID.

- [ ] **Step 1: Write `tests/test_android_relay.py`** using a fake `adb` executable. Assert valid portrait/landscape PNG IHDR dimensions; rejection of bad PNG and >8 MiB output; one capture at a time with a five-second deadline and killed stuck child; frame dimensions changing after rotation; exact `adb -s SERIAL shell input tap X Y` and `swipe X1 Y1 X2 Y2 MS` argument lists; rejected bool/out-of-bounds/fractional coordinates and durations; three capture failures yield `410`; SIGTERM reaps a current capture.
- [ ] **Step 2: Run `TMPDIR=/private/tmp python3 -m unittest tests.test_android_relay -v`**; expect import failure because `android_relay.py` does not exist.
- [ ] **Step 3: Implement the Task 2 interfaces**. Read `adb exec-out screencap -p` through a bounded pipe with an 8 MiB cap and five-second deadline, parse PNG signature/IHDR, publish at most every 250 ms, serialize validated input, and terminate the current child on relay shutdown. Use Task 1's HTTP server, `image/png`, and `X-Pixels-Width/Height`.
- [ ] **Step 4: Run `TMPDIR=/private/tmp python3 -m unittest tests.test_android_relay tests.test_device_relay tests.test_ios_relay -v`**; expect all to pass.
- [ ] **Step 5: Review uncommitted changes** with `git status --short` and `git diff -- skills/showwork/scripts/android_relay.py tests/test_android_relay.py` (use `git diff --no-index /dev/null FILE` for new files).

### Task 3: Companion attachment and lifecycle

**Files:** Create `skills/showwork/scripts/android_emulator.py`, `tests/test_android_emulator.py`; modify `skills/showwork/scripts/companion.py`, `store.py`, `tests/test_companion.py`, `tests/test_store.py`.

**Interfaces:** Produce `open_emulator(project: Path, serial: str, title: str | None = None) -> dict`, `close_emulator(project_id: str, session_id: str) -> dict`, `close_run(project_id: str, run_id: str) -> None`, `close_orphans(project_id: str) -> None`. `companion.py emulator open --project P --serial S [--title T]` prints `{session,run,endpoint}`; `emulator close --project P --session ID` prints `{closed}`. Session JSON has common fields plus `kind: "android-emulator"`, `serial`, `port`, `token`; `width/height` come from Task 2's ready line. Reuse `store.simulator_lifecycle_lock()` for attach/finish synchronization.

- [ ] **Step 1: Write lifecycle tests** in `test_android_emulator.py` and CLI/cleanup tests in `test_companion.py`/`test_store.py`. Assert missing run/adb, malformed serial, offline/unauthorized/booting/physical device, and relay timeout leave no session or child; same run/serial returns one session; another run is refused; dead relay becomes ended; `stop` and `publish` end relay but leave `adb get-state` as `device`; a pending attach is completed then closed by publish; PID-reuse identity mismatch is never signaled.
- [ ] **Step 2: Run `TMPDIR=/private/tmp python3 -m unittest tests.test_android_emulator tests.test_companion tests.test_store -v`**; expect new tests to fail before the module and CLI exist.
- [ ] **Step 3: Implement the four ownership functions and CLI/hooks**. Preflight the explicit serial with `adb devices -l`, `adb -s S shell getprop sys.boot_completed`, and `adb -s S shell getprop ro.kernel.qemu`; start Task 2's relay with a random 32-byte token; write the session only after ready and rechecking the run marker. Verify `--session` and `android_relay.py` in the PID's command before signaling. Add Android to `cleanup_sessions` while attempting every owner even if one raises.
- [ ] **Step 4: Run `TMPDIR=/private/tmp python3 -m unittest tests.test_android_emulator tests.test_companion tests.test_store tests.test_ios_simulator tests.test_browser -v`**; expect all to pass.
- [ ] **Step 5: Review uncommitted changes** with `git status --short` and `git diff -- skills/showwork/scripts/companion.py skills/showwork/scripts/store.py skills/showwork/scripts/android_emulator.py tests/test_android_emulator.py tests/test_companion.py tests/test_store.py`.

### Task 4: Read Android session records in the app backend

**Files:** Modify `app/src-tauri/src/store.rs`, `app/src-tauri/src/watch.rs` (tests in the same files).

**Interfaces:** Extend `SessionTransport` with `AndroidEmulator { serial: String, port: u16, token: String }` tagged as `android-emulator`. `SessionItem` JSON retains common camelCase fields and adds only `serial`, `port`, and `token` for this variant. The existing `list_sessions`, `list_all_sessions`, `delete_session`, and `running-changed` interfaces stay unchanged. Task 5 consumes this JSON shape.

- [ ] **Step 1: Write Rust tests**: valid Android disk JSON becomes the exact tagged frontend JSON and appears in watcher snapshots; empty/malformed serial, zero port/token, or zero dimensions are skipped; browser/iOS JSON is unchanged; a live Android relay record cannot be deleted, while ended/dead records can; the watcher fires on creation and end.
- [ ] **Step 2: Run `cargo test --manifest-path app/src-tauri/Cargo.toml`**; expect the new Android tests to fail before the reader accepts the variant.
- [ ] **Step 3: Add the Android variant and validation** in `store.rs`: require `emulator-<digits>` serial, nonempty token, nonzero port, and positive common width/height for this variant. Reuse the existing generic listing/deletion/watcher paths and keep browser/iOS serialization unchanged.
- [ ] **Step 4: Run `cargo test --manifest-path app/src-tauri/Cargo.toml`**; expect all Rust unit and integration tests to pass.
- [ ] **Step 5: Review uncommitted changes** with `git status --short` and `git diff -- app/src-tauri/src/store.rs app/src-tauri/src/watch.rs`.

### Task 5: Android tab, documentation, and installed-app proof

**Files:** Create `app/src/views/deviceSessionView.ts`, `app/src/views/androidSessionView.ts`, `app/tests/android.cjs`, `app/tests/fixtures/android-frame.png`; modify `app/src/views/iosSessionView.ts`, `app/src/views/tabs.ts`, `app/src/model.ts`, `app/src/main.ts`, `app/src/styles.css`, `app/tests/ui.cjs`, `README.md`, `docs/installation.md`, `skills/showwork/references/companion.md`.

**Interfaces:** `AndroidSession` extends the common session fields with `kind: 'android-emulator'`, `serial`, and `token`; `SessionItem` adds this variant. `createDeviceScreen(s: IosSession | AndroidSession, interactive: boolean): HTMLElement & { dispose(): void }` owns one poll/object URL per session across full and Split views. Existing `createIosScreen` remains an adapter; new `createAndroidScreen` adapts Android. Android reads `X-Pixels-Width/Height`, iOS still reads `X-Points-Width/Height`; pointer coordinates use each new frame's dimensions.

- [ ] **Step 1: Write `app/tests/android.cjs`** with a local fake PNG relay and mock session, plus a main-route assertion in `app/tests/ui.cjs`. Assert fallback `Android Emulator` tab; image-only full-height screen; letterboxed center tap and bounded drag in exact pixels; new landscape frame changes center mapping; Split shows browser/iOS/Android previews without input; two views share one poll; task switch aborts it; ended/restarted view shows placeholder; `410`, input failure, and repeated fetch failure hide stale content. Keep the PNG fixture tiny and non-sensitive.
- [ ] **Step 2: Run the Android UI test** with `NODE_PATH=/Users/brianchoi/personal/handeye/node_modules SHOWWORK_CHROMIUM='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' node app/tests/android.cjs`; expect failure because the Android view/type is missing.
- [ ] **Step 3: Implement the shared device view and Android routing**, preserving the existing iOS behavior and keeping Split view-only. Document `emulator open|close`, explicit serial, `adb` prerequisite, image-only input, separate report capture, and the four-frame-per-second maximum in the three listed guides.
- [ ] **Step 4: Build the app** with `npm run build` in `app/`; expect TypeScript and Vite success.
- [ ] **Step 5: Run the four UI tests** from `app/`. For each of `android`, `ios`, `live`, and `ui`, run `NODE_PATH=/Users/brianchoi/personal/handeye/node_modules SHOWWORK_CHROMIUM='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' node tests/NAME.cjs` with `NAME` set to that test name; expect four `ok` results.
- [ ] **Step 6: Run backend regressions**: `cargo test --manifest-path app/src-tauri/Cargo.toml` and `TMPDIR=/private/tmp python3 -m unittest discover -s tests`; expect all tests to pass.
- [ ] **Step 7: Build and install the desktop app** with `npm run tauri build` in `app/`; copy `app/src-tauri/target/release/bundle/macos/Showwork.app` to `/Applications/Showwork.app` after preserving the previous installed build. Confirm the installed bundle contains the new UI assets.
- [ ] **Step 8: Attach a disposable emulator in the installed app**. Create a uniquely named Android 36 AVD with `avdmanager create avd -n NAME -k 'system-images;android-36;google_apis;arm64-v8a' -p /private/tmp/NAME.avd`, boot it with `emulator -avd NAME -no-window -no-audio -no-snapshot`, then `emulator open` using its explicit serial. Confirm the live Android tab and Split beside another session.
- [ ] **Step 9: Prove input on that emulator**. Send tap and swipe through the relay input path, without desktop Computer Use. Capture the result separately with `adb -s SERIAL exec-out screencap -p` into `/tmp` and record emulator, Android version, app build, actions, and capture method.
- [ ] **Step 10: Probe real rotation** on the disposable AVD. Compare portrait and landscape PNG dimensions and tap targets; if its screenshot orientation cannot change, record the real rotation check as unverified while retaining the synthetic UI test result.
- [ ] **Step 11: Prove cleanup** with `emulator close`, `stop`, and `publish` in separate test runs. For each, assert relay exit and `adb -s SERIAL get-state` still reports `device`; then run `adb -s SERIAL emu kill`, `avdmanager delete avd -n NAME`, and check for relay/`adb screencap` children.
- [ ] **Step 12: Review the full uncommitted diff** with `git status --short`, `git diff --check`, and `git diff --stat`; report changed files and the real-emulator verification result. Do not stage or commit without a new explicit user request.

## Self-review record

- Spec coverage: capture limits, auth, input, ownership, session schema, app behavior, evidence, platform scope, and cleanup each map to Tasks 1–5. The five Review Focus conditions each have named assertions above.
- Interface check: Task 2's `{port,width,height}` ready line feeds Task 3; Task 3's disk fields match Task 4; Task 4's frontend JSON matches Task 5's union; Task 1 preserves the existing iOS headers while Android uses pixel headers.
- Plan scope: this produces one working Android Emulator attachment. Physical Android devices, a faster video transport, and an emulator manager remain separate work.
