import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { PayslipHistoryUpload } from "./PayslipHistoryUpload";
import { useAuthStore } from "../../store/authStore";
import { usePayslipHistoryStore } from "../../store/payslipHistoryStore";
import * as payslipApi from "../../api/payslip";
import * as pdfText from "../../utils/pdfText";
import * as encryption from "../../crypto/clientEncryption";

vi.mock("../../crypto/clientEncryption", () => ({
  encryptJSON: vi.fn(),
}));
vi.mock("../../utils/pdfText", () => ({
  extractPdfText: vi.fn(),
}));

function pdfFile(name: string) {
  return new File(["%PDF fake"], name, { type: "application/pdf" });
}

beforeEach(() => {
  useAuthStore.getState().setAuth("tok", "salt==", "user@example.com", {} as CryptoKey);
  usePayslipHistoryStore.getState().clear();
  vi.mocked(encryption.encryptJSON).mockResolvedValue({ ciphertextB64: "ct==", ivB64: "iv==" });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("PayslipHistoryUpload", () => {
  it("does nothing without an encryption key (not logged in / key not derived yet)", async () => {
    useAuthStore.getState().logout();
    const extract = vi.mocked(pdfText.extractPdfText);
    const user = userEvent.setup();
    render(<PayslipHistoryUpload />);

    await user.upload(screen.getByLabelText(/Upload past payslips/), pdfFile("jan.pdf"));

    expect(extract).not.toHaveBeenCalled();
  });

  it("processes each file, saving successful ones to history with the extracted month", async () => {
    const user = userEvent.setup();
    vi.mocked(pdfText.extractPdfText).mockResolvedValue("some payslip text");
    vi.spyOn(payslipApi, "parsePayslipText").mockResolvedValue({ month: "2026-01", basic: 50_000 });
    vi.spyOn(payslipApi, "savePayslip").mockResolvedValue({
      id: "s1",
      month: "2026-01",
      created_at: "2026-01-01",
    });
    render(<PayslipHistoryUpload />);

    await user.upload(screen.getByLabelText(/Upload past payslips/), pdfFile("jan.pdf"));

    await waitFor(() => expect(screen.getByText("saved (2026-01)")).toBeInTheDocument());
    expect(usePayslipHistoryStore.getState().entries).toEqual([
      { id: "s1", createdAt: "2026-01-01", data: { month: "2026-01", basic: 50_000 } },
    ]);
  });

  it("marks a file duplicate (not a red error) instead of creating a second row", async () => {
    const user = userEvent.setup();
    vi.mocked(pdfText.extractPdfText).mockResolvedValue("some payslip text");
    vi.spyOn(payslipApi, "parsePayslipText").mockResolvedValue({ month: "2026-01" });
    vi.spyOn(payslipApi, "savePayslip").mockRejectedValue({ response: { status: 409 } });
    render(<PayslipHistoryUpload />);

    await user.upload(screen.getByLabelText(/Upload past payslips/), pdfFile("jan.pdf"));

    await waitFor(() => expect(screen.getByText("already saved — skipped")).toBeInTheDocument());
    expect(usePayslipHistoryStore.getState().entries).toEqual([]);
  });

  it("flags a file with no extractable text without ever calling parsePayslipText", async () => {
    const user = userEvent.setup();
    vi.mocked(pdfText.extractPdfText).mockResolvedValue("   ");
    const parse = vi.spyOn(payslipApi, "parsePayslipText");
    render(<PayslipHistoryUpload />);

    await user.upload(screen.getByLabelText(/Upload past payslips/), pdfFile("scan.pdf"));

    await waitFor(() => expect(screen.getByText("No extractable text (scanned image?)")).toBeInTheDocument());
    expect(parse).not.toHaveBeenCalled();
  });

  it("flags a file where no month could be determined, without saving it", async () => {
    const user = userEvent.setup();
    vi.mocked(pdfText.extractPdfText).mockResolvedValue("text with no clear month");
    vi.spyOn(payslipApi, "parsePayslipText").mockResolvedValue({ basic: 50_000 }); // no `month`
    const save = vi.spyOn(payslipApi, "savePayslip");
    render(<PayslipHistoryUpload />);

    await user.upload(screen.getByLabelText(/Upload past payslips/), pdfFile("unclear.pdf"));

    await waitFor(() =>
      expect(screen.getByText("Couldn't determine the pay period — skipped")).toBeInTheDocument()
    );
    expect(save).not.toHaveBeenCalled();
  });

  it("processes multiple files independently, one success and one duplicate in the same batch", async () => {
    const user = userEvent.setup();
    vi.mocked(pdfText.extractPdfText).mockResolvedValue("text");
    vi.spyOn(payslipApi, "parsePayslipText")
      .mockResolvedValueOnce({ month: "2026-01" })
      .mockResolvedValueOnce({ month: "2026-02" });
    vi.spyOn(payslipApi, "savePayslip")
      .mockResolvedValueOnce({ id: "s1", month: "2026-01", created_at: "2026-01-01" })
      .mockRejectedValueOnce({ response: { status: 409 } });
    render(<PayslipHistoryUpload />);

    const input = screen.getByLabelText(/Upload past payslips/);
    await user.upload(input, [pdfFile("jan.pdf"), pdfFile("feb.pdf")]);

    await waitFor(() => expect(screen.getByText("saved (2026-01)")).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText("already saved — skipped")).toBeInTheDocument());
    expect(usePayslipHistoryStore.getState().entries).toHaveLength(1);
  });
});
