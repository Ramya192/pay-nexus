import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { apiClient } from "./client";
import { useTransactionStore } from "../store/transactionStore";
import {
  categorizeManualTransaction,
  deleteStatement,
  fetchSpendingAnalytics,
  fetchStatements,
  getErrorDetail,
  isDuplicateStatementError,
  parseStatementText,
  saveStatement,
  updateStatement,
} from "./statement";

beforeEach(() => {
  useTransactionStore.getState().clear();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("parseStatementText", () => {
  it("builds historical_labels from the store's own categorized transactions, excluding Uncategorized and non-string descriptions", async () => {
    useTransactionStore.setState({
      transactions: [
        { description: "Netflix", category: "Subscriptions" },
        { description: "ATM withdrawal", category: "Uncategorized" }, // excluded: not real signal
        { description: 12345, category: "Shopping" }, // excluded: not a string description
        { description: "Big Bazaar", category: "Groceries" },
      ],
    });
    const post = vi.spyOn(apiClient, "post").mockResolvedValue({
      data: { transactions: [], skipped_row_count: 0, truncated_chars: 0 },
    });
    await parseStatementText("raw text", "HDFC", "csv");
    expect(post).toHaveBeenCalledWith("/statement/parse", {
      text: "raw text",
      source_account: "HDFC",
      format: "csv",
      historical_labels: [
        { description: "Netflix", category: "Subscriptions" },
        { description: "Big Bazaar", category: "Groceries" },
      ],
    });
  });
});

describe("categorizeManualTransaction", () => {
  it("defaults occurrence to 0 and falls a blank category back to null", async () => {
    const post = vi.spyOn(apiClient, "post").mockResolvedValue({
      data: {
        transaction_id: "t1",
        date: "2026-08-01",
        description: "Cash",
        amount: -500,
        source_account: "Cash",
        category: "Shopping",
        category_source: "llm",
      },
    });
    await categorizeManualTransaction("2026-08-01", "Cash", -500, "Cash");
    expect(post).toHaveBeenCalledWith("/statement/categorize-manual", {
      date: "2026-08-01",
      description: "Cash",
      amount: -500,
      source_account: "Cash",
      category: null,
      occurrence: 0,
      historical_labels: [],
    });
  });
});

describe("saveStatement", () => {
  it("POSTs account/period/ciphertext/iv/content-hash together", async () => {
    const post = vi.spyOn(apiClient, "post").mockResolvedValue({
      data: { id: "st1", source_account: "HDFC", period_label: "2026-08", created_at: "2026-08-31" },
    });
    await saveStatement("HDFC", "2026-08", { ciphertextB64: "ct==", ivB64: "iv==" }, "hash123");
    expect(post).toHaveBeenCalledWith("/statement/save", {
      source_account: "HDFC",
      period_label: "2026-08",
      ciphertext_b64: "ct==",
      iv_b64: "iv==",
      content_hash: "hash123",
    });
  });
});

describe("isDuplicateStatementError", () => {
  it("is true only for a 409", () => {
    expect(isDuplicateStatementError({ response: { status: 409 } })).toBe(true);
    expect(isDuplicateStatementError({ response: { status: 500 } })).toBe(false);
  });
});

describe("getErrorDetail", () => {
  it("extracts the server's string detail", () => {
    expect(getErrorDetail({ response: { data: { detail: "duplicate under HDFC/2026-08" } } })).toBe(
      "duplicate under HDFC/2026-08"
    );
  });

  it("returns undefined when the error isn't shaped as expected", () => {
    expect(getErrorDetail(new Error("network down"))).toBeUndefined();
    expect(getErrorDetail({ response: { data: { detail: 42 } } })).toBeUndefined();
  });
});

describe("updateStatement", () => {
  it("PUTs to /statement/{id}", async () => {
    const put = vi.spyOn(apiClient, "put").mockResolvedValue({
      data: { id: "st1", source_account: "HDFC", period_label: "2026-08", created_at: "2026-08-31" },
    });
    await updateStatement("st1", { ciphertextB64: "ct==", ivB64: "iv==" });
    expect(put).toHaveBeenCalledWith("/statement/st1", { ciphertext_b64: "ct==", iv_b64: "iv==" });
  });
});

describe("deleteStatement", () => {
  it("DELETEs /statement/{id}", async () => {
    const del = vi.spyOn(apiClient, "delete").mockResolvedValue({ data: {} });
    await deleteStatement("st1");
    expect(del).toHaveBeenCalledWith("/statement/st1");
  });
});

describe("fetchStatements", () => {
  it("GETs /statement/list", async () => {
    const rows = [
      { id: "st1", source_account: "HDFC", period_label: "2026-08", ciphertext_b64: "ct==", iv_b64: "iv==", created_at: "2026-08-31" },
    ];
    vi.spyOn(apiClient, "get").mockResolvedValue({ data: rows });
    expect(await fetchStatements()).toEqual(rows);
  });
});

describe("fetchSpendingAnalytics", () => {
  it("POSTs the transaction list to /statement/analytics", async () => {
    const result = { category_breakdown: [], savings_projection: null };
    const post = vi.spyOn(apiClient, "post").mockResolvedValue({ data: result });
    const transactions = [{ amount: -100 }];
    expect(await fetchSpendingAnalytics(transactions)).toEqual(result);
    expect(post).toHaveBeenCalledWith("/statement/analytics", { transactions });
  });
});
