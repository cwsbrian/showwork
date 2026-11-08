# iOS Simulator Sessions in Showwork — design

Status: implementation target for the next live-session increment. This document narrows the later mobile work named in `2026-11-06-live-sessions-design.md` to **iOS Simulator only**. Android Emulator gets a separate design and plan.

## Result

An agent starts a Showwork task, boots an iOS Simulator with its normal tools, and attaches that already-booted device with `companion.py simulator open --project P --udid U [--title T]`. The selected task gains an iOS session tab. The user sees the live device screen inside Showwork, taps and swipes it, and can send text to the focused field. Two or more browser/iOS sessions appear together in the existing Split tab; previews do not accept input. Publishing or stopping the task ends the Showwork attachment, leaves the Simulator boot state alone, and marks its tab ended until the user closes it.

The app does not boot, shut down, install into, or erase a Simulator. The agent still uses `simctl`, `idb`, Xcode, or Maestro for setup and evidence. A real screenshot attached to a report is captured with the agent's device tool into the Showwork temporary directory, with the device, OS, app build, interaction, and capture method recorded. A streamed frame in the tab is for viewing and control, not automatically report evidence.

## Requirements and limits

- macOS only. Require Python 3.11+, Xcode Simulator tools, and an `idb` CLI with its companion that supports `describe`, `video-stream --format mjpeg`, `ui tap`, `ui swipe`, and `ui text`. If any part is missing, `simulator open` reports the missing command and creates no session.
- Attach by explicit UDID to a **booted** iOS Simulator. Do not choose an arbitrary `booted` device. A second attach to the same UDID and run returns the existing session. A different active run cannot attach the same UDID until its session ends.
- The companion owns a local relay process and its `idb video-stream` child, exactly as it owns headless Chrome sessions. `simulator close`, publish, stop, and orphan cleanup stop the relay and stream, record `ended_at`, and never shut down the Simulator.
- The relay listens only on `127.0.0.1` at an ephemeral port. It holds only the newest JPEG frame in memory. No frame, video, token, or one-off script is written to the project. Cap the stream at 10 fps, scale 0.5, and reject frames larger than 8 MiB.
- The relay's HTTP API requires a random session token on every actual request and accepts cross-origin calls only from `tauri://localhost` and `http://localhost:1420` (or `SHOWWORK_IOS_ORIGINS` for tests). CORS `OPTIONS` preflight checks the Origin and requested headers; browsers do not send the token value in preflight. Do not enable wildcard CORS. Reject malformed or out-of-bounds input; invoke `idb` with argument lists and a timeout, never a shell string.
- `GET /frame?after=N` waits up to 2 seconds for a newer frame. It returns JPEG bytes with sequence and current screen dimensions in **points**, `204` when unchanged, and `410` when the stream ended. `POST /input` accepts only `tap`, `swipe`, `text`, and `button: HOME`, with a 4 KiB JSON body limit. Text is at most 2048 characters; swipes last 0.05–2 seconds. The relay serializes input commands.
- The iOS tab fits the device image without stretching or cropping. Pointer coordinates map from the displayed image rectangle to the device's point dimensions, including letterboxing. A click is a tap; a drag is a swipe. A small text field with a Send button enters text into the Simulator's currently focused field. A Home button sends `idb ui button HOME`. Split previews remain view-only.
- On an orientation change, the image keeps its natural ratio and the relay sends point dimensions matching the frame orientation. Input mapping uses those current dimensions. If the stream or input path fails, the tab shows a clear error; the app does not keep showing an apparently live frozen frame.
- Ended tabs retain the last frame while the app process has it, dimmed as browser tabs do. After an app restart there is no saved frame; show an ended placeholder, not a broken image. Deleting an ended tab removes its session file.
- Browser tabs, reports, project switching, and the existing report store keep their behavior. No Android support, visible `Simulator.app` window, video recording, remote device, or automatic iOS app launch is in this increment.

## Transport and ownership

`ios_simulator.py` validates the UDID and current run, checks `idb describe --json` for a booted simulator and screen dimensions, starts `ios_relay.py`, waits for its first frame and ready line, and only then writes `sessions/<id>.json`. The record has the common session fields plus `kind: "ios-simulator"`, `udid`, `points_width`, `points_height`, `port`, and `token`; it has no browser `url` or `ws`. The relay PID is the session `pid`, so the existing Rust alive check and running watcher can detect a dead relay. The Python owner verifies that PID still belongs to this relay before signaling it, to avoid killing a reused PID.

The Rust reader accepts either the existing browser shape or the iOS shape, skips malformed or unknown kinds, and sends a tagged `kind` value to TypeScript. The webview uses `fetch` with an abortable long poll, reuses one stream per session across its tab and Split preview, and releases requests and object URLs when a task changes. The webview sends input only for the selected full tab. App CSP permits `http://127.0.0.1:*` connections and `blob:` images for this relay.

## Feasibility observed on this Mac

On 2026-11-07, Xcode 26.6 and an iOS 26.5 iPhone 17 Pro Simulator were available. Booting by UDID without `Simulator.app` produced an `idb` JPEG screenshot and two MJPEG frames from `idb video-stream --format mjpeg --fps 10 --scale-factor 0.5`. `idb ui tap 150 800 --udid ...` opened Safari, confirmed by a second screenshot. A later rotation probe was inconclusive: `idb rotation` reported an unsupported CoreDevice capability and `idb screenshot` then failed, while `simctl io screenshot` still worked. The test Simulator was shut down afterward. The basic capture/tap path is locally proven; orientation mapping, relay recovery, text entry, and installed-app integration are explicit execution gates, not verified results.

Technical basis: [idb video streams](https://fbidb.io/idb/video/), [idb UI input](https://fbidb.io/docs/idb/ui/), and [Apple's `simctl` reference](https://developer.apple.com/documentation/xcode/xcode-command-line-tool-reference).
