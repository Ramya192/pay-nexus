"""
SQLAlchemy ORM models — three tables, matching PROJECT_CONTEXT.md §4 and §9.

users               auth (login) + the salt issued at registration that the
                     client re-derives its AES-256-GCM key from.
payslip_snapshots    ciphertext only — POST /payslip/save. The server never
                     holds a plaintext salary figure at rest.
session_summaries    ciphertext, compressed cross-session summaries — what
                     GET /payslip/history hands the Nudge Agent (Agent 3).
                     Plaintext shape, once decrypted client-side, is the
                     JSON documented in PROJECT_CONTEXT.md §6.

Password hashing (login) and AES key derivation (payslip encryption) are
deliberately separate concerns: `hashed_password` authenticates the user;
`encryption_salt` only seeds the client's own PBKDF2 derivation and never
lets the server reconstruct the encryption key itself. Both the hashing and
the salt-generation helpers live in security/ (auth system — not built yet,
see PROJECT_CONTEXT.md §13 Phase 1 item 4).
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, LargeBinary, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.database import Base


def _new_id() -> str:
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)

    # Issued once at registration (POST /auth/register). The client derives
    # its AES key from this salt + the user's password via PBKDF2
    # (100,000 iterations, SHA-256) on every login — the server stores the
    # salt so that derivation is repeatable, never the key itself.
    encryption_salt: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    payslip_snapshots: Mapped[list["PayslipSnapshot"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    session_summaries: Mapped[list["SessionSummary"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    financial_profile: Mapped["FinancialProfile | None"] = relationship(
        back_populates="user", cascade="all, delete-orphan", uselist=False
    )


class PayslipSnapshot(Base):
    """One saved payslip. `ciphertext` is the AES-256-GCM blob produced
    client-side (§4); `iv` is the per-encryption nonce Web Crypto's AES-GCM
    requires and the client must send alongside it to decrypt later.
    """

    __tablename__ = "payslip_snapshots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True, nullable=False)
    month: Mapped[str] = mapped_column(String(20), nullable=False)  # e.g. "2026-07"
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    iv: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="payslip_snapshots")


class SessionSummary(Base):
    """A compressed, encrypted cross-session summary — never a raw payslip.
    Decrypted client-side, its plaintext matches the JSON shape from
    PROJECT_CONTEXT.md §6: payslip_snapshot / key_changes / nudges_given /
    regime_recommendation.
    """

    __tablename__ = "session_summaries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True, nullable=False)
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    iv: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="session_summaries")


class FinancialProfile(Base):
    """Encrypted investments/loans/insurance profile — ELSS & other mutual
    funds, stocks, FDs, RDs, home loan principal+interest, life and health
    insurance premiums. One row per user, upserted in place (PUT
    /financial-profile), not a growing log like PayslipSnapshot — a
    portfolio or a home loan doesn't reset every month the way a payslip
    does, so there's no "history" dimension worth keeping here. Same
    ciphertext-only contract as everything else in this file; the plaintext
    shape (once decrypted client-side) is documented in
    api/models/financial_profile.py, and tax_calculations.py is what turns
    it into exact 80C/80D/24(b) gap figures for the Nudge Agent.
    """

    __tablename__ = "financial_profiles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), unique=True, index=True, nullable=False
    )
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    iv: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="financial_profile")
