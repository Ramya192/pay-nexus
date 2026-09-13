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
 * V2 additions (overspending/goal-deadline/stale-statement below) are the
 * "don't wait to be asked" lever for the three newer agents — the payslip-
 * side alerts above already did this (a user never has to think to ask
 * "is my ITR deadline coming up"); spending/budget/goals had the same gap
 * until now, answerable in chat but never surfaced unprompted. Same
 * client-side-only, no-LLM computation as the payslip alerts, for the same
 * reason: these are exact, structural facts (an amount over a limit, a
 * date past a threshold), not something worth spending a model call on.
 *
 * NOTE on the 80C/80D/24(b) limits below: duplicated from
 * backend/tax_calculations.py's SECTION_80C_LIMIT / SECTION_80D_LIMIT_* /
 * SECTION_24B_LIMIT, not imported — there's no shared package between the
 * Python backend and this TS frontend. If those limits ever change, update
 * both. Deliberately a rough check, not a Section-accurate one the way the
 * backend's version is (e.g. no employee-PF annualization) — good enough
 * for "you have meaningfully unused room, go ask," not a replacement for
 * the real chat-computed figure. The V2 alerts below carry the same
 * "duplicated logic, not imported" caveat relative to
 * backend/budgeting/budgets.py's check_overspending and
 * backend/analytics/spending_trends.py's period grouping.
 */

import type { Budget } from "../store/budgetStore";
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
const STALE_STATEMENT_MONTHS = 2;
const GOAL_DEADLINE_REMINDER_DAYS = 30;
const GOAL_DEADLINE_URGENT_DAYS = 7;

export function computeAlerts(
  now: Date,
  snapshots: Record<string, unknown>[],
  financialProfile: FinancialProfile | null,
  transactions: Record<string, unknown>[] = [],
  budget: Budget | null = null,
  goals: Record<string, unknown>[] = []
): Alert[] {
  return [
    itrFilingDeadlineAlert(now),
    regimeDeclarationAlert(now),
    deductionHeadroomAlert(now, financialProfile),
    stalePayslipAlert(now, snapshots),
    overspendingAlert(transactions, budget),
    goalDeadlineApproachingAlert(now, goals),
    staleStatementAlert(now, transactions),
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

// --- V2: spending/budget/goal alerts --------------------------------------
//
// `transactions` items are the same plain-dict shape store/transactionStore.ts
// hands to /chat (models.Transaction plus a `statement_period` field — see
// backend/analytics/spending_trends.py's module docstring for why period
// grouping, not calendar-month slicing, is what these need to match the
// backend's own reasoning).

function periodOf(t: Record<string, unknown>): string | null {
  const period = t.statement_period;
  if (typeof period === "string" && period) return period;
  const date = t.date;
  return typeof date === "string" && date.length >= 7 ? date.slice(0, 7) : null;
}

function latestPeriod(transactions: Record<string, unknown>[]): string | null {
  const periods = new Set<string>();
  for (const t of transactions) {
    const p = periodOf(t);
    if (p) periods.add(p);
  }
  if (periods.size === 0) return null;
  return [...periods].sort().at(-1) ?? null;
}

const AVG_DAYS_PER_MONTH = 30.44;

/** How many real months long one statement period actually is — mirrors
 * backend/analytics/spending_trends.py's period_span_months (duplicated,
 * not imported — no shared package between this TS frontend and the
 * Python backend, same caveat as this file's own module docstring already
 * flags). Exists so overspendingAlert can prorate a MONTHLY budget target
 * before comparing it against a period's actual spend — without this, a
 * statement spanning more than ~1 real month (e.g. 01 Jul-15 Aug, 46 days)
 * always looks over budget purely from covering extra days, not from a
 * real overspend. Floored at 1.0 so a short period never shrinks the
 * effective budget below one full month's worth. */
function periodSpanMonths(transactions: Record<string, unknown>[], period: string): number {
  const dates = transactions
    .filter((t) => periodOf(t) === period)
    .map((t) => t.date)
    .filter((d): d is string => typeof d === "string" && d.length >= 10);
  if (dates.length === 0) return 1;

  const times = dates.map((d) => new Date(d).getTime()).filter((t) => !Number.isNaN(t));
  if (times.length === 0) return 1;

  const spanDays = (Math.max(...times) - Math.min(...times)) / 86_400_000 + 1;
  return Math.max(spanDays / AVG_DAYS_PER_MONTH, 1);
}

function spendingByCategoryForPeriod(transactions: Record<string, unknown>[], period: string): Record<string, number> {
  const totals: Record<string, number> = {};
  for (const t of transactions) {
    const amount = t.amount;
    if (typeof amount !== "number" || amount >= 0) continue; // expenses only
    if (periodOf(t) !== period) continue;
    const category = typeof t.category === "string" && t.category ? t.category : "Uncategorized";
    totals[category] = (totals[category] ?? 0) + -amount;
  }
  return totals;
}

function overspendingAlert(transactions: Record<string, unknown>[], budget: Budget | null): Alert | null {
  if (!budget) return null;
  const period = latestPeriod(transactions);
  if (!period) return null;

  const months = periodSpanMonths(transactions, period);
  const spentByCategory = spendingByCategoryForPeriod(transactions, period);
  const overCategories = Object.entries(budget)
    .map(([category, monthlyLimit]) => ({
      category,
      limit: monthlyLimit * months,
      spent: spentByCategory[category] ?? 0,
    }))
    .filter((c) => c.spent > c.limit)
    .sort((a, b) => b.spent - b.limit - (a.spent - a.limit));
  if (overCategories.length === 0) return null;

  const worst = overCategories[0];
  const overBy = worst.spent - worst.limit;
  const extra = overCategories.length - 1;
  return {
    id: "budget-overspending",
    title: overCategories.length === 1 ? `Over budget on ${worst.category}` : `Over budget on ${overCategories.length} categories`,
    message: `${worst.category}: ₹${worst.spent.toLocaleString("en-IN")} spent vs ₹${worst.limit.toLocaleString("en-IN")} budgeted for ${period} (₹${overBy.toLocaleString("en-IN")} over)${extra > 0 ? ` — plus ${extra} more categor${extra === 1 ? "y" : "ies"}` : ""}. Ask the BudgetPlanner for the full breakdown.`,
    severity: "warning",
  };
}

function goalDeadlineApproachingAlert(now: Date, goals: Record<string, unknown>[]): Alert | null {
  const candidates = goals
    .map((g) => {
      const name = typeof g.name === "string" && g.name ? g.name : "goal";
      const targetDate = typeof g.targetDate === "string" ? g.targetDate : null;
      const targetAmount = typeof g.targetAmount === "number" ? g.targetAmount : 0;
      const savedAmount = typeof g.savedAmount === "number" ? g.savedAmount : 0;
      if (!targetDate || targetAmount <= 0 || savedAmount >= targetAmount) return null;

      const [y, m, d] = targetDate.split("-").map(Number);
      if (!y || !m || !d) return null;
      const daysLeft = Math.ceil((new Date(y, m - 1, d).getTime() - now.getTime()) / 86_400_000);
      if (daysLeft < 0 || daysLeft > GOAL_DEADLINE_REMINDER_DAYS) return null;

      return { name, daysLeft, pct: Math.round((savedAmount / targetAmount) * 100) };
    })
    .filter((c): c is { name: string; daysLeft: number; pct: number } => c !== null)
    .sort((a, b) => a.daysLeft - b.daysLeft);
  if (candidates.length === 0) return null;

  const soonest = candidates[0];
  return {
    id: "goal-deadline-approaching",
    title: `"${soonest.name}" target date is approaching`,
    message: `${soonest.daysLeft} day${soonest.daysLeft === 1 ? "" : "s"} left and you're at ${soonest.pct}% funded — ask the GoalTracker whether your current savings rate will get you there in time.`,
    severity: soonest.daysLeft <= GOAL_DEADLINE_URGENT_DAYS ? "warning" : "info",
  };
}

function staleStatementAlert(now: Date, transactions: Record<string, unknown>[]): Alert | null {
  const period = latestPeriod(transactions);
  if (!period) return null;

  // Only meaningful for a "YYYY-MM"-shaped period (the calendar-month
  // fallback, or a clean single-month label the user typed) — a free-text
  // range like "16 Jul 2026 to 15 Aug 2026" can't be parsed into one date,
  // so this skips rather than guessing which end of the range to use.
  const match = /^(\d{4})-(\d{2})$/.exec(period);
  if (!match) return null;
  const latestDate = new Date(Number(match[1]), Number(match[2]) - 1, 1);
  const monthsSince = (now.getFullYear() - latestDate.getFullYear()) * 12 + (now.getMonth() - latestDate.getMonth());
  if (monthsSince < STALE_STATEMENT_MONTHS) return null;

  return {
    id: "stale-statement",
    title: "Your bank statements haven't been updated in a while",
    message: `Your most recent saved statement covers ${period} (${monthsSince} months ago) — upload a fresh one so spending and budget answers stay accurate.`,
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
