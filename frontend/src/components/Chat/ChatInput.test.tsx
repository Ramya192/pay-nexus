import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ChatInput } from "./ChatInput";

describe("ChatInput", () => {
  it("sends the trimmed text and clears the input", async () => {
    const user = userEvent.setup();
    const onSend = vi.fn();
    render(<ChatInput onSend={onSend} />);

    const input = screen.getByPlaceholderText("Am I on the best tax regime for me?");
    await user.type(input, "  How much did I spend on rent?  ");
    await user.click(screen.getByRole("button", { name: "Ask" }));

    expect(onSend).toHaveBeenCalledWith("How much did I spend on rent?");
    expect(input).toHaveValue("");
  });

  it("does not call onSend for a blank/whitespace-only submission", async () => {
    const user = userEvent.setup();
    const onSend = vi.fn();
    render(<ChatInput onSend={onSend} />);

    await user.type(screen.getByPlaceholderText("Am I on the best tax regime for me?"), "   ");
    await user.click(screen.getByRole("button", { name: "Ask" }));

    expect(onSend).not.toHaveBeenCalled();
  });

  it("submits on Enter (native form submit), not just the button click", async () => {
    const user = userEvent.setup();
    const onSend = vi.fn();
    render(<ChatInput onSend={onSend} />);

    const input = screen.getByPlaceholderText("Am I on the best tax regime for me?");
    await user.type(input, "hello{Enter}");

    expect(onSend).toHaveBeenCalledWith("hello");
  });

  it("disables the input and button when disabled", () => {
    render(<ChatInput onSend={vi.fn()} disabled />);
    expect(screen.getByPlaceholderText("Am I on the best tax regime for me?")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Ask" })).toBeDisabled();
  });
});
