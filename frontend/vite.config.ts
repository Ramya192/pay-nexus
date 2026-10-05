/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// E2E_API_TARGET lets the Playwright run (e2e/) point the dev proxy at its throwaway backend
// instead of a developer's real one on :8000.
const API = process.env.E2E_API_TARGET ?? "http://localhost:8000";

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  test: {
    environment: "jsdom",
    setupFiles: "./src/test/setup.ts",
    globals: true,
    exclude: ["e2e/**", "node_modules/**"],
  },
  server: {
    proxy: {
      "/auth": API,
      "/chat": API,
      "/payslip": API,
      "/financial-profile": API,
      "/statement": API,
      "/goals": API,
      "/budget": API,
      "/aa": API,
    },
  },
});
