import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { BudgetForm } from "./BudgetForm";
import { useBudgetStore } from "../../store/budgetStore";
import { useAuthStore } from "../../store/authStore";
import { usePayslipHistoryStore } from "../../store/payslipHistoryStore";
import { usePayslipStore } from "../../store/payslipStore";
import * as budgetApi from "../../api/budget";
import * as encryption from "../../crypto/clientEncryption";

vi.mock("../../crypto/clientEncryption", () => ({
  encryptJSON: vi.fn(),
}));

beforeEach(() => {
  useBudgetStore.getState().clear();
  useAuthStore.getState().logout();
  usePayslipStore.getState().clear();
  usePayslipHistoryStore.getState().clear();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("BudgetForm", () => {
  it("prefills from the already-saved budget when one exists, without calling the suggestion endpoint", async () => {
    const suggested = vi.spyOn(budgetApi, "fetchSuggestedBudget");
    useBudgetStore.getState().setBudget({ Rent: 20_000, Groceries: 8_000 });
    render(<BudgetForm />);

    await waitFor(() => expect(screen.getByLabelText(/^Rent/)).toHaveValue(20_000));
    expect(screen.getByLabelText(/^Groceries/)).toHaveValue(8_000);
    expect(suggested).not.toHaveBeenCalled();
  });

  it("prefills from the suggested budget when nothing is saved yet", async () => {
    vi.spyOn(budgetApi, "fetchSuggestedBudget").mockResolvedValue({
      salary_bracket: "50k-75k",
      budgets: { Rent: 15_000, Groceries: 6_000 },
    });
    render(<BudgetForm />);

    await waitFor(() => expect(screen.getByLabelText(/^Rent/)).toHaveValue(15_000));
  });

  it("passes a rough monthly income derived from the active payslip's gross fields", async () => {
    const suggested = vi
      .spyOn(budgetApi, "fetchSuggestedBudget")
      .mockResolvedValue({ salary_bracket: "50k-75k", budgets: {} });
    usePayslipStore.getState().setPayslipData({ basic: 40_000, hra: 16_000, specialAllowance: 4_000 });
    render(<BudgetForm />);

    await waitFor(() => expect(suggested).toHaveBeenCalledWith(60_000));
  });

  it("with no active payslip, derives the income from the newest saved payslip", async () => {
    const suggested = vi
      .spyOn(budgetApi, "fetchSuggestedBudget")
      .mockResolvedValue({ salary_bracket: "Below 30k", budgets: {} });
    usePayslipHistoryStore.getState().setEntries([
      { id: "1", createdAt: "x", data: { month: "2026-05", basic: 90_000 } },
      { id: "2", createdAt: "x", data: { month: "2026-06", basic: 15_000, hra: 6_000, specialAllowance: 4_000 } },
    ]);
    render(<BudgetForm />);

    await waitFor(() => expect(suggested).toHaveBeenCalledWith(25_000));
  });

  it("re-fetches the suggestion when payslip history hydrates after mount", async () => {
    const suggested = vi
      .spyOn(budgetApi, "fetchSuggestedBudget")
      .mockResolvedValue({ salary_bracket: "Below 30k", budgets: {} });
    render(<BudgetForm />);
    await waitFor(() => expect(suggested).toHaveBeenCalledWith(undefined));

    act(() => {
      usePayslipHistoryStore.getState().setEntries([
        { id: "1", createdAt: "x", data: { month: "2026-06", basic: 15_000, hra: 6_000, specialAllowance: 4_000 } },
      ]);
    });
    await waitFor(() => expect(suggested).toHaveBeenLastCalledWith(25_000));
  });

  it("does not overwrite values the user already typed when income arrives late", async () => {
    const user = userEvent.setup();
    vi.spyOn(budgetApi, "fetchSuggestedBudget").mockResolvedValue({
      salary_bracket: "Below 30k",
      budgets: { Rent: 7_200 },
    });
    render(<BudgetForm />);
    await waitFor(() => expect(screen.getByLabelText(/^Rent/)).toHaveValue(7_200));
    await user.clear(screen.getByLabelText(/^Rent/));
    await user.type(screen.getByLabelText(/^Rent/), "9000");

    act(() => {
      usePayslipHistoryStore.getState().setEntries([{ id: "1", createdAt: "x", data: { month: "2026-06", basic: 90_000 } }]);
    });
    await new Promise((r) => setTimeout(r, 50));
    expect(screen.getByLabelText(/^Rent/)).toHaveValue(9_000);
  });

  it("falls back to a blank, still-usable form if the suggestion fetch fails", async () => {
    vi.spyOn(budgetApi, "fetchSuggestedBudget").mockRejectedValue(new Error("network"));
    render(<BudgetForm />);
    await waitFor(() => expect(screen.getByRole("button", { name: "Save budget" })).toBeInTheDocument());
    expect(screen.getByLabelText(/^Rent/)).toHaveValue(null);
  });

  it("saves only the non-blank category values and shows the saved state", async () => {
    const user = userEvent.setup();
    useAuthStore.getState().setAuth("tok", "salt==", "user@example.com", {} as CryptoKey);
    vi.mocked(encryption.encryptJSON).mockResolvedValue({ ciphertextB64: "ct==", ivB64: "iv==" });
    const save = vi.spyOn(budgetApi, "saveBudget").mockResolvedValue();
    useBudgetStore.getState().setBudget({ Rent: 20_000 });
    render(<BudgetForm />);

    await waitFor(() => expect(screen.getByLabelText(/^Rent/)).toHaveValue(20_000));
    await user.click(screen.getByRole("button", { name: "Save budget" }));

    await waitFor(() => expect(screen.getByRole("button", { name: "Saved" })).toBeInTheDocument());
    expect(save).toHaveBeenCalled();
    const savedBudget = vi.mocked(encryption.encryptJSON).mock.calls[0][1];
    expect(savedBudget).toEqual({ Rent: 20_000 });
    expect(useBudgetStore.getState().budget).toEqual({ Rent: 20_000 });
  });

  it("shows an error and stays editable when the save fails", async () => {
    const user = userEvent.setup();
    useAuthStore.getState().setAuth("tok", "salt==", "user@example.com", {} as CryptoKey);
    vi.mocked(encryption.encryptJSON).mockResolvedValue({ ciphertextB64: "ct==", ivB64: "iv==" });
    vi.spyOn(budgetApi, "saveBudget").mockRejectedValue(new Error("network"));
    useBudgetStore.getState().setBudget({ Rent: 20_000 });
    render(<BudgetForm />);

    await waitFor(() => expect(screen.getByLabelText(/^Rent/)).toHaveValue(20_000));
    await user.click(screen.getByRole("button", { name: "Save budget" }));

    await waitFor(() =>
      expect(screen.getByText("Couldn't save your budget — try again.")).toBeInTheDocument()
    );
    // Unchanged from what was pre-seeded above -- a failed save never touches the store.
    expect(useBudgetStore.getState().budget).toEqual({ Rent: 20_000 });
  });
});
