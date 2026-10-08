# Mobile review: run, exercise, capture

Use the project's existing build and UI automation workflow. Prefer available simulator/emulator MCP tools and installed project test runners; discover them before claiming the runtime is unavailable. Do not install a new device-control framework for a screenshot. The snippets below are command shapes: resolve actual device IDs, artifact paths and app IDs from the project and local tool help.

## Select and run the reviewed build

Record the review revision and local diff, platform, device ID/model/OS, build command/artifact and app identifier. Use an existing suitable simulator/emulator or boot one already configured. Select a specific device to avoid targeting another app's session; do not wipe data, uninstall unrelated apps, reset all devices or stop devices you did not start.

### iOS

Needs a macOS host with Xcode and a compatible Simulator runtime (or an available remote simulator tool). On Linux, local `xcrun` cannot supply an iOS runtime. Discover devices with the available tool or `xcrun simctl list devices available`; select the intended UDID. Use the project's scheme/configuration to build **for Simulator**, install the resulting `.app`, then launch its bundle ID. Prefer the available iOS build/debug skill or tool when installed; it is not a dependency of Showwork.

```bash
xcrun simctl boot "$review_udid" # only if not already booted
xcrun simctl bootstatus "$review_udid" -b
xcrun simctl install "$review_udid" "$review_app_path"
xcrun simctl launch "$review_udid" "$review_bundle_id"
xcrun simctl io "$review_udid" screenshot "$review_capture_path"
```

When a GUI or simulator mirroring tool is available, open the selected device there as well; a successful boot alone does not prove its window is visible. Bound boot/build waits using the tool's timeout and report failures. Capture only after navigating the intended flow. `simctl launch`/`io screenshot` do not themselves tap through screens: use existing UI tests, accessibility/device tools or supported deep links for navigation. If interaction tooling is missing, attach the actual reachable screen and mark the remaining scenario unverified. Use local `xcrun simctl help` for installed-version syntax. [Apple Simulator tooling](https://developer.apple.com/videos/play/wwdc2020/10647/).

### Android

Discover the SDK from project settings/environment; `emulator` may live in the SDK's `emulator/` directory rather than PATH. List configured AVDs with `emulator -list-avds` and connected targets with `adb devices -l`. Boot the chosen AVD with `emulator -avd "$review_avd"` if needed, keeping its process session alive. Wait with a bounded timeout for the chosen emulator to be online and `sys.boot_completed` to be `1`. Use an emulator serial, not an arbitrary attached physical phone.

Build the project using its existing Gradle/Flutter/React Native workflow. Install the reviewed debug APK (or the project's split-APK installation command) and launch the declared activity. If an install would require uninstalling an existing app or discarding its data, report that conflict rather than doing so implicitly.

```bash
adb -s "$review_serial" install -r "$review_apk_path"
adb -s "$review_serial" shell am start -W -n "$review_package_activity"
adb -s "$review_serial" exec-out screencap -p > "$review_capture_path"
```

Use the project's UI tests or available emulator interaction tools to reach the affected screen and trigger the relevant normal/failure states. Reuse documented test data and app-specific device networking instead of assuming the emulator can reach a host service at its own `localhost`. [Android emulator startup](https://developer.android.com/studio/run/emulator-commandline) · [ADB install, activity launch and screen capture](https://developer.android.com/tools/adb).

## Capture evidence, not a mock phone

- Save real PNG/JPEG captures under `.showwork/visual/` with scenario-specific names. Check command success and decode/view each image; a blank, lock, splash or unrelated screen is not evidence of the reviewed flow. Record any such failure honestly.
- Reproduce the relevant interaction before capturing its result. Include before/action/after captures when needed to demonstrate a transition. A still image proves appearance at a moment, not persistence, network correctness or the entire interaction; pair it with observed steps/logs/tests.
- Record device/OS, reviewed app/build, timestamp, scenario/actions, expected/actual result and finding ID in each section's body. Use synthetic test data; do not expose credentials or private user records in the report.
- Attach the actual file with `kind: "observed"` and `image: "scenario.png"` (relative to the handoff JSON), then publish with the shared companion. It copies the image into its local served assets. Inspect it in the resulting page.
- Browser device emulation, a generated screen and a phone-shaped HTML mockup are not native simulator evidence. Never label them as such.
- If any platform cannot build, boot, launch, navigate or capture, record the failing step/command, observed error or missing prerequisite and the exact unverified scenario. Continue other review work and publish the partial report; do not claim mobile verification is complete. Do not erase an earlier failed attempt when a later one succeeds—explain the resolution.
