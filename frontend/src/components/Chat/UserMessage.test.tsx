import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { UserMessage } from "./UserMessage";

describe("UserMessage", () => {
  it("renders the message content", () => {
    render(<UserMessage content="How much did I spend on rent?" />);
    expect(screen.getByText("How much did I spend on rent?")).toBeInTheDocument();
  });
});
