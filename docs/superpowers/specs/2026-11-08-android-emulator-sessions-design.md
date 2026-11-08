# Android Emulator sessions in Showwork — design

Status: implementation target after the browser and iOS session work. This is one Android Emulator increment; it uses the existing task tabs and report store.

## Result

An agent starts a Showwork task, boots an Android Emulator with its normal tools, then attaches that **already running** device with `companion.py emulator open --project P --serial emulator-5554 [--title T]`. The task gains an Android tab. The user sees the device screen, taps and swipes the image, and can watch it beside browser and iOS tabs in Split. Split previews accept no input. `emulator close`, `stop`, and `publish` end only the Showwork attachment; the emulator remains running. An ended tab stays until closed.

The tab has no separate input bar. Agents use `adb` or an existing Maestro flow for text, Home, app setup, and evidence. A streamed frame is a preview, not report evidence. Report screenshots come from a separate `adb exec-out screencap -p` or Maestro capture in `/tmp`, with the emulator, Android version, app build, interaction, and capture method recorded.

## Transport and input

- macOS Showwork app, Python 3.11+, and Android SDK Platform Tools `adb` are required. Attach by explicit `emulator-<digits>` serial only. `adb devices -l` must list it as `device`; `sys.boot_completed` and `ro.kernel.qemu` must both be `1`. Offline, unauthorized, booting, missing, or physical devices create no session.
- Poll `adb -s SERIAL exec-out screencap -p` at most four times per second, with no overlapping captures. Each command has a five-second deadline and an 8 MiB output limit. Parse PNG IHDR dimensions from each capture. Keep only the newest PNG in memory; do not write preview frames or tokens to the project or device. Three consecutive capture failures end the relay and show an error instead of a frozen live screen. Session creation waits up to 20 seconds for the first valid frame.
- Use the existing relay API shape: `GET /health`, `GET /frame?after=N` with a two-second long poll, and `POST /input`. Android health returns `ready`, `pixels_width`, and `pixels_height`; iOS keeps its current points fields. A frame is `image/png` with `X-Frame-Seq`, `X-Pixels-Width`, and `X-Pixels-Height`; unchanged frames return `204`, and an ended capture loop returns `410`. The pixel dimensions update on every frame, including rotation. The app maps taps and drags from the visible, letterboxed image rectangle into those current pixel dimensions.
- `/input` accepts `tap {x,y}` and `swipe {x1,y1,x2,y2,duration}` only. Coordinates are finite integers inside the current frame; duration is 0.05–2 seconds and becomes 50–2000 milliseconds for `adb shell input swipe`. Run `adb` with argument arrays, an explicit `-s SERIAL`, and a five-second timeout. Serialize input commands. Text and Home remain agent-side `adb` actions, matching the iOS image-only UI.
- The relay binds to `127.0.0.1` on an ephemeral port. Every actual HTTP request needs a random session token and an Origin of `tauri://localhost` or `http://localhost:1420` (`SHOWWORK_ANDROID_ORIGINS` may override this in tests). CORS preflight validates Origin, method, and requested headers. Reject requests over 4 KiB, malformed JSON, and invalid input; never enable wildcard CORS or log tokens and frame bytes.

## Ownership and app integration

- One active run owns a serial across projects and worktrees. Reattaching the same serial to the same run returns its session. Another active run is refused. A dead relay is marked ended before a new attachment is attempted.
- The companion owns the relay and any current screenshot subprocess. It verifies the relay PID's command and session id before signaling an orphan, so a reused PID is never killed. Stop, publish, close, and orphan cleanup each end the relay and record `ended_at`; none boot, stop, wipe, install into, or reset the emulator.
- Store a session with the common `id, project_id, run, kind, title, width, height, pid, started_at, ended_at` fields and `kind: "android-emulator"`, `serial`, `port`, and `token`. Initial `width` and `height` are the first PNG's pixels; later frame headers carry rotation changes. Rust and TypeScript add this tagged variant without changing browser or iOS records. The existing watcher and tab shell handle it.
- Reuse the iOS screen's polling, object URL disposal, pointer mapping, and ended-frame behavior through a small common device view. Preserve the iOS relay's existing JPEG and `X-Points-*` contract. Android frames use PNG and `X-Pixels-*`. A failed relay or input path hides stale content and shows an error. Switching task/project aborts requests and prevents stale repaint.

## Scope and verification

No physical Android devices, emulator creation or shutdown by Showwork, video recording, audio, automatic app launch, text/Home controls in the tab, or Windows/Linux desktop app support. The executor uses a disposable headless AVD for installed-app proof, confirms tap, swipe, Split, stop/publish cleanup, and separately attempts rotation. If that AVD cannot change screenshot orientation, report the real rotation check as unverified; a synthetic PNG test still checks the coordinate math.

On this Mac, `adb` 37.0.1, the emulator CLI, two AVDs, and Android 36 system images are installed, but no emulator was running during planning. The capture and input path has not yet been exercised here. Android documents [raw PNG capture through `adb exec-out screencap -p`](https://developer.android.com/tools/adb), [explicit serial selection and device states](https://developer.android.com/tools/adb), and [headless emulator startup](https://developer.android.com/studio/run/emulator-commandline). Android's `screenrecord` has a 180-second maximum and does not support orientation changes during recording, so this increment uses bounded screenshot polling.
