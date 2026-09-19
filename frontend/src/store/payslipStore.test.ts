import { beforeEach, describe, expect, it } from "vitest";
import { usePayslipStore } from "./payslipStore";

beforeEach(() => {
  usePayslipStore.getState().clear();
});

describe("usePayslipStore", () => {
  it("starts with no payslip data", () => {
    expect(usePayslipStore.getState().payslipData).toBeNull();
  });

  it("setPayslipData replaces the stored data", () => {
    usePayslipStore.getState().setPayslipData({ basic: 50_000 });
    expect(usePayslipStore.getState().payslipData).toEqual({ basic: 50_000 });
  });

  it("clear resets to null", () => {
    usePayslipStore.getState().setPayslipData({ basic: 50_000 });
    usePayslipStore.getState().clear();
    expect(usePayslipStore.getState().payslipData).toBeNull();
  });
});
