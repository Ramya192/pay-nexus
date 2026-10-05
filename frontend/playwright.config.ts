import { defineConfig, devices } from "@playwright/test";

// End-to-end tests drive the real UI + real FastAPI routes, but against a throwaway SQLite
// backend (backend/e2e_server.py, port 8010) -- never the Azure Postgres from .env -- and with
// /chat mocked in the browser, so no model call or Azure spend ever happens.
const BACKEND_PORT = 8010;
const FRONTEND_PORT = 5174;
const PYTHON = process.platform === "win32" ? ".venv\\Scripts\\python.exe" : ".venv/bin/python";

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: `http://localhost:${FRONTEND_PORT}`,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: `${PYTHON} e2e_server.py ${BACKEND_PORT}`,
      cwd: "../backend",
      url: `http://127.0.0.1:${BACKEND_PORT}/docs`,
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command: `npm run dev -- --port ${FRONTEND_PORT} --strictPort`,
      url: `http://localhost:${FRONTEND_PORT}`,
      env: { E2E_API_TARGET: `http://127.0.0.1:${BACKEND_PORT}` },
      reuseExistingServer: false,
      timeout: 60_000,
    },
  ],
});
