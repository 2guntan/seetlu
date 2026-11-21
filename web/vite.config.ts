/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import { VitePWA } from "vite-plugin-pwa";

const THIRTY_DAYS = 30 * 24 * 3600;

export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: "autoUpdate",
      manifest: {
        name: "Seetlu",
        short_name: "Seetlu",
        lang: "fr",
        start_url: "/",
        display: "standalone",
        theme_color: "#1d45a6",
        background_color: "#f4f2ec",
      },
      workbox: {
        // Precache the self-hosted font so the design works offline (DESIGN.md).
        globPatterns: ["**/*.{js,css,html,svg,png,woff2}"],
        navigateFallback: "/index.html",
        navigateFallbackDenylist: [/^\/v1\//, /^\/healthz/],
        // AC-F7-3: last 30 days of data readable offline. Network first, cache fallback.
        // Clip URLs, auth and writes are never cached.
        runtimeCaching: [
          {
            urlPattern: ({ url, request }) =>
              request.method === "GET" &&
              /^\/v1\/(me|shops(\/[^/]+(\/(reports|today|hourly|events|sales|alert-rules|users))?)?)$/.test(url.pathname),
            handler: "NetworkFirst",
            options: {
              cacheName: "seetlu-data",
              networkTimeoutSeconds: 8,
              expiration: { maxEntries: 400, maxAgeSeconds: THIRTY_DAYS },
              cacheableResponse: { statuses: [200] },
            },
          },
        ],
      },
    }),
  ],
  build: { target: "es2020" },
  server: {
    port: 5173,
    proxy: Object.fromEntries(
      ["/v1", "/healthz"].map((p) => [p, { target: process.env.VITE_API_PROXY ?? "http://localhost:8000", changeOrigin: true }]),
    ),
  },
  preview: { port: 4173 },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test-setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
