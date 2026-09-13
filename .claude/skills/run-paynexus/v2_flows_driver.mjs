// Extended verification driver for PayNexus V2's previously-untested UI
// flows. One-shot script, not a REPL. Registers a fresh user each run.
//
// Usage: FRONTEND_URL=http://localhost:5173 node v2_flows_driver.mjs

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

const results = [];
const record = (name, ok, detail = "") => {
  results.push({ name, ok, detail });
  console.log(`${ok ? "PASS" : "FAIL"}: ${name}${detail ? " — " + detail : ""}`);
};

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1280, height: 1100 } });

const EXPECTED_404_PATHS = ["/financial-profile", "/budget"]; // both legitimately 404 for a fresh account
const consoleErrors = [];
page.on("console", (msg) => {
  if (msg.type() !== "error") return;
  if (/^Failed to load resource: the server responded with a status of \d+/.test(msg.text())) return;
  consoleErrors.push(msg.text());
});
page.on("pageerror", (err) => consoleErrors.push("pageerror: " + err.message));
page.on("dialog", (d) => d.accept()); // auto-accept window.confirm() for deletes
page.on("response", (res) => {
  if (res.status() < 400) return;
  if (res.status() === 404 && EXPECTED_404_PATHS.some((p) => res.url().includes(p))) return;
  consoleErrors.push(`HTTP ${res.status()}: ${res.url()}`);
});

async function clickTab(label) {
  await page.click(`button:has-text("${label}")`);
  await page.waitForTimeout(300);
}

try {
  console.log("--- register ---");
  const email = `flowtest-${Date.now()}@example.com`;
  const password = "TestPass123!";
  await page.goto(FRONTEND_URL, { waitUntil: "networkidle" });
  await page.fill("#email", email);
  await page.fill("#password", password);
  await page.click('button:has-text("Need an account? Register")');
  await page.click('button:has-text("Create account")');
  await page.waitForSelector('button:has-text("Bank statements")', { timeout: 15000 });
  record("register + land on main app", true);
  await shot(page, "01-registered");

  // Chat panel is left open (its default) deliberately, unlike earlier
  // runs of this script -- it used to have to be minimized here to avoid
  // its ~520px floating width covering right-side controls (a goal's
  // Delete/"Update progress" buttons) on this 1280px viewport. App.tsx now
  // reserves a matching right-hand margin on <main> while the panel is
  // open (chatWidgetUiStore.ts), so this script proceeding with it open is
  // itself the regression check for that fix.

  // ── Financial profile (Investments & loans) ────────────────────────
  console.log("--- financial profile: save ---");
  await clickTab("Investments & loans");
  const elss = page.locator("label", { hasText: "ELSS mutual funds" }).locator("xpath=following-sibling::input");
  await elss.fill("50000");
  const ppf = page.locator("label", { hasText: "PPF contribution" }).locator("xpath=following-sibling::input");
  await ppf.fill("30000");
  await page.click('button:has-text("Save financial profile")');
  await page.waitForTimeout(1000);
  await shot(page, "02-financial-profile-saved");
  record("financial profile: fill + save (no crash)", true);

  // ── Goals: add two, delete one, keep one for persistence check ─────
  console.log("--- goals: add ---");
  await clickTab("Goals");
  await page.fill("#goal-name", "Goa Trip");
  await page.fill("#goal-target-amount", "80000");
  await page.fill("#goal-saved-amount", "20000");
  await page.click('button:has-text("Add goal")');
  // Scoped to the goal-name <p>, not a bare text search -- "Emergency Fund"
  // below is ALSO a value in the (hidden) category <select>'s options, so a
  // plain `text=` locator matches that too.
  await page.waitForSelector("li p:has-text('Goa Trip')", { timeout: 5000 });
  record("goal 1 added and listed", true);

  await page.fill("#goal-name", "Emergency Fund");
  await page.fill("#goal-target-amount", "200000");
  await page.click('button:has-text("Add goal")');
  await page.waitForSelector("li p:has-text('Emergency Fund')", { timeout: 5000 });
  record("goal 2 added and listed", true);
  await shot(page, "03-goals-added");

  console.log("--- goals: update progress ---");
  const goaCard = page.locator("li", { hasText: "Goa Trip" });
  await goaCard.locator('button:has-text("Update progress")').click();
  const progressInput = goaCard.locator('input[type="number"]');
  await progressInput.fill("35000");
  await goaCard.locator('button:has-text("Save")').click();
  await page.waitForTimeout(800);
  const updatedText = await goaCard.textContent();
  record("goal update progress", updatedText?.includes("35,000") ?? false, updatedText ?? "");

  console.log("--- goals: delete one ---");
  const efCard = page.locator("li", { hasText: "Emergency Fund" });
  await efCard.locator('button:has-text("Delete")').click();
  await page.waitForTimeout(800);
  const stillThere = await page.locator("li p:has-text('Emergency Fund')").count();
  record("goal delete removes it from the list", stillThere === 0);
  await shot(page, "04-goals-after-delete");

  // ── Budget: verify suggested prefill, then save ─────────────────────
  console.log("--- budget: suggested prefill + save ---");
  await clickTab("Budget");
  await page.waitForTimeout(1000);
  const rentInput = page.locator('input[id^="budget-Rent"]');
  const rentValue = await rentInput.inputValue();
  record("budget suggested prefill populated a value", rentValue !== "" && Number(rentValue) > 0, `Rent=${rentValue}`);
  await rentInput.fill("15000");
  await page.click('button:has-text("Save budget")');
  await page.waitForSelector("text=Saved", { timeout: 5000 }).catch(() => {});
  await shot(page, "05-budget-saved");
  record("budget save (no crash)", true);

  // ── Bank statement: upload CSV, verify parsed, save, list, delete ───
  console.log("--- bank statement: upload CSV ---");
  await clickTab("Bank statements");
  const csv = "Date,Description,Amount\n2026-07-05,SWIGGY ORDER,-450\n2026-07-06,SALARY CREDIT,50000\n2026-07-10,NETFLIX,-500\n2026-07-10,NETFLIX,-500\n";
  const csvPath = path.join(SHOT_DIR, "test_statement.csv");
  fs.writeFileSync(csvPath, csv);

  await page.fill("#source-account", "HDFC Checking");
  await page.setInputFiles('input[type="file"]', csvPath);
  await page.waitForSelector("text=/transaction\\(s\\) found/", { timeout: 10000 });
  const reviewText = await page.locator("text=/transaction\\(s\\) found/").textContent();
  record("CSV parsed and shown for review", true, reviewText ?? "");
  await shot(page, "06-statement-parsed");

  await page.fill("#period-label", "2026-07");
  await page.click('button:has-text("Save statement")');
  await page.waitForSelector("text=Statement saved.", { timeout: 8000 });
  record("statement saved", true);
  await page.waitForTimeout(500);
  await shot(page, "07-statement-saved");

  console.log("--- bank statement: verify listed, then delete ---");
  const listed = await page.locator("text=/HDFC Checking.*2026-07/").count();
  record("saved statement appears in StatementList", listed > 0);

  await page.locator('button[title="Delete this saved statement"]').first().click();
  await page.waitForTimeout(800);
  const afterDelete = await page.locator("text=/HDFC Checking.*2026-07/").count();
  record("statement delete removes it from the list", afterDelete === 0);
  await shot(page, "08-statement-after-delete");

  // Re-upload one to leave behind for the persistence check below.
  await page.fill("#source-account", "HDFC Checking");
  await page.setInputFiles('input[type="file"]', csvPath);
  await page.waitForSelector("text=/transaction\\(s\\) found/", { timeout: 10000 });
  await page.fill("#period-label", "2026-08");
  await page.click('button:has-text("Save statement")');
  await page.waitForSelector("text=Statement saved.", { timeout: 8000 });
  record("re-saved a statement to check persistence after re-login", true);

  // ── Logout / login persistence ───────────────────────────────────────
  console.log("--- logout ---");
  await page.click('button:has-text("Log out")');
  await page.waitForSelector("#email", { timeout: 10000 });
  record("logout returns to auth screen", true);
  await shot(page, "09-after-logout");

  console.log("--- login again ---");
  await page.fill("#email", email);
  await page.fill("#password", password);
  await page.click('button:has-text("Log in")');
  await page.waitForSelector('button:has-text("Bank statements")', { timeout: 15000 });
  await page.waitForTimeout(1500); // let all the decrypt-on-login fetches land
  record("login round-trip succeeds", true);

  console.log("--- verify persistence after re-login ---");
  await clickTab("Goals");
  const goaStillThere = await page.locator("li p:has-text('Goa Trip')").count();
  record("goal persisted across logout/login", goaStillThere > 0);

  await clickTab("Investments & loans");
  await page.waitForTimeout(500);
  const elssAfterLogin = await page.locator("label", { hasText: "ELSS mutual funds" }).locator("xpath=following-sibling::input").inputValue();
  record("financial profile persisted across logout/login", elssAfterLogin === "50000", `got=${elssAfterLogin}`);

  await clickTab("Budget");
  await page.waitForTimeout(500);
  const rentAfterLogin = await page.locator('input[id^="budget-Rent"]').inputValue();
  record("budget persisted across logout/login (not re-suggested)", rentAfterLogin === "15000", `got=${rentAfterLogin}`);

  await clickTab("Bank statements");
  await page.waitForTimeout(500);
  const statementAfterLogin = await page.locator("text=/HDFC Checking.*2026-08/").count();
  record("bank statement persisted across logout/login", statementAfterLogin > 0);
  await shot(page, "10-persistence-verified");

  console.log("\n--- console errors ---");
  console.log(consoleErrors.length ? consoleErrors.join("\n") : "(none)");
} catch (err) {
  console.log("SCRIPT ERROR:", err.message);
  await shot(page, "99-error-state");
  console.log("--- console errors at failure ---");
  console.log(consoleErrors.length ? consoleErrors.join("\n") : "(none)");
} finally {
  console.log("\n=== SUMMARY ===");
  for (const r of results) console.log(`${r.ok ? "PASS" : "FAIL"}  ${r.name}`);
  const failed = results.filter((r) => !r.ok);
  console.log(failed.length ? `\n${failed.length} FAILED` : "\nALL PASSED");
  await browser.close();
}
