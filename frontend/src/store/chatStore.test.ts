import { beforeEach, describe, expect, it } from "vitest";
import { useChatStore, type ChatMessage } from "./chatStore";

beforeEach(() => {
  useChatStore.getState().reset();
});

describe("useChatStore", () => {
  it("starts empty", () => {
    const s = useChatStore.getState();
    expect(s.messages).toEqual([]);
    expect(s.activeAgents).toEqual([]);
    expect(s.queue).toEqual([]);
  });

  it("addMessage appends in order", () => {
    const userMsg: ChatMessage = { id: "1", role: "user", content: "hi" };
    const assistantMsg: ChatMessage = { id: "2", role: "assistant", content: "" };
    useChatStore.getState().addMessage(userMsg);
    useChatStore.getState().addMessage(assistantMsg);
    expect(useChatStore.getState().messages).toEqual([userMsg, assistantMsg]);
  });

  describe("activeAgents", () => {
    it("addActiveAgent adds a new agent", () => {
      useChatStore.getState().addActiveAgent("SpendingAnalyser");
      expect(useChatStore.getState().activeAgents).toEqual(["SpendingAnalyser"]);
    });

    it("addActiveAgent does not add the same agent twice", () => {
      useChatStore.getState().addActiveAgent("SpendingAnalyser");
      useChatStore.getState().addActiveAgent("SpendingAnalyser");
      expect(useChatStore.getState().activeAgents).toEqual(["SpendingAnalyser"]);
    });

    it("clearActiveAgents empties the list", () => {
      useChatStore.getState().addActiveAgent("SpendingAnalyser");
      useChatStore.getState().clearActiveAgents();
      expect(useChatStore.getState().activeAgents).toEqual([]);
    });
  });

  describe("updateLastMessage", () => {
    it("updates the last message only when it's the assistant's", () => {
      useChatStore.getState().addMessage({ id: "1", role: "user", content: "hi" });
      useChatStore.getState().addMessage({ id: "2", role: "assistant", content: "" });
      useChatStore.getState().updateLastMessage("Here's your answer", "SpendingAnalyser");
      const last = useChatStore.getState().messages.at(-1)!;
      expect(last.content).toBe("Here's your answer");
      expect(last.activeAgent).toBe("SpendingAnalyser");
    });

    it("does nothing when the last message is the user's (streaming update arriving before the assistant placeholder)", () => {
      useChatStore.getState().addMessage({ id: "1", role: "user", content: "hi" });
      useChatStore.getState().updateLastMessage("stray update");
      expect(useChatStore.getState().messages).toEqual([{ id: "1", role: "user", content: "hi" }]);
    });
  });

  describe("queue", () => {
    it("enqueue/dequeue is FIFO", () => {
      useChatStore.getState().enqueue("first question");
      useChatStore.getState().enqueue("second question");
      expect(useChatStore.getState().dequeue()).toBe("first question");
      expect(useChatStore.getState().dequeue()).toBe("second question");
    });

    it("dequeue on an empty queue returns undefined", () => {
      expect(useChatStore.getState().dequeue()).toBeUndefined();
    });

    it("removeFromQueue cancels one specific queued item without touching the rest", () => {
      useChatStore.getState().enqueue("keep me");
      const idToCancel = useChatStore.getState().queue[0].id;
      useChatStore.getState().enqueue("cancel me");
      const cancelId = useChatStore.getState().queue[1].id;
      useChatStore.getState().removeFromQueue(cancelId);
      const remaining = useChatStore.getState().queue;
      expect(remaining).toHaveLength(1);
      expect(remaining[0].id).toBe(idToCancel);
      expect(remaining[0].text).toBe("keep me");
    });
  });

  it("reset clears messages, activeAgents, and the queue together", () => {
    useChatStore.getState().addMessage({ id: "1", role: "user", content: "hi" });
    useChatStore.getState().addActiveAgent("SpendingAnalyser");
    useChatStore.getState().enqueue("queued");
    useChatStore.getState().reset();
    const s = useChatStore.getState();
    expect(s.messages).toEqual([]);
    expect(s.activeAgents).toEqual([]);
    expect(s.queue).toEqual([]);
  });
});
