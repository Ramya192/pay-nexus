import { afterEach, describe, expect, it, vi } from "vitest";
import { apiClient } from "./client";
import {
  deleteSnapshot,
  fetchHistory,
  fetchSnapshots,
  isDuplicatePayslipError,
  parsePayslipText,
  saveSessionSummary,
  savePayslip,
} from "./payslip";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("savePayslip", () => {
  it("POSTs the month and ciphertext/iv", async () => {
    const post = vi
      .spyOn(apiClient, "post")
      .mockResolvedValue({ data: { id: "p1", month: "2026-08", created_at: "2026-08-01" } });
    await savePayslip("2026-08", { ciphertextB64: "ct==", ivB64: "iv==" });
    expect(post).toHaveBeenCalledWith("/payslip/save", {
      month: "2026-08",
      ciphertext_b64: "ct==",
      iv_b64: "iv==",
    });
  });
});

describe("isDuplicatePayslipError", () => {
  it("is true for a 409 response", () => {
    expect(isDuplicatePayslipError({ response: { status: 409 } })).toBe(true);
  });

  it("is false for any other status", () => {
    expect(isDuplicatePayslipError({ response: { status: 500 } })).toBe(false);
  });

  it("is false for a malformed/non-axios error, not a throw", () => {
    expect(isDuplicatePayslipError(new Error("network down"))).toBe(false);
    expect(isDuplicatePayslipError(null)).toBe(false);
  });
});

describe("deleteSnapshot", () => {
  it("DELETEs /payslip/snapshots/{id}", async () => {
    const del = vi.spyOn(apiClient, "delete").mockResolvedValue({ data: {} });
    await deleteSnapshot("s1");
    expect(del).toHaveBeenCalledWith("/payslip/snapshots/s1");
  });
});

describe("fetchHistory", () => {
  it("GETs /payslip/history", async () => {
    const rows = [{ id: "h1", ciphertext_b64: "ct==", iv_b64: "iv==", created_at: "2026-01-01" }];
    vi.spyOn(apiClient, "get").mockResolvedValue({ data: rows });
    expect(await fetchHistory()).toEqual(rows);
  });
});

describe("saveSessionSummary", () => {
  it("POSTs the ciphertext/iv", async () => {
    const post = vi.spyOn(apiClient, "post").mockResolvedValue({ data: {} });
    await saveSessionSummary({ ciphertextB64: "ct==", ivB64: "iv==" });
    expect(post).toHaveBeenCalledWith("/payslip/session-summary", { ciphertext_b64: "ct==", iv_b64: "iv==" });
  });
});

describe("parsePayslipText", () => {
  it("unwraps the response's fields object", async () => {
    vi.spyOn(apiClient, "post").mockResolvedValue({ data: { fields: { basic: 50_000 } } });
    expect(await parsePayslipText("raw pdf text")).toEqual({ basic: 50_000 });
  });
});

describe("fetchSnapshots", () => {
  it("GETs /payslip/snapshots", async () => {
    const rows = [{ id: "s1", month: "2026-08", ciphertext_b64: "ct==", iv_b64: "iv==", created_at: "2026-08-01" }];
    vi.spyOn(apiClient, "get").mockResolvedValue({ data: rows });
    expect(await fetchSnapshots()).toEqual(rows);
  });
});
