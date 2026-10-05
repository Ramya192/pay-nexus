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

// Oldest -> newest by month ("YYYY-MM" sorts chronologically). Entries added
// during a session (batch upload) arrive in upload order, not month order, but
// /chat's trends and "latest payslip" logic assume chronological.
function chronologicalData(entries: SnapshotEntry[]): Record<string, unknown>[] {
  return [...entries]
    .sort((a, b) => String(a.data.month ?? "").localeCompare(String(b.data.month ?? "")))
    .map((e) => e.data);
}

export const usePayslipHistoryStore = create<PayslipHistoryState>((set) => ({
  entries: [],
  snapshots: [],
  setEntries: (entries) => set({ entries, snapshots: chronologicalData(entries) }),
  addEntry: (entry) =>
    set((s) => {
      const entries = [...s.entries, entry];
      return { entries, snapshots: chronologicalData(entries) };
    }),
  removeEntries: (ids) =>
    set((s) => {
      const idSet = new Set(ids);
      const entries = s.entries.filter((e) => !idSet.has(e.id));
      return { entries, snapshots: chronologicalData(entries) };
    }),
  clear: () => set({ entries: [], snapshots: [] }),
}));
