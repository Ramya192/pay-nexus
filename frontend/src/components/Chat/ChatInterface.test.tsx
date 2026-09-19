import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ChatInterface } from "./ChatInterface";
import { useChatStore } from "../../store/chatStore";
import { usePayslipStore } from "../../store/payslipStore";
import * as chatApi from "../../api/chat";
import type { ChatEvent } from "../../api/chat";

function deferred<T>() {
  let resolve!: (v: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

beforeEach(() => {
  useChatStore.getState().reset();
  usePayslipStore.getState().clear();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("ChatInterface", () => {
  it("sends a message: adds a user message + an empty assistant placeholder, and calls streamChat with the current store data", async () => {
    const user = userEvent.setup();
    usePayslipStore.getState().setPayslipData({ basic: 50_000 });
    const stream = vi.spyOn(chatApi, "streamChat").mockImplementation(async (_params, onEvent) => {
      onEvent({ event: "final", response: "You earn ₹50,000 basic." });
    });
    render(<ChatInterface />);

    await user.type(screen.getByPlaceholderText("Am I on the best tax regime for me?"), "what's my basic?{Enter}");

    await waitFor(() => expect(screen.getByText("You earn ₹50,000 basic.")).toBeInTheDocument());
    expect(screen.getByText("what's my basic?")).toBeInTheDocument();
    expect(stream).toHaveBeenCalledWith(
      expect.objectContaining({ query: "what's my basic?", payslipData: { basic: 50_000 } }),
      expect.any(Function),
      expect.anything()
    );
  });

  it("shows 'Thinking…' and the active agent while streaming, clearing both on the final event", async () => {
    const user = userEvent.setup();
    const { promise, resolve } = deferred<void>();
    let capturedOnEvent!: (e: ChatEvent) => void;
    vi.spyOn(chatApi, "streamChat").mockImplementation(async (_params, onEvent) => {
      capturedOnEvent = onEvent;
      return promise;
    });
    render(<ChatInterface />);

    await user.type(screen.getByPlaceholderText("Am I on the best tax regime for me?"), "hi{Enter}");
    await waitFor(() => expect(screen.getByText("Thinking…")).toBeInTheDocument());

    act(() => capturedOnEvent({ event: "agent_active", agent: "payslip_agent" }));
    await waitFor(() => expect(screen.getByText("Payslip Agent reasoning…")).toBeInTheDocument());

    act(() => capturedOnEvent({ event: "final", response: "Done" }));
    resolve();

    await waitFor(() => expect(screen.queryByText("Thinking…")).not.toBeInTheDocument());
    expect(screen.queryByText("Payslip Agent reasoning…")).not.toBeInTheDocument();
    expect(screen.getByText("Done")).toBeInTheDocument();
  });

  it("an error event mid-stream updates the assistant message with the server's detail", async () => {
    const user = userEvent.setup();
    vi.spyOn(chatApi, "streamChat").mockImplementation(async (_params, onEvent) => {
      onEvent({ event: "error", detail: "Regulatory Agent timed out" });
    });
    render(<ChatInterface />);

    await user.type(screen.getByPlaceholderText("Am I on the best tax regime for me?"), "hi{Enter}");

    await waitFor(() => expect(screen.getByText("Regulatory Agent timed out")).toBeInTheDocument());
  });

  describe("errors thrown by streamChat itself", () => {
    it("a Stop-triggered AbortError shows 'Stopped.'", async () => {
      const user = userEvent.setup();
      const { promise, reject } = deferred<void>();
      vi.spyOn(chatApi, "streamChat").mockImplementation(async () => promise);
      render(<ChatInterface />);

      await user.type(screen.getByPlaceholderText("Am I on the best tax regime for me?"), "hi{Enter}");
      await waitFor(() => expect(screen.getByRole("button", { name: "Stop" })).toBeInTheDocument());
      await user.click(screen.getByRole("button", { name: "Stop" }));
      reject(new DOMException("aborted", "AbortError"));

      await waitFor(() => expect(screen.getByText("Stopped.")).toBeInTheDocument());
    });

    it("a 401 shows a session-expired message, distinct from a generic server-down message", async () => {
      const user = userEvent.setup();
      const err = new Error("unauthorized") as Error & { status?: number };
      err.status = 401;
      vi.spyOn(chatApi, "streamChat").mockRejectedValue(err);
      render(<ChatInterface />);

      await user.type(screen.getByPlaceholderText("Am I on the best tax regime for me?"), "hi{Enter}");

      await waitFor(() =>
        expect(screen.getByText("Your session has expired — please log in again.")).toBeInTheDocument()
      );
    });

    it("a different HTTP status names the status, without claiming the server is down", async () => {
      const user = userEvent.setup();
      const err = new Error("server error") as Error & { status?: number };
      err.status = 500;
      vi.spyOn(chatApi, "streamChat").mockRejectedValue(err);
      render(<ChatInterface />);

      await user.type(screen.getByPlaceholderText("Am I on the best tax regime for me?"), "hi{Enter}");

      await waitFor(() =>
        expect(screen.getByText("PayNexus returned an error (500) — please try again.")).toBeInTheDocument()
      );
    });

    it("a plain network failure (no status at all) says to check the backend", async () => {
      const user = userEvent.setup();
      vi.spyOn(chatApi, "streamChat").mockRejectedValue(new TypeError("Failed to fetch"));
      render(<ChatInterface />);

      await user.type(screen.getByPlaceholderText("Am I on the best tax regime for me?"), "hi{Enter}");

      await waitFor(() =>
        expect(screen.getByText("Couldn't reach PayNexus — check that the backend is running.")).toBeInTheDocument()
      );
    });
  });

  describe("queueing a follow-up while a turn is in flight", () => {
    it("queues instead of firing a second concurrent request, then runs it once the first turn finishes", async () => {
      const user = userEvent.setup();
      const first = deferred<void>();
      const stream = vi.spyOn(chatApi, "streamChat").mockImplementationOnce(async (_p, onEvent) => {
        onEvent({ event: "final", response: "First answer" });
        return first.promise;
      });
      render(<ChatInterface />);

      await user.type(screen.getByPlaceholderText("Am I on the best tax regime for me?"), "first question{Enter}");
      await waitFor(() => expect(screen.getByRole("button", { name: "Stop" })).toBeInTheDocument());

      // Typed while the first turn is still in flight -- must be queued, not sent immediately.
      await user.type(screen.getByPlaceholderText("Am I on the best tax regime for me?"), "second question{Enter}");
      expect(screen.getByText("second question")).toBeInTheDocument(); // shown in the queue list
      expect(stream).toHaveBeenCalledTimes(1);

      stream.mockImplementationOnce(async (_p, onEvent) => {
        onEvent({ event: "final", response: "Second answer" });
      });
      first.resolve();

      await waitFor(() => expect(stream).toHaveBeenCalledTimes(2));
      expect(stream.mock.calls[1][0]).toMatchObject({ query: "second question" });
      await waitFor(() => expect(screen.getByText("Second answer")).toBeInTheDocument());
    });

    it("a queued question can be individually removed without touching the in-flight turn", async () => {
      const user = userEvent.setup();
      const first = deferred<void>();
      vi.spyOn(chatApi, "streamChat").mockImplementation(async () => first.promise);
      render(<ChatInterface />);

      await user.type(screen.getByPlaceholderText("Am I on the best tax regime for me?"), "first{Enter}");
      await waitFor(() => expect(screen.getByRole("button", { name: "Stop" })).toBeInTheDocument());
      await user.type(screen.getByPlaceholderText("Am I on the best tax regime for me?"), "unwanted{Enter}");

      await user.click(screen.getByRole("button", { name: "Remove queued question: unwanted" }));

      expect(screen.queryByText("unwanted")).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Stop" })).toBeInTheDocument(); // in-flight turn untouched
    });
  });
});
