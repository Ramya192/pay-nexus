import { expect, type Page } from "@playwright/test";

export const PASSWORD = "E2eTestPass123";

export function freshEmail(): string {
  return `e2e-${Date.now()}-${Math.floor(Math.random() * 1e6)}@example.com`;
}

export async function register(page: Page, email = freshEmail()): Promise<string> {
  await page.goto("/");
  await page.getByRole("button", { name: "Need an account? Register" }).click();
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByRole("button", { name: "Log out" })).toBeVisible();
  return email;
}

export async function login(page: Page, email: string) {
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Log in" }).click();
  await expect(page.getByRole("button", { name: "Log out" })).toBeVisible();
}

export async function logout(page: Page) {
  await page.getByRole("button", { name: "Log out" }).click();
  await expect(page.getByRole("button", { name: "Log in" })).toBeVisible();
}

export async function openTab(page: Page, name: string) {
  await page.getByRole("button", { name, exact: true }).click();
}

/** Fills the manual payslip form on the "Upload payslip" tab and saves it to history. Uses ids, not labels: every tab stays mounted, so text like "Month" matches many fields. */
export async function savePayslipToHistory(
  page: Page,
  fields: { month: string; basic: number; hra?: number; specialAllowance?: number }
) {
  await openTab(page, "Upload payslip");
  await page.locator("#payslip-month").fill(fields.month);
  await page.locator("#payslip-basic").fill(String(fields.basic));
  if (fields.hra !== undefined) await page.locator("#payslip-hra").fill(String(fields.hra));
  if (fields.specialAllowance !== undefined)
    await page.locator("#payslip-specialAllowance").fill(String(fields.specialAllowance));
  await page.getByRole("button", { name: "Save to history" }).click();
  await expect(page.getByRole("button", { name: "Saved to history" })).toBeVisible();
}

/**
 * Mocks POST /chat as a server-sent-event stream, optionally delayed so a test can act while an
 * answer is "in flight". The answer text echoes the question, so a test can tell which turn it is.
 */
export async function mockChat(page: Page, delayMs = 0) {
  await page.route("**/chat", async (route) => {
    if (route.request().method() !== "POST") return route.fallback();
    const body = route.request().postDataJSON() as { query?: string };
    if (delayMs) await new Promise((r) => setTimeout(r, delayMs));
    const frames = [
      { event: "agent_active", agent: "spending_agent" },
      { event: "final", response: `Mock answer to: ${body.query}`, active_agent: "spending_agent" },
    ];
    await route.fulfill({
      status: 200,
      contentType: "text/event-stream",
      body: frames.map((f) => `data: ${JSON.stringify(f)}\n\n`).join(""),
    });
  });
}
