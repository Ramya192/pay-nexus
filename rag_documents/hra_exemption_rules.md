# HRA Exemption Calculation Rules

**Compiled from public secondary sources (cleartax.in, and others), cross-checked against multiple
sources — NOT the verbatim statute text of Section 10(13A)/Rule 2A.** Old regime only; HRA is fully
taxable under the new regime (see `new_vs_old_tax_regime_faqs.md`'s Q4).

## The formula: least of three amounts

The HRA exemption is whichever of these three is **smallest**:

1. **Actual HRA received** from the employer during the period.
2. **50% of salary** (metro city — Delhi, Mumbai, Chennai, Kolkata) or **40% of salary**
   (non-metro), for the period the employee lived in rented accommodation.
3. **Rent actually paid, minus 10% of salary**, for the same period.

"Salary" here means Basic + Dearness Allowance (DA) only — it does NOT include HRA itself, special
allowance, bonus, or any other component. This matches `agents/payslip_agent.py`'s own stated HRA
exemption formula ("the least of (actual rent paid minus 10% of basic), (50% of basic in a metro
city / 40% elsewhere), (HRA actually received)") — this document is the source those figures should
trace back to.

## Worked example

Basic ₹42,000/month, HRA received ₹16,800/month, rent paid ₹20,000/month, metro city:

1. Actual HRA received: ₹16,800
2. 50% of basic: ₹21,000
3. Rent minus 10% of basic: ₹20,000 − ₹4,200 = ₹15,800

The least of the three is **₹15,800** — that's the exempt portion; the remaining ₹1,000 of HRA
received (₹16,800 − ₹15,800) is taxable.

## Notes

- If no rent is paid at all (living in own or employer-provided accommodation), none of the HRA
  received is exempt — it's fully taxable.
- The metro/non-metro classification depends on where the employee actually resides during the
  period, not the employer's registered office location.
- Rent Receipts/a rental agreement, and the landlord's PAN if annual rent exceeds ₹1,00,000, are
  typically required to substantiate the claim to the employer for TDS purposes.
