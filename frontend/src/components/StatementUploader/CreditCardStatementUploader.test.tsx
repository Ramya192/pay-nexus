import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { CreditCardStatementUploader } from "./CreditCardStatementUploader";
import { useAuthStore } from "../../store/authStore";
import { useTransactionStore } from "../../store/transactionStore";
import * as statementApi from "../../api/statement";
import * as pdfText from "../../utils/pdfText";
import * as encryption from "../../crypto/clientEncryption";
import * as contentHash from "../../utils/contentHash";

vi.mock("../../crypto/clientEncryption", () => ({
  encryptJSON: vi.fn(),
}));
vi.mock("../../utils/contentHash", () => ({
  computeContentHash: vi.fn(),
}));
vi.mock("../../utils/pdfText", () => ({
  extractPdfText: vi.fn(),
}));

function pdfFile(name = "cc-statement.pdf") {
  return new File(["%PDF fake"], name, { type: "application/pdf" });
}

function txn(overrides: Partial<statementApi.ParsedTransaction> = {}): statementApi.ParsedTransaction {
  return {
    transaction_id: "t1",
    date: "2026-07-10",
    description: "Amazon",
    amount: -3_000,
    source_account: "HDFC Credit Card",
    category: "Shopping",
    category_source: "rule",
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

async function getToReview(
  user: ReturnType<typeof userEvent.setup>,
  transactions = [txn({ amount: -3_000 }), txn({ transaction_id: "t2", amount: -2_000 })]
) {
  vi.mocked(pdfText.extractPdfText).mockResolvedValue("statement text");
  vi.spyOn(statementApi, "parseStatementText").mockResolvedValue({
    transactions,
    skipped_row_count: 0,
    truncated_chars: 0,
  });
  await user.type(screen.getByLabelText("Card name"), "HDFC Credit Card");
  await user.upload(screen.getByLabelText(/Upload credit card statement/), pdfFile());
  await waitFor(() => expect(screen.getByLabelText("Payment due date")).toBeInTheDocument());
  await user.type(screen.getByLabelText("Payment due date"), "2026-08-05");
}

describe("CreditCardStatementUploader", () => {
  it("requires a card name before a file can be processed", async () => {
    const user = userEvent.setup();
    render(<CreditCardStatementUploader />);

    await user.upload(screen.getByLabelText(/Upload credit card statement/), pdfFile());

    expect(screen.getByText(/Name the card first/)).toBeInTheDocument();
  });

  it("requires both a billing-cycle label and a due date before saving", async () => {
    const user = userEvent.setup();
    const save = vi.spyOn(statementApi, "saveStatement");
    render(<CreditCardStatementUploader />);
    await getToReview(user);
    await user.clear(screen.getByLabelText("Payment due date"));

    await user.click(screen.getByRole("button", { name: "Save statement" }));

    expect(screen.getByText(/Enter the payment due date/)).toBeInTheDocument();
    expect(save).not.toHaveBeenCalled();
  });

  it("saves the itemized entry (flagged counts_toward_net_savings: false) and a synthetic payment entry for the full itemized total, dated at the due date", async () => {
    const user = userEvent.setup();
    const save = vi
      .spyOn(statementApi, "saveStatement")
      .mockResolvedValueOnce({
        id: "st1",
        source_account: "HDFC Credit Card",
        period_label: "2026-07",
        created_at: "2026-07-31",
      })
      .mockResolvedValueOnce({
        id: "st2",
        source_account: "HDFC Credit Card — Bill Payment",
        period_label: "2026-08",
        created_at: "2026-08-05",
      });
    render(<CreditCardStatementUploader />);
    await getToReview(user);

    await user.click(screen.getByRole("button", { name: "Save statement" }));

    await waitFor(() =>
      expect(screen.getByText("Statement and payment record both saved.")).toBeInTheDocument()
    );
    expect(save).toHaveBeenCalledTimes(2);

    const entries = useTransactionStore.getState().entries;
    expect(entries).toHaveLength(2);
    const itemized = entries.find((e) => e.id === "st1")!;
    expect(itemized.transactions.every((t) => t.counts_toward_net_savings === false)).toBe(true);

    const payment = entries.find((e) => e.id === "st2")!;
    expect(payment.transactions).toEqual([
      expect.objectContaining({
        description: "Credit Card Bill Payment",
        date: "2026-08-05",
        amount: -5_000, // sum of the two itemized rows: -3000 + -2000
        source_account: "HDFC Credit Card — Bill Payment",
        counts_toward_category_spend: false,
      }),
    ]);
  });

  it("on a duplicate itemized-statement conflict, shows the server detail and never attempts the payment save at all", async () => {
    const user = userEvent.setup();
    vi.spyOn(statementApi, "saveStatement").mockRejectedValueOnce({
      response: { status: 409, data: { detail: "Already saved under a different card name" } },
    });
    render(<CreditCardStatementUploader />);
    await getToReview(user);

    await user.click(screen.getByRole("button", { name: "Save statement" }));

    await waitFor(() =>
      expect(screen.getByText("Already saved under a different card name")).toBeInTheDocument()
    );
    expect(statementApi.saveStatement).toHaveBeenCalledTimes(1); // never got to the payment save
    expect(useTransactionStore.getState().entries).toEqual([]);
  });

  it("when the itemized save succeeds but the payment save fails, shows the pending-payment retry panel WITHOUT re-attempting the itemized save", async () => {
    const user = userEvent.setup();
    const save = vi
      .spyOn(statementApi, "saveStatement")
      .mockResolvedValueOnce({
        id: "st1",
        source_account: "HDFC Credit Card",
        period_label: "2026-07",
        created_at: "2026-07-31",
      })
      .mockRejectedValueOnce(new Error("network"));
    render(<CreditCardStatementUploader />);
    await getToReview(user);

    await user.click(screen.getByRole("button", { name: "Save statement" }));

    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Retry payment record" })).toBeInTheDocument()
    );
    expect(screen.getByText(/Purchases are saved/)).toBeInTheDocument();
    expect(screen.getByText(/₹5,000/)).toBeInTheDocument(); // the pending payment amount, whole rupees
    expect(useTransactionStore.getState().entries).toHaveLength(1); // itemized entry already landed

    // Retry: only the payment save is attempted, not a 3rd saveStatement call for the itemized entry again.
    save.mockResolvedValueOnce({
      id: "st2",
      source_account: "HDFC Credit Card — Bill Payment",
      period_label: "2026-08",
      created_at: "2026-08-05",
    });
    await user.click(screen.getByRole("button", { name: "Retry payment record" }));

    await waitFor(() =>
      expect(screen.getByText("Statement and payment record both saved.")).toBeInTheDocument()
    );
    expect(save).toHaveBeenCalledTimes(3); // itemized (once) + payment failed attempt + payment retry
    expect(useTransactionStore.getState().entries).toHaveLength(2);
  });

  it("regression: a retry that ALSO fails actually shows its error message, and the stale review panel/Save button never reappears alongside the retry panel", async () => {
    const user = userEvent.setup();
    vi.spyOn(statementApi, "saveStatement")
      .mockResolvedValueOnce({
        id: "st1",
        source_account: "HDFC Credit Card",
        period_label: "2026-07",
        created_at: "2026-07-31",
      })
      .mockRejectedValueOnce(new Error("network")) // first payment attempt fails
      .mockRejectedValueOnce(new Error("network")); // retry also fails
    render(<CreditCardStatementUploader />);
    await getToReview(user);

    await user.click(screen.getByRole("button", { name: "Save statement" }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Retry payment record" })).toBeInTheDocument()
    );
    // The old review panel (with its own live "Save statement" button) must
    // not coexist with the retry panel -- clicking it again would otherwise
    // re-attempt saving the already-persisted itemized entry.
    expect(screen.queryByRole("button", { name: "Save statement" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Retry payment record" }));

    await waitFor(() =>
      expect(screen.getByText("Still couldn't save the payment record — try again.")).toBeInTheDocument()
    );
    expect(screen.getByRole("button", { name: "Retry payment record" })).toBeInTheDocument();
  });
});
