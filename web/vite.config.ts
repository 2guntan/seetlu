/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import { VitePWA } from "vite-plugin-pwa";

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
        theme_color: "#0f766e",
        background_color: "#ffffff",
      },
    }),
  ],
  server: {
    port: 5173,
    proxy: Object.fromEntries(
      ["/v1", "/healthz"].map((p) => [p, { target: process.env.VITE_API_PROXY ?? "http://localhost:8000", changeOrigin: true }]),
    ),
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test-setup.ts"],
  },
});
