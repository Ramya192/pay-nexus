import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { StatementUploader } from "./StatementUploader";
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

function pdfFile(name = "statement.pdf") {
  return new File(["%PDF fake"], name, { type: "application/pdf" });
}
function csvFile(content: string, name = "statement.csv") {
  return new File([content], name, { type: "text/csv" });
}

function txn(overrides: Partial<statementApi.ParsedTransaction> = {}): statementApi.ParsedTransaction {
  return {
    transaction_id: "t1",
    date: "2026-07-05",
    description: "Rent",
    amount: -20_000,
    source_account: "HDFC",
    category: "Rent",
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

async function nameAccount(user: ReturnType<typeof userEvent.setup>, name = "HDFC Checking") {
  await user.type(screen.getByLabelText("Account name"), name);
}

describe("StatementUploader", () => {
  it("requires an account name before a file can be processed", async () => {
    const user = userEvent.setup();
    const extract = vi.mocked(pdfText.extractPdfText);
    render(<StatementUploader />);

    await user.upload(screen.getByLabelText(/Upload bank statement/), pdfFile());

    expect(
      screen.getByText(/Name the account first/)
    ).toBeInTheDocument();
    expect(extract).not.toHaveBeenCalled();
  });

  it("parses a PDF (extracting text client-side) into a reviewable list with a single-month default period label", async () => {
    const user = userEvent.setup();
    vi.mocked(pdfText.extractPdfText).mockResolvedValue("statement text");
    vi.spyOn(statementApi, "parseStatementText").mockResolvedValue({
      transactions: [txn({ date: "2026-07-05" }), txn({ transaction_id: "t2", date: "2026-07-20" })],
      skipped_row_count: 0,
      truncated_chars: 0,
    });
    render(<StatementUploader />);
    await nameAccount(user);

    await user.upload(screen.getByLabelText(/Upload bank statement/), pdfFile());

    await waitFor(() => expect(screen.getByText("2 transaction(s) found — review below, then save.")).toBeInTheDocument());
    expect(screen.getByLabelText("Period label")).toHaveValue("2026-07");
  });

  it("parses a CSV via file.text() (no PDF extraction) and suggests a month-range label when it spans multiple months", async () => {
    const user = userEvent.setup();
    const extract = vi.mocked(pdfText.extractPdfText);
    vi.spyOn(statementApi, "parseStatementText").mockResolvedValue({
      transactions: [txn({ date: "2026-07-05" }), txn({ transaction_id: "t2", date: "2026-08-20" })],
      skipped_row_count: 0,
      truncated_chars: 0,
    });
    render(<StatementUploader />);
    await nameAccount(user);

    await user.upload(screen.getByLabelText(/Upload bank statement/), csvFile("date,desc,amount\n..."));

    await waitFor(() => expect(screen.getByLabelText("Period label")).toHaveValue("2026-07 to 2026-08"));
    expect(extract).not.toHaveBeenCalled();
  });

  it("shows skipped-row and truncation warnings when the parse result reports them", async () => {
    const user = userEvent.setup();
    vi.mocked(pdfText.extractPdfText).mockResolvedValue("text");
    vi.spyOn(statementApi, "parseStatementText").mockResolvedValue({
      transactions: [txn()],
      skipped_row_count: 3,
      truncated_chars: 500,
    });
    render(<StatementUploader />);
    await nameAccount(user);

    await user.upload(screen.getByLabelText(/Upload bank statement/), pdfFile());

    await waitFor(() =>
      expect(screen.getByText(/3 row\(s\) couldn't be read/)).toBeInTheDocument()
    );
    expect(screen.getByText(/only part of it could be parsed/)).toBeInTheDocument();
  });

  it("errors out when no transactions could be read at all", async () => {
    const user = userEvent.setup();
    vi.mocked(pdfText.extractPdfText).mockResolvedValue("text");
    vi.spyOn(statementApi, "parseStatementText").mockResolvedValue({
      transactions: [],
      skipped_row_count: 0,
      truncated_chars: 0,
    });
    render(<StatementUploader />);
    await nameAccount(user);

    await user.upload(screen.getByLabelText(/Upload bank statement/), pdfFile());

    await waitFor(() =>
      expect(screen.getByText("No transactions could be read from that file.")).toBeInTheDocument()
    );
  });

  it("shows a scanned-PDF-specific message when no text could be extracted", async () => {
    const user = userEvent.setup();
    vi.mocked(pdfText.extractPdfText).mockResolvedValue("   ");
    render(<StatementUploader />);
    await nameAccount(user);

    await user.upload(screen.getByLabelText(/Upload bank statement/), pdfFile());

    await waitFor(() =>
      expect(screen.getByText(/Couldn't find any text in that PDF/)).toBeInTheDocument()
    );
  });

  describe("save", () => {
    async function getToReview(user: ReturnType<typeof userEvent.setup>) {
      vi.mocked(pdfText.extractPdfText).mockResolvedValue("text");
      vi.spyOn(statementApi, "parseStatementText").mockResolvedValue({
        transactions: [txn()],
        skipped_row_count: 0,
        truncated_chars: 0,
      });
      await nameAccount(user);
      await user.upload(screen.getByLabelText(/Upload bank statement/), pdfFile());
      await waitFor(() => expect(screen.getByLabelText("Period label")).toBeInTheDocument());
    }

    it("requires a period label before saving", async () => {
      const user = userEvent.setup();
      const save = vi.spyOn(statementApi, "saveStatement");
      render(<StatementUploader />);
      await getToReview(user);
      await user.clear(screen.getByLabelText("Period label"));

      await user.click(screen.getByRole("button", { name: "Save statement" }));

      expect(screen.getByText(/Give this statement a period label/)).toBeInTheDocument();
      expect(save).not.toHaveBeenCalled();
    });

    it("saves successfully and adds the entry to the store", async () => {
      const user = userEvent.setup();
      vi.spyOn(statementApi, "saveStatement").mockResolvedValue({
        id: "st1",
        source_account: "HDFC Checking",
        period_label: "2026-07",
        created_at: "2026-07-31",
      });
      render(<StatementUploader />);
      await getToReview(user);

      await user.click(screen.getByRole("button", { name: "Save statement" }));

      await waitFor(() => expect(screen.getByText("Statement saved.")).toBeInTheDocument());
      expect(useTransactionStore.getState().entries).toHaveLength(1);
    });

    it("on a duplicate conflict, shows the server's own detail message and returns to the review state (not a hard error)", async () => {
      const user = userEvent.setup();
      vi.spyOn(statementApi, "saveStatement").mockRejectedValue({
        response: { status: 409, data: { detail: "Already saved under a different account name" } },
      });
      render(<StatementUploader />);
      await getToReview(user);

      await user.click(screen.getByRole("button", { name: "Save statement" }));

      await waitFor(() =>
        expect(screen.getByText("Already saved under a different account name")).toBeInTheDocument()
      );
      // Still in review -- the parsed list and Save button are still there, not wiped by an error state.
      expect(screen.getByRole("button", { name: "Save statement" })).toBeInTheDocument();
      expect(useTransactionStore.getState().entries).toEqual([]);
    });

    it("falls back to a generic duplicate message when the server gives no detail", async () => {
      const user = userEvent.setup();
      vi.spyOn(statementApi, "saveStatement").mockRejectedValue({ response: { status: 409 } });
      render(<StatementUploader />);
      await getToReview(user);

      await user.click(screen.getByRole("button", { name: "Save statement" }));

      await waitFor(() =>
        expect(screen.getByText(/is already saved\./)).toBeInTheDocument()
      );
    });
  });
});
