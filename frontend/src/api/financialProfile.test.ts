import { afterEach, describe, expect, it, vi } from "vitest";
import { apiClient } from "./client";
import { fetchFinancialProfile, saveFinancialProfile } from "./financialProfile";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("saveFinancialProfile", () => {
  it("PUTs the ciphertext/iv, remapped from the camelCase blob shape", async () => {
    const put = vi.spyOn(apiClient, "put").mockResolvedValue({ data: {} });
    await saveFinancialProfile({ ciphertextB64: "ct==", ivB64: "iv==" });
    expect(put).toHaveBeenCalledWith("/financial-profile", { ciphertext_b64: "ct==", iv_b64: "iv==" });
  });
});

describe("fetchFinancialProfile", () => {
  it("returns the row on success", async () => {
    const row = { ciphertext_b64: "ct==", iv_b64: "iv==", updated_at: "2026-01-01" };
    vi.spyOn(apiClient, "get").mockResolvedValue({ data: row });
    expect(await fetchFinancialProfile()).toEqual(row);
  });

  it("returns null for a fresh account (404), rather than throwing", async () => {
    vi.spyOn(apiClient, "get").mockRejectedValue({ response: { status: 404 } });
    expect(await fetchFinancialProfile()).toBeNull();
  });

  it("rethrows any other error", async () => {
    const serverError = { response: { status: 500 } };
    vi.spyOn(apiClient, "get").mockRejectedValue(serverError);
    await expect(fetchFinancialProfile()).rejects.toBe(serverError);
  });
});
