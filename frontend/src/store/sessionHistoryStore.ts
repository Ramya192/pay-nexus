import { create } from "zustand";

interface SessionHistoryState {
  // Decrypted, plaintext Level 2 summaries (§6) — fetched from GET
  // /payslip/history (ciphertext) and decrypted client-side on login, since
  // only the client holds the AES key. Fed to /chat as session_history so
  // the Nudge Agent can see cross-session patterns for the first time.
  history: Record<string, unknown>[];
  setHistory: (history: Record<string, unknown>[]) => void;
  clear: () => void;
}

export const useSessionHistoryStore = create<SessionHistoryState>((set) => ({
  history: [],
  setHistory: (history) => set({ history }),
  clear: () => set({ history: [] }),
}));
