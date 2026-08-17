import { useState } from "react";
import { createConsent, fetchViaAA, getConsentStatus } from "../../api/aa";
import type { ParsedTransaction } from "../../api/statement";

type Stage = "idle" | "creatingConsent" | "awaitingApproval" | "checkingStatus" | "fetching";

/**
 * Account Aggregator (Setu sandbox) linking flow — a third way to *arrive
 * at* a transaction list, alongside the PDF/CSV upload above. Deliberately
 * feeds its result back up to StatementUploader via `onFetched` rather than
 * rendering its own review list — the review-then-save UI already built
 * there is reused verbatim (see the AA integration plan, step 5: "extend
 * StatementUploader.tsx, don't replace it").
 *
 * Sandbox only — no real bank data. The consent approval page (mobile
 * number + OTP + bank selection) is Setu-hosted and opens in a new tab;
 * this component polls GET /aa/consent/{id} for status rather than relying
 * on the webhook, since a local dev backend isn't reachable from Setu's
 * servers without ngrok (see backend/api/routes/aa.py's module docstring).
 */
export function LinkBankViaAA({
  onFetched,
}: {
  onFetched: (transactions: ParsedTransaction[], sourceAccount: string, warnings: string[]) => void;
}) {
  const [vua, setVua] = useState("");
  const [accountLabel, setAccountLabel] = useState("");
  const [consentId, setConsentId] = useState<string | null>(null);
  const [webviewUrl, setWebviewUrl] = useState<string | null>(null);
  const [consentStatus, setConsentStatus] = useState<string | null>(null);
  const [stage, setStage] = useState<Stage>("idle");
  const [error, setError] = useState<string | null>(null);

  async function handleLink() {
    if (!vua.trim()) {
      setError("Enter your sandbox mobile number + AA handle (e.g. 9999999999@setu).");
      return;
    }
    setError(null);
    setStage("creatingConsent");
    try {
      const result = await createConsent(vua.trim());
      setConsentId(result.consent_id);
      setWebviewUrl(result.webview_url);
      setConsentStatus(result.status);
      setStage("awaitingApproval");
      window.open(result.webview_url, "_blank", "noopener,noreferrer");
    } catch {
      setStage("idle");
      setError("Couldn't start the consent flow — check the sandbox credentials in the backend's .env.");
    }
  }

  async function handleCheckStatus() {
    if (!consentId) return;
    setStage("checkingStatus");
    setError(null);
    try {
      const result = await getConsentStatus(consentId);
      setConsentStatus(result.status);
    } catch {
      setError("Couldn't check consent status — try again.");
    } finally {
      setStage("awaitingApproval");
    }
  }

  async function handleFetch() {
    if (!consentId) return;
    if (!accountLabel.trim()) {
      setError('Give this linked account a name (e.g. "HDFC (via Setu)") first.');
      return;
    }
    setStage("fetching");
    setError(null);
    try {
      const result = await fetchViaAA(consentId, accountLabel.trim());
      if (result.transactions.length === 0) {
        throw new Error("No transactions came back from the linked account.");
      }
      const warnings =
        result.skipped_row_count > 0
          ? [`${result.skipped_row_count} row(s) from the linked account couldn't be read and were skipped.`]
          : [];
      onFetched(result.transactions, accountLabel.trim(), warnings);
      // Reset the linking sub-flow — the fetched transactions now live in
      // the parent's review state, this component's job here is done.
      setStage("idle");
      setConsentId(null);
      setWebviewUrl(null);
      setConsentStatus(null);
      setVua("");
      setAccountLabel("");
    } catch (err) {
      setStage("awaitingApproval");
      setError(
        err instanceof Error ? err.message : "Couldn't fetch transactions — the consent may not be approved yet."
      );
    }
  }

  const busy = stage === "creatingConsent" || stage === "checkingStatus" || stage === "fetching";

  return (
    <div className="space-y-2 rounded-md border border-dashed border-slate-300 p-3">
      <label className="block text-xs font-medium text-slate-600">
        Link your bank (Setu sandbox){" "}
        <span className="font-normal text-slate-400">
          — consent-based, no manual upload; sandbox only, no real bank data
        </span>
      </label>

      {!consentId && (
        <div className="flex gap-2">
          <input
            type="text"
            value={vua}
            onChange={(e) => setVua(e.target.value)}
            placeholder="9999999999@setu"
            disabled={busy}
            className="flex-1 rounded-md border border-slate-300 px-2.5 py-1.5 text-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
          />
          <button
            type="button"
            onClick={handleLink}
            disabled={busy}
            className="shrink-0 rounded-md bg-brand-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-50"
          >
            {stage === "creatingConsent" ? "Starting…" : "Link account"}
          </button>
        </div>
      )}

      {consentId && (
        <div className="space-y-2">
          <p className="text-xs text-slate-500">
            Consent status: <span className="font-medium">{consentStatus}</span>. Complete approval in the tab
            that opened (mobile number + OTP + bank selection), then check status.
          </p>
          <div className="flex flex-wrap items-end gap-2">
            <button
              type="button"
              onClick={() => webviewUrl && window.open(webviewUrl, "_blank", "noopener,noreferrer")}
              className="rounded-md border border-slate-300 px-2.5 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50"
            >
              Reopen approval page
            </button>
            <button
              type="button"
              onClick={handleCheckStatus}
              disabled={busy}
              className="rounded-md border border-slate-300 px-2.5 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50 disabled:opacity-50"
            >
              {stage === "checkingStatus" ? "Checking…" : "Check status"}
            </button>
          </div>
          {consentStatus === "ACTIVE" && (
            <div className="flex items-end gap-2 pt-1">
              <div className="flex-1 space-y-1">
                <label className="block text-xs font-medium text-slate-600" htmlFor="aa-account-label">
                  Account name
                </label>
                <input
                  id="aa-account-label"
                  type="text"
                  value={accountLabel}
                  onChange={(e) => setAccountLabel(e.target.value)}
                  placeholder="e.g. HDFC (via Setu)"
                  disabled={busy}
                  className="w-full rounded-md border border-slate-300 px-2.5 py-1.5 text-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
                />
              </div>
              <button
                type="button"
                onClick={handleFetch}
                disabled={busy}
                className="shrink-0 rounded-md bg-brand-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-50"
              >
                {stage === "fetching" ? "Fetching…" : "Fetch transactions"}
              </button>
            </div>
          )}
        </div>
      )}
      {error && <p className="text-xs text-red-600">{error}</p>}
    </div>
  );
}
