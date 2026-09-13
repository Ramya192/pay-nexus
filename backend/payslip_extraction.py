"""
Turns raw text extracted from a payslip PDF into the same structured field
shape ManualEntryForm collects manually — backs POST /payslip/parse.

The PDF itself never reaches the server: frontend/.../PDFParser.tsx extracts
text client-side (pdfjs-dist) and only that text is sent here. Same trust
tier as payslip_data in /chat (§4) — this endpoint sees plaintext, exactly
like the Payslip Reasoning agent already does once a payslip is in an
active session. Nothing here is persisted; the extracted fields only
pre-fill a form the user still reviews and can edit before "Use this
payslip" actually puts them in session state.

Not a fifth agent in the §2 sense (no LangGraph node, no place in
PayNexusState) — it's a one-shot utility call, same pattern as
compression/context_compressor.py.
"""

import json

from openai import OpenAI

from config import config

_client = OpenAI(api_key=config.OPENAI_API_KEY)

# Matches ManualEntryForm.tsx's FIELDS keys exactly, plus isMetro — no
# remapping needed between what this returns and what the form expects.
_FIELDS = (
    "month",
    "basic",
    "hra",
    "specialAllowance",
    "pfEmployee",
    "pfEmployer",
    "professionalTax",
    "tds",
    "bonus",
    "rentPaid",
)

_SYSTEM_PROMPT = f"""Extract payslip fields from raw text pulled from a payslip PDF. Indian \
payslips vary widely in layout and terminology across employers — match on meaning, not exact \
label text (e.g. "Basic Pay"/"Basic Salary" both mean "basic"; "House Rent Allowance" means \
"hra"; "Provident Fund"/"EPF" means pfEmployee; "Income Tax"/"TDS" means tds).

Respond with a JSON object using exactly these keys: {", ".join(_FIELDS)} (numbers, not
strings; "month" as YYYY-MM if a pay period is stated), and "isMetro" (boolean — true unless the
text clearly names a non-metro city). Omit any key you cannot confidently find — never guess or
fabricate a figure just to fill the object out. An incomplete result the user finishes by hand is
far better than a wrong one they don't notice."""


def extract_payslip_fields(text: str) -> dict:
    response = _client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            # Payslips are a page or two — cap defensively rather than blow
            # past a context limit on a mis-extracted wall of PDF cruft.
            {"role": "user", "content": text[:8000]},
        ],
        response_format={"type": "json_object"},
    )
    parsed = json.loads(response.choices[0].message.content or "{}")
    if not isinstance(parsed, dict):
        return {}
    return {k: v for k, v in parsed.items() if k in _FIELDS or k == "isMetro"}
