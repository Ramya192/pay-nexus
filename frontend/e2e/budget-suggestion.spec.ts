import { expect, test } from "@playwright/test";
import { login, logout, openTab, register, savePayslipToHistory } from "./helpers";

// Regression: the Budget tab mounted before payslip history finished loading after login, so the
// suggestion ignored income and every account got the 18,000-rent default (R9).
test("budget suggestion scales with the saved payslip after a fresh login", async ({ page }) => {
  const email = await register(page);
  await savePayslipToHistory(page, { month: "2026-06", basic: 15000, hra: 6000, specialAllowance: 4000 });

  await logout(page);
  await login(page, email);

  await openTab(page, "Budget");
  // 25,000 gross -> "Below 30k" bracket: Rent 0.4 x 18,000 = 7,200 (not the 18,000 default).
  await expect(page.locator("#budget-Rent")).toHaveValue("7200");
});

test("a higher payslip gets the larger suggested budget", async ({ page }) => {
  const email = await register(page);
  await savePayslipToHistory(page, { month: "2026-06", basic: 50000, hra: 20000, specialAllowance: 15000 });
  await logout(page);
  await login(page, email);

  await openTab(page, "Budget");
  await expect(page.locator("#budget-Rent")).toHaveValue("18000");
});
