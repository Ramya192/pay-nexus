"""
Request/response schemas for GET/PUT /financial-profile. Same ciphertext-
only contract as api/models/payslip.py — `ciphertext_b64`/`iv_b64` are the
AES-256-GCM blob + nonce produced client-side (§4); this file never carries
a plaintext figure.

Plaintext shape (once decrypted client-side), for reference — the server
never sees this shape, only tax_calculations.py operating on the copy the
client sends fresh into each /chat call (same trust tier as payslip_data):
    {
      "elssMutualFunds": number,       # annual investment — 80C
      "ppf": number,                   # annual PPF contribution — 80C
      "otherMutualFunds": number,      # not deduction-relevant, capital-gains context only
      "stocks": number,                # not deduction-relevant, capital-gains context only
      "fdPrincipal": number,
      "fdInterestEarned": number,      # taxable income, not a deduction
      "rdPrincipal": number,
      "rdInterestEarned": number,      # taxable income, not a deduction
      "homeLoanPrincipalPaid": number, # annual — 80C
      "homeLoanInterestPaid": number,  # annual — 24(b), separate from 80C
      "lifeInsurancePremium": number,  # annual — 80C
      "healthInsurancePremium": number,# annual — 80D
      "healthInsuranceForSeniorCitizen": bool,
    }
"""

from pydantic import BaseModel


class FinancialProfileSaveRequest(BaseModel):
    ciphertext_b64: str
    iv_b64: str


class FinancialProfileOut(BaseModel):
    ciphertext_b64: str
    iv_b64: str
    updated_at: str
