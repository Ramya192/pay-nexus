import { apiClient } from "./client";
import type { EncryptedBlob } from "../crypto/clientEncryption";

export interface PayslipSaveResult {
  id: string;
  month: string;
  created_at: string;
}

/** Throws with `.response.status === 409` (see isDuplicatePayslipError below)
 * if a payslip for this month is already saved — the server checks by
 * month, the one payslip field it ever sees in plaintext (§4). */
export async function savePayslip(month: string, blob: EncryptedBlob): Promise<PayslipSaveResult> {
  const { data } = await apiClient.post<PayslipSaveResult>("/payslip/save", {
    month,
    ciphertext_b64: blob.ciphertextB64,
    iv_b64: blob.ivB64,
  });
  return data;
}

/** True for the "a payslip for this month is already saved" conflict —
 * callers use this to show an informative "already saved" state instead of
 * a red error. */
export function isDuplicatePayslipError(err: unknown): boolean {
  return (err as { response?: { status?: number } })?.response?.status === 409;
}

/** Deletes one saved snapshot — used by the Payslip history panel's
 * per-row delete button and its "Remove duplicates" cleanup action.
 * Deliberately not callable from chat/agents (§ security note in
 * backend/api/routes/payslip.py) — only this explicit, user-clicked path. */
export async function deleteSnapshot(id: string): Promise<void> {
  await apiClient.delete(`/payslip/snapshots/${id}`);
}

export interface SessionSummaryRow {
  id: string;
  ciphertext_b64: string;
  iv_b64: string;
  created_at: string;
}

/** Still ciphertext at this point — decrypt with crypto/clientEncryption.ts before use. */
export async function fetchHistory(): Promise<SessionSummaryRow[]> {
  const { data } = await apiClient.get<SessionSummaryRow[]>("/payslip/history");
  return data;
}

/** Persists an already-encrypted Level 2 summary (see api/chat.ts's summarizeSession). */
export async function saveSessionSummary(blob: EncryptedBlob): Promise<void> {
  await apiClient.post("/payslip/session-summary", {
    ciphertext_b64: blob.ciphertextB64,
    iv_b64: blob.ivB64,
  });
}

/**
 * Turns PDF-extracted text (see components/PayslipUploader/PDFParser.tsx)
 * into structured fields matching ManualEntryForm's shape. The PDF itself
 * never reaches the server — only the text already extracted client-side.
 */
export async function parsePayslipText(text: string): Promise<Record<string, unknown>> {
  const { data } = await apiClient.post<{ fields: Record<string, unknown> }>("/payslip/parse", {
    text,
  });
  return data.fields;
}

export interface PayslipSnapshotRow {
  id: string;
  month: string;
  ciphertext_b64: string;
  iv_b64: string;
  created_at: string;
}

/**
 * Every saved payslip snapshot, ciphertext included — NOT the same as
 * fetchHistory() above, which (despite the similar-sounding name) returns
 * compressed session summaries, not payslip snapshots. Decrypt each row
 * with crypto/clientEncryption.ts before use.
 */
export async function fetchSnapshots(): Promise<PayslipSnapshotRow[]> {
  const { data } = await apiClient.get<PayslipSnapshotRow[]>("/payslip/snapshots");
  return data;
}
