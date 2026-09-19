import { beforeEach, describe, expect, it } from "vitest";
import { computeAlerts, dismissForToday, isDismissedToday, type Alert } from "./alerts";
import type { Budget } from "../store/budgetStore";
import type { FinancialProfile } from "../store/financialProfileStore";

function findAlert(alerts: Alert[], id: string): Alert | undefined {
  return alerts.find((a) => a.id === id);
}

describe("computeAlerts", () => {
  describe("itr-filing-deadline", () => {
    it("appears within the June-July reminder window, with warning severity inside 14 days", () => {
      const now = new Date(2026, 6, 20); // July 20 -> 11 days left
      const alert = findAlert(computeAlerts(now, [], null), "itr-filing-deadline");
      expect(alert).toBeDefined();
      expect(alert!.severity).toBe("warning");
    });

    it("uses info severity when more than 14 days remain", () => {
      const now = new Date(2026, 5, 1); // June 1
      const alert = findAlert(computeAlerts(now, [], null), "itr-filing-deadline");
      expect(alert!.severity).toBe("info");
    });

    it("does not appear outside the reminder window", () => {
      const now = new Date(2026, 8, 1); // September
      expect(findAlert(computeAlerts(now, [], null), "itr-filing-deadline")).toBeUndefined();
    });
  });

  describe("regime-declaration", () => {
    it("appears February through April", () => {
      const now = new Date(2026, 2, 15); // March 15
      expect(findAlert(computeAlerts(now, [], null), "regime-declaration")).toBeDefined();
    });

    it("does not appear in May", () => {
      const now = new Date(2026, 4, 1);
      expect(findAlert(computeAlerts(now, [], null), "regime-declaration")).toBeUndefined();
    });
  });

  describe("deduction-headroom", () => {
    const now = new Date(2026, 1, 15); // Feb 15, inside the Jan-March window

    it("does not appear without a financial profile", () => {
      expect(findAlert(computeAlerts(now, [], null), "deduction-headroom")).toBeUndefined();
    });

    it("does not appear once 80C/80D/24(b) room is used up", () => {
      const profile: FinancialProfile = {
        elssMutualFunds: 150_000,
        healthInsurancePremium: 25_000,
        homeLoanInterestPaid: 200_000,
      };
      expect(findAlert(computeAlerts(now, [], profile), "deduction-headroom")).toBeUndefined();
    });

    it("rounds the remaining amount to whole rupees even from fractional inputs (regression for the ₹27,201.051 display bug)", () => {
      const profile: FinancialProfile = {
        elssMutualFunds: 33_333.33,
        lifeInsurancePremium: 10_000.66,
        healthInsurancePremium: 1_000.5,
      };
      const alert = findAlert(computeAlerts(now, [], profile), "deduction-headroom");
      expect(alert).toBeDefined();
      expect(alert!.message).not.toMatch(/\d\.\d/);
    });

    it("uses the higher senior-citizen 80D limit when flagged", () => {
      const profile: FinancialProfile = { healthInsuranceForSeniorCitizen: true };
      const alert = findAlert(computeAlerts(now, [], profile), "deduction-headroom");
      // Full 80C (150k) + senior 80D (50k) + full 24(b) (200k) = 4,00,000
      // (en-IN groups by lakh/crore, not thousands)
      expect(alert!.message).toContain("4,00,000");
    });
  });

  describe("stale-payslip", () => {
    it("does not appear with no snapshots", () => {
      expect(findAlert(computeAlerts(new Date(2026, 8, 1), [], null), "stale-payslip")).toBeUndefined();
    });

    it("does not appear for a recent snapshot", () => {
      const now = new Date(2026, 8, 15);
      expect(
        findAlert(computeAlerts(now, [{ month: "2026-08" }], null), "stale-payslip")
      ).toBeUndefined();
    });

    it("appears once the latest snapshot is 2+ months old", () => {
      const now = new Date(2026, 8, 1); // September 2026
      const alert = findAlert(
        computeAlerts(now, [{ month: "2026-01" }, { month: "2026-03" }], null),
        "stale-payslip"
      );
      expect(alert).toBeDefined();
      expect(alert!.message).toContain("2026-03");
      expect(alert!.message).toContain("6 months ago");
    });
  });

  describe("budget-overspending", () => {
    const now = new Date(2026, 8, 1);

    it("does not appear without a budget", () => {
      const transactions = [{ date: "2026-07-01", amount: -1000, category: "Rent" }];
      expect(
        findAlert(computeAlerts(now, [], null, transactions, null), "budget-overspending")
      ).toBeUndefined();
    });

    it("does not appear when spend is within budget", () => {
      const budget: Budget = { Rent: 30_000 };
      const transactions = [{ date: "2026-07-05", amount: -20_000, category: "Rent" }];
      expect(
        findAlert(computeAlerts(now, [], null, transactions, budget), "budget-overspending")
      ).toBeUndefined();
    });

    it("flags the worst category, prorates a multi-month period, and rounds all figures to whole rupees (regression for the ₹27,201.051 display bug)", () => {
      const budget: Budget = { Rent: 15_000 };
      // A 61-day period (Jul 1 - Aug 30) makes periodSpanMonths non-integer
      // (~2.004), which used to leak fractional rupees straight into the
      // alert text before the toLocaleString maximumFractionDigits fix.
      const transactions = [
        { date: "2026-07-01", amount: -20_000, category: "Rent", statement_period: "2026-07 to 2026-08" },
        { date: "2026-08-30", amount: -16_000, category: "Rent", statement_period: "2026-07 to 2026-08" },
      ];
      const alert = findAlert(computeAlerts(now, [], null, transactions, budget), "budget-overspending");
      expect(alert).toBeDefined();
      expect(alert!.title).toBe("Over budget on Rent");
      expect(alert!.message).toContain("₹36,000 spent");
      expect(alert!.message).not.toMatch(/\d\.\d/);
    });

    it("names the worst category and counts the rest when multiple categories are over budget", () => {
      const budget: Budget = { Rent: 10_000, Groceries: 5_000, Shopping: 5_000 };
      const transactions = [
        { date: "2026-07-05", amount: -20_000, category: "Rent" },
        { date: "2026-07-05", amount: -8_000, category: "Groceries" },
        { date: "2026-07-05", amount: -6_000, category: "Shopping" },
      ];
      const alert = findAlert(computeAlerts(now, [], null, transactions, budget), "budget-overspending");
      expect(alert!.title).toBe("Over budget on 3 categories");
      expect(alert!.message).toContain("plus 2 more categories");
    });
  });

  describe("goal-deadline-approaching", () => {
    const now = new Date(2026, 8, 1); // September 1

    it("does not appear when no goal has a near deadline", () => {
      const goals = [{ name: "Vacation", targetDate: "2027-06-01", targetAmount: 100_000, savedAmount: 10_000 }];
      expect(
        findAlert(computeAlerts(now, [], null, [], null, goals), "goal-deadline-approaching")
      ).toBeUndefined();
    });

    it("does not appear for an already-funded goal", () => {
      const goals = [{ name: "Vacation", targetDate: "2026-09-10", targetAmount: 50_000, savedAmount: 50_000 }];
      expect(
        findAlert(computeAlerts(now, [], null, [], null, goals), "goal-deadline-approaching")
      ).toBeUndefined();
    });

    it("uses warning severity inside 7 days and info severity beyond that", () => {
      const urgentGoals = [{ name: "Rent deposit", targetDate: "2026-09-05", targetAmount: 50_000, savedAmount: 25_000 }];
      const urgent = findAlert(computeAlerts(now, [], null, [], null, urgentGoals), "goal-deadline-approaching");
      expect(urgent!.severity).toBe("warning");

      const laterGoals = [{ name: "Rent deposit", targetDate: "2026-09-20", targetAmount: 50_000, savedAmount: 25_000 }];
      const later = findAlert(computeAlerts(now, [], null, [], null, laterGoals), "goal-deadline-approaching");
      expect(later!.severity).toBe("info");
    });

    it("picks the soonest deadline among multiple qualifying goals", () => {
      const goals = [
        { name: "Far goal", targetDate: "2026-09-25", targetAmount: 10_000, savedAmount: 0 },
        { name: "Near goal", targetDate: "2026-09-08", targetAmount: 10_000, savedAmount: 0 },
      ];
      const alert = findAlert(computeAlerts(now, [], null, [], null, goals), "goal-deadline-approaching");
      expect(alert!.title).toContain("Near goal");
    });
  });

  describe("stale-statement", () => {
    const now = new Date(2026, 8, 15);

    it("does not appear with no transactions", () => {
      expect(findAlert(computeAlerts(now, [], null), "stale-statement")).toBeUndefined();
    });

    it("does not appear for a recent statement period", () => {
      const transactions = [{ date: "2026-09-01", amount: -100 }];
      expect(findAlert(computeAlerts(now, [], null, transactions), "stale-statement")).toBeUndefined();
    });

    it("appears for a statement period 2+ months old", () => {
      const transactions = [{ date: "2026-03-01", amount: -100 }];
      const alert = findAlert(computeAlerts(now, [], null, transactions), "stale-statement");
      expect(alert).toBeDefined();
      expect(alert!.message).toContain("2026-03");
    });

    it("skips a free-text period range it can't parse as a single YYYY-MM month", () => {
      const transactions = [
        { date: "2026-01-01", amount: -100, statement_period: "16 Jul 2020 to 15 Aug 2020" },
      ];
      expect(findAlert(computeAlerts(now, [], null, transactions), "stale-statement")).toBeUndefined();
    });
  });
});

describe("alert dismissal", () => {
  beforeEach(() => localStorage.clear());

  it("is not dismissed by default", () => {
    expect(isDismissedToday("some-alert", new Date(2026, 8, 1, 12))).toBe(false);
  });

  it("stays dismissed for the rest of the same calendar day", () => {
    dismissForToday("some-alert", new Date(2026, 8, 1, 9));
    expect(isDismissedToday("some-alert", new Date(2026, 8, 1, 22))).toBe(true);
  });

  it("resets on a new day", () => {
    dismissForToday("some-alert", new Date(2026, 8, 1, 12));
    expect(isDismissedToday("some-alert", new Date(2026, 8, 2, 12))).toBe(false);
  });

  it("dismissal is scoped per alert id", () => {
    dismissForToday("alert-a", new Date(2026, 8, 1, 12));
    expect(isDismissedToday("alert-b", new Date(2026, 8, 1, 12))).toBe(false);
  });
});
