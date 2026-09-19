import { beforeEach, describe, expect, it } from "vitest";
import { useFinancialProfileStore } from "./financialProfileStore";

beforeEach(() => {
  useFinancialProfileStore.getState().clear();
});

describe("useFinancialProfileStore", () => {
  it("starts with no profile", () => {
    expect(useFinancialProfileStore.getState().profile).toBeNull();
  });

  it("setProfile replaces the stored profile", () => {
    useFinancialProfileStore.getState().setProfile({ elssMutualFunds: 50_000 });
    expect(useFinancialProfileStore.getState().profile).toEqual({ elssMutualFunds: 50_000 });
  });

  it("clear resets to null", () => {
    useFinancialProfileStore.getState().setProfile({ elssMutualFunds: 50_000 });
    useFinancialProfileStore.getState().clear();
    expect(useFinancialProfileStore.getState().profile).toBeNull();
  });
});
