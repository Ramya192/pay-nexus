import axios from "axios";
import { useAuthStore } from "../store/authStore";

/**
 * In dev (`npm run dev`), VITE_API_BASE_URL is unset, so this stays empty
 * and requests go to relative paths (`/auth/...`, `/payslip/...`) which
 * vite.config.ts's dev proxy forwards to http://localhost:8000. In a
 * production build, `.env.production` sets VITE_API_BASE_URL to the real
 * deployed backend (§13 Phase 6 — see README's deployment section) — Vite
 * inlines env vars prefixed VITE_ at build time, so this is baked into the
 * built JS, not read at runtime.
 */
export const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || "",
});

apiClient.interceptors.request.use((config) => {
  const token = useAuthStore.getState().token;
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});
