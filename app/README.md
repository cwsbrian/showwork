# Showwork app

The macOS desktop app that keeps every Showwork report, grouped by project and branch, and lets you read plans and results again or answer decisions. It reads reports that the Showwork skills save in `~/Library/Application Support/Showwork`.

Build with Node.js and the Rust toolchain. Release builds also need the updater signing key; see [app installation and updates](../docs/installation.md#app-macos). **Check for updates** compares the app's build commit with the latest commit on GitHub's `main` branch. When a matching signed app build is published, it downloads, installs, and restarts Showwork. It does not update the Codex or Claude skills; those use the separate `npx` installer.

License: MIT.
