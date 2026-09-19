import { beforeEach, describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { ActivePayslipBanner } from "./ActivePayslipBanner";
import { usePayslipStore } from "../../store/payslipStore";

beforeEach(() => {
  usePayslipStore.getState().clear();
});

describe("ActivePayslipBanner", () => {
  it("shows the 'no payslip active' state when nothing is loaded", () => {
    render(<ActivePayslipBanner />);
    expect(screen.getByText(/No payslip active this session/)).toBeInTheDocument();
  });

  it("shows the active state naming the month, once a payslip with one is loaded", () => {
    usePayslipStore.getState().setPayslipData({ month: "2026-08", basic: 50_000 });
    render(<ActivePayslipBanner />);
    expect(screen.getByText(/Active this session: payslip for 2026-08/)).toBeInTheDocument();
  });

  it("falls back to a generic 'a payslip' phrase when the month field is missing", () => {
    usePayslipStore.getState().setPayslipData({ basic: 50_000 });
    render(<ActivePayslipBanner />);
    expect(screen.getByText(/Active this session: a payslip/)).toBeInTheDocument();
  });
});
