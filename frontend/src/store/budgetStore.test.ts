import { beforeEach, describe, expect, it } from "vitest";
import { useBudgetStore } from "./budgetStore";

beforeEach(() => {
  useBudgetStore.getState().clear();
});

describe("useBudgetStore", () => {
  it("starts with no budget", () => {
    expect(useBudgetStore.getState().budget).toBeNull();
  });

  it("setBudget replaces the stored category limits", () => {
    useBudgetStore.getState().setBudget({ Rent: 20_000, Groceries: 8_000 });
    expect(useBudgetStore.getState().budget).toEqual({ Rent: 20_000, Groceries: 8_000 });
  });

  it("clear resets to null", () => {
    useBudgetStore.getState().setBudget({ Rent: 20_000 });
    useBudgetStore.getState().clear();
    expect(useBudgetStore.getState().budget).toBeNull();
  });
});
