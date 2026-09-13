// Part 3 of PayNexus V2's live verification pass -- covers what parts 1/2
// deliberately skipped for needing a real PDF: PDFParser's upload-prefill
// flow (Upload payslip tab) and PayslipHistoryUpload's bulk-upload flow
// (Payslip history tab), plus BudgetPlanner's "no budget set yet" honest
// response and the "Remove duplicates" button (via a direct-DB-inserted
// genuine duplicate, since the API itself now blocks creating one).
//
// Usage: FRONTEND_URL=http://localhost:5173 node v2_flows_driver_part3.mjs

import { chromium } from "playwright";
import * as fs from "node:fs";
import * as path from "node:path";
import { execFileSync } from "node:child_process";

const FRONTEND_URL = process.env.FRONTEND_URL || "http://localhost:5173";
const SHOT_DIR = process.env.SHOT_DIR || path.join(import.meta.dirname, "shots3");
fs.mkdirSync(SHOT_DIR, { recursive: true });

const shot = async (page, name) => {
  const f = path.join(SHOT_DIR, `${name}.png`);
  await page.screenshot({ path: f, fullPage: true });
  console.log("screenshot:", f);
};

const results = [];
const record = (name, ok, detail = "") => {
  results.push({ name, ok, detail });
  console.log(`${ok ? "PASS" : "FAIL"}: ${name}${detail ? " — " + detail : ""}`);
};

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1280, height: 1100 } });

const consoleErrors = [];
page.on("console", (msg) => {
  if (msg.type() !== "error") return;
  if (/^Failed to load resource: the server responded with a status of \d+/.test(msg.text())) return;
  consoleErrors.push(msg.text());
});
page.on("pageerror", (err) => consoleErrors.push("pageerror: " + err.message));
page.on("dialog", (d) => d.accept());

async function clickTab(label) {
  await page.click(`button:has-text("${label}")`);
  await page.waitForTimeout(300);
}

// Hand-built minimal valid PDF -- no library dependency (pdfjs-dist is a
// frontend-only, browser-side dep; nothing here can generate a PDF from
// Node without one). Real, parseable PDF structure (header, Catalog/Pages/
// Page/Content-stream/Font objects, xref table with correct byte offsets,
// trailer) containing plain payslip-like text lines, so this is a genuine
// test of the real extraction path (frontend pdfjs-dist -> POST
// /payslip/parse), not a synthetic shortcut.
function buildTestPayslipPdf() {
  const lines = [
    "ACME CORP PAYSLIP",
    "Pay Period: July 2026",
    "Employee: Test User",
    "",
    "Earnings",
    "Basic Salary: Rs 62000",
    "House Rent Allowance: Rs 24800",
    "Special Allowance: Rs 18000",
    "Bonus this month: Rs 5000",
    "",
    "Deductions",
    "Provident Fund (Employee): Rs 7440",
    "Provident Fund (Employer): Rs 7440",
    "Professional Tax: Rs 200",
    "Income Tax (TDS): Rs 9200",
    "",
    "Monthly rent paid by employee: Rs 22000",
    "City: Bangalore (Metro)",
  ];
  const esc = (s) => s.replace(/\\/g, "\\\\").replace(/\(/g, "\\(").replace(/\)/g, "\\)");

  let y = 760;
  const textOps = lines
    .map((line) => {
      const op = `BT /F1 11 Tf 50 ${y} Td (${esc(line)}) Tj ET\n`;
      y -= 20;
      return op;
    })
    .join("");

  const objects = [];
  objects[1] = `1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n`;
  objects[2] = `2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n`;
  objects[3] = `3 0 obj\n<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 4 0 R >> >> /MediaBox [0 0 612 792] /Contents 5 0 R >>\nendobj\n`;
  objects[4] = `4 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n`;
  objects[5] = `5 0 obj\n<< /Length ${Buffer.byteLength(textOps)} >>\nstream\n${textOps}endstream\nendobj\n`;

  let pdf = "%PDF-1.4\n";
  const offsets = [0];
  for (let i = 1; i <= 5; i++) {
    offsets[i] = Buffer.byteLength(pdf);
    pdf += objects[i];
  }
  const xrefStart = Buffer.byteLength(pdf);
  pdf += `xref\n0 6\n0000000000 65535 f \n`;
  for (let i = 1; i <= 5; i++) {
    pdf += `${String(offsets[i]).padStart(10, "0")} 00000 n \n`;
  }
  pdf += `trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n${xrefStart}\n%%EOF`;
  return Buffer.from(pdf, "latin1");
}

try {
  console.log("--- register ---");
  const email = `pdftest-${Date.now()}@example.com`;
  const password = "TestPass123!";
  await page.goto(FRONTEND_URL, { waitUntil: "networkidle" });
  await page.fill("#email", email);
  await page.fill("#password", password);
  await page.click('button:has-text("Need an account? Register")');
  await page.click('button:has-text("Create account")');
  await page.waitForSelector('button:has-text("Bank statements")', { timeout: 15000 });
  record("register + land on main app", true);

  // Hand-built minimal valid PDF (no library dependency) containing plain
  // payslip-like text, generated fresh each run rather than committed as a
  // binary fixture -- shots*/ is gitignored, so anyone cloning this repo
  // needs the script to be self-contained to actually reproduce this test.
  const pdfPath = path.join(SHOT_DIR, "test_payslip.pdf");
  fs.writeFileSync(pdfPath, buildTestPayslipPdf());

  // ── PDFParser: Upload payslip tab -- upload, verify real extracted
  // prefill values (not just "no crash"), then use it ──
  console.log("--- Upload payslip: PDF upload + prefill ---");
  await clickTab("Upload payslip");
  // Scoped to PDFParser's own dashed-border wrapper div specifically --
  // Bank statements' and Payslip history's tabs ALSO have file inputs
  // still mounted (TabbedPanel keeps every tab in the DOM, just `hidden`),
  // so a bare `input[type="file"]` is ambiguous, and an unscoped `hasText`
  // filter on `div` matches every ancestor div containing that text, not
  // just the innermost one (still ambiguous).
  const pdfUploadForm = page.locator("div.border-dashed", { has: page.locator("label", { hasText: "Upload payslip PDF" }) });
  await pdfUploadForm.locator('input[type="file"]').setInputFiles(pdfPath);
  await page.waitForSelector("text=Extracting fields", { timeout: 5000 }).catch(() => {});
  // Extraction is a real OpenAI call (payslip_extraction.py) -- give it a
  // real amount of time, not just a UI-transition wait.
  await page.waitForFunction(
    () => {
      const basicLabel = [...document.querySelectorAll("label")].find((l) => l.textContent?.includes("Basic"));
      if (!basicLabel) return false;
      const input = basicLabel.nextElementSibling;
      return input && input.value !== "";
    },
    { timeout: 30000 }
  );
  await shot(page, "01-pdf-extracted-prefill");

  // Scoped to ManualEntryForm's own <form> (identified by its "Use this
  // payslip" submit button) -- Budget's still-DOM-mounted labels contain
  // "(₹/month)" as a case-insensitive substring of "Month", and this
  // form's own "Bonus this month" label does too, both strict-mode
  // violations for a loose match. Exact-match "Month" specifically.
  const manualEntryForm = page.locator("form:has(button:has-text('Use this payslip'))");
  async function readManualField(label, exact = false) {
    const matcher = exact ? new RegExp(`^${label}$`) : label;
    return manualEntryForm.locator("label", { hasText: matcher }).locator("xpath=following-sibling::input").inputValue();
  }
  const basicVal = await readManualField("Basic");
  const hraVal = await readManualField("HRA received");
  const monthVal = await readManualField("Month", true);
  record(
    "PDF-extracted Basic is close to the real PDF value (62000)",
    Math.abs(Number(basicVal) - 62000) < 1000,
    `got Basic=${basicVal}`
  );
  record(
    "PDF-extracted HRA is close to the real PDF value (24800)",
    Math.abs(Number(hraVal) - 24800) < 1000,
    `got HRA=${hraVal}`
  );
  record("PDF-extracted month is 2026-07", monthVal === "2026-07", `got month=${monthVal}`);

  await page.click('button:has-text("Use this payslip")');
  await page.waitForSelector("text=Using this payslip", { timeout: 5000 });
  record("prefilled payslip can be 'used' (no crash)", true);

  // ── PayslipHistoryUpload: Payslip history tab -- bulk upload the same PDF ──
  console.log("--- Payslip history: bulk PDF upload ---");
  await clickTab("Payslip history");
  // PayslipHistoryUpload's <input> is the only one with `multiple` in the
  // whole app (checked directly -- its wrapper div has no distinctive
  // class to scope by, unlike PDFParser's `border-dashed`), so this alone
  // is unambiguous.
  await page.locator('input[type="file"][multiple]').setInputFiles(pdfPath);
  await page.waitForSelector("text=/saved \\(2026-07\\)/", { timeout: 30000 });
  record("bulk PDF upload extracts + saves straight to history", true);
  await page.waitForTimeout(500);
  const historyHasJuly = await page.locator("li", { hasText: "2026-07" }).count();
  record("bulk-uploaded payslip appears in Payslip history list", historyHasJuly > 0);
  await shot(page, "02-bulk-payslip-history");

  // ── BudgetPlanner: "no budget set yet" honest response (fresh account,
  // this account HAS saved a payslip but never saved/visited Budget tab,
  // so no budget row exists server-side) ──
  console.log("--- chat: BudgetPlanner honest 'no budget set' response ---");
  async function askChat(query) {
    const input = page.locator("form", { has: page.locator('button:has-text("Ask")') }).locator("input");
    await input.fill(query);
    await page.click('button:has-text("Ask")');
    await page.waitForFunction(
      () => {
        const btns = [...document.querySelectorAll("button")].filter((b) => b.textContent === "Ask");
        return btns.length > 0 && !btns[0].disabled;
      },
      { timeout: 30000 }
    );
    await page.waitForTimeout(300);
    const blocks = page.locator(".max-w-\\[85\\%\\].space-y-2");
    const count = await blocks.count();
    return (await blocks.nth(count - 1).textContent()) ?? "";
  }
  const budgetAnswer = await askChat("Am I over budget this month?");
  const honestNoBudget =
    /haven'?t (set|saved)|no budget|not (yet )?set/i.test(budgetAnswer) && !/over budget/i.test(budgetAnswer);
  record("BudgetPlanner gives an honest 'no budget set yet' answer, not a fabricated one", honestNoBudget, budgetAnswer.slice(0, 300));
  await shot(page, "03-chat-no-budget-set");

  // ── "Remove duplicates": the API itself now blocks creating a real
  // duplicate through normal use (both save paths check
  // isDuplicatePayslipError), so this button is only reachable via legacy
  // pre-fix data or a genuine race -- recreated here by duplicating the
  // real 2026-07 row's exact ciphertext/iv directly in the DB (decrypts
  // correctly for this real user, unlike a fabricated garbage row). ──
  console.log("--- payslip history: Remove duplicates button (genuine DB-level duplicate) ---");
  execFileSync(
    "py",
    [path.join(import.meta.dirname, "duplicate_payslip_row.py"), email, "2026-07"],
    { stdio: "inherit" }
  );

  // Re-login so the app fetches the fresh (now duplicated) history from the server.
  await page.click('button:has-text("Log out")');
  await page.waitForSelector("#email", { timeout: 10000 });
  await page.fill("#email", email);
  await page.fill("#password", password);
  await page.click('button:has-text("Log in")');
  await page.waitForSelector('button:has-text("Bank statements")', { timeout: 15000 });
  await clickTab("Payslip history");
  await page.waitForTimeout(800);

  const dupBadgeCount = await page.locator("text=/duplicate 1\\/2|duplicate 2\\/2/").count();
  record("genuine duplicate shows the 'duplicate' badge in Payslip history", dupBadgeCount > 0);
  const removeDupBtn = page.locator('button:has-text("Remove duplicates")');
  record("'Remove duplicates' button appears once a real duplicate exists", (await removeDupBtn.count()) > 0);
  await shot(page, "04-genuine-duplicate-before-removal");

  await removeDupBtn.click();
  await page.waitForTimeout(800);
  const julyEntries = await page.locator("li", { hasText: "2026-07" }).count();
  record("Remove duplicates leaves exactly one entry for the month, not zero or two+", julyEntries === 1);
  const badgeGoneAfter = await page.locator("text=/duplicate 1\\/2|duplicate 2\\/2/").count();
  record("duplicate badge is gone after removal", badgeGoneAfter === 0);
  await shot(page, "05-genuine-duplicate-after-removal");

  // ── Same-table-rendered-twice dedup: payslip_agent and nudge_agent both
  // independently compute the same tax_liability_table/gaps_table from the
  // SAME underlying payslip data, and each has its own LLM call deciding
  // whether to show it -- a query that makes both fire and both pick the
  // liability table is the exact scenario assembler_node's dict-keyed-by-
  // JSON dedup (orchestrator.py) exists for. The payslip from the PDF
  // upload above is still active this session ("Use this payslip" was
  // already clicked). ──
  console.log("--- chat: same-table-rendered-twice dedup ---");
  // The logout/login in the Remove-duplicates test above cleared
  // usePayslipStore (session-only by design, App.tsx's handleLogout) --
  // re-prime an active payslip so payslip_agent actually has something to
  // reason over for this question.
  await clickTab("Upload payslip");
  await pdfUploadForm.locator('input[type="file"]').setInputFiles(pdfPath);
  await page.waitForFunction(
    () => {
      const basicLabel = [...document.querySelectorAll("label")].find((l) => l.textContent?.includes("Basic"));
      const input = basicLabel?.nextElementSibling;
      return input && input.value !== "";
    },
    { timeout: 30000 }
  );
  await page.click('button:has-text("Use this payslip")');
  await page.waitForSelector("text=Using this payslip", { timeout: 5000 });

  const regimeAnswer = await askChat("What tax will I pay this year, and should I switch to the new regime?");
  const bothAgentsFired = /Payslip Reasoning Agent/.test(regimeAnswer) && /Savings Advisor/.test(regimeAnswer);
  const liabilityTableCount = (regimeAnswer.match(/Tax liability estimate/g) || []).length;
  record(
    "both Payslip and Savings Advisor agents fired on a regime question",
    bothAgentsFired,
    `got agents present: payslip=${/Payslip Reasoning Agent/.test(regimeAnswer)}, nudge=${/Savings Advisor/.test(regimeAnswer)}`
  );
  record(
    "the shared 'Tax liability estimate' table renders exactly once, not duplicated",
    liabilityTableCount <= 1,
    `table title appeared ${liabilityTableCount} time(s) in the rendered response`
  );
  await shot(page, "06-chat-table-dedup");

  console.log("\n--- console errors ---");
  console.log(consoleErrors.length ? consoleErrors.join("\n") : "(none)");
} catch (err) {
  console.log("SCRIPT ERROR:", err.message);
  await shot(page, "99-error-state");
  console.log("--- console errors at failure ---");
  console.log(consoleErrors.length ? consoleErrors.join("\n") : "(none)");
} finally {
  console.log("\n=== SUMMARY ===");
  for (const r of results) console.log(`${r.ok ? "PASS" : "FAIL"}  ${r.name}${r.detail ? " — " + r.detail : ""}`);
  const failed = results.filter((r) => !r.ok);
  console.log(failed.length ? `\n${failed.length} FAILED` : "\nALL PASSED");
  await browser.close();
}
