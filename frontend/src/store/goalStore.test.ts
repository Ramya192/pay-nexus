import { beforeEach, describe, expect, it } from "vitest";
import { useGoalStore, type Goal, type GoalEntry } from "./goalStore";

const manualGoal: Goal = {
  name: "Vacation",
  category: "Trip",
  targetAmount: 100_000,
  savedAmount: 40_000,
};

const fdGoal: Goal = {
  name: "Emergency fund",
  category: "Emergency Fund",
  targetAmount: 200_000,
  savedAmount: 50_000, // last-known, stale until a live value is fetched
  instrumentType: "fd",
  fdPrincipal: 45_000,
  fdAnnualRate: 7,
  fdStartDate: "2025-01-01",
};

const manualEntry: GoalEntry = { id: "g1", createdAt: "2026-01-01", data: manualGoal };
const fdEntry: GoalEntry = { id: "g2", createdAt: "2026-01-01", data: fdGoal };

beforeEach(() => {
  useGoalStore.getState().clear();
});

describe("useGoalStore", () => {
  it("starts empty", () => {
    const s = useGoalStore.getState();
    expect(s.entries).toEqual([]);
    expect(s.goals).toEqual([]);
    expect(s.liveValues).toEqual({});
  });

  it("setEntries derives goals as plain data (no id/createdAt) with savedAmount untouched absent a live value", () => {
    useGoalStore.getState().setEntries([manualEntry, fdEntry]);
    const s = useGoalStore.getState();
    expect(s.goals).toEqual([manualGoal, fdGoal]);
  });

  it("setLiveValue overrides only that entry's savedAmount in the derived goals list, not the stored entry itself", () => {
    useGoalStore.getState().setEntries([fdEntry]);
    useGoalStore.getState().setLiveValue("g2", 52_431.7);
    const s = useGoalStore.getState();
    expect(s.goals[0]).toMatchObject({ savedAmount: 52_431.7 });
    // The underlying entry's own data is never mutated by a live value.
    expect(s.entries[0].data.savedAmount).toBe(50_000);
  });

  it("a live value applies only to its own entry, leaving other goals' savedAmount alone", () => {
    useGoalStore.getState().setEntries([manualEntry, fdEntry]);
    useGoalStore.getState().setLiveValue("g2", 52_431.7);
    const s = useGoalStore.getState();
    expect(s.goals.find((g) => g.name === "Vacation")).toEqual(manualGoal);
    expect(s.goals.find((g) => g.name === "Emergency fund")).toMatchObject({ savedAmount: 52_431.7 });
  });

  it("addEntry appends and re-derives goals", () => {
    useGoalStore.getState().addEntry(manualEntry);
    useGoalStore.getState().addEntry(fdEntry);
    expect(useGoalStore.getState().goals).toHaveLength(2);
  });

  it("updateEntry replaces one goal's data by id, keeping any existing live value applied", () => {
    useGoalStore.getState().setEntries([fdEntry]);
    useGoalStore.getState().setLiveValue("g2", 60_000);
    useGoalStore.getState().updateEntry("g2", { ...fdGoal, fdAnnualRate: 7.5 });
    const s = useGoalStore.getState();
    expect(s.entries[0].data.fdAnnualRate).toBe(7.5);
    expect(s.goals[0]).toMatchObject({ savedAmount: 60_000, fdAnnualRate: 7.5 });
  });

  it("removeEntry drops the entry AND its live value, so a later goal reusing the id starts clean", () => {
    useGoalStore.getState().setEntries([fdEntry]);
    useGoalStore.getState().setLiveValue("g2", 60_000);
    useGoalStore.getState().removeEntry("g2");
    const s = useGoalStore.getState();
    expect(s.entries).toEqual([]);
    expect(s.goals).toEqual([]);
    expect(s.liveValues).toEqual({});
  });

  it("clear resets entries, goals, and liveValues together", () => {
    useGoalStore.getState().setEntries([fdEntry]);
    useGoalStore.getState().setLiveValue("g2", 60_000);
    useGoalStore.getState().clear();
    const s = useGoalStore.getState();
    expect(s.entries).toEqual([]);
    expect(s.goals).toEqual([]);
    expect(s.liveValues).toEqual({});
  });
});
