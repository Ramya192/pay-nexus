import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      "/auth": "http://localhost:8000",
      "/chat": "http://localhost:8000",
      "/payslip": "http://localhost:8000",
      "/financial-profile": "http://localhost:8000",
      "/statement": "http://localhost:8000",
      "/goals": "http://localhost:8000",
      "/budget": "http://localhost:8000",
      "/aa": "http://localhost:8000",
    },
  },
});
