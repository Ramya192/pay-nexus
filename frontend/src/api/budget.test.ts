import { afterEach, describe, expect, it, vi } from "vitest";
import { apiClient } from "./client";
import { fetchBudget, fetchSuggestedBudget, saveBudget } from "./budget";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("saveBudget", () => {
  it("PUTs the ciphertext/iv, remapped from the camelCase blob shape", async () => {
    const put = vi.spyOn(apiClient, "put").mockResolvedValue({ data: {} });
    await saveBudget({ ciphertextB64: "ct==", ivB64: "iv==" });
    expect(put).toHaveBeenCalledWith("/budget", { ciphertext_b64: "ct==", iv_b64: "iv==" });
  });
});

describe("fetchBudget", () => {
  it("returns the row on success", async () => {
    const row = { ciphertext_b64: "ct==", iv_b64: "iv==", updated_at: "2026-01-01" };
    vi.spyOn(apiClient, "get").mockResolvedValue({ data: row });
    expect(await fetchBudget()).toEqual(row);
  });

  it("returns null for a fresh account (404), rather than throwing", async () => {
    vi.spyOn(apiClient, "get").mockRejectedValue({ response: { status: 404 } });
    expect(await fetchBudget()).toBeNull();
  });

  it("rethrows any other error", async () => {
    const serverError = { response: { status: 500 } };
    vi.spyOn(apiClient, "get").mockRejectedValue(serverError);
    await expect(fetchBudget()).rejects.toBe(serverError);
  });
});

describe("fetchSuggestedBudget", () => {
  it("passes monthly_income as a query param when given", async () => {
    const get = vi.spyOn(apiClient, "get").mockResolvedValue({
      data: { salary_bracket: "50k-75k", budgets: { Rent: 20_000 } },
    });
    await fetchSuggestedBudget(60_000);
    expect(get).toHaveBeenCalledWith("/budget/suggested", { params: { monthly_income: 60_000 } });
  });

  it("sends no params when no income is given", async () => {
    const get = vi.spyOn(apiClient, "get").mockResolvedValue({
      data: { salary_bracket: "default", budgets: {} },
    });
    await fetchSuggestedBudget();
    expect(get).toHaveBeenCalledWith("/budget/suggested", { params: {} });
  });
});
