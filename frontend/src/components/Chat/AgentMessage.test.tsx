import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { AgentMessage } from "./AgentMessage";
import type { ChatMessage } from "../../store/chatStore";

function message(overrides: Partial<ChatMessage> = {}): ChatMessage {
  return { id: "1", role: "assistant", content: "Here's your answer.", ...overrides };
}

describe("AgentMessage", () => {
  it("renders the message content when not streaming", () => {
    render(<AgentMessage message={message()} pendingAgents={[]} />);
    expect(screen.getByText("Here's your answer.")).toBeInTheDocument();
  });

  it("shows the AgentIndicator instead of an empty bubble while streaming (empty content + active agents)", () => {
    render(<AgentMessage message={message({ content: "" })} pendingAgents={["payslip_agent"]} />);
    expect(screen.getByText("Payslip Agent reasoning…")).toBeInTheDocument();
    // No empty message bubble rendered while streaming.
    expect(document.querySelector(".rounded-bl-sm")).not.toBeInTheDocument();
  });

  it("shows both the indicator and the real content once a pending agent's answer starts arriving", () => {
    render(<AgentMessage message={message({ content: "Partial answer" })} pendingAgents={["payslip_agent"]} />);
    expect(screen.getByText("Payslip Agent reasoning…")).toBeInTheDocument();
    expect(screen.getByText("Partial answer")).toBeInTheDocument();
  });

  it("renders a NudgeCard when the message carries a nudge", () => {
    render(
      <AgentMessage
        message={message({ nudge: { title: "Trim your subscriptions", detail: "...", impact: null } })}
        pendingAgents={[]}
      />
    );
    expect(screen.getByText("Trim your subscriptions")).toBeInTheDocument();
  });

  it("renders one DataTable per table the message carries", () => {
    render(
      <AgentMessage
        message={message({
          tables: [
            { title: "Table A", headers: ["X"], rows: [["1"]] },
            { title: "Table B", headers: ["Y"], rows: [["2"]] },
          ],
        })}
        pendingAgents={[]}
      />
    );
    expect(screen.getByText("Table A")).toBeInTheDocument();
    expect(screen.getByText("Table B")).toBeInTheDocument();
  });
});
