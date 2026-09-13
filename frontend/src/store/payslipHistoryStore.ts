import { create } from "zustand";

export interface SnapshotEntry {
  id: string; // db row id — needed to delete a specific saved snapshot, never sent to /chat
  createdAt: string;
  data: Record<string, unknown>; // decrypted payslip fields
}

interface PayslipHistoryState {
  entries: SnapshotEntry[]; // full detail (id/createdAt/data), for the Payslip history management UI
  // Decrypted, plaintext saved payslip snapshots, oldest -> newest — derived
  // from entries (data only, no id/createdAt) and kept in sync on every
  // mutation below. This is the shape /chat's payslip_history field expects
  // (agents/payslip_agent.py, payslip_trends.py) — NOT the same thing as
  // sessionHistoryStore (that holds compressed session *summaries*, not raw
  // payslip fields).
  snapshots: Record<string, unknown>[];
  setEntries: (entries: SnapshotEntry[]) => void;
  addEntry: (entry: SnapshotEntry) => void;
  removeEntries: (ids: string[]) => void;
  clear: () => void;
}

export const usePayslipHistoryStore = create<PayslipHistoryState>((set) => ({
  entries: [],
  snapshots: [],
  setEntries: (entries) => set({ entries, snapshots: entries.map((e) => e.data) }),
  addEntry: (entry) =>
    set((s) => {
      const entries = [...s.entries, entry];
      return { entries, snapshots: entries.map((e) => e.data) };
    }),
  removeEntries: (ids) =>
    set((s) => {
      const idSet = new Set(ids);
      const entries = s.entries.filter((e) => !idSet.has(e.id));
      return { entries, snapshots: entries.map((e) => e.data) };
    }),
  clear: () => set({ entries: [], snapshots: [] }),
}));
