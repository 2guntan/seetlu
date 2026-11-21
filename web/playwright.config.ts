import { defineConfig, devices } from "@playwright/test";

// The 5 web journeys of docs/10. The API is mocked with page.route (e2e/mock-api.ts);
// the full stack is exercised by `make e2e`.
export default defineConfig({
  testDir: "e2e",
  timeout: 30_000,
  retries: process.env.CI ? 1 : 0,
  use: {
    baseURL: "http://localhost:4173",
    serviceWorkers: "block",
    locale: "fr-FR",
    timezoneId: "Africa/Dakar",
    ...devices["Pixel 5"],
  },
  webServer: {
    command: "npx vite build --logLevel error && npx vite preview --port 4173 --strictPort",
    url: "http://localhost:4173",
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
