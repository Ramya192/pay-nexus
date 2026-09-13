// One-off live verification for ManualExpenseEntry.tsx — register a fresh
// user, open the "Add a cash expense" section on the default "Bank
// statements" tab, submit one manual transaction, confirm it saves cleanly
// with no console/network errors. Mirrors driver.mjs's structure.
import { chromium } from "playwright";
import * as fs from "node:fs";
import * as path from "node:path";

const FRONTEND_URL = process.env.FRONTEND_URL || "http://localhost:5173";
const SHOT_DIR = path.join(import.meta.dirname, "shots_manual_entry");
fs.mkdirSync(SHOT_DIR, { recursive: true });

const shot = async (page, name) => {
  const f = path.join(SHOT_DIR, `${name}.png`);
  await page.screenshot({ path: f, fullPage: true });
  console.log("screenshot:", f);
};

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });

const EXPECTED_404_PATHS = ["/financial-profile", "/budget"]; // both legitimately 404 for a fresh account with none saved yet
const consoleErrors = [];
page.on("console", (msg) => {
  if (msg.type() !== "error") return;
  if (/^Failed to load resource: the server responded with a status of \d+/.test(msg.text())) return;
  consoleErrors.push(msg.text());
});
page.on("pageerror", (err) => consoleErrors.push("pageerror: " + err.message));
page.on("response", (res) => {
  if (res.status() < 400) return;
  if (res.status() === 404 && EXPECTED_404_PATHS.some((p) => res.url().includes(p))) return;
  consoleErrors.push(`HTTP ${res.status()}: ${res.url()}`);
});

try {
  console.log("--- nav + register ---");
  await page.goto(FRONTEND_URL, { waitUntil: "networkidle" });
  const uniqueEmail = `manual-entry-e2e-${Date.now()}@example.com`;
  await page.fill("#email", uniqueEmail);
  await page.fill("#password", "TestPass123");
  await page.click('button:has-text("Need an account? Register")');
  await page.click('button:has-text("Create account")');
  // "Bank statements" is the default-active tab (TabbedPanel's initial
  // state) — wait for its own upload-flow text as the "app is ready" signal.
  await page.waitForSelector("text=Optional — upload bank/credit-card statements", { timeout: 15000 });
  await shot(page, "01-bank-statements-tab");

  console.log("--- open Add a cash expense ---");
  await page.click("summary:has-text('Add a cash expense')");
  await shot(page, "02-form-open");

  console.log("--- fill and submit ---");
  await page.fill('input[type="date"]', "2026-09-10");
  await page.fill('input[placeholder="e.g. Vegetable market"]', "SWIGGY ORDER");
  // Amount field is the number input right after the date field, per the
  // component's own field order (date, amount, description, category, account).
  const form = page.locator("form", { has: page.locator('button:has-text("Add expense")') });
  await form.locator('input[type="number"]').fill("450");
  await shot(page, "03-form-filled");

  await page.click('button:has-text("Add expense")');
  await page.waitForSelector('button:has-text("Added")', { timeout: 10000 });
  await shot(page, "04-added");

  console.log("--- confirm it appears in the saved statement list (a new 'Cash' entry) ---");
  const cashEntryVisible = await page
    .waitForSelector("text=Cash", { timeout: 5000 })
    .then(() => true)
    .catch(() => false);
  console.log("Cash entry visible in StatementList:", cashEntryVisible);
  const countAfterFirst = await page.locator("text=/\\(1 transactions?\\)/").count();
  console.log("shows (1 transactions) after first entry:", countAfterFirst > 0);
  await shot(page, "05-statement-list");

  console.log("--- submit a SECOND manual entry, same month — must APPEND, not duplicate the entry ---");
  await page.fill('input[type="date"]', "2026-09-12");
  await page.fill('input[placeholder="e.g. Vegetable market"]', "Auto rickshaw");
  await form.locator('input[type="number"]').fill("80");
  await page.click('button:has-text("Add expense")');
  await page.waitForSelector('button:has-text("Added")', { timeout: 10000 });

  const cashEntryCount = await page.locator("text=/^Cash —/").count();
  const showsTwoTransactions = await page.locator("text=/\\(2 transactions\\)/").count();
  console.log("still exactly one 'Cash —' entry (not duplicated):", cashEntryCount === 1);
  console.log("that one entry now shows (2 transactions):", showsTwoTransactions > 0);
  await shot(page, "06-after-second-entry-appended");

  console.log("--- console/network errors ---");
  console.log(consoleErrors.length ? consoleErrors.join("\n") : "(none)");
  console.log(consoleErrors.length ? "FAIL: errors present" : "PASS");
} catch (err) {
  console.log("SCRIPT ERROR:", err.message);
  await shot(page, "99-error-state");
  console.log("--- console errors at failure ---");
  console.log(consoleErrors.length ? consoleErrors.join("\n") : "(none)");
} finally {
  await browser.close();
}
