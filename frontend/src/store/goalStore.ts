import { create } from "zustand";

export const GOAL_CATEGORIES = ["Trip", "Home", "Education", "Emergency Fund", "Retirement", "Other"] as const;
export type GoalCategory = (typeof GOAL_CATEGORIES)[number];

// Plaintext shape, once decrypted client-side — matches
// backend/api/models/goals.py's documented shape exactly, and read as-is
// (camelCase keys, no remapping) by backend/analytics/goal_progress.py.
export interface Goal {
  name: string;
  category: GoalCategory;
  targetAmount: number;
  targetDate?: string; // "YYYY-MM-DD", optional
  savedAmount: number;
}

export interface GoalEntry {
  id: string; // db row id — needed to update/delete a specific goal, never sent to /chat
  createdAt: string;
  data: Goal;
}

interface GoalState {
  entries: GoalEntry[]; // full detail (id/createdAt/data), for the Goals tab's list/edit/delete UI
  // Decrypted, plaintext goals (data only, no id/createdAt) — derived from
  // entries and kept in sync on every mutation below. This is the shape
  // /chat's `goals` field expects (agents/goal_agent.py), same "full
  // detail store + derived flat array for /chat" split as
  // payslipHistoryStore.ts's entries/snapshots and transactionStore.ts's
  // entries/transactions.
  goals: Record<string, unknown>[];
  setEntries: (entries: GoalEntry[]) => void;
  addEntry: (entry: GoalEntry) => void;
  updateEntry: (id: string, data: Goal) => void;
  removeEntry: (id: string) => void;
  clear: () => void;
}

function flatten(entries: GoalEntry[]): Record<string, unknown>[] {
  return entries.map((e) => e.data as unknown as Record<string, unknown>);
}

export const useGoalStore = create<GoalState>((set) => ({
  entries: [],
  goals: [],
  setEntries: (entries) => set({ entries, goals: flatten(entries) }),
  addEntry: (entry) =>
    set((s) => {
      const entries = [...s.entries, entry];
      return { entries, goals: flatten(entries) };
    }),
  updateEntry: (id, data) =>
    set((s) => {
      const entries = s.entries.map((e) => (e.id === id ? { ...e, data } : e));
      return { entries, goals: flatten(entries) };
    }),
  removeEntry: (id) =>
    set((s) => {
      const entries = s.entries.filter((e) => e.id !== id);
      return { entries, goals: flatten(entries) };
    }),
  clear: () => set({ entries: [], goals: [] }),
}));
