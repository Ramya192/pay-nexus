import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { StatementList } from "./StatementList";
import { useTransactionStore, type StatementEntry } from "../../store/transactionStore";
import { useAuthStore } from "../../store/authStore";
import * as statementApi from "../../api/statement";
import * as encryption from "../../crypto/clientEncryption";

vi.mock("../../crypto/clientEncryption", () => ({
  encryptJSON: vi.fn(),
}));

const augEntry: StatementEntry = {
  id: "s1",
  sourceAccount: "HDFC",
  periodLabel: "2026-08",
  createdAt: "2026-08-31",
  transactions: [
    {
      transaction_id: "t1",
      date: "2026-08-05",
      description: "Rent",
      amount: -20_000,
      source_account: "HDFC",
      category: "Rent",
      category_source: "rule",
    },
    {
      transaction_id: "t2",
      date: "2026-08-01",
      description: "Salary",
      amount: 80_000,
      source_account: "HDFC",
      category: "Income",
      category_source: "rule",
    },
  ],
};

beforeEach(() => {
  useTransactionStore.getState().clear();
  useAuthStore.getState().logout();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("StatementList", () => {
  it("shows an empty state with no saved statements", () => {
    render(<StatementList />);
    expect(screen.getByText("No bank statements saved yet.")).toBeInTheDocument();
  });

  it("lists a saved statement's account, period, and transaction count", () => {
    useTransactionStore.getState().setEntries([augEntry]);
    render(<StatementList />);
    expect(screen.getByText(/HDFC — 2026-08/)).toBeInTheDocument();
    expect(screen.getByText("(2 transactions)")).toBeInTheDocument();
  });

  it("expanding a row shows its transactions sorted by date, with signed amounts formatted as whole rupees", async () => {
    const user = userEvent.setup();
    useTransactionStore.getState().setEntries([augEntry]);
    render(<StatementList />);

    await user.click(screen.getByTitle("View transactions"));

    const rows = screen.getAllByText(/·/).map((el) => el.textContent);
    expect(rows).toEqual(["2026-08-01 · Salary", "2026-08-05 · Rent"]); // date order, earliest first

    expect(screen.getByText("+₹80,000")).toBeInTheDocument(); // income: "+"
    expect(screen.getByText("-₹20,000")).toBeInTheDocument(); // expense: "-"
  });

  describe("delete", () => {
    it("does nothing when the confirm dialog is cancelled", async () => {
      const user = userEvent.setup();
      vi.spyOn(window, "confirm").mockReturnValue(false);
      const del = vi.spyOn(statementApi, "deleteStatement");
      useTransactionStore.getState().setEntries([augEntry]);
      render(<StatementList />);

      await user.click(screen.getByTitle("Delete this saved statement"));

      expect(del).not.toHaveBeenCalled();
      expect(useTransactionStore.getState().entries).toHaveLength(1);
    });

    it("removes the entry from the store once confirmed and the API call succeeds", async () => {
      const user = userEvent.setup();
      vi.spyOn(window, "confirm").mockReturnValue(true);
      vi.spyOn(statementApi, "deleteStatement").mockResolvedValue();
      useTransactionStore.getState().setEntries([augEntry]);
      render(<StatementList />);

      await user.click(screen.getByTitle("Delete this saved statement"));

      await waitFor(() => expect(useTransactionStore.getState().entries).toHaveLength(0));
    });

    it("shows an error and keeps the entry when the API call fails", async () => {
      const user = userEvent.setup();
      vi.spyOn(window, "confirm").mockReturnValue(true);
      vi.spyOn(statementApi, "deleteStatement").mockRejectedValue(new Error("network"));
      useTransactionStore.getState().setEntries([augEntry]);
      render(<StatementList />);

      await user.click(screen.getByTitle("Delete this saved statement"));

      await waitFor(() =>
        expect(screen.getByText("Couldn't delete that statement — try again.")).toBeInTheDocument()
      );
      expect(useTransactionStore.getState().entries).toHaveLength(1);
    });
  });

  describe("category correction", () => {
    beforeEach(() => {
      useAuthStore.getState().setAuth("tok", "salt==", "user@example.com", {} as CryptoKey);
    });

    it("re-encrypts and saves the corrected list, marking the row user_corrected", async () => {
      const user = userEvent.setup();
      vi.mocked(encryption.encryptJSON).mockResolvedValue({ ciphertextB64: "ct==", ivB64: "iv==" });
      const update = vi.spyOn(statementApi, "updateStatement").mockResolvedValue({
        id: "s1",
        source_account: "HDFC",
        period_label: "2026-08",
        created_at: "2026-08-31",
      });
      useTransactionStore.getState().setEntries([augEntry]);
      render(<StatementList />);
      await user.click(screen.getByTitle("View transactions"));

      const selects = screen.getAllByRole("combobox");
      await user.selectOptions(selects[0], "Groceries"); // first row is Salary (2026-08-01, sorted first)

      await waitFor(() => expect(update).toHaveBeenCalled());
      const savedTransactions = vi.mocked(encryption.encryptJSON).mock.calls[0][1] as Array<{
        transaction_id: string;
        category: string;
        category_source: string;
      }>;
      const corrected = savedTransactions.find((t) => t.transaction_id === "t2")!;
      expect(corrected.category).toBe("Groceries");
      expect(corrected.category_source).toBe("user_corrected");
    });

    it("shows an error and leaves the store unchanged when saving the correction fails", async () => {
      const user = userEvent.setup();
      vi.mocked(encryption.encryptJSON).mockResolvedValue({ ciphertextB64: "ct==", ivB64: "iv==" });
      vi.spyOn(statementApi, "updateStatement").mockRejectedValue(new Error("network"));
      useTransactionStore.getState().setEntries([augEntry]);
      render(<StatementList />);
      await user.click(screen.getByTitle("View transactions"));

      await user.selectOptions(screen.getAllByRole("combobox")[0], "Groceries");

      await waitFor(() =>
        expect(screen.getByText("Couldn't save that correction — try again.")).toBeInTheDocument()
      );
      expect(
        useTransactionStore.getState().entries[0].transactions.find((t) => t.transaction_id === "t2")!.category
      ).toBe("Income"); // unchanged
    });
  });
});
