import { beforeEach, describe, expect, it } from "vitest";
import { useChatWidgetUiStore } from "./chatWidgetUiStore";

beforeEach(() => {
  useChatWidgetUiStore.setState({ open: true, maximized: false });
});

describe("useChatWidgetUiStore", () => {
  it("defaults to open and not maximized", () => {
    const s = useChatWidgetUiStore.getState();
    expect(s.open).toBe(true);
    expect(s.maximized).toBe(false);
  });

  it("setOpen toggles the open flag independently of maximized", () => {
    useChatWidgetUiStore.getState().setMaximized(true);
    useChatWidgetUiStore.getState().setOpen(false);
    const s = useChatWidgetUiStore.getState();
    expect(s.open).toBe(false);
    expect(s.maximized).toBe(true);
  });

  it("setMaximized toggles the maximized flag independently of open", () => {
    useChatWidgetUiStore.getState().setMaximized(true);
    const s = useChatWidgetUiStore.getState();
    expect(s.maximized).toBe(true);
    expect(s.open).toBe(true);
  });
});
