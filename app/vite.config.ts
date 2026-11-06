import { defineConfig } from "vite";
// @ts-expect-error type error without @types/node package
import process from "node:process";
import { fileURLToPath } from "node:url";
const assets = fileURLToPath(new URL("../skills/showwork/assets", import.meta.url));
const host = process.env.TAURI_DEV_HOST;

// https://vite.dev/config/
export default defineConfig(() => ({
  resolve: {
    alias: [
      { find: "@report-view.css", replacement: assets + "/report-view.css" },
      { find: "@report-view", replacement: assets + "/report-view.js" },
    ],
  },

  // Vite options tailored for Tauri development and only applied in `tauri dev` or `tauri build`
  //
  // 1. prevent Vite from obscuring rust errors
  clearScreen: false,
  // 2. tauri expects a fixed port, fail if that port is not available
  server: {
    port: 1420,
    strictPort: true,
    fs: { allow: [".", assets] },
    host: host || false,
    hmr: host
      ? {
          protocol: "ws",
          host,
          port: 1421,
        }
      : undefined,
    watch: {
      // 3. tell Vite to ignore watching `src-tauri`
      ignored: ["**/src-tauri/**"],
    },
  },
}));
