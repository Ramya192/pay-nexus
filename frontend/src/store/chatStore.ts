import { create } from "zustand";
import type { TableData } from "../components/Chat/DataTable";
import type { Nudge } from "../components/NudgeCard/NudgeCard";

/** Exact per-turn LLM cost/token metrics (backend/agents/llm_metrics.py) —
 * real numbers from OpenAI's own response.usage, never estimated. Lets a
 * turn's actual cost be inspected from the chat itself, the same way
 * DataTable does for RAG sources/computed figures. */
export interface TokenUsage {
  total_input_tokens: number;
  total_output_tokens: number;
  total_cost_usd: number;
  by_agent: Record<string, { input_tokens: number; output_tokens: number; cost_usd: number; calls: number }>;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  activeAgent?: string; // comma-joined node names from the assembler (backend §8)
  nudge?: Nudge | null; // present when the Nudge Agent ran and returned a parseable card
  tables?: TableData[]; // computed data tables the agent(s) chose to show (backend/agents/tables.py) — rendered as real <table>s, not prose
  tokenUsage?: TokenUsage;
}

export interface QueuedQuestion {
  id: string;
  text: string;
}

interface ChatState {
  messages: ChatMessage[];
  activeAgents: string[]; // currently-reasoning agents, for AgentIndicator
  // Follow-up questions typed while a turn is still in flight — ChatInterface
  // runs them one at a time (FIFO) instead of firing concurrent turns against
  // the same conversation state. See ChatInterface.tsx's runTurn/handleSend.
  // Each has its own id (not just the raw text) so a specific queued item can
  // be individually cancelled — see removeFromQueue.
  queue: QueuedQuestion[];
  addMessage: (m: ChatMessage) => void;
  addActiveAgent: (agent: string) => void;
  clearActiveAgents: () => void;
  updateLastMessage: (
    content: string,
    activeAgent?: string,
    nudge?: Nudge | null,
    tables?: TableData[],
    tokenUsage?: TokenUsage
  ) => void;
  enqueue: (text: string) => void;
  /** Pops and returns the oldest queued question, or undefined if empty. */
  dequeue: () => string | undefined;
  /** Removes one specific not-yet-started queued question (the Stop button
   * only ever cancels whichever turn is CURRENTLY running — this is the
   * only way to retract a queued one without touching that turn). */
  removeFromQueue: (id: string) => void;
  reset: () => void;
}

export const useChatStore = create<ChatState>((set, get) => ({
  messages: [],
  activeAgents: [],
  queue: [],
  reset: () => set({ messages: [], activeAgents: [], queue: [] }),
  addMessage: (m) => set((s) => ({ messages: [...s.messages, m] })),
  addActiveAgent: (agent) =>
    set((s) => (s.activeAgents.includes(agent) ? s : { activeAgents: [...s.activeAgents, agent] })),
  clearActiveAgents: () => set({ activeAgents: [] }),
  updateLastMessage: (content, activeAgent, nudge, tables, tokenUsage) =>
    set((s) => {
      const messages = [...s.messages];
      const last = messages[messages.length - 1];
      if (last && last.role === "assistant") {
        messages[messages.length - 1] = { ...last, content, activeAgent, nudge, tables, tokenUsage };
      }
      return { messages };
    }),
  enqueue: (text) => set((s) => ({ queue: [...s.queue, { id: crypto.randomUUID(), text }] })),
  dequeue: () => {
    const [next, ...rest] = get().queue;
    if (next !== undefined) set({ queue: rest });
    return next?.text;
  },
  removeFromQueue: (id) => set((s) => ({ queue: s.queue.filter((q) => q.id !== id) })),
}));
