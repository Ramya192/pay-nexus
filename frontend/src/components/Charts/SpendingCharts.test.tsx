import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { SpendingCharts } from "./SpendingCharts";
import { useTransactionStore } from "../../store/transactionStore";
import * as statementApi from "../../api/statement";

beforeEach(() => {
  useTransactionStore.getState().clear();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("SpendingCharts", () => {
  it("renders nothing at all with no transactions on file (StatementUploader/StatementList already cover that empty state)", () => {
    const fetchAnalytics = vi.spyOn(statementApi, "fetchSpendingAnalytics");
    const { container } = render(<SpendingCharts />);
    expect(container).toBeEmptyDOMElement();
    expect(fetchAnalytics).not.toHaveBeenCalled();
  });

  it("fetches analytics once transactions exist and renders both chart headings on success", async () => {
    vi.spyOn(statementApi, "fetchSpendingAnalytics").mockResolvedValue({
      category_breakdown: [{ category: "Rent", total_spent: 20_000 }],
      savings_projection: {
        historical_periods: ["2026-06", "2026-07", "2026-08"],
        historical_values: [10_000, 12_000, 9_000],
        projected_periods: ["2026-09"],
        projected_values: [11_000],
        r_squared: 0.82,
      },
    });
    useTransactionStore.getState().setEntries([
      {
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
        ],
      },
    ]);
    render(<SpendingCharts />);

    expect(screen.getByText("Loading charts…")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("Spending by category")).toBeInTheDocument());
    expect(screen.getByText("Net savings trend")).toBeInTheDocument();
    expect(screen.getByText(/Projection fit quality \(R²\): 0.82/)).toBeInTheDocument();
  });

  it("shows an error message and never a loading/chart state when the fetch fails", async () => {
    vi.spyOn(statementApi, "fetchSpendingAnalytics").mockRejectedValue(new Error("network"));
    useTransactionStore.getState().setEntries([
      {
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
        ],
      },
    ]);
    render(<SpendingCharts />);

    await waitFor(() =>
      expect(screen.getByText("Couldn't load charts right now — try again in a moment.")).toBeInTheDocument()
    );
    expect(screen.queryByText("Spending by category")).not.toBeInTheDocument();
  });

  it("shows the 'no expense transactions' state when the category breakdown comes back empty", async () => {
    vi.spyOn(statementApi, "fetchSpendingAnalytics").mockResolvedValue({
      category_breakdown: [],
      savings_projection: null,
    });
    useTransactionStore.getState().setEntries([
      {
        id: "s1",
        sourceAccount: "HDFC",
        periodLabel: "2026-08",
        createdAt: "2026-08-31",
        transactions: [
          {
            transaction_id: "t1",
            date: "2026-08-05",
            description: "Salary",
            amount: 80_000,
            source_account: "HDFC",
            category: "Income",
            category_source: "rule",
          },
        ],
      },
    ]);
    render(<SpendingCharts />);

    await waitFor(() => expect(screen.getByText("No expense transactions on file yet.")).toBeInTheDocument());
    expect(screen.getByText("Needs at least 3 periods of statement history to project a trend.")).toBeInTheDocument();
  });
});
