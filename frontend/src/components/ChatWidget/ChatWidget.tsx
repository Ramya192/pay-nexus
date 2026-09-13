import { Minus, MessageCircle } from "lucide-react";
import { useState } from "react";
import { ChatInterface } from "../Chat/ChatInterface";

/**
 * Floating popup, per user request — replaces the always-visible main-panel
 * chat with a launcher button + panel, minimizable back to the button.
 * Defaults OPEN on load (below), not closed: unlike a typical support-chat
 * widget, chat is PayNexus's actual core feature, not a secondary channel —
 * defaulting it closed would make a first-time user's main way of asking a
 * question invisible until they noticed the button. Conversation state
 * (chatStore) is independent of whether this panel is mounted, so
 * minimizing mid-answer doesn't lose or interrupt anything in flight —
 * ChatInterface's streaming callbacks write to the Zustand store directly,
 * not to component state.
 */
export function ChatWidget() {
  const [open, setOpen] = useState(true);

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        aria-label="Open chat"
        className="fixed bottom-5 right-5 z-40 flex h-14 w-14 items-center justify-center rounded-full bg-brand-600 text-white shadow-lg hover:bg-brand-700"
      >
        <MessageCircle className="h-6 w-6" aria-hidden="true" />
      </button>
    );
  }

  return (
    <div className="fixed bottom-5 right-5 z-40 flex h-[min(760px,85vh)] w-[min(520px,calc(100vw-2.5rem))] flex-col overflow-hidden rounded-xl border border-slate-200 bg-white shadow-2xl">
      <div className="flex items-center justify-between border-b border-slate-200 bg-brand-600 px-4 py-3 text-white">
        <div className="flex items-center gap-2">
          <MessageCircle className="h-4 w-4" aria-hidden="true" />
          <span className="text-sm font-semibold">PayNexus Assistant</span>
        </div>
        <button
          onClick={() => setOpen(false)}
          aria-label="Minimize chat"
          className="rounded p-1 hover:bg-white/15"
        >
          <Minus className="h-4 w-4" aria-hidden="true" />
        </button>
      </div>
      <div className="min-h-0 flex-1">
        <ChatInterface />
      </div>
    </div>
  );
}
