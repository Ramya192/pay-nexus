"""
SQLAlchemy ORM models — matching PROJECT_CONTEXT.md §4 and §9.

users               auth (login) + the salt issued at registration that the
                     client re-derives its AES-256-GCM key from.
payslip_snapshots    ciphertext only — POST /payslip/save. The server never
                     holds a plaintext salary figure at rest.
session_summaries    ciphertext, compressed cross-session summaries — what
                     GET /payslip/history hands the Nudge Agent (Agent 3).
                     Plaintext shape, once decrypted client-side, is the
                     JSON documented in PROJECT_CONTEXT.md §6.
bank_statements      ciphertext only — POST /statement/save (SpendingAnalyser,
                     V2). Same growing-log shape as payslip_snapshots; see
                     that class for why. The parsed-and-categorized
                     transaction list is the plaintext (once decrypted
                     client-side), matching models.Transaction.
goals                ciphertext only — POST/PUT /goals (Goal Tracker UI, V2).
                     One row per goal (Trip, Home Loan, ...); no plaintext
                     discriminator field, unlike payslip_snapshots' month or
                     bank_statements' source_account+period_label — see that
                     class's own docstring for why none is needed here.
budgets              ciphertext only — PUT /budget (BudgetPlanner, V2). One
                     row per user, upserted in place — same singleton shape
                     as financial_profiles, not a growing log; a budget is a
                     standing target that gets edited, not a new one every
                     period.

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
    bank_statements: Mapped[list["BankStatement"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    goals: Mapped[list["Goal"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    budget: Mapped["Budget | None"] = relationship(
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


class BankStatement(Base):
    """One saved, parsed-and-categorized bank/credit-card statement upload
    (SpendingAnalyser, V2). Growing-log, same shape as PayslipSnapshot —
    `ciphertext` is the AES-256-GCM blob of the full transaction list
    (models.Transaction, encoded client-side after POST /statement/parse
    returns it), `iv` is the per-encryption nonce.

    `source_account` and `period_label` are the one plaintext discriminator
    pair kept server-side, same reasoning as PayslipSnapshot.month: enough
    to detect a duplicate upload (same account, same statement period) and
    to list statements in the UI, without the server ever seeing a
    transaction description or amount.

    `content_hash` is a second, independent duplicate signal: a SHA-256
    fingerprint of the transaction list itself (date+description+amount,
    deliberately excluding source_account and category — see
    frontend/src/utils/contentHash.ts), computed client-side and sent
    alongside the ciphertext. It exists because source_account/period_label
    alone can't catch the same real statement re-saved under a *different*
    account name (a real gap found in testing) — the server still never
    sees a transaction description or amount, only this one-way hash of
    them, same non-reversibility a password hash relies on. Nullable
    because statements saved before this column existed have no value to
    backfill (recomputing it would mean decrypting their ciphertext
    server-side, which this app never does) — those rows just don't
    participate in hash-based duplicate detection, which is an acceptable
    gap for old data, not a bug.
    """

    __tablename__ = "bank_statements"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True, nullable=False)
    source_account: Mapped[str] = mapped_column(String(100), nullable=False)  # e.g. "HDFC Checking"
    # Widened from String(20) to String(60) — a calendar-aligned bank
    # statement fits "2026-07" easily, but a credit card's own billing
    # cycle (e.g. "16 Jul 2026 to 15 Aug 2026", 26 chars) doesn't, and
    # Postgres hard-fails on overflow rather than silently truncating like
    # MySQL would. See analytics/spending_trends.py's module docstring for
    # why period_label needs to hold a real billing-cycle description, not
    # just "YYYY-MM", in the first place.
    period_label: Mapped[str] = mapped_column(String(60), nullable=False)  # e.g. "2026-07" or "16 Jul 2026 to 15 Aug 2026"
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    iv: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    content_hash: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="bank_statements")


class Goal(Base):
    """One savings goal — Trip, Home Loan, Education, Emergency Fund, etc.
    (Goal Tracker UI, V2). `ciphertext` is the AES-256-GCM blob of
    {name, category, target_amount, target_date, saved_amount} (plaintext
    shape documented in frontend/src/store/goalStore.ts), `iv` is the
    per-encryption nonce.

    Growing-log like PayslipSnapshot/BankStatement (one row per goal, not a
    singleton like FinancialProfile — a user can have several goals at
    once), but with no plaintext discriminator field: a user can have two
    goals with the same name/category (e.g. two separate "Trip" goals), so
    there's nothing here worth exposing server-side for dedup the way
    PayslipSnapshot.month or BankStatement's (source_account, period_label)
    pair are. Editable in place via PUT /goals/{id} (progress toward a goal
    changes over time) rather than only ever appended to — the one growing-
    log table here that also supports update, not just create+delete.

    Read (not written) by the GoalTracker LangGraph agent (agents/
    goal_agent.py) — narrates target-vs-saved progress and, when
    transactions are also on file, compares it against an actual savings
    rate. Live FD/stock price lookups for market-linked goals are still not
    built — every goal is treated as a flat cash target for now.
    """

    __tablename__ = "goals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True, nullable=False)
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    iv: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="goals")


class Budget(Base):
    """Encrypted per-category monthly budget — {category: amount} dict
    (plaintext shape once decrypted client-side; keys match
    categorization/categories.py's CATEGORIES). One row per user, upserted
    in place (PUT /budget), same singleton reasoning as FinancialProfile:
    a budget is a standing target the user edits over time, not a new one
    every period — the periods it gets *checked against* come from
    transactions already saved via BankStatement, not from this table.
    """

    __tablename__ = "budgets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), unique=True, index=True, nullable=False
    )
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    iv: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="budget")
