import { afterEach, describe, expect, it, vi } from "vitest";
import { apiClient } from "./client";
import { createGoal, deleteGoal, fetchGoalValuations, fetchGoals, updateGoal } from "./goals";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("createGoal", () => {
  it("POSTs the ciphertext/iv and returns the save receipt", async () => {
    const post = vi.spyOn(apiClient, "post").mockResolvedValue({ data: { id: "g1", created_at: "2026-01-01" } });
    const result = await createGoal({ ciphertextB64: "ct==", ivB64: "iv==" });
    expect(post).toHaveBeenCalledWith("/goals", { ciphertext_b64: "ct==", iv_b64: "iv==" });
    expect(result).toEqual({ id: "g1", created_at: "2026-01-01" });
  });
});

describe("updateGoal", () => {
  it("PUTs to /goals/{id} with the ciphertext/iv", async () => {
    const put = vi.spyOn(apiClient, "put").mockResolvedValue({ data: { id: "g1", created_at: "2026-01-01" } });
    await updateGoal("g1", { ciphertextB64: "ct==", ivB64: "iv==" });
    expect(put).toHaveBeenCalledWith("/goals/g1", { ciphertext_b64: "ct==", iv_b64: "iv==" });
  });
});

describe("deleteGoal", () => {
  it("DELETEs /goals/{id}", async () => {
    const del = vi.spyOn(apiClient, "delete").mockResolvedValue({ data: {} });
    await deleteGoal("g1");
    expect(del).toHaveBeenCalledWith("/goals/g1");
  });
});

describe("fetchGoals", () => {
  it("GETs /goals and returns the rows", async () => {
    const rows = [{ id: "g1", ciphertext_b64: "ct==", iv_b64: "iv==", created_at: "2026-01-01" }];
    vi.spyOn(apiClient, "get").mockResolvedValue({ data: rows });
    expect(await fetchGoals()).toEqual(rows);
  });
});

describe("fetchGoalValuations", () => {
  it("skips the network call entirely for an empty entry list", async () => {
    const post = vi.spyOn(apiClient, "post");
    expect(await fetchGoalValuations([])).toEqual([]);
    expect(post).not.toHaveBeenCalled();
  });

  it("POSTs the entries and returns per-goal results when non-empty", async () => {
    const entries = [{ goal_id: "g1", instrument_type: "fd" as const, fd_principal: 45_000, fd_annual_rate: 7 }];
    const results = [{ goal_id: "g1", current_value: 48_000, error: null }];
    const post = vi.spyOn(apiClient, "post").mockResolvedValue({ data: results });
    expect(await fetchGoalValuations(entries)).toEqual(results);
    expect(post).toHaveBeenCalledWith("/goals/valuation", entries);
  });
});
