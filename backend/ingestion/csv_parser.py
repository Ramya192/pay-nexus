"""CSV bank/credit-card statement ingestion. Plaintext CSV text in (already
read client-side before the request — same trust tier as the PDF path's
extracted text, see statement_extraction.py), structured Transactions out.

No LLM call: a CSV is already row-structured, unlike a PDF's flattened
text, so ingestion/normalize.py's column-alias matching is enough on its
own — mirrors expense-simplifier/ingestion/csv_parser.py's role, adapted to
take already-read text (this backend never receives the file itself,
matching the "PDF/file never reaches the server" rule for both formats)
rather than a file path/buffer.
"""

from __future__ import annotations

import csv
import io

from ingestion.normalize import rows_to_transactions
from models import Transaction


def parse_csv_text(text: str, source_account: str) -> tuple[list[Transaction], list[dict]]:
    reader = csv.DictReader(io.StringIO(text))
    rows = list(reader)
    return rows_to_transactions(rows, source_account)
