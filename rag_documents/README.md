# RAG source documents

Drop the source files for the Regulatory Intelligence Agent's index here as
`.pdf`, `.txt`, or `.md`. Per `PROJECT_CONTEXT.md` §5, that's:

1. Income Tax Act 1961 — key sections (80C, 80D, 80CCD, 10(13A), 10(14), 192, 194) — `it_act_key_sections.md`
2. Budget 2024-25 Finance Bill highlights — `budget_2024-25_highlights.txt`
3. Budget 2025-26 Finance Bill highlights — `budget_2025-26_highlights.txt`
4. New tax regime vs. old regime comparison (FY2024-25 onwards) — `new_vs_old_tax_regime_faqs.md`
5. EPFO circulars — PF wage ceiling, VPF rules — `epfo_employer_information_booklet.txt`
6. State-wise Professional Tax slabs (Telangana, Maharashtra, Karnataka, Tamil Nadu) — `professional_tax_state_slabs.md`
7. HRA exemption calculation rules — `hra_exemption_rules.md`
8. Standard deduction history and current limits — `standard_deduction_history.md`
9. Form 16 Part A and Part B structure explanation — `form_16_structure.md`
10. TDS on salary — Section 192 detailed guide — `it_act_key_sections.md` / `tds_compliance_faqs.md`

All 10/10 populated (Aug 2026) — see README.md's "RAG made visible, evaluated, and the corpus
finished" section for how: `incometaxindia.gov.in`/`indiacode.nic.in` block automated fetching, so
items 1–2, 6–9 are compiled from secondary sources (cleartax.in and others), cross-checked and
clearly labeled as such, rather than verbatim primary-source text.

Whenever any file here changes, rebuild the index from `backend/`:

```bash
python -m rag.build_index
```

...and re-run the eval harness (`python -m rag.eval`) to catch any regression before trusting the
rebuilt index — that first run against the original 4-doc corpus is what caught a real bug (a stale
figure in one of these documents outranking the current one), not a formality.
