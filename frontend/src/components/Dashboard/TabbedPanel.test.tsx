import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { TabbedPanel } from "./TabbedPanel";

// TabbedPanel's own job is purely navigation (which tab/sub-tab is active,
// and keeping every panel mounted so in-progress form state survives
// switching away and back) -- every child form/uploader/list has its own
// dedicated test file already, so each is stubbed here to keep this test
// isolated to that navigation logic.
vi.mock("../BudgetPlanner/BudgetForm", () => ({ BudgetForm: () => <div data-testid="budget-form" /> }));
vi.mock("../Charts/SpendingCharts", () => ({ SpendingCharts: () => <div data-testid="spending-charts" /> }));
vi.mock("../FinancialProfile/FinancialProfileForm", () => ({
  FinancialProfileForm: () => <div data-testid="financial-profile-form" />,
}));
vi.mock("../GoalTracker/GoalForm", () => ({ GoalForm: () => <div data-testid="goal-form" /> }));
vi.mock("../GoalTracker/GoalList", () => ({ GoalList: () => <div data-testid="goal-list" /> }));
vi.mock("../PayslipUploader/ActivePayslipBanner", () => ({
  ActivePayslipBanner: () => <div data-testid="active-payslip-banner" />,
}));
vi.mock("../PayslipUploader/PayslipHistoryList", () => ({
  PayslipHistoryList: () => <div data-testid="payslip-history-list" />,
}));
vi.mock("../PayslipUploader/PayslipHistoryUpload", () => ({
  PayslipHistoryUpload: () => <div data-testid="payslip-history-upload" />,
}));
vi.mock("../PayslipUploader/PayslipUploader", () => ({
  PayslipUploader: () => <div data-testid="payslip-uploader" />,
}));
vi.mock("../StatementUploader/CreditCardStatementUploader", () => ({
  CreditCardStatementUploader: () => <div data-testid="credit-card-uploader" />,
}));
vi.mock("../StatementUploader/ManualExpenseEntry", () => ({
  ManualExpenseEntry: () => <div data-testid="manual-expense-entry" />,
}));
vi.mock("../StatementUploader/StatementList", () => ({
  StatementList: () => <div data-testid="statement-list" />,
}));
vi.mock("../StatementUploader/StatementUploader", () => ({
  StatementUploader: () => <div data-testid="statement-uploader" />,
}));

function isHidden(testId: string): boolean {
  return screen.getByTestId(testId).closest(".hidden") !== null;
}

describe("TabbedPanel", () => {
  it("defaults to the Bank statements tab, with every other tab's content mounted but hidden", () => {
    render(<TabbedPanel />);
    expect(isHidden("statement-uploader")).toBe(false);
    expect(isHidden("statement-list")).toBe(false);
    expect(isHidden("spending-charts")).toBe(false);

    expect(isHidden("budget-form")).toBe(true);
    expect(isHidden("payslip-uploader")).toBe(true);
    expect(isHidden("payslip-history-upload")).toBe(true);
    expect(isHidden("financial-profile-form")).toBe(true);
    expect(isHidden("goal-form")).toBe(true);
    // Mounted, not unmounted -- present in the DOM even while hidden.
    expect(screen.getByTestId("budget-form")).toBeInTheDocument();
  });

  it("switching tabs shows the new tab and hides the previous one, without unmounting it", async () => {
    const user = userEvent.setup();
    render(<TabbedPanel />);

    await user.click(screen.getByRole("button", { name: "Budget" }));

    expect(isHidden("budget-form")).toBe(false);
    expect(isHidden("statement-uploader")).toBe(true);
    expect(screen.getByTestId("statement-uploader")).toBeInTheDocument(); // still mounted

    await user.click(screen.getByRole("button", { name: "Goals" }));

    expect(isHidden("goal-form")).toBe(false);
    expect(isHidden("goal-list")).toBe(false);
    expect(isHidden("budget-form")).toBe(true);
  });

  it("the Upload payslip tab shows both the active-payslip banner and the uploader together", async () => {
    const user = userEvent.setup();
    render(<TabbedPanel />);
    await user.click(screen.getByRole("button", { name: "Upload payslip" }));

    expect(isHidden("active-payslip-banner")).toBe(false);
    expect(isHidden("payslip-uploader")).toBe(false);
  });

  it("the Payslip history tab shows both the bulk upload and the managed list together", async () => {
    const user = userEvent.setup();
    render(<TabbedPanel />);
    await user.click(screen.getByRole("button", { name: "Payslip history" }));

    expect(isHidden("payslip-history-upload")).toBe(false);
    expect(isHidden("payslip-history-list")).toBe(false);
  });

  describe("Bank statements sub-tabs (bank vs. credit card)", () => {
    it("defaults to Bank statement, hiding the credit-card uploader", () => {
      render(<TabbedPanel />);
      expect(isHidden("statement-uploader")).toBe(false);
      expect(isHidden("credit-card-uploader")).toBe(true);
    });

    it("switches to the credit-card uploader without unmounting the bank one, and both stay independent of the outer tab bar", async () => {
      const user = userEvent.setup();
      render(<TabbedPanel />);

      await user.click(screen.getByRole("button", { name: "Credit card statement" }));

      expect(isHidden("credit-card-uploader")).toBe(false);
      expect(isHidden("statement-uploader")).toBe(true);
      expect(screen.getByTestId("statement-uploader")).toBeInTheDocument();
      // The shared ManualExpenseEntry/StatementList/SpendingCharts below the
      // sub-tabs aren't gated by uploadKind at all -- still visible.
      expect(isHidden("statement-list")).toBe(false);
    });
  });
});
