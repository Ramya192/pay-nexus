import { beforeEach, describe, expect, it } from "vitest";
import { usePayslipHistoryStore, type SnapshotEntry } from "./payslipHistoryStore";

const entry1: SnapshotEntry = { id: "1", createdAt: "2026-01-01", data: { month: "2026-01" } };
const entry2: SnapshotEntry = { id: "2", createdAt: "2026-02-01", data: { month: "2026-02" } };

beforeEach(() => {
  usePayslipHistoryStore.getState().clear();
});

describe("usePayslipHistoryStore", () => {
  it("starts empty", () => {
    const s = usePayslipHistoryStore.getState();
    expect(s.entries).toEqual([]);
    expect(s.snapshots).toEqual([]);
  });

  it("setEntries derives snapshots (data only, no id/createdAt) from entries", () => {
    usePayslipHistoryStore.getState().setEntries([entry1, entry2]);
    const s = usePayslipHistoryStore.getState();
    expect(s.entries).toEqual([entry1, entry2]);
    expect(s.snapshots).toEqual([{ month: "2026-01" }, { month: "2026-02" }]);
  });

  it("addEntry appends and keeps snapshots in sync", () => {
    usePayslipHistoryStore.getState().addEntry(entry1);
    usePayslipHistoryStore.getState().addEntry(entry2);
    const s = usePayslipHistoryStore.getState();
    expect(s.entries).toHaveLength(2);
    expect(s.snapshots).toEqual([{ month: "2026-01" }, { month: "2026-02" }]);
  });

  it("removeEntries drops only the matching ids and keeps snapshots in sync", () => {
    usePayslipHistoryStore.getState().setEntries([entry1, entry2]);
    usePayslipHistoryStore.getState().removeEntries(["1"]);
    const s = usePayslipHistoryStore.getState();
    expect(s.entries).toEqual([entry2]);
    expect(s.snapshots).toEqual([{ month: "2026-02" }]);
  });

  it("clear resets both entries and snapshots", () => {
    usePayslipHistoryStore.getState().setEntries([entry1]);
    usePayslipHistoryStore.getState().clear();
    const s = usePayslipHistoryStore.getState();
    expect(s.entries).toEqual([]);
    expect(s.snapshots).toEqual([]);
  });
});
