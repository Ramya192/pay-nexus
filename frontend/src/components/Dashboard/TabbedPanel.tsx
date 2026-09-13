import { History, Upload, Wallet } from "lucide-react";
import { useState, type ReactNode } from "react";
import { FinancialProfileForm } from "../FinancialProfile/FinancialProfileForm";
import { ActivePayslipBanner } from "../PayslipUploader/ActivePayslipBanner";
import { PayslipHistoryList } from "../PayslipUploader/PayslipHistoryList";
import { PayslipHistoryUpload } from "../PayslipUploader/PayslipHistoryUpload";
import { PayslipUploader } from "../PayslipUploader/PayslipUploader";

type TabId = "upload" | "history" | "profile";

const TABS: { id: TabId; label: string; icon: typeof Upload }[] = [
  { id: "upload", label: "Upload payslip", icon: Upload },
  { id: "history", label: "Payslip history", icon: History },
  { id: "profile", label: "Investments & loans", icon: Wallet },
];

/**
 * Replaces the old always-visible sidebar (three stacked <details> sections
 * — upload, history, financial profile) with tabs, per user request: the
 * three areas are mutually exclusive tasks, not something a user works
 * across simultaneously, so only one needs to be on screen at a time.
 * Content of each tab is unchanged from the old sidebar sections — this is
 * a navigation change, not a rebuild of what's inside them.
 */
export function TabbedPanel() {
  const [active, setActive] = useState<TabId>("upload");

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
