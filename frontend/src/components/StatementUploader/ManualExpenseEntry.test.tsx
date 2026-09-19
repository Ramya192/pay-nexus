import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ManualExpenseEntry } from "./ManualExpenseEntry";
import { useAuthStore } from "../../store/authStore";
import { useTransactionStore, type StatementEntry } from "../../store/transactionStore";
import * as statementApi from "../../api/statement";
import * as encryption from "../../crypto/clientEncryption";
import * as contentHash from "../../utils/contentHash";

vi.mock("../../crypto/clientEncryption", () => ({
  encryptJSON: vi.fn(),
}));
vi.mock("../../utils/contentHash", () => ({
  computeContentHash: vi.fn(),
}));

function categorizedTxn(overrides: Partial<statementApi.ParsedTransaction> = {}): statementApi.ParsedTransaction {
  return {
    transaction_id: "new-1",
    date: "2026-08-05",
    description: "Vegetable market",
    amount: -500,
    source_account: "Cash",
    category: "Groceries",
    category_source: "llm",
    ...overrides,
  };
}

beforeEach(() => {
  useTransactionStore.getState().clear();
  useAuthStore.getState().setAuth("tok", "salt==", "user@example.com", {} as CryptoKey);
  vi.mocked(encryption.encryptJSON).mockResolvedValue({ ciphertextB64: "ct==", ivB64: "iv==" });
  vi.mocked(contentHash.computeContentHash).mockResolvedValue("hash123");
});

afterEach(() => {
  vi.restoreAllMocks();
});

async function fillRequiredFields(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText("Date"), "2026-08-05");
  await user.type(screen.getByLabelText("Description"), "Vegetable market");
  await user.type(screen.getByLabelText("Amount (₹)"), "500");
}

describe("ManualExpenseEntry", () => {
  it("requires date, description, and amount before submitting", async () => {
    const user = userEvent.setup();
    const categorize = vi.spyOn(statementApi, "categorizeManualTransaction");
    render(<ManualExpenseEntry />);

    await user.click(screen.getByRole("button", { name: "Add expense" }));

    expect(screen.getByText("Date, description, and amount are all required.")).toBeInTheDocument();
    expect(categorize).not.toHaveBeenCalled();
  });

  it("always sends the amount as a negative (expense), even if typed positive", async () => {
    const user = userEvent.setup();
    const categorize = vi.spyOn(statementApi, "categorizeManualTransaction").mockResolvedValue(categorizedTxn());
    vi.spyOn(statementApi, "saveStatement").mockResolvedValue({
      id: "st1",
      source_account: "Cash",
      period_label: "2026-08",
      created_at: "2026-08-05",
    });
    render(<ManualExpenseEntry />);

    await fillRequiredFields(user);
    await user.click(screen.getByRole("button", { name: "Add expense" }));

    await waitFor(() => expect(categorize).toHaveBeenCalled());
    expect(categorize).toHaveBeenCalledWith("2026-08-05", "Vegetable market", -500, "Cash", undefined, 0);
  });

  it("creates a new saved statement (POST) when this account/month has nothing saved yet", async () => {
    const user = userEvent.setup();
    vi.spyOn(statementApi, "categorizeManualTransaction").mockResolvedValue(categorizedTxn());
    const save = vi.spyOn(statementApi, "saveStatement").mockResolvedValue({
      id: "st1",
      source_account: "Cash",
      period_label: "2026-08",
      created_at: "2026-08-05",
    });
    const update = vi.spyOn(statementApi, "updateStatement");
    render(<ManualExpenseEntry />);

    await fillRequiredFields(user);
    await user.click(screen.getByRole("button", { name: "Add expense" }));

    await waitFor(() => expect(save).toHaveBeenCalled());
    expect(update).not.toHaveBeenCalled();
    expect(useTransactionStore.getState().entries).toHaveLength(1);
    expect(screen.getByRole("button", { name: "Added" })).toBeInTheDocument();
  });

  it("appends to an existing statement (PUT) when this account/month already has one saved, computing the right dedup occurrence", async () => {
    const user = userEvent.setup();
    const existing: StatementEntry = {
      id: "st1",
      sourceAccount: "Cash",
      periodLabel: "2026-08",
      createdAt: "2026-08-01",
      transactions: [categorizedTxn({ transaction_id: "existing-1" })], // same date/desc/amount/account already present once
    };
    useTransactionStore.getState().setEntries([existing]);
    const categorize = vi
      .spyOn(statementApi, "categorizeManualTransaction")
      .mockResolvedValue(categorizedTxn({ transaction_id: "new-2" }));
    const update = vi.spyOn(statementApi, "updateStatement").mockResolvedValue({
      id: "st1",
      source_account: "Cash",
      period_label: "2026-08",
      created_at: "2026-08-01",
    });
    const save = vi.spyOn(statementApi, "saveStatement");
    render(<ManualExpenseEntry />);

    await fillRequiredFields(user);
    await user.click(screen.getByRole("button", { name: "Add expense" }));

    await waitFor(() => expect(update).toHaveBeenCalled());
    expect(save).not.toHaveBeenCalled();
    // One identical row already exists -> this is occurrence #1, not #0.
    expect(categorize).toHaveBeenCalledWith("2026-08-05", "Vegetable market", -500, "Cash", undefined, 1);
    expect(useTransactionStore.getState().entries[0].transactions).toHaveLength(2);
  });

  it("passes the selected category, or undefined for 'Auto-categorize'", async () => {
    const user = userEvent.setup();
    const categorize = vi.spyOn(statementApi, "categorizeManualTransaction").mockResolvedValue(categorizedTxn());
    vi.spyOn(statementApi, "saveStatement").mockResolvedValue({
      id: "st1",
      source_account: "Cash",
      period_label: "2026-08",
      created_at: "2026-08-05",
    });
    render(<ManualExpenseEntry />);

    await fillRequiredFields(user);
    await user.selectOptions(screen.getByLabelText("Category"), "Shopping");
    await user.click(screen.getByRole("button", { name: "Add expense" }));

    await waitFor(() => expect(categorize).toHaveBeenCalled());
    expect(categorize).toHaveBeenCalledWith("2026-08-05", "Vegetable market", -500, "Cash", "Shopping", 0);
  });

  it("shows an error and does not reset the form when the save fails", async () => {
    const user = userEvent.setup();
    vi.spyOn(statementApi, "categorizeManualTransaction").mockRejectedValue(new Error("network down"));
    render(<ManualExpenseEntry />);

    await fillRequiredFields(user);
    await user.click(screen.getByRole("button", { name: "Add expense" }));

    await waitFor(() => expect(screen.getByText("network down")).toBeInTheDocument());
    expect(screen.getByLabelText("Description")).toHaveValue("Vegetable market");
    expect(useTransactionStore.getState().entries).toEqual([]);
  });
});
