// Generates real, text-embedded PDF payslips via Playwright's print-to-PDF
// — a genuine PDF the extraction pipeline (pdfjs-dist text extraction +
// gpt-4o-mini structuring) processes identically to a real one, without
// needing an actual scanned document. Used to finally exercise the
// PDF-upload-prefill and bulk-upload flows, previously untested for lack
// of real PDF fixtures.
import { chromium } from "playwright";
import * as fs from "node:fs";
import * as path from "node:path";

const OUT_DIR = path.join(import.meta.dirname, "fixtures");
fs.mkdirSync(OUT_DIR, { recursive: true });

function payslipHtml({ month, monthLabel, basic, hra, specialAllowance, pfEmployee, professionalTax, tds }) {
  return `<!doctype html><html><body style="font-family: Arial, sans-serif; font-size: 13px;">
    <h2>Acme Corp Pvt Ltd — Payslip for ${monthLabel}</h2>
    <p>Employee: Test User &nbsp; Pay Period: ${month}</p>
    <table border="1" cellpadding="6" cellspacing="0" style="border-collapse: collapse; width: 400px;">
      <tr><td>Basic</td><td>₹${basic.toLocaleString("en-IN")}</td></tr>
      <tr><td>HRA</td><td>₹${hra.toLocaleString("en-IN")}</td></tr>
      <tr><td>Special Allowance</td><td>₹${specialAllowance.toLocaleString("en-IN")}</td></tr>
      <tr><td>PF (Employee)</td><td>₹${pfEmployee.toLocaleString("en-IN")}</td></tr>
      <tr><td>Professional Tax</td><td>₹${professionalTax.toLocaleString("en-IN")}</td></tr>
      <tr><td>TDS</td><td>₹${tds.toLocaleString("en-IN")}</td></tr>
    </table>
  </body></html>`;
}

const PAYSLIPS = [
  { file: "payslip_2026-05.pdf", month: "2026-05", monthLabel: "May 2026", basic: 50000, hra: 20000, specialAllowance: 15000, pfEmployee: 6000, professionalTax: 200, tds: 7500 },
  { file: "payslip_2026-06.pdf", month: "2026-06", monthLabel: "June 2026", basic: 50000, hra: 20000, specialAllowance: 15000, pfEmployee: 6000, professionalTax: 200, tds: 7800 },
  { file: "payslip_2026-07.pdf", month: "2026-07", monthLabel: "July 2026", basic: 50000, hra: 20000, specialAllowance: 15000, pfEmployee: 6000, professionalTax: 200, tds: 8000 },
];

const browser = await chromium.launch();
const page = await browser.newPage();
for (const p of PAYSLIPS) {
  await page.setContent(payslipHtml(p));
  const outPath = path.join(OUT_DIR, p.file);
  await page.pdf({ path: outPath });
  console.log("generated:", outPath);
}
// One "bad" file — an unrelated PDF with no discernible pay period, to
// exercise the bulk-upload flow's error/skip path.
await page.setContent(`<!doctype html><html><body><p>This is not a payslip at all, just some random text.</p></body></html>`);
await page.pdf({ path: path.join(OUT_DIR, "not_a_payslip.pdf") });
console.log("generated:", path.join(OUT_DIR, "not_a_payslip.pdf"));
await browser.close();
