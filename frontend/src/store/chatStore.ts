import { create } from "zustand";
import type { Nudge } from "../components/NudgeCard/NudgeCard";

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  activeAgent?: string; // comma-joined node names from the assembler (backend §8)
  nudge?: Nudge | null; // present when the Nudge Agent ran and returned a parseable card
}

interface ChatState {
  messages: ChatMessage[];
  activeAgents: string[]; // currently-reasoning agents, for AgentIndicator
  addMessage: (m: ChatMessage) => void;
  addActiveAgent: (agent: string) => void;
  clearActiveAgents: () => void;
  updateLastMessage: (content: string, activeAgent?: string, nudge?: Nudge | null) => void;
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
  updateLastMessage: (content, activeAgent, nudge) =>
    set((s) => {
      const messages = [...s.messages];
      const last = messages[messages.length - 1];
      if (last && last.role === "assistant") {
        messages[messages.length - 1] = { ...last, content, activeAgent, nudge };
      }
      return { messages };
    }),
}));
