import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AuthScreen } from "./AuthScreen";
import { useAuthStore } from "../../store/authStore";
import { useSessionHistoryStore } from "../../store/sessionHistoryStore";
import { useFinancialProfileStore } from "../../store/financialProfileStore";
import { usePayslipHistoryStore } from "../../store/payslipHistoryStore";
import { useTransactionStore } from "../../store/transactionStore";
import { useGoalStore } from "../../store/goalStore";
import { useBudgetStore } from "../../store/budgetStore";
import * as authApi from "../../api/auth";
import * as budgetApi from "../../api/budget";
import * as financialProfileApi from "../../api/financialProfile";
import * as goalsApi from "../../api/goals";
import * as payslipApi from "../../api/payslip";
import * as statementApi from "../../api/statement";
import * as encryption from "../../crypto/clientEncryption";

vi.mock("../../crypto/clientEncryption", () => ({
  deriveEncryptionKey: vi.fn(),
  decryptJSON: vi.fn(),
}));

const fakeKey = {} as CryptoKey;

function resetAllStores() {
  useAuthStore.getState().logout();
  useSessionHistoryStore.getState().clear();
  useFinancialProfileStore.getState().clear();
  usePayslipHistoryStore.getState().clear();
  useTransactionStore.getState().clear();
  useGoalStore.getState().clear();
  useBudgetStore.getState().clear();
}

beforeEach(() => {
  resetAllStores();
  vi.mocked(encryption.deriveEncryptionKey).mockResolvedValue(fakeKey);
  // Sensible empty-account defaults -- each test only overrides what it cares about.
  vi.spyOn(payslipApi, "fetchHistory").mockResolvedValue([]);
  vi.spyOn(financialProfileApi, "fetchFinancialProfile").mockResolvedValue(null);
  vi.spyOn(payslipApi, "fetchSnapshots").mockResolvedValue([]);
  vi.spyOn(statementApi, "fetchStatements").mockResolvedValue([]);
  vi.spyOn(goalsApi, "fetchGoals").mockResolvedValue([]);
  vi.spyOn(budgetApi, "fetchBudget").mockResolvedValue(null);
});

afterEach(() => {
  vi.restoreAllMocks();
});

async function fillAndSubmit(user: ReturnType<typeof userEvent.setup>, email = "user@example.com", password = "hunter22") {
  await user.type(screen.getByLabelText("Email"), email);
  await user.type(screen.getByLabelText("Password"), password);
  await user.click(screen.getByRole("button", { name: /^(Log in|Create account)$/ }));
}

describe("AuthScreen", () => {
  it("defaults to login mode and toggles to register", async () => {
    const user = userEvent.setup();
    render(<AuthScreen />);
    expect(screen.getByRole("button", { name: "Log in" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Need an account? Register" }));

    expect(screen.getByRole("button", { name: "Create account" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Have an account? Log in" })).toBeInTheDocument();
  });

  it("logs in: calls login (not register), derives the key client-side, and authenticates the store", async () => {
    const user = userEvent.setup();
    const loginSpy = vi
      .spyOn(authApi, "login")
      .mockResolvedValue({ access_token: "tok123", token_type: "bearer", encryption_salt: "salt==" });
    const registerSpy = vi.spyOn(authApi, "register");
    render(<AuthScreen />);

    await fillAndSubmit(user, "user@example.com", "hunter22");

    await waitFor(() => expect(useAuthStore.getState().token).toBe("tok123"));
    expect(loginSpy).toHaveBeenCalledWith("user@example.com", "hunter22");
    expect(registerSpy).not.toHaveBeenCalled();
    expect(encryption.deriveEncryptionKey).toHaveBeenCalledWith("hunter22", "salt==");
    expect(useAuthStore.getState().userEmail).toBe("user@example.com");
  });

  it("registers: calls register, not login, when in register mode", async () => {
    const user = userEvent.setup();
    const registerSpy = vi
      .spyOn(authApi, "register")
      .mockResolvedValue({ access_token: "tok123", token_type: "bearer", encryption_salt: "salt==" });
    const loginSpy = vi.spyOn(authApi, "login");
    render(<AuthScreen />);
    await user.click(screen.getByRole("button", { name: "Need an account? Register" }));

    await fillAndSubmit(user);

    await waitFor(() => expect(useAuthStore.getState().token).toBe("tok123"));
    expect(registerSpy).toHaveBeenCalled();
    expect(loginSpy).not.toHaveBeenCalled();
  });

  it("shows a mode-specific error and never authenticates when the credentials are rejected", async () => {
    const user = userEvent.setup();
    vi.spyOn(authApi, "login").mockRejectedValue(new Error("401"));
    render(<AuthScreen />);

    await fillAndSubmit(user);

    await waitFor(() => expect(screen.getByText("Incorrect email or password.")).toBeInTheDocument());
    expect(useAuthStore.getState().token).toBeNull();
  });

  it("shows the register-specific error message when account creation fails", async () => {
    const user = userEvent.setup();
    vi.spyOn(authApi, "register").mockRejectedValue(new Error("email taken"));
    render(<AuthScreen />);
    await user.click(screen.getByRole("button", { name: "Need an account? Register" }));

    await fillAndSubmit(user);

    await waitFor(() => expect(screen.getByText("Could not create that account.")).toBeInTheDocument());
  });

  it("hydrates every store from decrypted server data after a successful login", async () => {
    const user = userEvent.setup();
    vi.spyOn(authApi, "login").mockResolvedValue({
      access_token: "tok",
      token_type: "bearer",
      encryption_salt: "salt==",
    });
    vi.spyOn(payslipApi, "fetchHistory").mockResolvedValue([
      { id: "h1", ciphertext_b64: "ct", iv_b64: "iv", created_at: "2026-01-01" },
    ]);
    vi.spyOn(financialProfileApi, "fetchFinancialProfile").mockResolvedValue({
      ciphertext_b64: "ct",
      iv_b64: "iv",
      updated_at: "2026-01-01",
    });
    vi.spyOn(payslipApi, "fetchSnapshots").mockResolvedValue([
      { id: "s1", month: "2026-01", ciphertext_b64: "ct", iv_b64: "iv", created_at: "2026-01-01" },
    ]);
    vi.spyOn(statementApi, "fetchStatements").mockResolvedValue([
      { id: "st1", source_account: "HDFC", period_label: "2026-01", ciphertext_b64: "ct-statement", iv_b64: "iv", created_at: "2026-01-01" },
    ]);
    vi.spyOn(goalsApi, "fetchGoals").mockResolvedValue([
      { id: "g1", ciphertext_b64: "ct", iv_b64: "iv", created_at: "2026-01-01" },
    ]);
    vi.spyOn(budgetApi, "fetchBudget").mockResolvedValue({ ciphertext_b64: "ct", iv_b64: "iv", updated_at: "2026-01-01" });

    vi.mocked(encryption.decryptJSON).mockImplementation(async (_key, blob) => {
      // A saved statement's plaintext is a transaction ARRAY (transactionStore's
      // flatten() calls .map() on it) -- every other row type here decrypts to
      // a plain object, so this needs to actually branch on which row it is.
      if ("ciphertextB64" in blob && blob.ciphertextB64 === "ct-statement") {
        return [{ transaction_id: "t1", date: "2026-01-05", amount: -100 }];
      }
      return { decrypted: true };
    });

    render(<AuthScreen />);
    await fillAndSubmit(user);

    // The six hydration steps run sequentially (each awaited in turn), not
    // in parallel -- wait for the LAST one (budget) before asserting on any
    // of the earlier ones, since by then every prior await has necessarily
    // already resolved.
    await waitFor(() => expect(useBudgetStore.getState().budget).toEqual({ decrypted: true }));
    expect(useSessionHistoryStore.getState().history).toEqual([{ decrypted: true }]);
    expect(useFinancialProfileStore.getState().profile).toEqual({ decrypted: true });
    expect(usePayslipHistoryStore.getState().entries).toEqual([
      { id: "s1", createdAt: "2026-01-01", data: { decrypted: true } },
    ]);
    expect(useTransactionStore.getState().entries).toEqual([
      {
        id: "st1",
        sourceAccount: "HDFC",
        periodLabel: "2026-01",
        createdAt: "2026-01-01",
        transactions: [{ transaction_id: "t1", date: "2026-01-05", amount: -100 }],
      },
    ]);
    expect(useGoalStore.getState().entries).toEqual([
      { id: "g1", createdAt: "2026-01-01", data: { decrypted: true } },
    ]);
    expect(useBudgetStore.getState().budget).toEqual({ decrypted: true });
  });

  it("skips one undecryptable row without dropping every other row of the same type (row-level resilience)", async () => {
    const user = userEvent.setup();
    vi.spyOn(authApi, "login").mockResolvedValue({
      access_token: "tok",
      token_type: "bearer",
      encryption_salt: "salt==",
    });
    vi.spyOn(payslipApi, "fetchSnapshots").mockResolvedValue([
      { id: "bad", month: "2026-01", ciphertext_b64: "corrupt", iv_b64: "iv", created_at: "2026-01-01" },
      { id: "good", month: "2026-02", ciphertext_b64: "ct", iv_b64: "iv", created_at: "2026-02-01" },
    ]);
    vi.mocked(encryption.decryptJSON).mockImplementation(async (_key, blob) => {
      if ((blob as { ciphertextB64: string }).ciphertextB64 === "corrupt") throw new Error("bad key");
      return { month: "2026-02" };
    });

    render(<AuthScreen />);
    await fillAndSubmit(user);

    await waitFor(() =>
      expect(usePayslipHistoryStore.getState().entries).toEqual([
        { id: "good", createdAt: "2026-02-01", data: { month: "2026-02" } },
      ])
    );
    // Login itself still succeeded despite the bad row.
    expect(useAuthStore.getState().token).toBe("tok");
  });

  it("a whole hydration category failing outright (e.g. one endpoint down) never blocks login or the other categories", async () => {
    const user = userEvent.setup();
    vi.spyOn(authApi, "login").mockResolvedValue({
      access_token: "tok",
      token_type: "bearer",
      encryption_salt: "salt==",
    });
    vi.spyOn(payslipApi, "fetchHistory").mockRejectedValue(new Error("network down"));
    vi.spyOn(goalsApi, "fetchGoals").mockResolvedValue([
      { id: "g1", ciphertext_b64: "ct", iv_b64: "iv", created_at: "2026-01-01" },
    ]);
    vi.mocked(encryption.decryptJSON).mockResolvedValue({ name: "Goa Trip" });

    render(<AuthScreen />);
    await fillAndSubmit(user);

    await waitFor(() => expect(useAuthStore.getState().token).toBe("tok"));
    expect(useSessionHistoryStore.getState().history).toEqual([]); // never populated, but didn't throw past login
    await waitFor(() => expect(useGoalStore.getState().entries).toHaveLength(1)); // unaffected by the other category's failure
  });

  it("disables the submit button and shows a loading indicator while the request is in flight", async () => {
    const user = userEvent.setup();
    let resolveLogin!: (v: { access_token: string; token_type: string; encryption_salt: string }) => void;
    vi.spyOn(authApi, "login").mockImplementation(
      () => new Promise((resolve) => { resolveLogin = resolve; })
    );
    render(<AuthScreen />);

    await user.type(screen.getByLabelText("Email"), "user@example.com");
    await user.type(screen.getByLabelText("Password"), "hunter22");
    await user.click(screen.getByRole("button", { name: "Log in" }));

    expect(screen.getByRole("button", { name: "…" })).toBeDisabled();

    resolveLogin({ access_token: "tok", token_type: "bearer", encryption_salt: "salt==" });
    await waitFor(() => expect(useAuthStore.getState().token).toBe("tok"));
  });
});
