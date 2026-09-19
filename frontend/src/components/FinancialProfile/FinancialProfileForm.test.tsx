import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { FinancialProfileForm } from "./FinancialProfileForm";
import { useAuthStore } from "../../store/authStore";
import { useFinancialProfileStore } from "../../store/financialProfileStore";
import * as financialProfileApi from "../../api/financialProfile";
import * as encryption from "../../crypto/clientEncryption";

vi.mock("../../crypto/clientEncryption", () => ({
  encryptJSON: vi.fn(),
}));

beforeEach(() => {
  useAuthStore.getState().logout();
  useFinancialProfileStore.getState().clear();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("FinancialProfileForm", () => {
  it("hydrates from an already-loaded profile, including the senior-citizen checkbox", async () => {
    useFinancialProfileStore.getState().setProfile({
      elssMutualFunds: 50_000,
      healthInsuranceForSeniorCitizen: true,
    });
    render(<FinancialProfileForm />);

    await waitFor(() => expect(screen.getByLabelText(/ELSS mutual funds/)).toHaveValue(50_000));
    expect(screen.getByRole("checkbox", { name: /senior citizen/ })).toBeChecked();
  });

  it("hydrates asynchronously if the profile lands after mount (e.g. login decrypt finishing later)", async () => {
    render(<FinancialProfileForm />);
    expect(screen.getByLabelText(/ELSS mutual funds/)).toHaveValue(null);

    act(() => useFinancialProfileStore.getState().setProfile({ elssMutualFunds: 75_000 }));

    await waitFor(() => expect(screen.getByLabelText(/ELSS mutual funds/)).toHaveValue(75_000));
  });

  describe("save", () => {
    beforeEach(() => {
      useAuthStore.getState().setAuth("tok", "salt==", "user@example.com", {} as CryptoKey);
    });

    it("builds only the filled-in fields plus the senior-citizen flag, and updates the store only after the save succeeds", async () => {
      const user = userEvent.setup();
      vi.mocked(encryption.encryptJSON).mockResolvedValue({ ciphertextB64: "ct==", ivB64: "iv==" });
      vi.spyOn(financialProfileApi, "saveFinancialProfile").mockResolvedValue();
      render(<FinancialProfileForm />);

      await user.type(screen.getByLabelText(/ELSS mutual funds/), "50000");
      await user.click(screen.getByRole("checkbox", { name: /senior citizen/ }));
      await user.click(screen.getByRole("button", { name: "Save financial profile" }));

      await waitFor(() => expect(screen.getByRole("button", { name: "Saved" })).toBeInTheDocument());
      expect(useFinancialProfileStore.getState().profile).toEqual({
        elssMutualFunds: 50_000,
        healthInsuranceForSeniorCitizen: true,
      });
    });

    it("regression: does NOT update the store when the save fails -- the store previously updated optimistically before the save, leaving stale unsaved data behind on failure", async () => {
      const user = userEvent.setup();
      vi.mocked(encryption.encryptJSON).mockResolvedValue({ ciphertextB64: "ct==", ivB64: "iv==" });
      vi.spyOn(financialProfileApi, "saveFinancialProfile").mockRejectedValue(new Error("network down"));
      render(<FinancialProfileForm />);

      await user.type(screen.getByLabelText(/ELSS mutual funds/), "50000");
      await user.click(screen.getByRole("button", { name: "Save financial profile" }));

      await waitFor(() => expect(screen.getByText("network down")).toBeInTheDocument());
      expect(useFinancialProfileStore.getState().profile).toBeNull();
    });
  });
});
