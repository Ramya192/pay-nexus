"""
Agent 1 — Payslip Reasoning. Always GPT-4o, never the local-SLM path — see
PROJECT_CONTEXT.md §2 and §14 ("tax calculation errors directly mislead
users, accuracy over cost"). Sees the user's actual decrypted payslip
values; the only agent that does (§4).
"""

import json

from openai import OpenAI

from agents.state import PayNexusState
from config import config

_client = OpenAI(api_key=config.OPENAI_API_KEY)

_SYSTEM_PROMPT = """You are the Payslip Reasoning Agent inside PayNexus, an Indian payslip \
literacy assistant. You are given one user's actual decrypted payslip components and a \
question about them. Reason step by step over:
- Basic, HRA, Special Allowance, PF (employee + employer), Professional Tax, TDS, Bonus, Reimbursements
- HRA exemption: the least of (actual rent paid minus 10% of basic), (50% of basic in a metro \
  city / 40% elsewhere), (HRA actually received)
- Old vs. new tax regime comparison for this specific salary structure
- Bonus tax impact, Form 16 Part A/B reconciliation, month-on-month pay change

Be specific with rupee figures wherever the payslip data supports it. If a figure can't be \
computed from what's given, say what additional input is needed rather than guessing.

Respond with a JSON object: {"explanation": string, "component_breakdown": object, \
"follow_up_suggestions": array of strings}."""


def payslip_agent_node(state: PayNexusState) -> dict:
    payslip_data = state.get("payslip_data") or {}
    if not payslip_data:
        return {
            "payslip_response": json.dumps(
                {
                    "explanation": "No payslip is attached to this session yet — upload or "
                    "enter one to get a component breakdown.",
                    "component_breakdown": {},
                    "follow_up_suggestions": ["Upload a payslip to get started."],
                }
            )
        }

    user_prompt = (
        f"Payslip data (JSON): {json.dumps(payslip_data)}\n\nQuestion: {state['user_query']}"
    )

    response = _client.chat.completions.create(
        model=config.PAYSLIP_AGENT_MODEL,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        response_format={"type": "json_object"},
    )
    return {"payslip_response": response.choices[0].message.content or "{}"}
