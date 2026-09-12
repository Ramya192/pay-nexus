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
11. Code on Wages (Central) Rules, 2026 — Form V payslip format, 50% wage rule — `code_on_wages_payslip_rules_2026.md`

All 10/10 populated (Aug 2026) — see README.md's "RAG made visible, evaluated, and the corpus
finished" section for how: `incometaxindia.gov.in`/`indiacode.nic.in` block automated fetching, so
items 1–2, 6–9 are compiled from secondary sources (cleartax.in and others), cross-checked and
clearly labeled as such, rather than verbatim primary-source text.

Item 11 added 2026-09-12 after a real, live gap: a user asked about 2026 payslip-format rules and
got a confidently wrong "no such rules exist" answer — the rules are real (notified 8 May 2026) but
the regulatory agent's domain-restricted live web-search fallback (see `agents/regulatory_agent.py`'s
module docstring) failed to surface them from `labour.gov.in`. Rather than keep tuning an inherently
unreliable live search for something this important, it's curated here directly — same pattern as
items 1–2 and 6–9. Also prompted a general hardening (same date, see `agents/regulatory_agent.py`'s
`_WEB_SEARCH_MISS_SENTINEL`): the web-search fallback no longer caches a genuine "couldn't find a
clear answer" result as if it were a confirmed fact — that would have let a bad answer entrench
itself in the fast local-RAG path for the full cache TTL instead of self-correcting. This document is
the durable fix for a real gap the automated fallback missed; a fresh miss on a *different* new rule
in the future will still get an honest "couldn't find it" from the app rather than a wrong confident
answer, but reaching the same fast, always-correct state THAT reliably still means adding a curated
document here, by hand, once the fact is verified — there is no way to fully automate "notice a novel
government rule the moment it's notified and trust it unverified," and this app's whole design
philosophy (see `PROJECT_CONTEXT.md`) is to never guess on regulatory figures.

Whenever any file here changes, rebuild the index from `backend/`:

```bash
python -m rag.build_index
```

...and re-run the eval harness (`python -m rag.eval`) to catch any regression before trusting the
rebuilt index — that first run against the original 4-doc corpus is what caught a real bug (a stale
figure in one of these documents outranking the current one), not a formality.
