# Showwork app

The macOS desktop app that keeps every Showwork report, grouped by project and branch, and lets you read plans and results again or answer decisions. It reads reports that the Showwork skills save in `~/Library/Application Support/Showwork`.

Build with Node.js and the Rust toolchain. Release builds also need the updater signing key; see [app installation and updates](../docs/installation.md#app-macos). On launch and every 30 minutes, the app compares its build commit with the latest commit on GitHub's `main` branch. A matching signed build shows an **Update available** notice at the bottom left; the user can install it there and restart Showwork. It does not update the Codex or Claude skills; those use the separate `npx` installer.

License: MIT.
