/**
 * Client-side AES-256-GCM encryption via the Web Crypto API — the
 * mechanism behind PayNexus's privacy pitch (PROJECT_CONTEXT.md §4).
 * Payslip values are encrypted here, in the browser, before any network
 * call, using a key derived from the user's password + a server-issued
 * salt. The server only ever stores or returns ciphertext (see
 * backend/api/routes/payslip.py) — it never has the key itself.
 */

const PBKDF2_ITERATIONS = 100_000;
const GCM_IV_BYTES = 12; // standard AES-GCM nonce size

async function importPasswordKey(password: string): Promise<CryptoKey> {
  return crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(password),
    "PBKDF2",
    false,
    ["deriveKey"]
  );
}

/** Derives the AES-256-GCM key from the user's password + their server-issued salt. */
export async function deriveEncryptionKey(password: string, saltB64: string): Promise<CryptoKey> {
  const passwordKey = await importPasswordKey(password);
  const salt = base64ToBytes(saltB64);
  return crypto.subtle.deriveKey(
    { name: "PBKDF2", salt: salt as BufferSource, iterations: PBKDF2_ITERATIONS, hash: "SHA-256" },
    passwordKey,
    { name: "AES-GCM", length: 256 },
    false,
    ["encrypt", "decrypt"]
  );
}

export interface EncryptedBlob {
  ciphertextB64: string;
  ivB64: string;
}

/** Encrypts a plain object (e.g. payslip components) into a ciphertext+iv pair. */
export async function encryptJSON(key: CryptoKey, data: unknown): Promise<EncryptedBlob> {
  const iv = crypto.getRandomValues(new Uint8Array(GCM_IV_BYTES));
  const plaintext = new TextEncoder().encode(JSON.stringify(data));
  const ciphertext = await crypto.subtle.encrypt({ name: "AES-GCM", iv }, key, plaintext);
  return {
    ciphertextB64: bytesToBase64(new Uint8Array(ciphertext)),
    ivB64: bytesToBase64(iv),
  };
}

/** Decrypts a ciphertext+iv pair (e.g. a session summary from GET /payslip/history). */
export async function decryptJSON<T = unknown>(key: CryptoKey, blob: EncryptedBlob): Promise<T> {
  const iv = base64ToBytes(blob.ivB64);
  const ciphertext = base64ToBytes(blob.ciphertextB64);
  const plaintext = await crypto.subtle.decrypt(
    { name: "AES-GCM", iv: iv as BufferSource },
    key,
    ciphertext as BufferSource
  );
  return JSON.parse(new TextDecoder().decode(plaintext)) as T;
}

function bytesToBase64(bytes: Uint8Array): string {
  let binary = "";
  bytes.forEach((b) => (binary += String.fromCharCode(b)));
  return btoa(binary);
}

function base64ToBytes(b64: string): Uint8Array {
  const binary = atob(b64);
  return Uint8Array.from(binary, (c) => c.charCodeAt(0));
}
