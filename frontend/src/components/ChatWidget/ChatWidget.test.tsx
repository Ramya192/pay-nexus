import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ChatWidget } from "./ChatWidget";
import { useChatWidgetUiStore } from "../../store/chatWidgetUiStore";

// ChatWidget's own job is just the open/minimize/maximize chrome around
// ChatInterface -- ChatInterface itself (streaming, agent orchestration) is
// out of scope here, so it's stubbed out to keep this test isolated and fast.
vi.mock("../Chat/ChatInterface", () => ({
  ChatInterface: () => <div data-testid="chat-interface" />,
}));

beforeEach(() => {
  useChatWidgetUiStore.setState({ open: true, maximized: false });
});

describe("ChatWidget", () => {
  it("shows only the launcher button when closed", () => {
    useChatWidgetUiStore.setState({ open: false });
    render(<ChatWidget />);
    expect(screen.getByRole("button", { name: "Open chat" })).toBeInTheDocument();
    expect(screen.queryByTestId("chat-interface")).not.toBeInTheDocument();
  });

  it("shows the panel with ChatInterface mounted when open", () => {
    render(<ChatWidget />);
    expect(screen.getByTestId("chat-interface")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Open chat" })).not.toBeInTheDocument();
  });

  it("minimizing closes the panel AND resets maximized back to false", async () => {
    const user = userEvent.setup();
    useChatWidgetUiStore.setState({ open: true, maximized: true });
    render(<ChatWidget />);

    await user.click(screen.getByRole("button", { name: "Minimize chat" }));

    expect(useChatWidgetUiStore.getState().open).toBe(false);
    expect(useChatWidgetUiStore.getState().maximized).toBe(false);
  });

  it("the maximize button toggles maximized state and its own label", async () => {
    const user = userEvent.setup();
    render(<ChatWidget />);

    expect(screen.getByRole("button", { name: "Maximize chat" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Maximize chat" }));

    expect(useChatWidgetUiStore.getState().maximized).toBe(true);
    expect(screen.getByRole("button", { name: "Restore chat size" })).toBeInTheDocument();
  });
});
