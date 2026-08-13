import { apiClient } from "./client";
import type { EncryptedBlob } from "../crypto/clientEncryption";

export async function savePayslip(month: string, blob: EncryptedBlob): Promise<void> {
  await apiClient.post("/payslip/save", {
    month,
    ciphertext_b64: blob.ciphertextB64,
    iv_b64: blob.ivB64,
  });
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
