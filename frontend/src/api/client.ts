import axios from "axios";
import { useAuthStore } from "../store/authStore";

/**
 * Base URL is left empty — requests go to relative paths (`/auth/...`,
 * `/payslip/...`) which vite.config.ts's dev proxy forwards to
 * http://localhost:8000. Set a real base URL here once the backend has a
 * deployed address (§13 Phase 6).
 */
export const apiClient = axios.create();

apiClient.interceptors.request.use((config) => {
  const token = useAuthStore.getState().token;
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});
