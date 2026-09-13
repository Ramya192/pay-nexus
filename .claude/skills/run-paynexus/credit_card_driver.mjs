// Live verification for CreditCardStatementUploader.tsx — register a fresh
// user, switch the Bank statements tab to "Credit card statement", upload a
// billing-cycle CSV crossing a month boundary, set a due date in a THIRD
// month, save, confirm both the itemized entry AND the synthetic payment
// entry persist as two separate, correctly-labeled StatementList rows.
import { chromium } from "playwright";
import * as fs from "node:fs";
import * as path from "node:path";

const FRONTEND_URL = process.env.FRONTEND_URL || "http://localhost:5173";
const SHOT_DIR = path.join(import.meta.dirname, "shots_credit_card");
fs.mkdirSync(SHOT_DIR, { recursive: true });
const CSV_PATH = path.join(import.meta.dirname, "fixtures", "cc_statement.csv");

const shot = async (page, name) => {
  const f = path.join(SHOT_DIR, `${name}.png`);
  await page.screenshot({ path: f, fullPage: true });
  console.log("screenshot:", f);
};

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });

const EXPECTED_404_PATHS = ["/financial-profile", "/budget"];
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
  const uniqueEmail = `cc-e2e-${Date.now()}@example.com`;
  await page.fill("#email", uniqueEmail);
  await page.fill("#password", "TestPass123");
  await page.click('button:has-text("Need an account? Register")');
  await page.click('button:has-text("Create account")');
  await page.waitForSelector("text=Optional — upload bank/credit-card statements", { timeout: 15000 });

  console.log("--- switch to Credit card statement ---");
  await page.click('button:has-text("Credit card statement")');
  await shot(page, "01-cc-tab-active");

  console.log("--- name the card, upload the CSV ---");
  await page.fill("#cc-source-account", "HDFC Credit Card");
  // Both uploaders stay mounted (StatementUploader hidden via CSS, not
  // unmounted) so there are two file inputs in the DOM — scope to the
  // genuinely visible one, not just the first in document order.
  await page.locator('input[type="file"]:visible').setInputFiles(CSV_PATH);
  await page.waitForSelector("text=/transaction\\(s\\) found/", { timeout: 10000 });
  await shot(page, "02-parsed-review");

  console.log("--- set billing cycle + due date, save ---");
  const periodInput = page.locator("#cc-period-label");
  await periodInput.fill("");
  await periodInput.fill("20 Aug 2026 to 19 Sep 2026");
  await page.fill("#cc-due-date", "2026-10-05"); // due date in a THIRD month, distinct from both itemized transaction months
  await shot(page, "03-period-and-due-date-set");

  await page.click('button:has-text("Save statement")');
  await page.waitForSelector("text=Statement and payment record both saved.", { timeout: 15000 });
  await shot(page, "04-saved");

  console.log("--- confirm both entries exist, correctly labeled ---");
  const itemizedVisible = await page
    .waitForSelector("text=/HDFC Credit Card — 20 Aug 2026 to 19 Sep 2026/", { timeout: 5000 })
    .then(() => true)
    .catch(() => false);
  const paymentVisible = await page
    .waitForSelector("text=/HDFC Credit Card — Bill Payment — 2026-10/", { timeout: 5000 })
    .then(() => true)
    .catch(() => false);
  console.log("itemized entry visible (billing-cycle label):", itemizedVisible);
  console.log("payment entry visible (due-date month label):", paymentVisible);
  const paymentTxnCount = await page.locator("text=/HDFC Credit Card — Bill Payment.*\\(1 transactions?\\)/").count();
  console.log("payment entry has exactly 1 transaction:", paymentTxnCount > 0);
  await shot(page, "05-statement-list-both-entries");

  console.log("--- intercept the real /chat request body to confirm the flags reach the agents ---");
  let chatBody = null;
  page.on("request", (req) => {
    if (req.url().includes("/chat") && req.method() === "POST") {
      try {
        chatBody = JSON.parse(req.postData() || "{}");
      } catch {
        /* ignore */
      }
    }
  });
  await page
    .locator("form", { has: page.locator('button:has-text("Ask")') })
    .locator("input")
    .fill("where is most of my money going this month?");
  await page.click('button:has-text("Ask")');
  await page.waitForSelector('button:has-text("Ask"):not([disabled])', { timeout: 40000 });

  const txns = chatBody?.transactions || [];
  const itemizedRow = txns.find((t) => t.description === "AMAZON.IN");
  const paymentRow = txns.find((t) => t.description === "Credit Card Bill Payment");
  console.log("itemized row counts_toward_net_savings === false:", itemizedRow?.counts_toward_net_savings === false);
  console.log("payment row counts_toward_category_spend === false:", paymentRow?.counts_toward_category_spend === false);
  console.log("payment row date is the due date (2026-10-05):", paymentRow?.date === "2026-10-05");
  console.log("payment row amount matches itemized total (-3100):", paymentRow?.amount === -3100);
  await shot(page, "06-after-chat-question");

  console.log("--- console/network errors ---");
  console.log(consoleErrors.length ? consoleErrors.join("\n") : "(none)");
  const allGood =
    itemizedVisible &&
    paymentVisible &&
    paymentTxnCount > 0 &&
    consoleErrors.length === 0 &&
    itemizedRow?.counts_toward_net_savings === false &&
    paymentRow?.counts_toward_category_spend === false &&
    paymentRow?.date === "2026-10-05" &&
    paymentRow?.amount === -3100;
  console.log(allGood ? "PASS" : "FAIL");
} catch (err) {
  console.log("SCRIPT ERROR:", err.message);
  await shot(page, "99-error-state");
  console.log("--- console errors at failure ---");
  console.log(consoleErrors.length ? consoleErrors.join("\n") : "(none)");
} finally {
  await browser.close();
}
