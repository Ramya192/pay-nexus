import { beforeEach, describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { MessageList } from "./MessageList";
import { useChatStore } from "../../store/chatStore";

beforeEach(() => {
  useChatStore.getState().reset();
});

describe("MessageList", () => {
  it("shows the example-questions empty state when there are no messages", () => {
    render(<MessageList />);
    expect(screen.getByText(/Ask something like/)).toBeInTheDocument();
  });

  it("renders user and assistant messages in order, hiding the empty state", () => {
    useChatStore.getState().addMessage({ id: "1", role: "user", content: "How much did I spend?" });
    useChatStore.getState().addMessage({ id: "2", role: "assistant", content: "You spent ₹36,000." });
    render(<MessageList />);
    expect(screen.queryByText(/Ask something like/)).not.toBeInTheDocument();
    expect(screen.getByText("How much did I spend?")).toBeInTheDocument();
    expect(screen.getByText("You spent ₹36,000.")).toBeInTheDocument();
  });

  it("only passes activeAgents to the LAST message, not earlier ones", () => {
    useChatStore.getState().addMessage({ id: "1", role: "assistant", content: "" });
    useChatStore.getState().addMessage({ id: "2", role: "assistant", content: "" });
    useChatStore.getState().addActiveAgent("payslip_agent");
    render(<MessageList />);
    // Only one AgentIndicator line should render (for the last message), not two.
    expect(screen.getAllByText("Payslip Agent reasoning…")).toHaveLength(1);
  });
});
