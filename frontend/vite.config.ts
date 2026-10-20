import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// In dev the Vite server proxies API/auth calls to Django so the browser sees one origin
// (session cookie + CSRF work exactly as in production, where Django serves the built SPA).
const backend = process.env.VITE_BACKEND_URL ?? "http://web:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": { target: backend },
      "/auth": { target: backend },
      "/healthz": { target: backend },
    },
  },
  build: { outDir: "dist", sourcemap: true },
  test: {
    environment: "jsdom",
    globals: true,
    include: ["src/**/*.test.{ts,tsx}"],
    setupFiles: ["src/test/setup.ts"],
  },
});
