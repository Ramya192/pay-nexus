import { useState, type ChangeEvent, type FormEvent } from "react";
import { login, register } from "../../api/auth";
import { fetchFinancialProfile } from "../../api/financialProfile";
import { fetchHistory, fetchSnapshots } from "../../api/payslip";
import { decryptJSON, deriveEncryptionKey } from "../../crypto/clientEncryption";
import { useAuthStore } from "../../store/authStore";
import { useFinancialProfileStore, type FinancialProfile } from "../../store/financialProfileStore";
import { usePayslipHistoryStore, type SnapshotEntry } from "../../store/payslipHistoryStore";
import { useSessionHistoryStore } from "../../store/sessionHistoryStore";

export function AuthScreen() {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const setAuth = useAuthStore((s) => s.setAuth);
  const setHistory = useSessionHistoryStore((s) => s.setHistory);
  const setFinancialProfile = useFinancialProfileStore((s) => s.setProfile);
  const setEntries = usePayslipHistoryStore((s) => s.setEntries);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const call = mode === "login" ? login : register;
      const { access_token, encryption_salt } = await call(email, password);
      // Derived here, in the browser, and never sent anywhere — only
      // ciphertext crosses the network from this point on (§4).
      const aesKey = await deriveEncryptionKey(password, encryption_salt);
      setAuth(access_token, encryption_salt, email, aesKey);

      // Load and decrypt whatever Level 2 summaries exist (§6) — a fresh
      // registration will just get []. Decrypt row-by-row so one bad row
      // (e.g. corrupted, or from a key that's since changed) can't block
      // login entirely; skip it and keep going.
      try {
        const rows = await fetchHistory();
        const decrypted: Record<string, unknown>[] = [];
        for (const row of rows) {
          try {
            decrypted.push(
              await decryptJSON(aesKey, { ciphertextB64: row.ciphertext_b64, ivB64: row.iv_b64 })
            );
          } catch (rowErr) {
            console.warn("Skipping undecryptable session summary row", row.id, rowErr);
          }
        }
        setHistory(decrypted);
      } catch (historyErr) {
        // Non-fatal — chat still works with empty session_history, just
        // without cross-session pattern data for this login.
        console.warn("Could not load session history", historyErr);
      }

      // Same pattern for the financial profile — null just means none
      // saved yet (fetchFinancialProfile already treats 404 as that, not
      // an error), which is the normal state for a fresh registration.
      try {
        const row = await fetchFinancialProfile();
        if (row) {
          const profile = await decryptJSON<FinancialProfile>(aesKey, {
            ciphertextB64: row.ciphertext_b64,
            ivB64: row.iv_b64,
          });
          setFinancialProfile(profile);
        }
      } catch (profileErr) {
        console.warn("Could not load financial profile", profileErr);
      }

      // Same row-by-row resilience as session history — one bad snapshot
      // shouldn't block login or drop every other month on file.
      try {
        const rows = await fetchSnapshots();
        const decrypted: SnapshotEntry[] = [];
        for (const row of rows) {
          try {
            const data = await decryptJSON<Record<string, unknown>>(aesKey, {
              ciphertextB64: row.ciphertext_b64,
              ivB64: row.iv_b64,
            });
            decrypted.push({ id: row.id, createdAt: row.created_at, data });
          } catch (rowErr) {
            console.warn("Skipping undecryptable payslip snapshot", row.id, rowErr);
          }
        }
        setEntries(decrypted);
      } catch (snapshotsErr) {
        console.warn("Could not load payslip snapshots", snapshotsErr);
      }
    } catch {
      setError(
        mode === "login" ? "Incorrect email or password." : "Could not create that account."
      );
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50">
      <form
        onSubmit={handleSubmit}
        className="w-full max-w-sm space-y-4 rounded-xl border border-slate-200 bg-white p-8 shadow-sm"
      >
        <div>
          <h1 className="text-xl font-semibold text-slate-900">PayNexus</h1>
          <p className="text-sm text-slate-500">Your pay, explained. Your finances, guided.</p>
        </div>
        <div className="space-y-1">
          <label className="text-sm font-medium text-slate-700" htmlFor="email">
            Email
          </label>
          <input
            id="email"
            type="email"
            required
            value={email}
            onChange={(e: ChangeEvent<HTMLInputElement>) => setEmail(e.target.value)}
            className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
          />
        </div>
        <div className="space-y-1">
          <label className="text-sm font-medium text-slate-700" htmlFor="password">
            Password
          </label>
          <input
            id="password"
            type="password"
            required
            minLength={8}
            value={password}
            onChange={(e: ChangeEvent<HTMLInputElement>) => setPassword(e.target.value)}
            className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
          />
        </div>
        {error && <p className="text-sm text-red-600">{error}</p>}
        <button
          type="submit"
          disabled={loading}
          className="w-full rounded-md bg-brand-600 px-3 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-50"
        >
          {loading ? "…" : mode === "login" ? "Log in" : "Create account"}
        </button>
        <button
          type="button"
          onClick={() => setMode(mode === "login" ? "register" : "login")}
          className="w-full text-center text-sm text-brand-600 hover:underline"
        >
          {mode === "login" ? "Need an account? Register" : "Have an account? Log in"}
        </button>
      </form>
    </div>
  );
}
