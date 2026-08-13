# Income Tax Act 1961 — Key Sections for Salaried Employees

**Compiled from public secondary sources (cleartax.in, bajajfinserv.in, and others), cross-checked
against multiple sources and against this app's own computed constants
(backend/tax_calculations.py, backend/tax_slabs.py) — NOT the verbatim statute text.**
`incometaxindia.gov.in` and `indiacode.nic.in` (the primary/official sources) block automated
fetching, so this document summarizes operative provisions rather than quoting the Act directly.
Figures reflect FY 2025-26 unless noted; verify against the primary Act before relying on this for
filing. Covers the sections PayNexus's own agents reason about most: 80C, 80D, 80CCD, 10(13A),
10(14), 192, 194.

## Section 80C — Deductions for investments and payments (old regime only)

Individuals and HUFs can deduct up to **₹1,50,000 per financial year**, combined across all
eligible items below — not a separate limit per item:

- Life insurance premiums (approved insurers)
- Public Provident Fund (PPF)
- Employee Provident Fund (EPF) — the employee's own contribution
- Equity Linked Savings Scheme (ELSS) mutual funds
- National Savings Certificate (NSC)
- Sukanya Samriddhi Yojana (SSY)
- 5-year tax-saving fixed deposits
- Senior Citizen Savings Scheme (SCSS)
- Home loan principal repayment
- Stamp duty and registration charges on a property purchase
- Tuition fees for up to two children's full-time education

Not available under the new tax regime at all. This matches
`tax_calculations.py`'s `SECTION_80C_LIMIT = 150_000`.

## Section 80CCD — Pension scheme (NPS) contributions

- **80CCD(1B)**: an *additional* ₹50,000 deduction for the employee's own NPS contribution, on top
  of the ₹1,50,000 Section 80C limit (so up to ₹2,00,000 combined) — old regime only.
- **80CCD(2)**: the *employer's* NPS contribution is deductible separately, up to 14% of salary
  (basic + DA) under the new regime, or 10% under the old regime — this is the one Chapter-VIA
  deduction still available under the new regime (see `new_vs_old_tax_regime_faqs.md`'s Q6).

## Section 80D — Health insurance premiums

- Premium for self, spouse, and dependent children: deductible up to **₹25,000/year**
  (₹50,000/year if the individual is a senior citizen, 60+).
- Premium for parents: a **separate** additional cap, ₹25,000/year (₹50,000/year if the parents are
  senior citizens) — on top of the self/family cap above, not combined with it.
- Old regime only.

`tax_calculations.py`'s `compute_80d()` currently only models the self/family cap
(`SECTION_80D_LIMIT_STANDARD = 25_000`, `SECTION_80D_LIMIT_SENIOR = 50_000`) — the separate parents'
bucket described here isn't computed there yet, a known simplification already flagged in that
module's own docstring.

## Section 10(13A) — House Rent Allowance (HRA) exemption

HRA is exempt from tax, up to the least of three amounts (see `hra_exemption_rules.md` for the full
worked calculation) — old regime only; HRA is fully taxable under the new regime.

## Section 10(14) — Special allowances

Certain allowances paid to cover specific employment-related expenses are exempt up to prescribed
limits regardless of regime — e.g. conveyance allowance for commuting, and allowances for
transport/travel on official duty. Distinct from HRA (10(13A)) and from the flat standard deduction
(Section 16(ia)) — this exempts specific allowance components, not a blanket amount.

## Section 192 — TDS on salary

Employers must estimate each employee's total taxable income for the year and deduct tax at source
proportionally from each salary payment, based on that estimate and the employee's chosen regime.
Since FY 2023-24, the new regime is the default for TDS purposes if the employee does not explicitly
communicate a regime choice to the employer in writing (see `new_vs_old_tax_regime_faqs.md`'s Q3).
No TDS is required if estimated annual income doesn't exceed the basic exemption threshold for the
applicable regime.

## Section 194 — TDS on non-salary payments

Distinct from Section 192 — 194 and its sub-sections (194A, 194J, etc.) cover TDS on dividends,
interest, professional fees, and other non-salary payments, not an employee's own paycheck. Included
here only because it's commonly confused with 192; PayNexus's users are salaried employees, so 192 is
almost always the relevant section, not 194.
