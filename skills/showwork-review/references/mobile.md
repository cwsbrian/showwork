# Mobile review: run, exercise, capture in Showwork

Use the project's existing build and UI automation workflow. Discover available simulator tools and installed project test runners before claiming the runtime is unavailable. Keep the tested iOS Simulator visible as a live Showwork app tab throughout interaction and capture. Do not open Simulator.app or a separate browser as the viewing surface. Do not install a new device-control framework for a screenshot. The snippets below are command shapes: resolve actual device IDs, artifact paths and app IDs from the project and local tool help.

When Maestro is already available, prefer a project flow or a short flow on the selected iOS Simulator to navigate the reviewed state and run `takeScreenshot`. Record the flow, device, and resulting image path. Use the device commands below or another existing tool if Maestro cannot reach the scenario. A successful screenshot still requires inspection of the image and observed interaction steps.

## Select and run the reviewed build

Record the review revision and local diff, platform, device ID/model/OS, build command/artifact and app identifier. Use an existing suitable iOS Simulator or boot one already configured. Select a specific device to avoid targeting another app's session; do not wipe data, uninstall unrelated apps, reset all devices or stop devices you did not start.

### iOS

Needs a macOS host with Xcode and a compatible Simulator runtime (or an available remote simulator tool). On Linux, local `xcrun` cannot supply an iOS runtime. Discover devices with the available tool or `xcrun simctl list devices available`; select the intended UDID. Use the project's scheme/configuration to build **for Simulator**, install the resulting `.app`, then launch its bundle ID. Prefer the available iOS build/debug skill or tool when installed; it is not a dependency of Showwork.

```bash
xcrun simctl boot "$review_udid" # only if not already booted
xcrun simctl bootstatus "$review_udid" -b
xcrun simctl install "$review_udid" "$review_app_path"
xcrun simctl launch "$review_udid" "$review_bundle_id"
xcrun simctl io "$review_udid" screenshot "$review_capture_path"
```

After booting, immediately attach that UDID with `companion.py simulator open --project ... --udid "$review_udid" --require-app` and confirm its live tab appears in Showwork. A successful boot alone does not prove the in-app view works. Bound boot/build waits using the tool's timeout and report failures. Capture only after navigating the intended flow on this same device. `simctl launch`/`io screenshot` do not themselves tap through screens: use Showwork's device view, existing UI tests, accessibility/device tools or supported deep links for navigation. If interaction tooling is missing, attach the actual reachable screen and mark the remaining scenario unverified. Use local `xcrun simctl help` for installed-version syntax. [Apple Simulator tooling](https://developer.apple.com/videos/play/wwdc2020/10647/).

### Android (runtime gap)

Showwork currently has an iOS Simulator tab but no Android emulator tab. Run safe Android source/build/tests when relevant, but do not open a separate emulator window or treat a phone-shaped web preview as Android evidence. Mark runtime interaction and captures unverified with this specific tool gap.

## Capture evidence, not a mock phone

- Save real PNG/JPEG captures inside the temporary directory returned by `companion.py path --project ...`, outside the project with scenario-specific names. Check command success and decode/view each image; a blank, lock, splash or unrelated screen is not evidence of the reviewed flow. Record any such failure honestly.
- Reproduce the relevant interaction before capturing its result. Include before/action/after captures when needed to demonstrate a transition. A still image proves appearance at a moment, not persistence, network correctness or the entire interaction; pair it with observed steps/logs/tests.
- Record device/OS, reviewed app/build, timestamp, scenario/actions, expected/actual result and finding ID in each section's body. Use synthetic test data; do not expose credentials or private user records in the report.
- Attach the actual file with `kind: "observed"` and `image: "scenario.png"` (relative to the handoff JSON), then publish with the shared companion. It copies the image into its local served assets. Inspect it in the resulting page.
- Browser device emulation, a generated screen and a phone-shaped HTML mockup are not native simulator evidence. Never label them as such.
- If any platform cannot build, boot, launch, navigate or capture, record the failing step/command, observed error or missing prerequisite and the exact unverified scenario. Continue other review work and publish the partial report; do not claim mobile verification is complete. Do not erase an earlier failed attempt when a later one succeeds—explain the resolution.
