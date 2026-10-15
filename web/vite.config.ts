import { defineConfig } from "vite";

// Dev only: forward API calls to a running backend. Host is kept so the Origin check still matches.
export default defineConfig({
  server: {
    proxy: { "/api": { target: process.env.COOLPILOT_API ?? "http://127.0.0.1:8769", changeOrigin: false } },
  },
});
