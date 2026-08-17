import { apiClient } from "./client";
import type { ParsedTransaction } from "./statement";

export interface ConsentCreateResult {
  consent_id: string;
  webview_url: string; // Setu-hosted page — open this for the user to approve (mobile + OTP + bank selection)
  status: string;
}

/** Starts a new Account Aggregator consent request (Setu sandbox). `vua` is
 * the user's mobile number + AA handle, e.g. "9999999999@setu" — asked
 * inline by the UI, never persisted. */
export async function createConsent(vua: string): Promise<ConsentCreateResult> {
  const { data } = await apiClient.post<ConsentCreateResult>("/aa/consent", { vua });
  return data;
}

export interface ConsentStatusResult {
  consent_id: string;
  status: string;
}

export async function getConsentStatus(consentId: string): Promise<ConsentStatusResult> {
  const { data } = await apiClient.get<ConsentStatusResult>(`/aa/consent/${consentId}`);
  return data;
}

export interface AAFetchResult {
  transactions: ParsedTransaction[];
  skipped_row_count: number;
}

/** Once consent status is ACTIVE — creates a data session, polls Setu
 * directly until it's ready (not the webhook; see backend/api/routes/aa.py's
 * module docstring for why), returns categorized transactions for review.
 * Nothing persisted here — same "parse first, review, then explicitly
 * save" contract as api/statement.ts's parseStatementText. */
export async function fetchViaAA(
  consentId: string,
  sourceAccount: string,
  months = 4
): Promise<AAFetchResult> {
  const { data } = await apiClient.post<AAFetchResult>("/aa/fetch", {
    consent_id: consentId,
    source_account: sourceAccount,
    months,
  });
  return data;
}
