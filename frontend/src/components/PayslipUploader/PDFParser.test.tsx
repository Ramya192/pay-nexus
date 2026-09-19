import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { PDFParser } from "./PDFParser";
import * as payslipApi from "../../api/payslip";
import * as pdfText from "../../utils/pdfText";

vi.mock("../../utils/pdfText", () => ({
  extractPdfText: vi.fn(),
}));

function pdfFile() {
  return new File(["%PDF-1.4 fake content"], "payslip.pdf", { type: "application/pdf" });
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("PDFParser", () => {
  it("extracts text, parses it, and hands the fields to onExtracted", async () => {
    const user = userEvent.setup();
    vi.mocked(pdfText.extractPdfText).mockResolvedValue("Basic: 50000");
    vi.spyOn(payslipApi, "parsePayslipText").mockResolvedValue({ basic: 50_000 });
    const onExtracted = vi.fn();
    render(<PDFParser onExtracted={onExtracted} />);

    const input = screen.getByLabelText(/Upload payslip PDF/) as HTMLInputElement;
    await user.upload(input, pdfFile());

    await waitFor(() => expect(onExtracted).toHaveBeenCalledWith({ basic: 50_000 }));
    // Cleared so re-selecting the very same file still re-fires onChange.
    expect(input.value).toBe("");
  });

  it("shows a specific message for a PDF with no extractable text (likely scanned), without ever calling parsePayslipText", async () => {
    const user = userEvent.setup();
    vi.mocked(pdfText.extractPdfText).mockResolvedValue("   ");
    const parse = vi.spyOn(payslipApi, "parsePayslipText");
    render(<PDFParser onExtracted={vi.fn()} />);

    await user.upload(screen.getByLabelText(/Upload payslip PDF/), pdfFile());

    await waitFor(() =>
      expect(screen.getByText(/Couldn't find any text in that PDF/)).toBeInTheDocument()
    );
    expect(parse).not.toHaveBeenCalled();
  });

  it("shows the underlying error message when text extraction itself fails", async () => {
    const user = userEvent.setup();
    vi.mocked(pdfText.extractPdfText).mockRejectedValue(new Error("Corrupt PDF stream"));
    render(<PDFParser onExtracted={vi.fn()} />);

    await user.upload(screen.getByLabelText(/Upload payslip PDF/), pdfFile());

    await waitFor(() => expect(screen.getByText("Corrupt PDF stream")).toBeInTheDocument());
  });

  it("does nothing when the file picker is dismissed with no file chosen", async () => {
    const extract = vi.mocked(pdfText.extractPdfText);
    render(<PDFParser onExtracted={vi.fn()} />);
    const input = screen.getByLabelText(/Upload payslip PDF/) as HTMLInputElement;

    // Simulate the change event firing with an empty file list (cancel).
    Object.defineProperty(input, "files", { value: [], configurable: true });
    input.dispatchEvent(new Event("change", { bubbles: true }));

    expect(extract).not.toHaveBeenCalled();
  });
});
