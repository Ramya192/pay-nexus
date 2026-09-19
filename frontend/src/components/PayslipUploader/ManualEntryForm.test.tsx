import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ManualEntryForm } from "./ManualEntryForm";
import { useAuthStore } from "../../store/authStore";
import { usePayslipStore } from "../../store/payslipStore";
import { usePayslipHistoryStore } from "../../store/payslipHistoryStore";
import * as payslipApi from "../../api/payslip";
import * as encryption from "../../crypto/clientEncryption";

vi.mock("../../crypto/clientEncryption", () => ({
  encryptJSON: vi.fn(),
}));

beforeEach(() => {
  useAuthStore.getState().logout();
  usePayslipStore.getState().clear();
  usePayslipHistoryStore.getState().clear();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("ManualEntryForm", () => {
  it("prefills from initialValues/initialIsMetro (e.g. a PDF extraction)", () => {
    render(<ManualEntryForm initialValues={{ month: "2026-08", basic: "50000" }} initialIsMetro={false} />);
    expect(screen.getByLabelText("Month")).toHaveValue("2026-08");
    expect(screen.getByLabelText("Basic (₹)")).toHaveValue(50_000);
    expect(screen.getByRole("checkbox", { name: /Metro city/ })).not.toBeChecked();
  });

  describe("Use this payslip", () => {
    it("sets the session payslip (isMetro + only the filled-in fields, numbers coerced) and confirms with a checkmark", async () => {
      const user = userEvent.setup();
      const onSaved = vi.fn();
      render(<ManualEntryForm onSaved={onSaved} initialValues={{ month: "2026-08", basic: "50000" }} />);

      await user.click(screen.getByRole("button", { name: "Use this payslip" }));

      expect(usePayslipStore.getState().payslipData).toEqual({ isMetro: true, month: "2026-08", basic: 50_000 });
      expect(onSaved).toHaveBeenCalled();
      expect(screen.getByRole("button", { name: "Using this payslip" })).toBeInTheDocument();
    });

    it("editing a field after using it resets the confirmation back to the plain label", async () => {
      const user = userEvent.setup();
      render(<ManualEntryForm initialValues={{ month: "2026-08" }} />);
      await user.click(screen.getByRole("button", { name: "Use this payslip" }));
      expect(screen.getByRole("button", { name: "Using this payslip" })).toBeInTheDocument();

      await user.type(screen.getByLabelText("Basic (₹)"), "1");

      expect(screen.getByRole("button", { name: "Use this payslip" })).toBeInTheDocument();
    });
  });

  describe("Save to history", () => {
    beforeEach(() => {
      useAuthStore.getState().setAuth("tok", "salt==", "user@example.com", {} as CryptoKey);
    });

    it("requires a month before saving, without calling the API", async () => {
      const user = userEvent.setup();
      const save = vi.spyOn(payslipApi, "savePayslip");
      render(<ManualEntryForm />);

      await user.click(screen.getByRole("button", { name: "Save to history" }));

      expect(screen.getByText("Enter a month before saving to history.")).toBeInTheDocument();
      expect(save).not.toHaveBeenCalled();
    });

    it("encrypts and saves, then adds the entry to payslip history", async () => {
      const user = userEvent.setup();
      vi.mocked(encryption.encryptJSON).mockResolvedValue({ ciphertextB64: "ct==", ivB64: "iv==" });
      vi.spyOn(payslipApi, "savePayslip").mockResolvedValue({
        id: "snap1",
        month: "2026-08",
        created_at: "2026-08-01",
      });
      render(<ManualEntryForm initialValues={{ month: "2026-08", basic: "50000" }} />);

      await user.click(screen.getByRole("button", { name: "Save to history" }));

      await waitFor(() => expect(screen.getByText("Saved to history")).toBeInTheDocument());
      expect(usePayslipHistoryStore.getState().entries).toEqual([
        { id: "snap1", createdAt: "2026-08-01", data: { isMetro: true, month: "2026-08", basic: 50_000 } },
      ]);
    });

    it("shows an 'already saved' hint (not a red error) on a duplicate-month conflict", async () => {
      const user = userEvent.setup();
      vi.mocked(encryption.encryptJSON).mockResolvedValue({ ciphertextB64: "ct==", ivB64: "iv==" });
      const conflict = { response: { status: 409 } };
      vi.spyOn(payslipApi, "savePayslip").mockRejectedValue(conflict);
      render(<ManualEntryForm initialValues={{ month: "2026-08" }} />);

      await user.click(screen.getByRole("button", { name: "Save to history" }));

      await waitFor(() => expect(screen.getByText("Already saved")).toBeInTheDocument());
      expect(
        screen.getByText(/A payslip for this month is already saved/)
      ).toBeInTheDocument();
      expect(usePayslipHistoryStore.getState().entries).toEqual([]);
    });

    it("shows a real error message for a non-duplicate failure", async () => {
      const user = userEvent.setup();
      vi.mocked(encryption.encryptJSON).mockResolvedValue({ ciphertextB64: "ct==", ivB64: "iv==" });
      vi.spyOn(payslipApi, "savePayslip").mockRejectedValue(new Error("network down"));
      render(<ManualEntryForm initialValues={{ month: "2026-08" }} />);

      await user.click(screen.getByRole("button", { name: "Save to history" }));

      await waitFor(() => expect(screen.getByText("network down")).toBeInTheDocument());
    });
  });
});
