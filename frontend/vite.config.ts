import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { VitePWA } from "vite-plugin-pwa";
import { defineConfig } from "vitest/config";

// In dev the Vite server proxies API/auth calls to Django so the browser sees one origin
// (session cookie + CSRF work exactly as in production, where Django serves the built SPA).
const backend = process.env.VITE_BACKEND_URL ?? "http://web:8000";

export default defineConfig({
  base: "/app/",
  plugins: [
    react(),
    tailwindcss(),
    VitePWA({
      registerType: "autoUpdate",
      scope: "/app/",
      includeAssets: ["icons/apple-touch-icon.png"],
      manifest: {
        name: "Travel History",
        short_name: "Travel",
        description: "Our family's travel history",
        start_url: "/app/",
        scope: "/app/",
        display: "standalone",
        background_color: "#f8fafc",
        theme_color: "#1d4ed8",
        icons: [
          { src: "icons/icon-192.png", sizes: "192x192", type: "image/png" },
          { src: "icons/icon-512.png", sizes: "512x512", type: "image/png" },
          { src: "icons/maskable-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
        ],
      },
      workbox: {
        // App shell only. API data and map tiles are never cached by the service worker.
        globPatterns: ["**/*.{js,css,html,png,svg,woff2}"],
        navigateFallback: "/app/index.html",
        navigateFallbackDenylist: [/^\/api\//, /^\/auth\//],
        runtimeCaching: [],
      },
    }),
  ],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": { target: backend },
      "/auth": { target: backend },
      "/healthz": { target: backend },
    },
  },
  // MapLibre alone is ~800 kB minified; it is one cacheable chunk, not a sign of bloat.
  build: { outDir: "dist", sourcemap: true, chunkSizeWarningLimit: 1200 },
  test: {
    environment: "jsdom",
    globals: true,
    include: ["src/**/*.test.{ts,tsx}"],
    setupFiles: ["src/test/setup.ts"],
  },
});
