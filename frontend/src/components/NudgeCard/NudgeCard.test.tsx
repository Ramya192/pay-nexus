import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { NudgeCard } from "./NudgeCard";

describe("NudgeCard", () => {
  it("renders the title and detail", () => {
    render(<NudgeCard nudge={{ title: "Trim your subscriptions", detail: "You have 3 overlapping streaming plans.", impact: null }} />);
    expect(screen.getByText("Trim your subscriptions")).toBeInTheDocument();
    expect(screen.getByText("You have 3 overlapping streaming plans.")).toBeInTheDocument();
  });

  it("shows the impact line when present", () => {
    render(
      <NudgeCard
        nudge={{ title: "Trim your subscriptions", detail: "...", impact: "≈ ₹18,000 saved annually" }}
      />
    );
    expect(screen.getByText("≈ ₹18,000 saved annually")).toBeInTheDocument();
  });

  it("omits the impact line entirely when null (not enough history for a figure yet)", () => {
    render(<NudgeCard nudge={{ title: "Trim your subscriptions", detail: "...", impact: null }} />);
    expect(screen.queryByText(/saved annually/)).not.toBeInTheDocument();
  });
});
