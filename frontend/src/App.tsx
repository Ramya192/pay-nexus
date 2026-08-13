import { useState } from "react";
import { summarizeSession } from "./api/chat";
import { saveSessionSummary } from "./api/payslip";
import { AuthScreen } from "./components/Auth/AuthScreen";
import { ChatInterface } from "./components/Chat/ChatInterface";
import { PayslipUploader } from "./components/PayslipUploader/PayslipUploader";
import { encryptJSON } from "./crypto/clientEncryption";
import { useAuthStore } from "./store/authStore";
import { useChatStore } from "./store/chatStore";
import { usePayslipStore } from "./store/payslipStore";
import { useSessionHistoryStore } from "./store/sessionHistoryStore";

export default function App() {
  const token = useAuthStore((s) => s.token);
  const email = useAuthStore((s) => s.userEmail);
  const aesKey = useAuthStore((s) => s.aesKey);
  const logout = useAuthStore((s) => s.logout);
  const [loggingOut, setLoggingOut] = useState(false);

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
      useSessionHistoryStore.getState().clear();
      logout();
      setLoggingOut(false);
    }
  }

  return (
    <div className="flex h-screen flex-col bg-slate-50">
      <header className="flex items-center justify-between border-b border-slate-200 bg-white px-4 py-3">
        <div>
          <h1 className="text-base font-semibold text-slate-900">PayNexus</h1>
          <p className="text-xs text-slate-500">{email}</p>
        </div>
        <button
          onClick={handleLogout}
          disabled={loggingOut}
          className="text-sm text-slate-500 hover:text-slate-800 disabled:opacity-50"
        >
          {loggingOut ? "Saving session…" : "Log out"}
        </button>
      </header>
      <div className="flex flex-1 overflow-hidden">
        <aside className="w-80 overflow-y-auto border-r border-slate-200 bg-white p-4">
          <h2 className="mb-3 text-sm font-semibold text-slate-700">Your payslip</h2>
          <PayslipUploader />
        </aside>
        <main className="flex-1">
          <ChatInterface />
        </main>
      </div>
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

  const exchanges: { query: string; response: string }[] = [];
  for (let i = 0; i < messages.length - 1; i++) {
    const user = messages[i];
    const assistant = messages[i + 1];
    if (user.role === "user" && assistant?.role === "assistant" && assistant.content) {
      exchanges.push({ query: user.content, response: assistant.content });
    }
  }
  if (exchanges.length === 0) return;

  const payslipData = usePayslipStore.getState().payslipData;
  const summary = await summarizeSession(exchanges, payslipData);
  const blob = await encryptJSON(aesKey, summary);
  await saveSessionSummary(blob);
}
