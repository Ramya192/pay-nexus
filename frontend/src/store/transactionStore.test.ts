import { beforeEach, describe, expect, it } from "vitest";
import { useTransactionStore, type StatementEntry } from "./transactionStore";
import type { ParsedTransaction } from "../api/statement";

function tx(overrides: Partial<ParsedTransaction>): ParsedTransaction {
  return {
    transaction_id: "t1",
    date: "2026-07-01",
    description: "Rent",
    amount: -20_000,
    source_account: "HDFC",
    category: "Rent",
    category_source: "rule",
    ...overrides,
  };
}

const julyEntry: StatementEntry = {
  id: "s1",
  sourceAccount: "HDFC",
  periodLabel: "2026-07",
  createdAt: "2026-07-31",
  transactions: [tx({ transaction_id: "a" })],
};

const augEntry: StatementEntry = {
  id: "s2",
  sourceAccount: "HDFC",
  periodLabel: "2026-08",
  createdAt: "2026-08-31",
  transactions: [tx({ transaction_id: "b", date: "2026-08-01" })],
};

beforeEach(() => {
  useTransactionStore.getState().clear();
});

describe("useTransactionStore", () => {
  it("starts empty", () => {
    const s = useTransactionStore.getState();
    expect(s.entries).toEqual([]);
    expect(s.transactions).toEqual([]);
  });

  it("setEntries flattens transactions and stamps each with its statement's periodLabel", () => {
    useTransactionStore.getState().setEntries([julyEntry, augEntry]);
    const s = useTransactionStore.getState();
    expect(s.transactions).toHaveLength(2);
    expect(s.transactions[0]).toMatchObject({ transaction_id: "a", statement_period: "2026-07" });
    expect(s.transactions[1]).toMatchObject({ transaction_id: "b", statement_period: "2026-08" });
  });

  it("addEntry appends and re-flattens", () => {
    useTransactionStore.getState().addEntry(julyEntry);
    useTransactionStore.getState().addEntry(augEntry);
    expect(useTransactionStore.getState().transactions).toHaveLength(2);
  });

  it("removeEntries drops only the matching statement and its transactions", () => {
    useTransactionStore.getState().setEntries([julyEntry, augEntry]);
    useTransactionStore.getState().removeEntries(["s1"]);
    const s = useTransactionStore.getState();
    expect(s.entries).toEqual([augEntry]);
    expect(s.transactions).toHaveLength(1);
    expect(s.transactions[0]).toMatchObject({ transaction_id: "b" });
  });

  it("updateEntryTransactions replaces one statement's transaction list in place, by id", () => {
    useTransactionStore.getState().setEntries([julyEntry, augEntry]);
    const corrected = [tx({ transaction_id: "a", category: "Shopping" })];
    useTransactionStore.getState().updateEntryTransactions("s1", corrected);
    const s = useTransactionStore.getState();
    expect(s.entries.find((e) => e.id === "s1")!.transactions).toEqual(corrected);
    // The other statement's own transactions are untouched.
    expect(s.entries.find((e) => e.id === "s2")!.transactions).toEqual(augEntry.transactions);
    expect(s.transactions.find((t) => t.transaction_id === "a")).toMatchObject({ category: "Shopping" });
  });

  it("clear resets both entries and the flattened list", () => {
    useTransactionStore.getState().setEntries([julyEntry]);
    useTransactionStore.getState().clear();
    const s = useTransactionStore.getState();
    expect(s.entries).toEqual([]);
    expect(s.transactions).toEqual([]);
  });
});
