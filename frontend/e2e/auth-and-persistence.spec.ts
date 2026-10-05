import { expect, test } from "@playwright/test";
import { login, logout, openTab, register, savePayslipToHistory } from "./helpers";

test("saved data survives logout and login; a wrong password shows the generic error", async ({ page }) => {
  const email = await register(page);
  await savePayslipToHistory(page, { month: "2026-05", basic: 40000 });

  await logout(page);

  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill("definitely-wrong-password");
  await page.getByRole("button", { name: "Log in" }).click();
  await expect(page.getByText("Incorrect email or password.")).toBeVisible();

  await login(page, email);
  await openTab(page, "Payslip history");
  await expect(page.getByText("2026-05", { exact: true })).toBeVisible();
});
