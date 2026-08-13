/**
 * Client-side, date/data-driven alert computation — the same "compute
 * exactly, never let an LLM guess" principle backend/tax_calculations.py
 * and tax_slabs.py use, just on the frontend: these are pure functions of
 * the current date and already-loaded payslip/financial data, no LLM call
 * and no extra network round trip. Run once after login (App.tsx, once
 * AuthScreen.tsx has already loaded history/profile/snapshots into their
 * stores) and rendered as dismissible banners (components/Alerts/AlertBanner.tsx),
 * not blocking modals — none of these need to interrupt the user, and a
 * modal that can't be dismissed for a whole two-month window would get old
 * fast.
 *
 * NOTE on the 80C/80D/24(b) limits below: duplicated from
 * backend/tax_calculations.py's SECTION_80C_LIMIT / SECTION_80D_LIMIT_* /
 * SECTION_24B_LIMIT, not imported — there's no shared package between the
 * Python backend and this TS frontend. If those limits ever change, update
 * both. Deliberately a rough check, not a Section-accurate one the way the
 * backend's version is (e.g. no employee-PF annualization) — good enough
 * for "you have meaningfully unused room, go ask," not a replacement for
 * the real chat-computed figure.
 */

import type { FinancialProfile } from "../store/financialProfileStore";

export interface Alert {
  id: string;
  title: string;
  message: string;
  severity: "info" | "warning";
}

const SECTION_80C_LIMIT = 150_000;
const SECTION_80D_LIMIT_STANDARD = 25_000;
const SECTION_80D_LIMIT_SENIOR = 50_000;
const SECTION_24B_LIMIT = 200_000;

// ITR filing deadline: July 31, for the financial year that closed the
// preceding March 31. Reminder window starts June 1 so it isn't a surprise.
const ITR_REMINDER_START_MONTH = 5; // June, 0-indexed
const ITR_FILING_DEADLINE_MONTH = 6; // July
const ITR_FILING_DEADLINE_DAY = 31;

// Employers typically collect the old-vs-new regime declaration for the
// new financial year around its start (April 1) — window opens mid-Feb.
const REGIME_DECLARATION_START_MONTH = 1; // Feb
const REGIME_DECLARATION_END_MONTH = 3; // April, inclusive

// Last chance to actually invest before the financial year closes March 31.
const FY_END_HEADROOM_START_MONTH = 0; // Jan
const FY_END_HEADROOM_END_MONTH = 2; // March, inclusive
const MEANINGFUL_HEADROOM_THRESHOLD = 20_000;

const STALE_PAYSLIP_MONTHS = 2;

export function computeAlerts(
  now: Date,
  snapshots: Record<string, unknown>[],
  financialProfile: FinancialProfile | null
): Alert[] {
  return [
    itrFilingDeadlineAlert(now),
    regimeDeclarationAlert(now),
    deductionHeadroomAlert(now, financialProfile),
    stalePayslipAlert(now, snapshots),
  ].filter((a): a is Alert => a !== null);
}

function itrFilingDeadlineAlert(now: Date): Alert | null {
  const month = now.getMonth();
  if (month < ITR_REMINDER_START_MONTH || month > ITR_FILING_DEADLINE_MONTH) return null;
  const deadline = new Date(now.getFullYear(), ITR_FILING_DEADLINE_MONTH, ITR_FILING_DEADLINE_DAY);
  const daysLeft = Math.ceil((deadline.getTime() - now.getTime()) / 86_400_000);
  if (daysLeft < 0) return null;
  return {
    id: "itr-filing-deadline",
    title: "Income tax return filing deadline approaching",
    message:
      daysLeft === 0
        ? "Today is the ITR filing deadline (July 31) for the last financial year — file today if you haven't already."
        : `${daysLeft} day${daysLeft === 1 ? "" : "s"} left to file your income tax return for the last financial year (deadline: July 31).`,
    severity: daysLeft <= 14 ? "warning" : "info",
  };
}

function regimeDeclarationAlert(now: Date): Alert | null {
  const month = now.getMonth();
  if (month < REGIME_DECLARATION_START_MONTH || month > REGIME_DECLARATION_END_MONTH) return null;
  return {
    id: "regime-declaration",
    title: "Confirm your tax regime for the new financial year",
    message:
      "Employers typically ask you to declare old vs. new tax regime around the start of the financial year (April) — ask the Savings Advisor which one is cheaper for you before confirming it with payroll.",
    severity: "info",
  };
}

function deductionHeadroomAlert(now: Date, financialProfile: FinancialProfile | null): Alert | null {
  const month = now.getMonth();
  if (month < FY_END_HEADROOM_START_MONTH || month > FY_END_HEADROOM_END_MONTH) return null;
  if (!financialProfile) return null;

  const num = (v: number | undefined) => (typeof v === "number" && v > 0 ? v : 0);
  const used80c =
    num(financialProfile.elssMutualFunds) +
    num(financialProfile.lifeInsurancePremium) +
    num(financialProfile.homeLoanPrincipalPaid);
  const remaining80c = Math.max(0, SECTION_80C_LIMIT - used80c);

  const senior = financialProfile.healthInsuranceForSeniorCitizen === true;
  const limit80d = senior ? SECTION_80D_LIMIT_SENIOR : SECTION_80D_LIMIT_STANDARD;
  const remaining80d = Math.max(0, limit80d - num(financialProfile.healthInsurancePremium));

  const remaining24b = Math.max(0, SECTION_24B_LIMIT - num(financialProfile.homeLoanInterestPaid));

  const totalRemaining = remaining80c + remaining80d + remaining24b;
  if (totalRemaining < MEANINGFUL_HEADROOM_THRESHOLD) return null;

  return {
    id: "deduction-headroom",
    title: "Unused tax deduction room before the financial year closes",
    message: `You have roughly ₹${totalRemaining.toLocaleString("en-IN")} of unused 80C/80D/24(b) deduction room, and the financial year closes March 31 — ask the Savings Advisor for the exact breakdown before it's too late to invest.`,
    severity: "warning",
  };
}

function stalePayslipAlert(now: Date, snapshots: Record<string, unknown>[]): Alert | null {
  if (snapshots.length === 0) return null;
  const months = snapshots
    .map((s) => (typeof s.month === "string" ? s.month : null))
    .filter((m): m is string => m !== null)
    .sort();
  const latest = months[months.length - 1];
  if (!latest) return null;

  const [y, m] = latest.split("-").map(Number);
  if (!y || !m) return null;
  const latestDate = new Date(y, m - 1, 1);
  const monthsSince = (now.getFullYear() - latestDate.getFullYear()) * 12 + (now.getMonth() - latestDate.getMonth());
  if (monthsSince < STALE_PAYSLIP_MONTHS) return null;

  return {
    id: "stale-payslip",
    title: "Your payslip history hasn't been updated in a while",
    message: `Your most recent saved payslip is from ${latest} (${monthsSince} months ago) — add your latest one so trends and recommendations stay accurate.`,
    severity: "info",
  };
}

// --- Dismissal: per-day, not permanent — a July reminder dismissed once
// shouldn't vanish for the rest of the filing window, just for today.
// localStorage (not a store) since it's UI chrome tied to this device/
// browser, not account data, and deliberately never encrypted/synced.

const DISMISSED_KEY_PREFIX = "paynexus_alert_dismissed_";

function todayKey(now: Date): string {
  return now.toISOString().slice(0, 10); // YYYY-MM-DD
}

export function isDismissedToday(id: string, now: Date): boolean {
  try {
    return localStorage.getItem(DISMISSED_KEY_PREFIX + id) === todayKey(now);
  } catch {
    return false; // storage unavailable (private browsing, etc.) — never block the alert on that
  }
}

export function dismissForToday(id: string, now: Date): void {
  try {
    localStorage.setItem(DISMISSED_KEY_PREFIX + id, todayKey(now));
  } catch {
    // Non-fatal — worst case the alert reappears next render.
  }
}
