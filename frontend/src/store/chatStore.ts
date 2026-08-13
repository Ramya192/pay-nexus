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

interface ChatState {
  messages: ChatMessage[];
  activeAgents: string[]; // currently-reasoning agents, for AgentIndicator
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
  reset: () => void;
}

export const useChatStore = create<ChatState>((set) => ({
  messages: [],
  activeAgents: [],
  reset: () => set({ messages: [], activeAgents: [] }),
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
}));
