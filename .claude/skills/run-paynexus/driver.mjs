// Playwright driver for run-paynexus. One-shot scripted flow, not a REPL —
// tmux isn't available on this Windows/Git Bash setup, and a REPL is only
// useful with something to pipe interactive commands into. Re-run the whole
// script each time; it registers a fresh test user per run, so there's no
// state to reset between runs.
//
// Usage (from this directory, after `npm install`):
//   FRONTEND_URL=http://localhost:5173 node driver.mjs
//
// Requires both dev servers already running — this drives the browser, it
// doesn't launch the app. See SKILL.md's "Run (agent path)" for how to
// start them first.
import { chromium } from "playwright";
import * as fs from "node:fs";
import * as path from "node:path";

const FRONTEND_URL = process.env.FRONTEND_URL || "http://localhost:5173";
const SHOT_DIR = process.env.SHOT_DIR || path.join(import.meta.dirname, "shots");
fs.mkdirSync(SHOT_DIR, { recursive: true });

const shot = async (page, name) => {
  const f = path.join(SHOT_DIR, `${name}.png`);
  await page.screenshot({ path: f, fullPage: true });
  console.log("screenshot:", f);
};

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });

// GET /financial-profile intentionally 404s for a fresh account with no
// saved profile yet (api/routes/financial_profile.py, api/financialProfile.ts
// both treat this as the real "empty" signal, not an error) — but every
// run here registers a brand-new user, so it 404s on EVERY single run, and
// the browser logs its own "Failed to load resource: ... 404" line to the
// console regardless of the app already handling the response gracefully.
// Found as a real, pre-existing false-positive: this script has reported
// FAIL on every run since it was first written, for an endpoint behaving
// exactly as designed — filtered out here by name, not by blanket-ignoring
// all console errors, so an actually broken resource still fails the run.
const EXPECTED_404_PATHS = ["/financial-profile"];

const consoleErrors = [];
page.on("console", (msg) => {
  if (msg.type() !== "error") return;
  // The browser logs this generic line (no URL attached — it's on the
  // Response object, not the console message) for ANY non-2xx XHR/fetch,
  // even ones the app already handles correctly. The response listener
  // below is the precise, URL-aware check for real HTTP failures; this
  // generic duplicate would otherwise fail every run regardless of which
  // endpoint it came from.
  if (/^Failed to load resource: the server responded with a status of \d+/.test(msg.text())) return;
  consoleErrors.push(msg.text());
});
page.on("pageerror", (err) => consoleErrors.push("pageerror: " + err.message));
page.on("response", (res) => {
  if (res.status() < 400) return;
  if (res.status() === 404 && EXPECTED_404_PATHS.some((p) => res.url().includes(p))) return;
  consoleErrors.push(`HTTP ${res.status()}: ${res.url()}`);
});

// Payslip fields keyed by their <label> text — see
// frontend/src/components/PayslipUploader/ManualEntryForm.tsx's FIELDS
// array if these labels ever change.
const PAYSLIP_FIELDS = {
  "Basic (₹)": "50000",
  "HRA received (₹)": "20000",
  "Special Allowance (₹)": "15000",
  "PF — employee (₹)": "6000",
  TDS: "8000",
  "Bonus this month (₹)": "0",
  "Monthly rent paid (₹)": "18000",
};

try {
  console.log("--- nav ---");
  await page.goto(FRONTEND_URL, { waitUntil: "networkidle" });
  await shot(page, "01-landing");

  console.log("--- register ---");
  const uniqueEmail = `e2e-${Date.now()}@example.com`;
  await page.fill("#email", uniqueEmail);
  await page.fill("#password", "TestPass123");
  // AuthScreen defaults to "login" mode — switch to register first.
  await page.click('button:has-text("Need an account? Register")');
  await page.click('button:has-text("Create account")');
  // "Upload payslip" is the TabbedPanel's default-active tab (see
  // frontend/src/components/Dashboard/TabbedPanel.tsx) — replaced the old
  // sidebar's "Your payslip" <h2> when the sidebar became tabs.
  await page.waitForSelector("text=Upload payslip PDF", { timeout: 15000 });
  await shot(page, "02-post-register-main-app");

  console.log("--- enter payslip ---");
  await page.fill('input[type="month"]', "2026-07");
  for (const [label, value] of Object.entries(PAYSLIP_FIELDS)) {
    const input = page.locator("label", { hasText: label }).locator("xpath=following-sibling::input");
    if (await input.count()) await input.fill(value);
  }
  await page.click('button:has-text("Use this payslip")');
  await shot(page, "03-payslip-entered");

  console.log("--- ask a question ---");
  // Scoped to the form containing the "Ask" button rather than matching the
  // input's placeholder text -- the placeholder is just UI copy and
  // shouldn't be load-bearing for a selector (it's changed at least once).
  await page
    .locator("form", { has: page.locator('button:has-text("Ask")') })
    .locator("input")
    .fill("Why did my take-home drop this month?");
  await page.click('button:has-text("Ask")');

  // The agent indicator can resolve before this poll ever catches it —
  // Agent 1 alone often answers in well under a second of wall-clock
  // streaming time. Don't treat a miss here as a failure; the thing that
  // actually matters is the final response landing correctly below.
  const sawIndicator = await page
    .waitForSelector("text=/reasoning/", { timeout: 8000 })
    .then(() => true)
    .catch(() => false);
  console.log("agent indicator caught mid-flight:", sawIndicator, "(often false even on success — see Gotchas)");

  console.log("--- wait for final response ---");
  await page.waitForSelector('button:has-text("Ask"):not([disabled])', { timeout: 30000 });
  await shot(page, "04-final-response");

  console.log("--- console errors ---");
  console.log(consoleErrors.length ? consoleErrors.join("\n") : "(none)");
  console.log(consoleErrors.length ? "FAIL: console errors present" : "PASS");
} catch (err) {
  console.log("SCRIPT ERROR:", err.message);
  await shot(page, "99-error-state");
  console.log("--- console errors at failure ---");
  console.log(consoleErrors.length ? consoleErrors.join("\n") : "(none)");
} finally {
  await browser.close();
}
