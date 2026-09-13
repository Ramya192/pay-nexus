"""One-off test helper: duplicates an existing PayslipSnapshot row for a
given (user email, month) directly in the DB -- bypassing POST /payslip/save's
application-level dedup check on purpose, to recreate the exact scenario
PayslipHistoryList.tsx's "Remove duplicates" button exists for (legacy
pre-fix data, or a genuine race between two concurrent saves), which the
API itself now structurally prevents from happening through normal use.

Copies the EXACT ciphertext/iv bytes from the real existing row, so the
duplicate decrypts perfectly for the real user (same AES key) instead of
being an undecryptable garbage row the frontend would just skip.

Usage: python duplicate_payslip_row.py <email> <month>
"""
import sys

sys.path.insert(0, r"c:\Users\priya\Documents\personal-projects\paynexus-v2\backend")

from sqlalchemy import select

from db.database import SessionLocal
from db.models import PayslipSnapshot, User

email, month = sys.argv[1], sys.argv[2]

db = SessionLocal()
try:
    user = db.scalar(select(User).where(User.email == email))
    assert user, f"no user with email {email}"
    original = db.scalar(
        select(PayslipSnapshot).where(PayslipSnapshot.user_id == user.id, PayslipSnapshot.month == month)
    )
    assert original, f"no existing snapshot for {email} / {month} to duplicate"

    dup = PayslipSnapshot(
        user_id=user.id,
        month=month,
        ciphertext=original.ciphertext,
        iv=original.iv,
    )
    db.add(dup)
    db.commit()
    print(f"OK: duplicated snapshot {original.id} -> {dup.id} for {email}/{month}")
finally:
    db.close()
