# Showwork app

The macOS desktop app that keeps every Showwork report, grouped by project and branch, and lets you read plans and results again or answer decisions. It reads reports that the Showwork skills save in `~/Library/Application Support/Showwork`.

Build with Node.js and the Rust toolchain: `npm install && npm run tauri build`, then copy `src-tauri/target/release/bundle/macos/Showwork.app` to `/Applications`. See [docs/installation.md](../docs/installation.md#app-macos).

License: MIT.
