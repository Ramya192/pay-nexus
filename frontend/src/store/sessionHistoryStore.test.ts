import { beforeEach, describe, expect, it } from "vitest";
import { useSessionHistoryStore } from "./sessionHistoryStore";

beforeEach(() => {
  useSessionHistoryStore.getState().clear();
});

describe("useSessionHistoryStore", () => {
  it("starts empty", () => {
    expect(useSessionHistoryStore.getState().history).toEqual([]);
  });

  it("setHistory replaces the list", () => {
    useSessionHistoryStore.getState().setHistory([{ summary: "session 1" }]);
    expect(useSessionHistoryStore.getState().history).toEqual([{ summary: "session 1" }]);
  });

  it("clear resets to an empty list", () => {
    useSessionHistoryStore.getState().setHistory([{ summary: "session 1" }]);
    useSessionHistoryStore.getState().clear();
    expect(useSessionHistoryStore.getState().history).toEqual([]);
  });
});
