# Standard Deduction — History and Current Limits

**Compiled from public secondary sources (cleartax.in, angelone.in, newsonair.gov.in press
releases), cross-checked across multiple sources and against `tax_slabs.py`'s current constants —
NOT the verbatim statute text of Section 16(ia).**

## What it is

A flat deduction from gross salary, applied automatically (no receipts or proof of expense needed)
before computing taxable income — distinct from HRA (Section 10(13A), needs actual rent paid) and
from Chapter-VIA deductions like 80C (needs actual investments).

## Timeline

| Period | Limit | Note |
|---|---|---|
| Pre-2005 | ₹30,000 or 40% of salary (whichever lower), ₹20,000 above ₹5L income | Original "standard deduction" |
| FY 2005-06 – FY 2017-18 | ₹0 | Removed entirely in Budget 2005 |
| FY 2018-19 | ₹40,000 | Reintroduced in Budget 2018, replacing transport + medical reimbursement allowances |
| FY 2019-20 onward (old regime) | ₹50,000 | Raised in Budget 2019 |
| FY 2023-24 (new regime) | ₹50,000 | Extended to the new regime for the first time (Budget 2023) |
| **FY 2024-25 onward (new regime only)** | **₹75,000** | Raised in Budget 2024; **old regime stayed at ₹50,000** — this is the split PayNexus's own `tax_slabs.py` encodes (`_OLD_REGIME_STANDARD_DEDUCTION = 50_000`, `_NEW_REGIME_STANDARD_DEDUCTION = 75_000`) |

## Currently (FY 2025-26)

- **New regime**: ₹75,000
- **Old regime**: ₹50,000

This is exactly the split behind `new_vs_old_tax_regime_faqs.md`'s editorial note — that document's
own Q5 states the pre-Budget-2024 ₹50,000-for-both figure, now superseded for the new regime.
