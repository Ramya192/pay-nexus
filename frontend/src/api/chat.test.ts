import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { apiClient } from "./client";
import { useAuthStore } from "../store/authStore";
import { streamChat, summarizeSession, type ChatEvent } from "./chat";

function streamFromChunks(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  let i = 0;
  return new ReadableStream({
    pull(controller) {
      if (i < chunks.length) {
        controller.enqueue(encoder.encode(chunks[i++]));
      } else {
        controller.close();
      }
    },
  });
}

function baseParams() {
  return {
    query: "how much did I spend on rent?",
    payslipData: null,
    financialProfile: null,
    sessionHistory: [],
    payslipHistory: [],
    conversation: [],
    transactions: [],
    goals: [],
    budgets: null,
  };
}

beforeEach(() => {
  useAuthStore.getState().logout();
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("streamChat", () => {
  it("parses multiple SSE frames delivered in one chunk, in order", async () => {
    const body = streamFromChunks([
      'data: {"event":"agent_active","agent":"SpendingAnalyser"}\n\n' +
        'data: {"event":"final","response":"You spent ₹36,000 on rent."}\n\n',
    ]);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, body }));

    const events: ChatEvent[] = [];
    await streamChat(baseParams(), (e) => events.push(e));

    expect(events).toEqual([
      { event: "agent_active", agent: "SpendingAnalyser" },
      { event: "final", response: "You spent ₹36,000 on rent." },
    ]);
  });

  it("still delivers the final frame when the stream closes without its trailing blank-line separator (regression: this exact case previously dropped the final event)", async () => {
    const body = streamFromChunks([
      'data: {"event":"agent_active","agent":"SpendingAnalyser"}\n\n',
      'data: {"event":"final","response":"Done"}', // no trailing "\n\n" before the stream closes
    ]);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, body }));

    const events: ChatEvent[] = [];
    await streamChat(baseParams(), (e) => events.push(e));

    expect(events).toContainEqual({ event: "final", response: "Done" });
  });

  it("skips a malformed frame (logs it) without losing the frames around it", async () => {
    const body = streamFromChunks([
      "data: not-json\n\n" + 'data: {"event":"final","response":"ok"}\n\n',
    ]);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, body }));
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    const events: ChatEvent[] = [];
    await streamChat(baseParams(), (e) => events.push(e));

    expect(events).toEqual([{ event: "final", response: "ok" }]);
    expect(errorSpy).toHaveBeenCalled();
  });

  it("throws an Error tagged with the HTTP status when the response isn't ok", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 500, body: null }));
    await expect(streamChat(baseParams(), () => {})).rejects.toMatchObject({ status: 500 });
  });

  it("sends the Authorization header only when logged in", async () => {
    // A fresh stream per call -- a ReadableStream can only be read once, and
    // this test calls streamChat twice.
    const fetchMock = vi.fn().mockImplementation(async () => ({ ok: true, body: streamFromChunks([""]) }));
    vi.stubGlobal("fetch", fetchMock);

    await streamChat(baseParams(), () => {});
    let init = fetchMock.mock.calls[0][1];
    expect(init.headers.Authorization).toBeUndefined();

    useAuthStore.getState().setAuth("tok123", "salt==", "user@example.com", {} as CryptoKey);
    await streamChat(baseParams(), () => {});
    init = fetchMock.mock.calls[1][1];
    expect(init.headers.Authorization).toBe("Bearer tok123");
  });

  it("maps camelCase params onto the snake_case request body the backend expects", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, body: streamFromChunks([""]) });
    vi.stubGlobal("fetch", fetchMock);

    await streamChat(
      { ...baseParams(), payslipData: { basic: 50_000 }, financialProfile: { elssMutualFunds: 10_000 } },
      () => {}
    );
    const init = fetchMock.mock.calls[0][1];
    const sentBody = JSON.parse(init.body);
    expect(sentBody.payslip_data).toEqual({ basic: 50_000 });
    expect(sentBody.financial_profile).toEqual({ elssMutualFunds: 10_000 });
  });
});

describe("summarizeSession", () => {
  it("POSTs exchanges/payslipData and unwraps the summary", async () => {
    const post = vi.spyOn(apiClient, "post").mockResolvedValue({ data: { summary: { month: "2026-08" } } });
    const exchanges = [{ query: "q", response: "a" }];
    const result = await summarizeSession(exchanges, { basic: 50_000 });
    expect(post).toHaveBeenCalledWith("/chat/summarize", { exchanges, payslip_data: { basic: 50_000 } });
    expect(result).toEqual({ month: "2026-08" });
  });
});
