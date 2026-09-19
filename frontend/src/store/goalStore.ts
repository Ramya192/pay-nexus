import { create } from "zustand";

export const GOAL_CATEGORIES = ["Trip", "Home", "Education", "Emergency Fund", "Retirement", "Other"] as const;
export type GoalCategory = (typeof GOAL_CATEGORIES)[number];

export const INSTRUMENT_TYPES = ["fd", "mutual_fund"] as const;
export type InstrumentType = (typeof INSTRUMENT_TYPES)[number];

// Plaintext shape, once decrypted client-side — matches
// backend/api/models/goals.py's documented shape exactly, and read as-is
// (camelCase keys, no remapping) by backend/analytics/goal_progress.py.
export interface Goal {
  name: string;
  category: GoalCategory;
  targetAmount: number;
  targetDate?: string; // "YYYY-MM-DD", optional
  savedAmount: number;
  // V2.1 — absent/undefined means a plain manual-entry goal (savedAmount is
  // typed in directly, as always). instrumentType present means savedAmount
  // is instead a LAST-KNOWN value, refreshed at read time from a live
  // lookup (see GoalList.tsx, api/goals.ts's fetchGoalValuations) — never
  // stale-persisted as if it were current, only ever displayed/used live.
  instrumentType?: InstrumentType;
  fdPrincipal?: number;
  fdAnnualRate?: number; // annual %, e.g. 7.0 for 7%
  fdStartDate?: string; // "YYYY-MM-DD"
  mfSchemeCode?: string;
  mfUnitsHeld?: number;
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
  // Live-fetched current values for instrument-linked goals, keyed by
  // entry id — deliberately NOT persisted (never sent through updateGoal),
  // just merged into `goals`/the displayed savedAmount at read time. A
  // page reload re-fetches rather than trusting a stale saved number, same
  // "always exact, refreshed at read time" principle
  // analytics/investment_valuation.py's docstring states for the backend
  // side of this feature.
  liveValues: Record<string, number>;
  setEntries: (entries: GoalEntry[]) => void;
  addEntry: (entry: GoalEntry) => void;
  updateEntry: (id: string, data: Goal) => void;
  removeEntry: (id: string) => void;
  setLiveValue: (id: string, value: number) => void;
  clear: () => void;
}

function flatten(entries: GoalEntry[], liveValues: Record<string, number>): Record<string, unknown>[] {
  return entries.map((e) => {
    const data = e.data as unknown as Record<string, unknown>;
    const liveValue = liveValues[e.id];
    // Override savedAmount with the live value for an instrument-linked
    // goal whose valuation has actually been fetched this session — this
    // is what /chat's `goals` field (agents/goal_agent.py) sees too, so a
    // chat answer about goal progress reflects the real current value, not
    // whatever was last manually typed in.
    return liveValue !== undefined ? { ...data, savedAmount: liveValue } : data;
  });
}

export const useGoalStore = create<GoalState>((set) => ({
  entries: [],
  goals: [],
  liveValues: {},
  setEntries: (entries) => set((s) => ({ entries, goals: flatten(entries, s.liveValues) })),
  addEntry: (entry) =>
    set((s) => {
      const entries = [...s.entries, entry];
      return { entries, goals: flatten(entries, s.liveValues) };
    }),
  updateEntry: (id, data) =>
    set((s) => {
      const entries = s.entries.map((e) => (e.id === id ? { ...e, data } : e));
      return { entries, goals: flatten(entries, s.liveValues) };
    }),
  removeEntry: (id) =>
    set((s) => {
      const entries = s.entries.filter((e) => e.id !== id);
      const liveValues = { ...s.liveValues };
      delete liveValues[id];
      return { entries, liveValues, goals: flatten(entries, liveValues) };
    }),
  setLiveValue: (id, value) =>
    set((s) => {
      const liveValues = { ...s.liveValues, [id]: value };
      return { liveValues, goals: flatten(s.entries, liveValues) };
    }),
  clear: () => set({ entries: [], goals: [], liveValues: {} }),
}));
