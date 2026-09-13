import type { ParsedTransaction } from "../api/statement";

/**
 * A privacy-safe fingerprint of a transaction list's actual content —
 * deliberately excludes source_account (the whole point is catching the
 * same statement re-saved under a DIFFERENT account name — a real gap
 * found in testing: re-uploading the same PDF as "HDFC Checking1" sailed
 * through undetected) and category (categorization can vary slightly
 * between two parses of the same raw text, which would otherwise cause a
 * false negative). Sent to the server alongside the encrypted blob so
 * POST /statement/save can catch a duplicate it could never detect any
 * other way — the ciphertext itself is opaque, so this one-way hash is the
 * only content-derived signal the server ever sees, and it reveals nothing
 * about the actual transactions, same non-reversibility a password hash
 * relies on.
 *
 * Exact-match only, not fuzzy: if the same real statement gets parsed
 * slightly differently on a second upload (different OCR/extraction
 * artifacts), the hash won't match and the duplicate won't be caught. That
 * trade-off is deliberate — a fuzzy match risks false positives (rejecting
 * two genuinely different accounts that happen to overlap), which is worse
 * than an occasional missed duplicate.
 */
export async function computeContentHash(transactions: ParsedTransaction[]): Promise<string> {
  const canonical = [...transactions]
    .map((t) => `${t.date}|${t.description.trim().toLowerCase()}|${t.amount.toFixed(2)}`)
    .sort()
    .join("\n");
  const bytes = new TextEncoder().encode(canonical);
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}
