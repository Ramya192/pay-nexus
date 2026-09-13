"""
Ground-truth questions for rag/eval.py — every `expected_source` and
`expected_keywords` value here was verified by hand against the actual
text in rag_documents/ (not guessed/assumed), so a failure means the
pipeline is actually wrong, not that the ground truth is. Extend this file
whenever a new source document is added to the corpus (see
rag_documents/README.md for the 10-topic list) — an eval harness is only
as good as its coverage of what's actually indexed.
"""

from dataclasses import dataclass


@dataclass
class EvalCase:
    question: str
    expected_source: str  # filename in rag_documents/ that should appear in top-k retrieval
    # Facts the generated answer should contain if it's actually grounded.
    # A single entry may be "|"-joined acceptable alternatives (e.g. a date
    # the model might phrase either "1 April 2026" or "April 1, 2026") —
    # any one alternative matching counts that keyword as found. Keep this
    # for genuine phrasing variance only; don't use it to paper over a
    # keyword that's actually wrong.
    expected_keywords: list[str]


EVAL_CASES: list[EvalCase] = [
    EvalCase(
        question="What is the standard deduction under the new tax regime?",
        expected_source="budget_2025-26_highlights.txt",
        expected_keywords=["75,000"],
    ),
    EvalCase(
        question="Up to what income is there no tax payable under the new regime?",
        expected_source="budget_2025-26_highlights.txt",
        expected_keywords=["12 lakh"],
    ),
    EvalCase(
        question="By how much was the TDS threshold on rent increased in Budget 2025-26?",
        expected_source="budget_2025-26_highlights.txt",
        expected_keywords=["6 lakh"],
    ),
    EvalCase(
        question="Can I claim HRA exemption under the new tax regime?",
        expected_source="new_vs_old_tax_regime_faqs.md",
        expected_keywords=["10(13A)"],
    ),
    EvalCase(
        question="Do I need to notify my employer which tax regime I'm choosing?",
        expected_source="new_vs_old_tax_regime_faqs.md",
        expected_keywords=["default"],
    ),
    EvalCase(
        question="What is the Section 87A rebate under the old tax regime?",
        expected_source="new_vs_old_tax_regime_faqs.md",
        expected_keywords=["12,500"],
    ),
    EvalCase(
        question="What is the EPF wage ceiling for mandatory contributions?",
        expected_source="epfo_employer_information_booklet.txt",
        expected_keywords=["15,000"],
    ),
    EvalCase(
        question="What is the statutory EPF employee contribution rate?",
        expected_source="epfo_employer_information_booklet.txt",
        expected_keywords=["12%"],
    ),
    EvalCase(
        # "|"-joined alternatives — the model paraphrases the date order
        # ("April 1, 2026" vs. the source's "1st April 2026"), and a
        # correct answer shouldn't be marked wrong just for that. Any one
        # alternative matching counts the keyword as found.
        question="When does the new Income Tax Act 2025 take over from the 1961 Act for TDS on salary?",
        expected_source="tds_compliance_faqs.md",
        expected_keywords=["1 April 2026|1st April 2026|April 1, 2026|April 1st, 2026"],
    ),
    EvalCase(
        question="Have TDS rates and monetary thresholds changed under the Income Tax Act 2025 transition?",
        expected_source="tds_compliance_faqs.md",
        expected_keywords=["retained|unchanged|not changed|no change|remain the same|same"],
    ),
    # Added once the corpus reached all 10 planned topics (previously 4/10).
    EvalCase(
        question="What is the maximum deduction under Section 80C and what does it cover?",
        expected_source="it_act_key_sections.md",
        expected_keywords=["1,50,000|1.5 lakh|150,000"],
    ),
    EvalCase(
        question="What is the additional NPS deduction under Section 80CCD(1B)?",
        expected_source="it_act_key_sections.md",
        expected_keywords=["50,000"],
    ),
    EvalCase(
        question="How is the HRA exemption amount calculated?",
        expected_source="hra_exemption_rules.md",
        expected_keywords=["least of|smallest"],
    ),
    EvalCase(
        question="Why was the standard deduction removed in 2005 and when was it reintroduced?",
        expected_source="standard_deduction_history.md",
        expected_keywords=["2018|Budget 2018"],
    ),
    EvalCase(
        question="What information does Part A of Form 16 contain?",
        expected_source="form_16_structure.md",
        expected_keywords=["TAN|TRACES"],
    ),
    EvalCase(
        question="Is professional tax paid monthly or half-yearly in Tamil Nadu?",
        expected_source="professional_tax_state_slabs.md",
        expected_keywords=["half-yearly|half yearly"],
    ),
    EvalCase(
        question="By how much did the employer NPS contribution deduction limit increase in Budget 2024-25?",
        expected_source="budget_2024-25_highlights.txt",
        expected_keywords=["14%"],
    ),
]
