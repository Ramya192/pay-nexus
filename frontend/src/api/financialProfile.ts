import { apiClient } from "./client";
import type { EncryptedBlob } from "../crypto/clientEncryption";

export interface FinancialProfileRow {
  ciphertext_b64: string;
  iv_b64: string;
  updated_at: string;
}

/** Persists an already-encrypted financial profile — upserts in place (one row per user). */
export async function saveFinancialProfile(blob: EncryptedBlob): Promise<void> {
  await apiClient.put("/financial-profile", {
    ciphertext_b64: blob.ciphertextB64,
    iv_b64: blob.ivB64,
  });
}

/**
 * Still ciphertext at this point — decrypt with crypto/clientEncryption.ts.
 * Returns null for a fresh account with no profile saved yet (404), rather
 * than throwing — that's an expected state, not an error.
 */
export async function fetchFinancialProfile(): Promise<FinancialProfileRow | null> {
  try {
    const { data } = await apiClient.get<FinancialProfileRow>("/financial-profile");
    return data;
  } catch (err: unknown) {
    const status = (err as { response?: { status?: number } })?.response?.status;
    if (status === 404) return null;
    throw err;
  }
}
