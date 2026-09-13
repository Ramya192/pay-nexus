// Live verification for the two previously-untested-for-lack-of-real-PDFs
// flows: PDFParser.tsx (single PDF -> prefill -> review -> "Use this
// payslip") and PayslipHistoryUpload.tsx (bulk upload -> straight to
// encrypted history, no review). Uses real, text-embedded PDFs generated
// by generate_payslip_pdfs.mjs — the extraction pipeline (pdfjs-dist +
// gpt-4o-mini) processes these identically to a real scanned payslip.
import { chromium } from "playwright";
import * as fs from "node:fs";
import * as path from "node:path";

const FRONTEND_URL = process.env.FRONTEND_URL || "http://localhost:5173";
const SHOT_DIR = path.join(import.meta.dirname, "shots_pdf_upload");
fs.mkdirSync(SHOT_DIR, { recursive: true });
const FIX = (name) => path.join(import.meta.dirname, "fixtures", name);

const shot = async (page, name) => {
  const f = path.join(SHOT_DIR, `${name}.png`);
  await page.screenshot({ path: f, fullPage: true });
  console.log("screenshot:", f);
};

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1280, height: 1000 } });

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
  // Deliberately triggered by this script's own duplicate-file test case
  // (uploading payslip_2026-05.pdf twice) — the frontend correctly catches
  // and displays this as "already saved", not a real failure.
  if (res.status() === 409 && res.url().includes("/payslip/save")) return;
  consoleErrors.push(`HTTP ${res.status()}: ${res.url()}`);
});

try {
  console.log("--- nav + register ---");
  await page.goto(FRONTEND_URL, { waitUntil: "networkidle" });
  const uniqueEmail = `pdf-e2e-${Date.now()}@example.com`;
  await page.fill("#email", uniqueEmail);
  await page.fill("#password", "TestPass123");
  await page.click('button:has-text("Need an account? Register")');
  await page.click('button:has-text("Create account")');
  // "Bank statements" is the default-active tab (not "Upload payslip" —
  // the tab order changed in an earlier UI update); switch explicitly.
  await page.waitForSelector("text=Optional — upload bank/credit-card statements", { timeout: 15000 });
  await page.click('button:has-text("Upload payslip")');
  await page.waitForSelector("text=Upload payslip PDF", { timeout: 5000 });
  await shot(page, "01-landing-upload-tab");

  console.log("=== FLOW 1: PDFParser — single PDF upload, prefill, review, use ===");
  await page.setInputFiles('input[accept="application/pdf"]:visible', FIX("payslip_2026-07.pdf"));
  await page.waitForSelector("text=Extracting fields…", { timeout: 5000 }).catch(() => {});
  // Extraction is a real gpt-4o-mini call — give it real time.
  await page.waitForFunction(
    () => document.querySelector('input[type="month"]')?.value,
    { timeout: 30000 }
  );
  await shot(page, "02-pdf-extracted-prefilled");

  const monthValue = await page.locator('input[type="month"]').inputValue();
  const basicValue = await page
    .locator("label", { hasText: "Basic (₹)" })
    .locator("xpath=following-sibling::input")
    .inputValue();
  console.log("extracted month:", monthValue, "(expected 2026-07)");
  console.log("extracted basic:", basicValue, "(expected 50000)");

  await page.click('button:has-text("Use this payslip")');
  await page.waitForSelector('button:has-text("Using this payslip")', { timeout: 5000 });
  console.log("'Use this payslip' confirmed active");
  await shot(page, "03-pdf-flow-used");

  console.log("=== FLOW 2: PayslipHistoryUpload — bulk upload (3 real + 1 duplicate + 1 bad file) ===");
  await page.click('button:has-text("Payslip history")');
  await page.waitForSelector("text=Upload past payslips", { timeout: 5000 });

  const bulkInput = page.locator('input[accept="application/pdf"][multiple]');
  await bulkInput.setInputFiles([
    FIX("payslip_2026-05.pdf"),
    FIX("payslip_2026-06.pdf"),
    FIX("payslip_2026-05.pdf"), // deliberate duplicate — same month as the first file
    FIX("not_a_payslip.pdf"), // deliberate bad file — no discernible pay period
  ]);

  // Files process sequentially, each a real LLM call — wait generously for
  // all 4 statuses to leave "queued"/"processing…".
  await page.waitForFunction(
    () => {
      const items = Array.from(document.querySelectorAll("li"));
      const relevant = items.filter((li) => /payslip_2026|not_a_payslip/.test(li.textContent || ""));
      return (
        relevant.length === 4 &&
        relevant.every((li) => !/queued|processing/.test(li.textContent || ""))
      );
    },
    { timeout: 60000 }
  );
  await shot(page, "04-bulk-upload-final-statuses");

  const statusTexts = await page.locator("li").allTextContents();
  const relevant = statusTexts.filter((t) => /payslip_2026|not_a_payslip/.test(t));
  console.log("final statuses:");
  relevant.forEach((t) => console.log(" ", t));

  const savedCount = relevant.filter((t) => /saved \(/.test(t)).length;
  const duplicateCount = relevant.filter((t) => /already saved/.test(t)).length;
  const errorCount = relevant.filter((t) => /pay period|Failed/.test(t)).length;
  console.log("saved:", savedCount, "(expected 2)  duplicate:", duplicateCount, "(expected 1)  error/skipped:", errorCount, "(expected 1)");

  console.log("--- console/network errors ---");
  console.log(consoleErrors.length ? consoleErrors.join("\n") : "(none)");
  const allGood =
    monthValue === "2026-07" &&
    basicValue === "50000" &&
    savedCount === 2 &&
    duplicateCount === 1 &&
    errorCount === 1 &&
    consoleErrors.length === 0;
  console.log(allGood ? "PASS" : "FAIL");
} catch (err) {
  console.log("SCRIPT ERROR:", err.message);
  await shot(page, "99-error-state");
  console.log("--- console errors at failure ---");
  console.log(consoleErrors.length ? consoleErrors.join("\n") : "(none)");
} finally {
  await browser.close();
}
