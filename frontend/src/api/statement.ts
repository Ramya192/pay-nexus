import { apiClient } from "./client";
import type { EncryptedBlob } from "../crypto/clientEncryption";

export interface ParsedTransaction {
  transaction_id: string;
  date: string;
  description: string;
  amount: number;
  source_account: string;
  category: string | null;
  category_source: string | null;
}

export interface StatementParseResult {
  transactions: ParsedTransaction[];
  skipped_row_count: number;
  truncated_chars: number;
}

/**
 * Turns already-extracted statement text into categorized transaction rows
 * (backend/api/routes/statement.py). Nothing is persisted here — same
 * "parse first, review, then explicitly save" shape as api/payslip.ts's
 * parsePayslipText. The bank statement file itself never reaches the
 * server: PDF text is extracted client-side (utils/pdfText.ts), and CSV
 * text is just the file's own contents read directly.
 */
export async function parseStatementText(
  text: string,
  sourceAccount: string,
  format: "pdf" | "csv"
): Promise<StatementParseResult> {
  const { data } = await apiClient.post<StatementParseResult>("/statement/parse", {
    text,
    source_account: sourceAccount,
    format,
  });
  return data;
}

export interface StatementSaveResult {
  id: string;
  source_account: string;
  period_label: string;
  created_at: string;
}

/** Throws with `.response.status === 409` (see isDuplicateStatementError
 * below) if a statement for this (source_account, period_label) pair is
 * already saved (same dedup shape as payslip.py's month check, §4), OR if
 * `contentHash` matches an already-saved statement under a *different*
 * account name — see utils/contentHash.ts for why that second check
 * exists. Either way, use getErrorDetail(err) to show the server's actual
 * explanation (it names which existing account/period the duplicate is
 * under) rather than a generic message. */
export async function saveStatement(
  sourceAccount: string,
  periodLabel: string,
  blob: EncryptedBlob,
  contentHash: string
): Promise<StatementSaveResult> {
  const { data } = await apiClient.post<StatementSaveResult>("/statement/save", {
    source_account: sourceAccount,
    period_label: periodLabel,
    ciphertext_b64: blob.ciphertextB64,
    iv_b64: blob.ivB64,
    content_hash: contentHash,
  });
  return data;
}

export function isDuplicateStatementError(err: unknown): boolean {
  return (err as { response?: { status?: number } })?.response?.status === 409;
}

/** The backend's own explanation for a 409 (e.g. which existing
 * account/period a duplicate collides with) — falls back to undefined if
 * the error isn't shaped as expected, so callers can still supply a
 * generic message. */
export function getErrorDetail(err: unknown): string | undefined {
  const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  return typeof detail === "string" ? detail : undefined;
}

/** Overwrites a saved statement's ciphertext in place — used to persist a
 * per-row category correction (StatementList.tsx): the caller decrypts the
 * full transaction list, edits one row's category client-side, then
 * re-encrypts the whole list and sends it here. source_account/period_label
 * are untouched — a correction doesn't change the statement's identity. */
export async function updateStatement(id: string, blob: EncryptedBlob): Promise<StatementSaveResult> {
  const { data } = await apiClient.put<StatementSaveResult>(`/statement/${id}`, {
    ciphertext_b64: blob.ciphertextB64,
    iv_b64: blob.ivB64,
  });
  return data;
}

/** Deletes one saved statement — used by the statement list's per-row
 * delete button. Deliberately not callable from chat/agents, same
 * reasoning as api/payslip.ts's deleteSnapshot. */
export async function deleteStatement(id: string): Promise<void> {
  await apiClient.delete(`/statement/${id}`);
}

export interface StatementRow {
  id: string;
  source_account: string;
  period_label: string;
  ciphertext_b64: string;
  iv_b64: string;
  created_at: string;
}

/** Still ciphertext at this point — decrypt with crypto/clientEncryption.ts
 * before use. The plaintext, once decrypted, is a ParsedTransaction[]. */
export async function fetchStatements(): Promise<StatementRow[]> {
  const { data } = await apiClient.get<StatementRow[]>("/statement/list");
  return data;
}
