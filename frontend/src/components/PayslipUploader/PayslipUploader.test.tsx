import { describe, expect, it, vi } from "vitest";
import { act, render, screen } from "@testing-library/react";
import { PayslipUploader } from "./PayslipUploader";

// PDFParser (real PDF extraction) and ManualEntryForm (its own large form)
// are each out of scope here -- this component's own job is just wiring
// extraction results from one into the other, which is what's under test.
let capturedOnExtracted: ((fields: Record<string, unknown>) => void) | null = null;
vi.mock("./PDFParser", () => ({
  PDFParser: ({ onExtracted }: { onExtracted: (fields: Record<string, unknown>) => void }) => {
    capturedOnExtracted = onExtracted;
    return <div data-testid="pdf-parser" />;
  },
}));
vi.mock("./ManualEntryForm", () => ({
  ManualEntryForm: ({
    initialValues,
    initialIsMetro,
  }: {
    initialValues?: Record<string, string>;
    initialIsMetro?: boolean;
  }) => (
    <div data-testid="manual-entry-form">
      {JSON.stringify({ initialValues, initialIsMetro })}
    </div>
  ),
}));

describe("PayslipUploader", () => {
  it("starts with no prefill", () => {
    render(<PayslipUploader />);
    expect(screen.getByTestId("manual-entry-form").textContent).toBe(
      JSON.stringify({ initialValues: undefined, initialIsMetro: undefined })
    );
  });

  it("passes extracted fields through to ManualEntryForm as string values, dropping isMetro/null/undefined from the values map", () => {
    render(<PayslipUploader />);
    act(() => capturedOnExtracted!({ basic: 50_000, hra: 20_000, isMetro: false, bonus: null }));

    const payload = JSON.parse(screen.getByTestId("manual-entry-form").textContent!);
    expect(payload.initialValues).toEqual({ basic: "50000", hra: "20000" });
    expect(payload.initialIsMetro).toBe(false);
  });

  it("defaults isMetro to true when the extraction didn't return a boolean for it", () => {
    render(<PayslipUploader />);
    act(() => capturedOnExtracted!({ basic: 50_000 }));

    const payload = JSON.parse(screen.getByTestId("manual-entry-form").textContent!);
    expect(payload.initialIsMetro).toBe(true);
  });
});
