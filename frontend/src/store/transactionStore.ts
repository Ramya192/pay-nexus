import { create } from "zustand";
import type { ParsedTransaction } from "../api/statement";

export interface StatementEntry {
  id: string; // db row id — needed to delete a specific saved statement, never sent to /chat
  sourceAccount: string;
  periodLabel: string;
  createdAt: string;
  transactions: ParsedTransaction[]; // decrypted, categorized transactions from this one statement
}

interface TransactionState {
  entries: StatementEntry[]; // full detail (id/account/period/createdAt), for the statement list/management UI
  // Decrypted, plaintext transactions flattened across every saved
  // statement — derived from entries and kept in sync on every mutation
  // below. This is the shape /chat's `transactions` field expects
  // (agents/spending_agent.py) — same "full detail store + derived flat
  // array for /chat" split as payslipHistoryStore.ts's entries/snapshots.
  //
  // Each transaction gets a `statement_period` field stamped on here (the
  // statement's own periodLabel it was saved under, e.g. a credit card's
  // "16 Jul 2026 to 15 Aug 2026" billing cycle) — backend/analytics/
  // spending_trends.py groups period-over-period trends by this instead of
  // slicing each transaction's calendar month, so a billing cycle that
  // crosses a calendar-month boundary isn't split into two trend buckets.
  transactions: Record<string, unknown>[];
  setEntries: (entries: StatementEntry[]) => void;
  addEntry: (entry: StatementEntry) => void;
  removeEntries: (ids: string[]) => void;
  // Replaces one saved statement's transaction list in place — used after a
  // per-row category correction is persisted (StatementList.tsx). Takes the
  // full corrected list, not a single-row patch, since that's what
  // PUT /statement/{id} itself expects too (there's no per-transaction row
  // server-side to patch, only one ciphertext blob per statement).
  updateEntryTransactions: (id: string, transactions: ParsedTransaction[]) => void;
  clear: () => void;
}

function flatten(entries: StatementEntry[]): Record<string, unknown>[] {
  return entries.flatMap((e) =>
    e.transactions.map((t) => ({ ...t, statement_period: e.periodLabel }) as Record<string, unknown>)
  );
}

export const useTransactionStore = create<TransactionState>((set) => ({
  entries: [],
  transactions: [],
  setEntries: (entries) => set({ entries, transactions: flatten(entries) }),
  addEntry: (entry) =>
    set((s) => {
      const entries = [...s.entries, entry];
      return { entries, transactions: flatten(entries) };
    }),
  removeEntries: (ids) =>
    set((s) => {
      const idSet = new Set(ids);
      const entries = s.entries.filter((e) => !idSet.has(e.id));
      return { entries, transactions: flatten(entries) };
    }),
  updateEntryTransactions: (id, transactions) =>
    set((s) => {
      const entries = s.entries.map((e) => (e.id === id ? { ...e, transactions } : e));
      return { entries, transactions: flatten(entries) };
    }),
  clear: () => set({ entries: [], transactions: [] }),
}));
