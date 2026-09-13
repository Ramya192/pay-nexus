import { Gauge, History, PiggyBank, Target, Upload, Wallet } from "lucide-react";
import { useState, type ReactNode } from "react";
import { BudgetForm } from "../BudgetPlanner/BudgetForm";
import { FinancialProfileForm } from "../FinancialProfile/FinancialProfileForm";
import { GoalForm } from "../GoalTracker/GoalForm";
import { GoalList } from "../GoalTracker/GoalList";
import { ActivePayslipBanner } from "../PayslipUploader/ActivePayslipBanner";
import { PayslipHistoryList } from "../PayslipUploader/PayslipHistoryList";
import { PayslipHistoryUpload } from "../PayslipUploader/PayslipHistoryUpload";
import { PayslipUploader } from "../PayslipUploader/PayslipUploader";
import { StatementList } from "../StatementUploader/StatementList";
import { StatementUploader } from "../StatementUploader/StatementUploader";

type TabId = "spending" | "budget" | "upload" | "history" | "profile" | "goals";

// Order here is the tab order shown — Bank statements first (per user
// request), Budget right after it (closely related — both work off
// transaction data), then the original payslip-first flow (Upload payslip,
// Payslip history, Investments & loans), then Goals last.
const TABS: { id: TabId; label: string; icon: typeof Upload }[] = [
  { id: "spending", label: "Bank statements", icon: PiggyBank },
  { id: "budget", label: "Budget", icon: Gauge },
  { id: "upload", label: "Upload payslip", icon: Upload },
  { id: "history", label: "Payslip history", icon: History },
  { id: "profile", label: "Investments & loans", icon: Wallet },
  { id: "goals", label: "Goals", icon: Target },
];

/**
 * Replaces the old always-visible sidebar (three stacked <details> sections
 * — upload, history, financial profile) with tabs, per user request: the
 * areas are mutually exclusive tasks, not something a user works across
 * simultaneously, so only one needs to be on screen at a time. Content of
 * each tab (other than Budget/Goals, new in V2) is unchanged from the old
 * sidebar sections — this is a navigation change, not a rebuild of what's
 * inside them.
 */
export function TabbedPanel() {
  const [active, setActive] = useState<TabId>("spending");

  return (
    <div className="mx-auto max-w-2xl">
      <div className="flex gap-1 border-b border-slate-200">
        {TABS.map((tab) => {
          const Icon = tab.icon;
          const isActive = tab.id === active;
          return (
            <button
              key={tab.id}
              onClick={() => setActive(tab.id)}
              className={`flex items-center gap-1.5 border-b-2 px-4 py-2.5 text-sm font-medium transition-colors ${
                isActive
                  ? "border-brand-600 text-brand-700"
                  : "border-transparent text-slate-500 hover:text-slate-800"
              }`}
            >
              <Icon className="h-4 w-4" aria-hidden="true" />
              {tab.label}
            </button>
          );
        })}
      </div>

      <div className="py-5">
        <TabPanel visible={active === "spending"}>
          <p className="mb-3 text-xs text-slate-400">
            Optional — upload bank/credit-card statements so the SpendingAnalyser can answer
            questions about where your money actually goes, not just your payslip.
          </p>
          <StatementUploader />
          <div className="mt-3 border-t border-slate-100 pt-3">
            <StatementList />
          </div>
        </TabPanel>

        <TabPanel visible={active === "budget"}>
          <p className="mb-3 text-xs text-slate-400">
            Set per-category monthly targets, then ask the BudgetPlanner in chat (e.g. "am I over
            budget?") once you've saved a bank statement to check actual spend against them.
          </p>
          <BudgetForm />
        </TabPanel>

        <TabPanel visible={active === "upload"}>
          <ActivePayslipBanner />
          <PayslipUploader />
        </TabPanel>

        <TabPanel visible={active === "history"}>
          <p className="mb-3 text-xs text-slate-400">
            Optional — upload past months so the Savings Advisor can compute real month-over-month
            trends instead of relying on session memory alone.
          </p>
          <PayslipHistoryUpload />
          <div className="mt-3 border-t border-slate-100 pt-3">
            <PayslipHistoryList />
          </div>
        </TabPanel>

        <TabPanel visible={active === "profile"}>
          <p className="mb-3 text-xs text-slate-400">
            Optional — lets the Savings Advisor compute exact 80C/80D/24(b) gaps instead of guessing
            from your payslip alone.
          </p>
          <FinancialProfileForm />
        </TabPanel>

        <TabPanel visible={active === "goals"}>
          <p className="mb-3 text-xs text-slate-400">
            Track savings goals — Trip, Home Loan, Education, and so on. Ask the GoalTracker in chat
            (e.g. "how am I doing on my goals?") once at least one is added.
          </p>
          <GoalForm />
          <div className="mt-3 border-t border-slate-100 pt-3">
            <GoalList />
          </div>
        </TabPanel>
      </div>
    </div>
  );
}

// Kept mounted (display:none via hidden, not conditionally rendered) rather
// than unmounted on tab switch — PayslipUploader/ManualEntryForm hold
// meaningful in-progress form state (typed values, a PDF pre-fill) that a
// user switching to check "Payslip history" and back shouldn't lose.
function TabPanel({ visible, children }: { visible: boolean; children: ReactNode }) {
  return <div className={visible ? "" : "hidden"}>{children}</div>;
}
