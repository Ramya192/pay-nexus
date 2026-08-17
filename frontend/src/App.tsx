import { Landmark } from "lucide-react";
import { useMemo, useState } from "react";
import { summarizeSession } from "./api/chat";
import { saveSessionSummary } from "./api/payslip";
import { AlertBanner } from "./components/Alerts/AlertBanner";
import { DevAlertPreview, resolvePreviewDate } from "./components/Alerts/DevAlertPreview";
import { AuthScreen } from "./components/Auth/AuthScreen";
import { ChatWidget } from "./components/ChatWidget/ChatWidget";
import { TabbedPanel } from "./components/Dashboard/TabbedPanel";
import { encryptJSON } from "./crypto/clientEncryption";
import { computeAlerts } from "./utils/alerts";
import { buildExchanges } from "./utils/exchanges";
import { useAuthStore } from "./store/authStore";
import { useBudgetStore } from "./store/budgetStore";
import { useChatStore } from "./store/chatStore";
import { useChatWidgetUiStore } from "./store/chatWidgetUiStore";
import { useFinancialProfileStore } from "./store/financialProfileStore";
import { useGoalStore } from "./store/goalStore";
import { usePayslipHistoryStore } from "./store/payslipHistoryStore";
import { usePayslipStore } from "./store/payslipStore";
import { useSessionHistoryStore } from "./store/sessionHistoryStore";
import { useTransactionStore } from "./store/transactionStore";

export default function App() {
  const token = useAuthStore((s) => s.token);
  const email = useAuthStore((s) => s.userEmail);
  const aesKey = useAuthStore((s) => s.aesKey);
  const logout = useAuthStore((s) => s.logout);
  const [loggingOut, setLoggingOut] = useState(false);
  const [previewKey, setPreviewKey] = useState("real"); // dev-only override, see DevAlertPreview.tsx
  const snapshots = usePayslipHistoryStore((s) => s.snapshots);
  const financialProfile = useFinancialProfileStore((s) => s.profile);
  const transactions = useTransactionStore((s) => s.transactions);
  const budget = useBudgetStore((s) => s.budget);
  const goals = useGoalStore((s) => s.goals);
  const chatOpen = useChatWidgetUiStore((s) => s.open);
  const chatMaximized = useChatWidgetUiStore((s) => s.maximized);
  // Recomputed only when the underlying data actually changes — these are
  // pure functions of date + already-loaded data (utils/alerts.ts), not an
  // LLM call, so this is cheap enough to just be a memo, not a fetch.
  const alerts = useMemo(
    () => computeAlerts(resolvePreviewDate(previewKey), snapshots, financialProfile, transactions, budget, goals),
    [previewKey, snapshots, financialProfile, transactions, budget, goals]
  );

  if (!token) return <AuthScreen />;

  async function handleLogout() {
    setLoggingOut(true);
    try {
      await saveSessionSummaryIfAny(aesKey);
    } catch (err) {
      // Non-fatal — losing this session's summary shouldn't trap the user
      // logged in. Next session just won't have this one's pattern data.
      console.warn("Could not save session summary on logout", err);
    } finally {
      useChatStore.getState().reset();
      usePayslipStore.getState().clear();
      useFinancialProfileStore.getState().clear();
      usePayslipHistoryStore.getState().clear();
      useSessionHistoryStore.getState().clear();
      useTransactionStore.getState().clear();
      useGoalStore.getState().clear();
      useBudgetStore.getState().clear();
      logout();
      setLoggingOut(false);
    }
  }

  return (
    <div className="flex h-screen flex-col bg-slate-50">
      <header className="flex items-center justify-between border-b border-slate-200 bg-white px-4 py-3">
        <div className="flex items-center gap-2.5">
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-brand-600 text-white">
            <Landmark className="h-4.5 w-4.5" aria-hidden="true" />
          </span>
          <div>
            <h1 className="text-lg font-semibold tracking-tight text-slate-900">PayNexus</h1>
            <p className="text-xs text-slate-500">{email}</p>
          </div>
        </div>
        <button
          onClick={handleLogout}
          disabled={loggingOut}
          className="text-sm text-slate-500 hover:text-slate-800 disabled:opacity-50"
        >
          {loggingOut ? "Saving session…" : "Log out"}
        </button>
      </header>
      {import.meta.env.DEV && <DevAlertPreview value={previewKey} onChange={setPreviewKey} />}
      <AlertBanner alerts={alerts} />
      {/* The chat panel floats at fixed bottom-5 right-5, ~520px wide, and
          isn't part of this flex layout (position: fixed takes it out of
          flow) — so its overlap with right-side page content (e.g. a
          goal's Delete/"Update progress" buttons, confirmed hidden behind
          it) has to be fixed here by reserving matching space, not by
          anything the panel itself can do. Only applied at `lg` and up:
          below that breakpoint the panel already grows to near-full-width
          per its own `calc(100vw-2.5rem)` sizing, where reserving the same
          margin would crush the content instead of the two coexisting.
          Skipped while maximized — that state already covers virtually the
          whole screen (`inset-4`/`inset-8`), so there's no content margin
          worth reserving underneath it. */}
      <main className={`flex-1 overflow-y-auto p-6 ${chatOpen && !chatMaximized ? "lg:pr-[560px]" : ""}`}>
        <TabbedPanel />
      </main>
      <ChatWidget />
    </div>
  );
}

/**
 * Level 2 compression (§6), triggered at session end — this app has no
 * websocket/heartbeat to detect a session ending any other way, so "user
 * clicks Log out" is the signal. Skips the round trip entirely if nothing
 * was actually asked this session, so logging out of an idle tab doesn't
 * burn an OpenAI call for nothing.
 */
async function saveSessionSummaryIfAny(aesKey: CryptoKey | null): Promise<void> {
  const messages = useChatStore.getState().messages;
  if (!aesKey || messages.length === 0) return;

  const exchanges = buildExchanges(messages);
  if (exchanges.length === 0) return;

  const payslipData = usePayslipStore.getState().payslipData;
  const summary = await summarizeSession(exchanges, payslipData);
  const blob = await encryptJSON(aesKey, summary);
  await saveSessionSummary(blob);
}
