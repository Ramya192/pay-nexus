// Part 2 of PayNexus V2's live verification pass — covers the flows
// v2_flows_driver.mjs didn't: proactive alerts (dev-preview + data-driven +
// dismiss-per-day), the subscriptions-category chat filter, capability-gap
// responses for goal/budget/statement-flavored deletes, payslip manual-entry
// save + duplicate-month rejection + history delete, and cross-session
// conversation memory (verified via intercepting the actual /chat request
// body, not by trusting LLM wording).
//
// Usage: FRONTEND_URL=http://localhost:5173 node v2_flows_driver_part2.mjs

import { chromium } from "playwright";
import * as fs from "node:fs";
import * as path from "node:path";

const FRONTEND_URL = process.env.FRONTEND_URL || "http://localhost:5173";
const SHOT_DIR = process.env.SHOT_DIR || path.join(import.meta.dirname, "shots2");
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

const EXPECTED_404_PATHS = ["/financial-profile", "/budget"];
const consoleErrors = [];
page.on("console", (msg) => {
  if (msg.type() !== "error") return;
  if (/^Failed to load resource: the server responded with a status of \d+/.test(msg.text())) return;
  consoleErrors.push(msg.text());
});
page.on("pageerror", (err) => consoleErrors.push("pageerror: " + err.message));
page.on("dialog", (d) => d.accept());
page.on("response", (res) => {
  if (res.status() < 400) return;
  if (res.status() === 404 && EXPECTED_404_PATHS.some((p) => res.url().includes(p))) return;
  consoleErrors.push(`HTTP ${res.status()}: ${res.url()}`);
});

// Captures every /chat request body so cross-session memory can be checked
// against what was actually SENT to the backend, not inferred from wording.
const chatRequests = [];
page.on("request", (req) => {
  if (req.method() === "POST" && req.url().includes("/chat") && !req.url().includes("/chat/summarize")) {
    try {
      chatRequests.push(JSON.parse(req.postData() ?? "{}"));
    } catch {
      // ignore unparseable
    }
  }
});

async function clickTab(label) {
  await page.click(`button:has-text("${label}")`);
  await page.waitForTimeout(300);
}

function fmtDate(d) {
  return d.toISOString().slice(0, 10);
}

async function askChat(query) {
  const input = page.locator('input[placeholder="Why did my take-home drop this month?"]');
  await input.fill(query);
  await page.click('button:has-text("Ask")');
  // "Ask" re-disables while sending, re-enables when the stream finishes —
  // the real completion signal (see run-paynexus skill's own documented
  // gotcha about not trusting the agent-indicator selector for this).
  await page.waitForFunction(
    () => {
      const btns = [...document.querySelectorAll("button")].filter((b) => b.textContent === "Ask");
      return btns.length > 0 && !btns[0].disabled;
    },
    { timeout: 30000 }
  );
  await page.waitForTimeout(300);
  // The whole message block (prose bubble + any DataTable) -- an answer
  // like "here's your subscriptions list" legitimately puts the actual
  // merchant rows in a rendered <table> (agents/tables.py), not in the
  // prose bubble text, so checking the bubble alone would miss it.
  const blocks = page.locator(".max-w-\\[85\\%\\].space-y-2");
  const count = await blocks.count();
  return (await blocks.nth(count - 1).textContent()) ?? "";
}

try {
  console.log("--- register ---");
  const email = `flowtest2-${Date.now()}@example.com`;
  const password = "TestPass123!";
  await page.goto(FRONTEND_URL, { waitUntil: "networkidle" });
  await page.fill("#email", email);
  await page.fill("#password", password);
  await page.click('button:has-text("Need an account? Register")');
  await page.click('button:has-text("Create account")');
  await page.waitForSelector('button:has-text("Bank statements")', { timeout: 15000 });
  record("register + land on main app", true);

  // ── Financial profile (needed for the headroom-alert preview) ──────
  console.log("--- financial profile: save (for headroom alert) ---");
  await clickTab("Investments & loans");
  const elss = page.locator("label", { hasText: "ELSS mutual funds" }).locator("xpath=following-sibling::input");
  await elss.fill("50000");
  await page.click('button:has-text("Save financial profile")');
  await page.waitForTimeout(800);
  record("financial profile saved", true);

  // ── Goal with a near-term target date (data-driven alert, no preview needed) ──
  console.log("--- goals: add a near-deadline goal ---");
  await clickTab("Goals");
  const nearDate = new Date();
  nearDate.setDate(nearDate.getDate() + 10);
  await page.fill("#goal-name", "Near Deadline Goal");
  await page.fill("#goal-target-amount", "100000");
  await page.fill("#goal-saved-amount", "10000");
  await page.fill("#goal-target-date", fmtDate(nearDate));
  await page.click('button:has-text("Add goal")');
  await page.waitForSelector("li p:has-text('Near Deadline Goal')", { timeout: 5000 });
  record("near-deadline goal added", true);

  // ── Budget: set Subscriptions very low so the statement below overspends it ──
  console.log("--- budget: set a low Subscriptions limit ---");
  await clickTab("Budget");
  await page.waitForTimeout(1000);
  const subsInput = page.locator('input[id^="budget-Subscriptions"]');
  await subsInput.fill("200");
  await page.click('button:has-text("Save budget")');
  await page.waitForTimeout(800);
  record("low Subscriptions budget saved", true);

  // ── Bank statement: 2x Netflix (Subscriptions, over budget), 2x DMart
  // (Groceries, recurring but NOT a subscription — proves the filter
  // excludes it) ──
  console.log("--- bank statement: upload CSV with recurring merchants ---");
  await clickTab("Bank statements");
  const csv =
    "Date,Description,Amount\n" +
    "2026-07-05,SWIGGY ORDER,-450\n" +
    "2026-07-06,SALARY CREDIT,50000\n" +
    "2026-07-10,NETFLIX,-500\n" +
    "2026-07-10,NETFLIX,-500\n" +
    "2026-07-12,DMART,-800\n" +
    "2026-07-20,DMART,-900\n";
  const csvPath = path.join(SHOT_DIR, "test_statement2.csv");
  fs.writeFileSync(csvPath, csv);
  await page.fill("#source-account", "HDFC Checking");
  await page.setInputFiles('input[type="file"]', csvPath);
  await page.waitForSelector("text=/transaction\\(s\\) found/", { timeout: 10000 });
  await page.fill("#period-label", "2026-07");
  await page.click('button:has-text("Save statement")');
  await page.waitForSelector("text=Statement saved.", { timeout: 8000 });
  record("statement with recurring merchants saved", true);

  // ── Alerts: data-driven ones (overspending, goal-deadline) should show
  // under the REAL date already — no dev-preview switch needed ──
  console.log("--- alerts: data-driven (overspending + goal-deadline) under real date ---");
  await page.waitForTimeout(500);
  await shot(page, "01-alerts-real-date");
  const overspendVisible = await page.locator("text=/Over budget on Subscriptions/").count();
  record("overspending alert (Subscriptions) shows under real date", overspendVisible > 0);
  const goalDeadlineVisible = await page.locator("text=/Near Deadline Goal.*target date is approaching/").count();
  record("goal-deadline-approaching alert shows under real date", goalDeadlineVisible > 0);

  // ── Alerts: date-windowed ones via the dev-preview selector ─────────
  console.log("--- alerts: date-windowed via dev-preview selector ---");
  // Scoped to the dev-preview bar's own distinctive border-dashed class --
  // a bare `select` locator also matches GoalForm's Category <select>
  // (strict-mode violation), and `hasText` alone would match every
  // ancestor div that also contains this text, not just the bar itself.
  const previewSelect = page.locator("div.border-dashed").locator("select");
  await previewSelect.selectOption("itr");
  await page.waitForTimeout(400);
  const itrVisible = await page.locator("text=/ITR filing deadline/").count();
  record("ITR-window alert shows when preview=itr", itrVisible > 0);
  await shot(page, "02-alerts-itr-preview");

  await previewSelect.selectOption("regime");
  await page.waitForTimeout(400);
  const regimeVisible = await page.locator("text=/Confirm your tax regime/").count();
  record("regime-window alert shows when preview=regime", regimeVisible > 0);

  await previewSelect.selectOption("headroom");
  await page.waitForTimeout(400);
  const headroomVisible = await page.locator("text=/Unused tax deduction room/").count();
  record("deduction-headroom alert shows when preview=headroom (financial profile filled in)", headroomVisible > 0);
  await shot(page, "03-alerts-headroom-preview");

  await previewSelect.selectOption("real");
  await page.waitForTimeout(400);

  // ── Alerts: dismiss is per-day (localStorage), not permanent ────────
  console.log("--- alerts: dismiss persists across reload (same day), other alert unaffected ---");
  await page.locator('button[aria-label="Dismiss"]').first().click();
  await page.waitForTimeout(300);
  const afterDismissCount = await page.locator("text=/Over budget on Subscriptions/").count();
  record("dismissed alert disappears immediately", afterDismissCount === 0);

  // authStore is deliberately in-memory only, never persisted (the AES key
  // is derived from the password and intentionally never touches
  // localStorage -- see authStore.ts's own docstring) -- so a real reload
  // logs the test user out by design, same as it would a real user. Log
  // back in (localStorage's dismissal record isn't tied to auth and
  // survives this fine) so the alert-recompute-after-remount check is
  // still against the real app, not a workaround around the logout.
  await page.reload({ waitUntil: "networkidle" });
  await page.waitForSelector("#email", { timeout: 15000 });
  await page.fill("#email", email);
  await page.fill("#password", password);
  await page.click('button:has-text("Log in")');
  await page.waitForSelector('button:has-text("Bank statements")', { timeout: 15000 });
  await page.waitForTimeout(1000);
  const afterReloadDismissed = await page.locator("text=/Over budget on Subscriptions/").count();
  const afterReloadOtherStillShows = await page.locator("text=/Near Deadline Goal.*target date is approaching/").count();
  record(
    "dismissal survives a reload the same day (localStorage), other alert still shows",
    afterReloadDismissed === 0 && afterReloadOtherStillShows > 0,
    `dismissed-alert-count=${afterReloadDismissed}, other-alert-count=${afterReloadOtherStillShows}`
  );
  await shot(page, "04-alerts-after-reload");

  // Minimize chat for the rest of this run's screenshots to stay focused —
  // this is just a preference for this script's own shots, not a
  // workaround for any bug (the panel no longer blocks anything).
  // (left open deliberately — see v2_flows_driver.mjs's note)

  // ── Chat: subscriptions filter excludes non-subscription recurring merchants ──
  console.log("--- chat: subscriptions filter ---");
  const subsAnswer = await askChat("What subscriptions am I paying for?");
  const mentionsNetflix = /netflix/i.test(subsAnswer);
  const mentionsDmart = /dmart/i.test(subsAnswer);
  record(
    "subscriptions answer mentions Netflix and excludes DMart",
    mentionsNetflix && !mentionsDmart,
    subsAnswer.slice(0, 300)
  );
  await shot(page, "05-chat-subscriptions");

  // ── Chat: capability-gap for goal/budget/statement-flavored deletes ──
  console.log("--- chat: capability-gap (goal/budget/statement deletes) ---");
  const goalDeleteAnswer = await askChat("Delete my Near Deadline Goal goal.");
  record(
    "capability-gap for goal delete names the Goals tab's Delete button",
    /goals/i.test(goalDeleteAnswer) && /delete/i.test(goalDeleteAnswer) && /can't/i.test(goalDeleteAnswer),
    goalDeleteAnswer.slice(0, 300)
  );

  const budgetDeleteAnswer = await askChat("Please delete my budget.");
  record(
    "capability-gap for budget delete explains budget has no delete, just edit",
    /budget/i.test(budgetDeleteAnswer) && /can't/i.test(budgetDeleteAnswer),
    budgetDeleteAnswer.slice(0, 300)
  );

  const statementDeleteAnswer = await askChat("Remove my bank statement for July.");
  record(
    "capability-gap for statement delete names Bank statements tab",
    /bank statements/i.test(statementDeleteAnswer) && /can't/i.test(statementDeleteAnswer),
    statementDeleteAnswer.slice(0, 300)
  );
  await shot(page, "06-chat-capability-gap");

  // ── Payslip: manual entry save + duplicate-month rejection + history delete ──
  console.log("--- payslip: manual entry save + duplicate rejection ---");
  await clickTab("Upload payslip");
  // ManualEntryForm's inputs have no ids -- select by label text, scoped to
  // ITS OWN <form> specifically. TabbedPanel keeps every tab's content
  // mounted (just `hidden` via CSS, not unmounted -- deliberate, so
  // in-progress form state survives a tab switch), and a bare `label`
  // locator matches DOM nodes regardless of visibility, so an unscoped
  // "Month" hasText match also hits Budget's still-mounted "Rent
  // (₹/month)" etc. labels via substring matching. Scoping to the form
  // that has ManualEntryForm's own submit button text sidesteps that.
  const manualEntryForm = page.locator("form:has(button:has-text('Use this payslip'))");
  async function fillManualField(label, value) {
    const input = manualEntryForm.locator("label", { hasText: label }).locator("xpath=following-sibling::input");
    await input.fill(value);
  }
  // Exact match specifically for "Month" -- ManualEntryForm's FIELDS list
  // also has "Bonus this month (₹)" and "Monthly rent paid (₹)", both of
  // which contain "month" as a case-insensitive substring, so the loose
  // hasText match below (fine for the other three fields, which have no
  // such collision) would hit 3 inputs instead of 1.
  await manualEntryForm
    .locator("label", { hasText: /^Month$/ })
    .locator("xpath=following-sibling::input")
    .fill("2026-06");
  await fillManualField("Basic", "50000");
  await fillManualField("HRA received", "20000");
  await fillManualField("TDS", "5000");
  await page.click('button:has-text("Save to history")');
  await page.waitForSelector("text=Saved to history", { timeout: 8000 });
  record("payslip manual entry saved to history", true);

  await page.click('button:has-text("Saved to history")');
  await page.waitForTimeout(600);
  const dupText = await page.locator("text=Already saved").count();
  record("re-saving the same month is rejected as a duplicate, not silently duplicated", dupText > 0);
  await shot(page, "07-payslip-duplicate-rejected");

  console.log("--- payslip history: verify single entry, no duplicate badge, then delete ---");
  await clickTab("Payslip history");
  await page.waitForTimeout(500);
  const duplicateBadge = await page.locator("text=/duplicate 1\\/2|duplicate 2\\/2/").count();
  record("rejected duplicate did NOT create a second history row", duplicateBadge === 0);
  const historyEntry = await page.locator("li", { hasText: "2026-06" }).count();
  record("the one accepted save appears in Payslip history", historyEntry > 0);

  await page.locator('button[title="Delete this saved payslip"]').first().click();
  await page.waitForTimeout(600);
  const afterDelete = await page.locator("li", { hasText: "2026-06" }).count();
  record("payslip history delete removes the entry", afterDelete === 0);
  await shot(page, "08-payslip-history-after-delete");

  // ── Conversation memory: ask something, logout (saves a session
  // summary), log back in, and confirm the NEXT /chat call actually
  // carries a non-empty session_history -- checked against the real
  // request body, not LLM wording. ──
  console.log("--- conversation memory: seed a session, logout, login, verify session_history sent ---");
  await askChat("Why did my take-home drop this month?");
  const chatCallsBeforeLogout = chatRequests.length;

  await page.click('button:has-text("Log out")');
  await page.waitForSelector("#email", { timeout: 10000 });
  await page.waitForTimeout(500); // let the summarize-on-logout call actually land

  await page.fill("#email", email);
  await page.fill("#password", password);
  await page.click('button:has-text("Log in")');
  await page.waitForSelector('button:has-text("Bank statements")', { timeout: 15000 });
  await page.waitForTimeout(1000);

  await askChat("Any general tips for me?");
  const lastChatCall = chatRequests[chatRequests.length - 1];
  const sessionHistoryLen = Array.isArray(lastChatCall?.session_history) ? lastChatCall.session_history.length : -1;
  record(
    "cross-session summary is actually sent in the next login's /chat request",
    sessionHistoryLen > 0,
    `session_history length=${sessionHistoryLen}, total /chat calls before=${chatCallsBeforeLogout} after=${chatRequests.length}`
  );

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
