# RAG source documents

Drop the source files for the Regulatory Intelligence Agent's index here as
`.pdf`, `.txt`, or `.md`. Per `PROJECT_CONTEXT.md` §5, that's:

1. Income Tax Act 1961 — key sections (80C, 80D, 80CCD, 10(13A), 10(14), 192, 194)
2. Budget 2024-25 Finance Bill highlights
3. Budget 2025-26 Finance Bill highlights
4. New tax regime vs. old regime comparison (FY2024-25 onwards)
5. EPFO circulars — PF wage ceiling, VPF rules
6. State-wise Professional Tax slabs (Telangana, Maharashtra, Karnataka, Tamil Nadu)
7. HRA exemption calculation rules
8. Standard deduction history and current limits
9. Form 16 Part A and Part B structure explanation
10. TDS on salary — Section 192 detailed guide

Once populated, build the index from `backend/`:

```bash
python -m rag.build_index
```

This folder is empty in the scaffold — nothing to index yet.
