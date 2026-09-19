import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { AgentIndicator } from "./AgentIndicator";

describe("AgentIndicator", () => {
  it("renders nothing for an empty agent list", () => {
    const { container } = render(<AgentIndicator agents={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows the friendly display label for a known agent, not its internal name", () => {
    render(<AgentIndicator agents={["nudge_agent"]} />);
    expect(screen.getByText("Savings Advisor reasoning…")).toBeInTheDocument();
    expect(screen.queryByText("nudge_agent")).not.toBeInTheDocument();
  });

  it("falls back to a generic label for an unrecognized agent name", () => {
    render(<AgentIndicator agents={["some_future_agent"]} />);
    expect(screen.getByText("some_future_agent reasoning…")).toBeInTheDocument();
  });

  it("renders one line per agent, in order", () => {
    render(<AgentIndicator agents={["payslip_agent", "regulatory_agent"]} />);
    const labels = screen.getAllByText(/reasoning…$/).map((el) => el.textContent);
    expect(labels).toEqual(["Payslip Agent reasoning…", "Regulatory Agent reasoning…"]);
  });
});
